"""Visión con Claude: lee capturas de gráficos y páginas de PDF con gráficos/tablas.

Carril A. Implementa ``VisionProvider.describe(image: bytes, prompt) -> str``.
Lo usan ``ingest.chart_reader`` y ``ingest.pdf_reader`` para producir ``DocumentInsight``.
Modelo: ``BRIEFER_VISION_MODEL``.
"""

from __future__ import annotations

from briefer.config import Settings
from briefer.providers.base import VisionProvider


def detect_media_type(image: bytes) -> str:
    """Devuelve ``image/png``, ``image/jpeg``, ``image/webp`` o ``image/gif`` por cabecera."""
    # TODO: comprobar magic bytes: b"\x89PNG" -> png; b"\xff\xd8" -> jpeg;
    # b"RIFF....WEBP" -> webp; b"GIF8" -> gif. Si no se reconoce, ValueError.
    raise NotImplementedError("detect_media_type: pendiente (carril A)")


class ClaudeVision(VisionProvider):
    """Descripción/extracción de imágenes con Claude."""

    provider_name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.briefer_vision_model
        self._client = None

    def describe(self, image: bytes, prompt: str) -> str:
        """Envía la imagen + prompt a Claude y devuelve el texto de respuesta."""
        # TODO:
        # 1. import anthropic, base64 (perezoso); cliente como en AnthropicLLM.
        # 2. content = [{"type": "image", "source": {"type": "base64",
        #    "media_type": detect_media_type(image), "data": base64.b64encode(image).decode()}},
        #    {"type": "text", "text": prompt}].
        # 3. messages.create(model=self.model, max_tokens=1500, messages=[{"role": "user",
        #    "content": content}]) y concatenar bloques de texto.
        # 4. last_usage desde resp.usage.
        # Casos borde: imagen > 5 MB o lado > 8000 px -> reescalar con Pillow antes de enviar;
        # imagen que no es un gráfico -> el prompt debe pedir que lo diga explícitamente.
        raise NotImplementedError("ClaudeVision.describe: pendiente (carril A)")
