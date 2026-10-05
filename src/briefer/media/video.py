"""Vídeo corto del briefing: imágenes (portada + gráficos) + audio del podcast + subtítulos.

Carril C (opcional). Entrada: ``AudioAsset`` (+ segments), lista de imágenes PNG, ``Transcript``.
Salida: ``VideoAsset`` MP4. Herramientas: ``moviepy`` (>= 2.0) + ffmpeg (``imageio-ffmpeg``).
Extra no previsto en el MVP: clips generativos con Stable Video Diffusion (notebook 5).
"""

from __future__ import annotations

from pathlib import Path

from briefer.schemas import AudioAsset, Transcript, VideoAsset


def make_video(
    audio: AudioAsset,
    images: list[Path],
    out_path: Path,
    transcript: Transcript | None = None,
    size: tuple[int, int] = (1080, 1920),
    fps: int = 24,
) -> VideoAsset:
    """Monta el vídeo: cada imagen ocupa un tramo del audio; subtítulos desde ``segments``."""
    # TODO:
    # 1. from moviepy import ImageClip, AudioFileClip, CompositeVideoClip, TextClip,
    #    concatenate_videoclips (API de moviepy 2.x: with_duration, with_position...).
    # 2. Repartir audio.duration_s entre las imágenes (o alinear cada gráfico con el
    #    segmento en que se menciona su ticker: mejora "con sentido").
    # 3. Redimensionar/encuadrar cada imagen a ``size`` (vertical 9:16 para redes).
    # 4. Subtítulos: un TextClip por AudioSegment (start_s-end_s) en la parte inferior.
    #    TextClip necesita una fuente TTF: incluir ruta configurable o usar la del sistema.
    # 5. write_videofile(out_path, fps=fps, codec="libx264", audio_codec="aac").
    # Casos borde: sin imágenes -> fondo de color liso con el título; vídeo largo (>5 min)
    # tarda mucho -> mostrar progreso en la UI; ffmpeg no encontrado -> error claro.
    raise NotImplementedError("make_video: pendiente (carril C, opcional)")
