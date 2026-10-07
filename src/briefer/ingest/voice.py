"""Voz a texto: preguntas por voz (Q&A) y notas de voz como contexto del briefing.

Carril A. Entrada: audio (ruta o bytes de ``st.audio_input``). Salida: ``str`` o
``DocumentInsight(source_type="voice")``. Usa ``STTProvider`` (Whisper API o local, notebook 7).
"""

from __future__ import annotations

import inspect
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


def vocabulary_hint(tickers: list[str] | None, max_names: int = 20) -> str:
    """Pista de vocabulario para el STT: nombres de las empresas del briefing e índices.

    Sin ella, la transcripción confunde nombres propios con la voz sintética (medido: «Apple» se
    oyó «Yabel» y el Q&A respondió que Apple no estaba en el briefing). Devuelve ``""`` si no
    hay tickers. Solo nombres públicos de empresas: nada de la cartera (pesos) ni del usuario.
    """
    from briefer.ingest.tickers import normalize_ticker, ticker_info

    names: list[str] = []
    for raw in tickers or []:
        ticker = normalize_ticker(raw)
        info = ticker_info(ticker)
        name = str(info["name"]) if info else ticker.split(".")[0].lstrip("^")
        if name and name not in names:
            names.append(name)
    if not names:
        return ""
    return "Vocabulario: " + ", ".join([*names[:max_names], "IBEX 35", "S&P 500"]) + "."


def _accepts_prompt(stt: STTProvider) -> bool:
    """``True`` si ``stt.transcribe`` admite el argumento opcional ``prompt``."""
    try:
        return "prompt" in inspect.signature(stt.transcribe).parameters
    except (TypeError, ValueError):
        return False


def _is_hint_echo(text: str, hint: str) -> bool:
    """``True`` si el texto es (parte de) la pista: el modelo la repite ante audio sin voz."""
    fold = lambda s: re.sub(r"[^\w]+", " ", s.casefold()).strip()  # noqa: E731
    folded = fold(text)
    return bool(folded) and folded in fold(hint)


def transcribe_question(
    audio_path: Path, stt: STTProvider, language: str = "es", vocabulary: str | None = None
) -> str:
    """Transcribe una pregunta hablada; devuelve texto limpio (espacios normalizados).

    ``vocabulary`` (opcional, ver ``vocabulary_hint``) se pasa como ``prompt`` al STT si lo
    admite. Si la salida es solo un eco de esa pista (audio sin voz), se trata como vacía.

    Raises:
        FileNotFoundError: si no existe el audio.
        ValueError: si la transcripción queda vacía.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"No existe el audio: {audio_path}")
    if vocabulary and _accepts_prompt(stt):
        raw = stt.transcribe(audio_path, language, prompt=vocabulary)  # type: ignore[call-arg]
    else:
        raw = stt.transcribe(audio_path, language)
    text = " ".join(str(raw or "").split())
    if vocabulary and _is_hint_echo(text, vocabulary):
        text = ""
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
