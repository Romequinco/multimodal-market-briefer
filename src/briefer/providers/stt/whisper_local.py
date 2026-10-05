"""Voz a texto local con Whisper (``faster-whisper``).

Carril A. Implementa ``STTProvider.transcribe``. Inspirado en el **notebook 7 de clase
(transcripción con Whisper)**, que usa ``openai/whisper-base`` con ``transformers``; aquí se
propone ``faster-whisper`` (CTranslate2) por ser más rápido en CPU. Alternativa equivalente:
``transformers.pipeline("automatic-speech-recognition", model="openai/whisper-base")``.
Modelo: ``BRIEFER_WHISPER_LOCAL_MODEL`` (tiny/base/small…). Coste: 0 €.
"""

from __future__ import annotations

from pathlib import Path

from briefer.config import Settings
from briefer.providers.base import STTProvider


class WhisperLocal(STTProvider):
    """Whisper en local; el modelo se carga una vez."""

    provider_name = "whisper_local"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.briefer_whisper_local_model
        self._model = None

    def transcribe(self, audio_path: Path, language: str = "es") -> str:
        """Transcribe con faster-whisper y une los segmentos."""
        # TODO:
        # 1. from faster_whisper import WhisperModel (perezoso).
        # 2. self._model = WhisperModel(self.model, device="auto", compute_type="int8")
        #    (cachear; usar settings.briefer_local_device si no es "auto").
        # 3. segments, info = self._model.transcribe(str(audio_path), language=language,
        #    vad_filter=True); texto = " ".join(s.text.strip() for s in segments).
        # Casos borde: la primera llamada descarga el modelo (avisar en UI); audio en otro
        # idioma (info.language) -> registrar en log; ffmpeg ausente para formatos no wav.
        raise NotImplementedError("WhisperLocal.transcribe: pendiente (carril A, opcional)")
