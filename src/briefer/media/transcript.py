"""Transcripción del episodio en texto plano y subtítulos SRT.

Carril C. Entrada: ``PodcastScript`` + ``AudioAsset`` (con ``segments``). Salida:
``Transcript(text, srt_path)``. No necesita STT: los tiempos salen de la síntesis.
"""

from __future__ import annotations

from pathlib import Path

from briefer.schemas import AudioSegment, PodcastScript, Transcript


def format_srt_timestamp(seconds: float) -> str:
    """``3.5`` -> ``"00:00:03,500"`` (formato SRT)."""
    # TODO: horas, minutos, segundos y milisegundos con divmod; redondear ms.
    raise NotImplementedError("format_srt_timestamp: pendiente (carril C)")


def segments_to_srt(segments: list[AudioSegment], speaker_names: dict[str, str] | None = None) -> str:
    """Texto SRT: índice, ``inicio --> fin`` y texto (prefijo con el nombre del hablante)."""
    # TODO: partir líneas largas (> 42 caracteres/fila, máx. 2 filas) en varios bloques
    # repartiendo el tiempo proporcionalmente a los caracteres (mejor lectura en vídeo).
    raise NotImplementedError("segments_to_srt: pendiente (carril C)")


def build_transcript(
    script: PodcastScript,
    segments: list[AudioSegment],
    out_dir: Path,
    speaker_names: dict[str, str] | None = None,
) -> Transcript:
    """Genera la transcripción legible y escribe ``out_dir/podcast.srt``."""
    # TODO: text = "\n".join(f"{nombre}: {línea.text}"); escribir el SRT en UTF-8;
    # si segments está vacío (sin audio), devolver Transcript(text=..., srt_path=None).
    raise NotImplementedError("build_transcript: pendiente (carril C)")
