"""Marcado del audio sintético (AI Act art. 50): metadatos ID3 del MP3 final, sin red."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from briefer.media import podcast
from briefer.providers.mock import MockTTS, write_silence_wav
from briefer.schemas import PodcastScript, ScriptLine


def _has_ffmpeg() -> bool:
    try:
        podcast.ffmpeg_exe()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_ffmpeg(), reason="requiere ffmpeg (imageio-ffmpeg)")


def _tags(path: Path) -> str:
    proc = subprocess.run([podcast.ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc.stderr


class MP3Ext(MockTTS):
    """MockTTS que escribe partes «.mp3» (con contenido WAV): fuerza la vía ffmpeg como con edge-tts."""

    audio_extension = ".mp3"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        return write_silence_wav(Path(out_path).with_suffix(".mp3"), 0.4)  # contenido WAV, ffmpeg lo detecta


def test_concat_audio_writes_ai_metadata(tmp_path: Path) -> None:
    parts = [write_silence_wav(tmp_path / f"{i}.wav", 0.3) for i in range(2)]
    out = podcast.concat_audio(parts, tmp_path / "out.mp3", metadata=podcast.AI_AUDIO_METADATA)
    info = _tags(out)
    assert "Voces sintéticas generadas por IA" in info
    assert "Briefly (voces sintéticas IA)" in info


def test_synthesize_podcast_mp3_is_marked_as_synthetic(tmp_path: Path) -> None:
    script = PodcastScript(title="Episodio de prueba", lines=[ScriptLine(speaker="A", text="Hola"),
                                                              ScriptLine(speaker="B", text="Adiós")])
    audio = podcast.synthesize_podcast(script, MP3Ext(), tmp_path, "a", "b")
    assert audio.path.suffix == ".mp3"
    info = _tags(audio.path)
    assert "comment" in info and "sintéticas" in info
    assert "Episodio de prueba" in info  # título del episodio
    # El MP3 es válido: ffmpeg lo decodifica entero sin errores
    proc = subprocess.run([podcast.ffmpeg_exe(), "-v", "error", "-i", str(audio.path), "-f", "null", "-"],
                          capture_output=True, text=True)
    assert proc.returncode == 0 and not proc.stderr.strip()


def test_wav_output_has_no_metadata_but_works(tmp_path: Path) -> None:
    script = PodcastScript(title="T", lines=[ScriptLine(speaker="A", text="Hola")])
    audio = podcast.synthesize_podcast(script, MockTTS(), tmp_path, "a", "b")
    assert audio.path.suffix == ".wav" and audio.path.exists()


def test_tag_audio_writes_ai_metadata_without_reencoding(tmp_path) -> None:
    """La respuesta hablada del Q&A también lleva las etiquetas de voz sintética (AI Act art. 50)."""
    import subprocess

    import imageio_ffmpeg

    from briefer.media import podcast

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    mp3 = tmp_path / "respuesta.mp3"
    subprocess.run([exe, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", str(mp3)],
                   check=True, capture_output=True)
    podcast.tag_audio(mp3)
    info = subprocess.run([exe, "-i", str(mp3)], capture_output=True).stderr.decode("utf-8", "replace")
    assert "voces sintéticas IA" in info
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    assert podcast.tag_audio(wav) == wav  # WAV (mock): sin tocar
