"""Síntesis del podcast a 2 voces: TTS por línea del guion + concatenación.

Carril C. Entrada: ``PodcastScript`` + ``TTSProvider`` + voces A/B. Salida: ``AudioAsset``
(fichero final + ``segments`` con tiempos de inicio/fin por línea, que usa
``media.transcript`` para el SRT y ``media.video`` para los subtítulos).
"""

from __future__ import annotations

from pathlib import Path

from briefer.providers.base import TTSProvider
from briefer.schemas import AudioAsset, PodcastScript


def audio_duration_s(path: Path) -> float:
    """Duración de un fichero de audio (wav con ``wave``; mp3 con ffprobe/imageio-ffmpeg)."""
    # TODO: .wav -> wave.open: frames / rate. Otros -> imageio_ffmpeg.count_frames_and_secs
    # o leer con moviepy AudioFileClip(path).duration.
    raise NotImplementedError("audio_duration_s: pendiente (carril C)")


def concat_audio(paths: list[Path], out_path: Path, pause_s: float = 0.35) -> Path:
    """Concatena audios con una pausa corta entre intervenciones; devuelve ``out_path``."""
    # TODO:
    # Opción A (sin dependencias extra): ffmpeg (imageio_ffmpeg.get_ffmpeg_exe()) con el
    #   demuxer concat (fichero lista) + silencio generado con anullsrc; salida mp3.
    # Opción B: moviepy concatenate_audioclips([...]) con AudioClip de silencio.
    # Casos borde: mezclar wav (mock) y mp3 -> re-codificar todo al mismo formato;
    # lista vacía -> ValueError.
    raise NotImplementedError("concat_audio: pendiente (carril C)")


def synthesize_podcast(
    script: PodcastScript,
    tts: TTSProvider,
    out_dir: Path,
    voice_a: str,
    voice_b: str,
    pause_s: float = 0.35,
) -> AudioAsset:
    """Genera el audio completo del episodio."""
    # TODO:
    # 1. Para cada línea i: voice = voice_a si speaker == "A" si no voice_b;
    #    p = tts.synthesize(line.text, voice, out_dir / "parts" / f"{i:03d}_{speaker}").
    # 2. Medir duración de cada parte (audio_duration_s) y acumular start_s/end_s
    #    (sumando pause_s entre líneas) -> AudioSegment.
    # 3. final = concat_audio(parts, out_dir / f"podcast{ext}", pause_s).
    # 4. AudioAsset(path=final, duration_s=total, segments=segments).
    # Paralelizable: sintetizar líneas con ThreadPoolExecutor (edge-tts es I/O bound),
    # manteniendo el orden. Coste TTS: costs.estimate_tts_cost_eur(tts.provider_name, chars).
    raise NotImplementedError("synthesize_podcast: pendiente (carril C)")
