"""Voz a texto con la API de OpenAI (Whisper / gpt-4o-mini-transcribe).

Carril A. Implementa ``STTProvider.transcribe(audio_path, language) -> str``.
Lo usa ``ingest.voice`` (pregunta por voz y notas de voz). Modelo: ``BRIEFER_WHISPER_API_MODEL``.
Coste aproximado en ``costs.STT_PRICES_USD_PER_MIN``.
"""

from __future__ import annotations

from pathlib import Path

from briefer.config import Settings
from briefer.providers.base import STTProvider


class WhisperAPI(STTProvider):
    """Transcripción remota con ``openai.audio.transcriptions``."""

    provider_name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.briefer_whisper_api_model

    def transcribe(self, audio_path: Path, language: str = "es") -> str:
        """Transcribe ``audio_path`` (wav/mp3/m4a/webm) en ``language``."""
        # TODO:
        # 1. from openai import OpenAI; client = OpenAI(api_key=...).
        # 2. with open(audio_path, "rb") as f: client.audio.transcriptions.create(
        #    model=self.model, file=f, language=language) -> .text
        # 3. Normalizar espacios; devolver "" si no hay voz.
        # Casos borde: fichero > 25 MB (límite API) -> trocear o rechazar; formato no
        # soportado -> convertir a wav con ffmpeg (imageio-ffmpeg); audio vacío de
        # st.audio_input (0 bytes).
        raise NotImplementedError("WhisperAPI.transcribe: pendiente (carril A)")
