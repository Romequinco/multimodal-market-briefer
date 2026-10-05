"""Interfaces abstractas (ABC) de la capa de conexión con modelos de IA.

Transversal (las implementan los tres carriles). La lógica de negocio (``ingest``,
``agents``, ``media``) depende SOLO de estas interfaces, nunca de un SDK concreto; así
cambiar Claude por Gemini, o Whisper API por Whisper local, es un cambio de ``.env``
(ver ``registry.py`` y ADR-002).

Cada implementación expone ``provider_name`` y ``model`` para las métricas (``StepMetric``)
y, si factura por tokens, rellena ``last_usage`` tras cada llamada para estimar costes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class _Provider(ABC):  # noqa: B024 - base común; los métodos abstractos van en cada familia
    """Atributos comunes a todos los proveedores."""

    provider_name: str = "base"
    model: str = ""

    def __repr__(self) -> str:  # pragma: no cover - cosmético
        return f"{type(self).__name__}(provider={self.provider_name!r}, model={self.model!r})"


class LLMProvider(_Provider):
    """Modelo de lenguaje (Agente Analista, Guionista y Q&A)."""

    def __init__(self) -> None:
        # Uso de la última llamada: {"input_tokens": int, "output_tokens": int}.
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        """Genera una respuesta.

        Args:
            system: prompt de sistema.
            messages: historial estilo chat ``[{"role": "user"|"assistant", "content": str}]``.
            response_model: si se indica, la respuesta DEBE devolverse como instancia válida
                de ese modelo Pydantic (salida estructurada / JSON validado).

        Returns:
            ``str`` si ``response_model`` es ``None``; si no, una instancia de ``response_model``.
        """


class VisionProvider(_Provider):
    """Modelo de visión-lenguaje (lectura de capturas de gráficos y páginas de PDF)."""

    def __init__(self) -> None:
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    @abstractmethod
    def describe(self, image: bytes, prompt: str) -> str:
        """Describe/extrae información de ``image`` (PNG/JPEG en bytes) guiado por ``prompt``."""


class STTProvider(_Provider):
    """Voz a texto (pregunta por voz del usuario)."""

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str = "es") -> str:
        """Transcribe el audio de ``audio_path`` y devuelve el texto."""


class TTSProvider(_Provider):
    """Texto a voz (podcast a 2 voces y respuesta hablada del Q&A)."""

    #: Extensión del audio que produce esta implementación (".mp3", ".wav"...).
    audio_extension: str = ".mp3"

    @abstractmethod
    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        """Sintetiza ``text`` con ``voice`` y lo guarda; devuelve la ruta REAL escrita
        (puede cambiar la extensión de ``out_path`` según ``audio_extension``)."""


class ImageGenProvider(_Provider):
    """Texto a imagen (portada/infografía opcional del briefing)."""

    @abstractmethod
    def generate(self, prompt: str, out_path: Path) -> Path:
        """Genera una imagen PNG a partir de ``prompt`` y devuelve su ruta."""


class ImageClassifier(_Provider):
    """Clasificación zero-shot de imágenes (enrutar una captura: velas, tabla, otra cosa)."""

    @abstractmethod
    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
        """Devuelve ``{etiqueta: probabilidad}`` (suma ~1) para cada etiqueta de ``labels``."""


__all__ = [
    "ImageClassifier",
    "ImageGenProvider",
    "LLMProvider",
    "STTProvider",
    "TTSProvider",
    "VisionProvider",
]
