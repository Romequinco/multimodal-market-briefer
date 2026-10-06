"""Texto a imagen con **Gemini** para la portada del episodio (``BRIEFER_IMAGE_GEN_PROVIDER=gemini``).

Carril C (opcional, de pago). Implementa ``ImageGenProvider.generate(prompt, out_path) -> Path``.

- Modelo ``BRIEFER_GEMINI_IMAGE_MODEL`` (``gemini-3.1-flash-lite-image``, «Nano Banana 2 Lite»):
  el más barato de la API de Gemini, 0,0336 $ por imagen 1K (página oficial de precios,
  consultada el 06-oct-2026). Se pide con ``generate_content`` y ``response_modalities=["IMAGE"]``.
- Formato **16:9** a 1K (``ImageConfig``): la portada es horizontal; el vídeo vertical la encaja
  en 9:16. (``prominent_people`` solo existe en Vertex AI, no en la API de Gemini: las personas
  reales se excluyen desde el prompt, ``media.cover``.)
- La respuesta trae la imagen en ``inline_data`` (PNG o JPEG según el modelo): se normaliza a
  **PNG** con Pillow y se escribe de forma atómica.
- Sin reintentos anidados: el SDK reintenta **una vez** ante 408/429/5xx (``HttpRetryOptions``).
  Sin facturación en el proyecto de la clave, los modelos de imagen responden 429 con cuota 0
  (no tienen nivel gratuito): se traduce a un mensaje claro (``is_no_billing_error``).
  Una respuesta sin imagen (filtro de seguridad, texto en vez de imagen) es un ``RuntimeError``
  claro; el pipeline lo trata como paso opcional fallido (sin portada).
- ``last_usage`` guarda los tokens de la última llamada (informativo: el coste se estima por
  imagen en ``costs.IMAGE_GEN_PRICES_USD_PER_IMAGE``).
"""

from __future__ import annotations

import io
import os
import threading
from pathlib import Path
from typing import Any

from briefer.config import Settings
from briefer.logging_utils import get_logger, redact_secrets
from briefer.providers.base import ImageGenProvider

log = get_logger("providers.image.gemini")

TIMEOUT_MS = 90_000
RETRY_ATTEMPTS = 2  # 1 intento + 1 reintento del SDK, como máximo
RETRY_STATUS = [408, 429, 500, 502, 503, 504]
ASPECT_RATIO = "16:9"
IMAGE_SIZE = "1K"


def is_no_billing_error(exc: BaseException) -> bool:
    """``True`` si es el 429 de «cuota 0 del nivel gratuito» (modelos de imagen sin facturación)."""
    text = redact_secrets(exc)
    return "RESOURCE_EXHAUSTED" in text and "free_tier" in text and "limit: 0" in text


class GeminiImage(ImageGenProvider):
    """Cliente de generación de imágenes de Gemini (``from google import genai``)."""

    provider_name = "gemini"

    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.model = settings.briefer_gemini_image_model
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            from google.genai import types

            if not self.settings.has_secret("gemini_api_key"):
                raise RuntimeError("Falta GEMINI_API_KEY en .env")
            self._client = genai.Client(
                api_key=self.settings.gemini_api_key.get_secret_value(),  # type: ignore[union-attr]
                http_options=types.HttpOptions(
                    timeout=TIMEOUT_MS,
                    retry_options=types.HttpRetryOptions(
                        attempts=RETRY_ATTEMPTS, http_status_codes=RETRY_STATUS
                    ),
                ),
            )
        return self._client

    @staticmethod
    def _image_bytes(resp: Any) -> bytes:
        """Bytes de la primera parte con imagen; ``RuntimeError`` si no hay ninguna."""
        reason = ""
        for cand in getattr(resp, "candidates", None) or []:
            reason = str(getattr(cand, "finish_reason", "") or reason)
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None)
                mime = str(getattr(inline, "mime_type", "") or "")
                if data and (not mime or mime.startswith("image/")):
                    return bytes(data)
        detail = f" (motivo: {reason})" if reason else ""
        raise RuntimeError(f"Gemini no devolvió ninguna imagen{detail}")

    def _record_usage(self, resp: Any) -> None:
        meta = getattr(resp, "usage_metadata", None)
        self.last_usage = {
            "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
            "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
        }

    def generate(self, prompt: str, out_path: Path) -> Path:
        """Genera la imagen de ``prompt`` y la guarda como PNG en ``out_path`` (extensión .png)."""
        if not prompt or not prompt.strip():
            raise ValueError("GeminiImage.generate: el prompt está vacío")
        from google.genai import types
        from PIL import Image

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=ASPECT_RATIO, image_size=IMAGE_SIZE),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            resp = self._get_client().models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        except Exception as exc:
            if is_no_billing_error(exc):
                raise RuntimeError(
                    f"La clave de Gemini no tiene facturación activa: {self.model} no tiene nivel "
                    "gratuito (cuota 0). Activa la facturación del proyecto o usa "
                    "BRIEFER_IMAGE_GEN_PROVIDER=none"
                ) from None
            raise
        self._record_usage(resp)
        data = self._image_bytes(resp)
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception as exc:  # noqa: BLE001 - se re-lanza con un mensaje claro
            raise RuntimeError("Gemini devolvió una imagen que no se puede abrir") from exc

        out = Path(out_path).with_suffix(".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{out.stem}.{os.getpid()}.{threading.get_ident()}.part")
        try:
            image.convert("RGB").save(tmp, format="PNG")
            os.replace(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)
        log.info("Portada generada con %s (%dx%d)", self.model, image.width, image.height)
        return out


__all__ = ["ASPECT_RATIO", "GeminiImage", "is_no_billing_error"]
