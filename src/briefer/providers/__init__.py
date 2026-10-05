"""Capa de conexión con modelos de IA (proveedores intercambiables por configuración).

- ``base``: interfaces abstractas (LLM, visión, STT, TTS, imagen, clasificador).
- ``mock``: implementaciones falsas deterministas (sin red ni claves).
- ``registry``: elige la implementación según ``.env``.
- Subpaquetes ``llm``, ``vision``, ``stt``, ``tts``, ``image``: implementaciones reales.

La lógica de negocio solo debe importar ``base`` y ``registry``.
"""

from briefer.providers.base import (
    ImageClassifier,
    ImageGenProvider,
    LLMProvider,
    STTProvider,
    TTSProvider,
    VisionProvider,
)

__all__ = [
    "ImageClassifier",
    "ImageGenProvider",
    "LLMProvider",
    "STTProvider",
    "TTSProvider",
    "VisionProvider",
]
