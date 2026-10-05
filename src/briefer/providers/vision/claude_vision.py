"""Visión con Claude: lee capturas de gráficos y páginas de PDF con gráficos/tablas.

Implementa ``VisionProvider.describe(image: bytes, prompt) -> str`` (proveedor del carril B;
lo usan ``ingest.chart_reader`` e ``ingest.pdf_reader`` del carril A para producir
``DocumentInsight``). Modelo: ``BRIEFER_VISION_MODEL`` (``claude-sonnet-5-5``).

- El tipo de imagen se detecta por la cabecera (``detect_media_type``), no por la extensión.
- Imágenes de más de 5 MB o con un lado > ``MAX_SIDE_PX`` se reescalan con Pillow antes de
  enviarlas (límite de la API y ahorro de subida).
- ``last_usage`` recoge los tokens de la llamada; timeouts y reintentos como en ``AnthropicLLM``.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from briefer.config import Settings
from briefer.providers.base import VisionProvider
from briefer.providers.llm import _anthropic_common as common

#: Límite de tamaño de imagen en base64 de la API (5 MB) y lado máximo que se envía.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SIDE_PX = 2_000
MAX_TOKENS = 4_000
DEFAULT_EFFORT = "low"


def detect_media_type(image: bytes) -> str:
    """Devuelve ``image/png``, ``image/jpeg``, ``image/webp`` o ``image/gif`` por cabecera.

    Raises:
        ValueError: imagen vacía o formato no reconocido.
    """
    if not image:
        raise ValueError("Imagen vacía")
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    if image[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise ValueError("Formato de imagen no soportado (se admiten PNG, JPEG, WEBP y GIF)")


def prepare_image(image: bytes) -> tuple[bytes, str]:
    """Devuelve ``(bytes, media_type)`` listos para la API, reescalando si hace falta.

    Si la imagen supera ``MAX_IMAGE_BYTES`` o tiene un lado mayor que ``MAX_SIDE_PX`` se
    reduce (manteniendo proporción) y se re-codifica: PNG si cabe, si no JPEG calidad 85.
    """
    media_type = detect_media_type(image)
    try:
        from PIL import Image
    except ImportError:  # sin Pillow se envía tal cual
        return image, media_type
    with Image.open(io.BytesIO(image)) as img:
        too_big = len(image) > MAX_IMAGE_BYTES or max(img.size) > MAX_SIDE_PX
        if not too_big:
            return image, media_type
        img = img.convert("RGB") if img.mode not in ("RGB", "L") else img.copy()
        img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        if buf.tell() <= MAX_IMAGE_BYTES:
            return buf.getvalue(), "image/png"
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"


class ClaudeVision(VisionProvider):
    """Descripción/extracción de imágenes con Claude."""

    provider_name = "anthropic"

    def __init__(self, settings: Settings, effort: str | None = DEFAULT_EFFORT) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.briefer_vision_model
        self.effort = effort
        self._client: Any = None

    def _get_client(self) -> Any:
        """Cliente compartido con ``AnthropicLLM`` (``common.get_client``)."""
        if self._client is None:
            self._client = common.get_client(self.settings)
        return self._client

    def warmup(self) -> float:
        """Precalienta el SDK y la conexión (llamada gratuita). Ver ``AnthropicLLM.warmup``."""
        if self._client is not None:
            return 0.0
        return common.warmup_client(self.settings, self.model)

    def describe(self, image: bytes, prompt: str) -> str:
        """Envía la imagen + prompt a Claude y devuelve el texto de respuesta.

        Raises:
            ValueError: imagen vacía o formato no soportado.
            anthropic.APIError / LLMResponseError: fallo de la API o respuesta inutilizable.
        """
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}  # no arrastrar la llamada anterior
        data, media_type = prepare_image(image)
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            },
            {"type": "text", "text": prompt},
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": content}],
        }
        options = common.request_options(self.model, self.effort)
        if options:
            kwargs["output_config"] = options
        resp = self._get_client().messages.create(**kwargs)
        self.last_usage = common.usage_dict(resp)
        return common.response_text(resp)
