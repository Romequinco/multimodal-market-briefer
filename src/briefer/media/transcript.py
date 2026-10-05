"""Transcripción del episodio en texto plano y subtítulos SRT.

Carril C. Entrada: ``PodcastScript`` + ``AudioAsset`` (con ``segments``). Salida:
``Transcript(text, srt_path)``. No necesita STT: los tiempos salen de la síntesis.

Los subtítulos siguen pautas de legibilidad habituales: como mucho 2 filas de 42 caracteres
por bloque; las intervenciones largas se trocean en varios bloques repartiendo el tiempo del
segmento en proporción a los caracteres de cada trozo.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from briefer.schemas import AudioSegment, PodcastScript, Transcript

MAX_CHARS_PER_ROW = 42
MAX_ROWS = 2
FALLBACK_SPEAKER_NAMES = {"A": "Presentador", "B": "Analista"}


def default_speaker_names() -> dict[str, str]:
    """Nombres legibles de los locutores desde la configuración (o genéricos si falla)."""
    try:
        from briefer.config import get_settings

        s = get_settings()
        return {"A": s.briefer_speaker_a_name, "B": s.briefer_speaker_b_name}
    except Exception:  # pragma: no cover - .env mal formado
        return dict(FALLBACK_SPEAKER_NAMES)


def _names(speaker_names: dict[str, str] | None) -> dict[str, str]:
    names = dict(FALLBACK_SPEAKER_NAMES) if speaker_names is not None else default_speaker_names()
    names.update(speaker_names or {})
    return names


def format_srt_timestamp(seconds: float) -> str:
    """``3.5`` -> ``"00:00:03,500"`` (formato SRT). Los negativos se recortan a 0."""
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _split_caption(text: str, width: int = MAX_CHARS_PER_ROW, rows: int = MAX_ROWS) -> list[str]:
    """Trocea ``text`` en bloques de como mucho ``rows`` filas de ``width`` caracteres."""
    wrapped = textwrap.wrap(" ".join(text.split()), width=width, break_long_words=True) or [""]
    return ["\n".join(wrapped[i : i + rows]) for i in range(0, len(wrapped), rows)]


def segments_to_srt(segments: list[AudioSegment], speaker_names: dict[str, str] | None = None) -> str:
    """Texto SRT: índice, ``inicio --> fin`` y texto (prefijo con el nombre del hablante).

    El nombre del locutor solo aparece en el primer bloque de cada intervención para no
    restar espacio en pantalla.
    """
    names = _names(speaker_names)
    blocks: list[str] = []
    index = 1
    for seg in segments:
        name = names.get(seg.speaker, seg.speaker)
        chunks = _split_caption(f"{name}: {seg.text.strip()}")
        weights = [max(1, len(c.replace("\n", " "))) for c in chunks]
        total_w = sum(weights)
        span = max(0.0, seg.end_s - seg.start_s)
        cursor = seg.start_s
        for chunk, w in zip(chunks, weights, strict=True):
            end = cursor + span * w / total_w
            blocks.append(f"{index}\n{format_srt_timestamp(cursor)} --> {format_srt_timestamp(end)}\n{chunk}\n")
            index += 1
            cursor = end
    return "\n".join(blocks)


def build_transcript(
    script: PodcastScript,
    segments: list[AudioSegment],
    out_dir: Path,
    speaker_names: dict[str, str] | None = None,
) -> Transcript:
    """Genera la transcripción legible y escribe ``out_dir/podcast.srt``.

    ``text`` usa una línea por intervención con el nombre del locutor (``"Álvaro: …"``),
    separadas por una línea en blanco. Si ``segments`` está vacío (sin audio) no hay SRT.
    """
    names = _names(speaker_names)
    source = segments or script.lines
    text = "\n\n".join(
        f"{names.get(item.speaker, item.speaker)}: {item.text.strip()}" for item in source if item.text.strip()
    )
    if not segments:
        return Transcript(text=text, srt_path=None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    srt_path = out_dir / "podcast.srt"
    srt_path.write_text(segments_to_srt(segments, names), encoding="utf-8")
    return Transcript(text=text, srt_path=srt_path)


__all__ = ["build_transcript", "default_speaker_names", "format_srt_timestamp", "segments_to_srt"]
