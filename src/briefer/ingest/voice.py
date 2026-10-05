"""Voz a texto: preguntas por voz (Q&A) y notas de voz como contexto del briefing.

Carril A. Entrada: audio (ruta o bytes de ``st.audio_input``). Salida: ``str`` o
``DocumentInsight(source_type="voice")``. Usa ``STTProvider`` (Whisper API o local, notebook 7).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from briefer.providers.base import STTProvider
from briefer.schemas import DocumentInsight

# Longitud máxima del resumen de una nota de voz.
SUMMARY_MAX_CHARS = 300


def save_audio_upload(data: bytes, out_dir: Path, suffix: str = ".wav") -> Path:
    """Guarda los bytes de un audio subido/grabado en ``out_dir`` y devuelve la ruta.

    El nombre es ``voz_<timestamp>_<uuid corto><suffix>`` para no pisar ficheros. ``suffix`` se
    sanea (``.`` + 1-8 letras o cifras; si no, ``.wav``) porque viene del nombre del fichero subido.

    Raises:
        ValueError: si el audio está vacío (``st.audio_input`` puede devolver 0 bytes).
    """
    if not data:
        raise ValueError("El audio está vacío: vuelve a grabar la pregunta")
    suffix = (suffix if suffix.startswith(".") else f".{suffix}").lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):  # viene del nombre subido: nada de rutas
        suffix = ".wav"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"voz_{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:6]}{suffix}"
    path.write_bytes(data)
    return path


def transcribe_question(audio_path: Path, stt: STTProvider, language: str = "es") -> str:
    """Transcribe una pregunta hablada; devuelve texto limpio (espacios normalizados).

    Raises:
        FileNotFoundError: si no existe el audio.
        ValueError: si la transcripción queda vacía.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"No existe el audio: {audio_path}")
    text = " ".join(str(stt.transcribe(audio_path, language) or "").split())
    if not text:
        raise ValueError("No se ha entendido el audio")
    return text


def voice_to_insight(audio_path: Path, stt: STTProvider, language: str = "es") -> DocumentInsight:
    """Convierte una nota de voz en ``DocumentInsight`` (source_type="voice")."""
    text = transcribe_question(audio_path, stt, language)
    summary = text if len(text) <= SUMMARY_MAX_CHARS else text[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return DocumentInsight(
        source_type="voice",
        source_name=Path(audio_path).name,
        extracted_text=text,
        key_figures={},
        summary=summary,
    )
