"""Voz a texto: preguntas por voz (Q&A) y notas de voz como contexto del briefing.

Carril A. Entrada: audio (ruta o bytes de ``st.audio_input``). Salida: ``str`` o
``DocumentInsight(source_type="voice")``. Usa ``STTProvider`` (Whisper API o local, notebook 7).
"""

from __future__ import annotations

from pathlib import Path

from briefer.providers.base import STTProvider
from briefer.schemas import DocumentInsight


def save_audio_upload(data: bytes, out_dir: Path, suffix: str = ".wav") -> Path:
    """Guarda los bytes de un audio subido/grabado en ``out_dir`` y devuelve la ruta."""
    # TODO: out_dir.mkdir(parents=True, exist_ok=True); nombre con timestamp + uuid corto;
    # validar tamaño > 0 (st.audio_input puede devolver audio vacío).
    raise NotImplementedError("save_audio_upload: pendiente (carril A)")


def transcribe_question(audio_path: Path, stt: STTProvider, language: str = "es") -> str:
    """Transcribe una pregunta hablada; devuelve texto limpio."""
    # TODO: text = stt.transcribe(audio_path, language).strip(); si queda vacío ->
    # ValueError("No se ha entendido el audio") para mostrar en la UI.
    raise NotImplementedError("transcribe_question: pendiente (carril A)")


def voice_to_insight(audio_path: Path, stt: STTProvider, language: str = "es") -> DocumentInsight:
    """Convierte una nota de voz en ``DocumentInsight`` (source_type="voice")."""
    # TODO: texto = transcribe_question(...); DocumentInsight(source_type="voice",
    # source_name=audio_path.name, extracted_text=texto, key_figures={}, summary=texto[:300]).
    raise NotImplementedError("voice_to_insight: pendiente (carril A)")
