"""Vídeo corto del briefing (``media.video``): reparto de diapositivas, subtítulos ASS y MP4 real.

Sin red. El test de integración usa el ffmpeg de ``imageio-ffmpeg`` (se salta si no está) y un WAV
de silencio de ``MockTTS``; tarda ~1 s.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from briefer.media import podcast, video
from briefer.providers.mock import write_silence_wav
from briefer.schemas import AudioAsset, AudioSegment, VideoAsset


def _has_ffmpeg() -> bool:
    try:
        podcast.ffmpeg_exe()
        return True
    except Exception:
        return False


def _seg(speaker: str, text: str, start: float, end: float) -> AudioSegment:
    return AudioSegment(speaker=speaker, text=text, start_s=start, end_s=end)  # type: ignore[arg-type]


SEGMENTS = [
    _seg("A", "Buenas noches. Hoy Santander lidera el IBEX.", 0.0, 10.0),
    _seg("B", "Vamos a desglosar el día en los mercados.", 10.0, 20.0),
    _seg("A", "Empecemos por el Banco Santander, que sube un 3 %.", 20.0, 40.0),
    _seg("B", "En Estados Unidos, Apple y NVIDIA también suben.", 40.0, 60.0),
    _seg("A", "Iberdrola cierra plana.", 60.0, 80.0),
    _seg("B", "Recuerda: voces sintéticas, no es asesoramiento.", 80.0, 100.0),
]


# ── Reparto de diapositivas ────────────────────────────────────────────────────────


def test_image_keywords_from_chart_names() -> None:
    assert "Santander" in video.image_keywords(Path("charts/SAN_MC_price.png"))
    assert "Santander" in video.image_keywords(Path("price_SAN.MC.png"))
    assert "AAPL" in video.image_keywords(Path("AAPL_price.png"))
    assert video.image_keywords(Path("overview_change.png")) == []
    assert video.image_keywords(Path("portfolio_weights.png")) == []
    assert video.image_keywords(Path("cover.png")) == []


def test_plan_slides_uniform_without_segments() -> None:
    imgs = [Path("a.png"), Path("b.png"), Path("c.png"), Path("d.png")]
    plan = video.plan_slides(imgs, 40.0)
    assert [p for p, _ in plan] == imgs
    assert all(d == pytest.approx(10.0) for _, d in plan)
    assert video.plan_slides([], 40.0) == []
    assert video.plan_slides(imgs[:1], 12.5) == [(imgs[0], 12.5)]


def test_plan_slides_uniform_without_mentions() -> None:
    imgs = [Path("cover.png"), Path("overview_change.png")]
    plan = video.plan_slides(imgs, 100.0, SEGMENTS)
    assert [d for _, d in plan] == pytest.approx([50.0, 50.0])


def test_plan_slides_aligned_by_ticker() -> None:
    imgs = [Path("overview_change.png"), Path("IBE_MC_price.png"), Path("SAN_MC_price.png"),
            Path("AAPL_price.png")]
    plan = video.plan_slides(imgs, 100.0, SEGMENTS)
    names = [p.name for p, _ in plan]
    # El general abre; luego cada valor en el orden en que se menciona (la apertura no cuenta).
    assert names == ["overview_change.png", "SAN_MC_price.png", "AAPL_price.png", "IBE_MC_price.png"]
    starts = [sum(d for _, d in plan[:i]) for i in range(len(plan))]
    assert 20.0 <= starts[1] < 30.0  # «Banco Santander», dentro del tercer tramo
    assert 40.0 <= starts[2] < 60.0  # «Apple»
    assert starts[3] == pytest.approx(60.0)  # «Iberdrola» abre el quinto tramo
    assert sum(d for _, d in plan) == pytest.approx(100.0)


def test_plan_slides_places_unmentioned_and_keeps_minimum() -> None:
    imgs = [Path("cover.png"), Path("SAN_MC_price.png"), Path("NVDA_price.png"), Path("overview_change.png")]
    plan = video.plan_slides(imgs, 100.0, SEGMENTS, min_slide_s=3.0)
    assert {p.name for p, _ in plan} == {p.name for p in imgs}
    assert plan[0][0].name == "cover.png"
    assert sum(d for _, d in plan) == pytest.approx(100.0)
    assert all(d >= 3.0 for _, d in plan)


def test_plan_slides_short_audio_falls_back_to_uniform() -> None:
    imgs = [Path("overview_change.png"), Path("SAN_MC_price.png")]
    plan = video.plan_slides(imgs, 4.0, SEGMENTS, min_slide_s=3.0)
    assert [d for _, d in plan] == pytest.approx([2.0, 2.0])


# ── Subtítulos ASS ─────────────────────────────────────────────────────────────────


def test_ass_timestamp_and_escape() -> None:
    assert video.ass_timestamp(0) == "0:00:00.00"
    assert video.ass_timestamp(3.5) == "0:00:03.50"
    assert video.ass_timestamp(3725.257) == "1:02:05.26"
    assert video.ass_timestamp(-2) == "0:00:00.00"
    assert video.ass_escape("a {\\b1} b\\Nc\n  d") == "a (/b1) b/Nc d"


def test_build_ass_events_times_and_speakers() -> None:
    segs = [
        _seg("A", "Hola {mundo}", 0.0, 2.0),
        _seg("B", " ".join(["palabra"] * 30), 2.0, 12.0),  # larga: se trocea
        _seg("A", "   ", 12.0, 13.0),  # vacía: se omite
    ]
    ass = video.build_ass(segs, (720, 1280), {"A": "Toro", "B": "Osa"})
    assert "PlayResX: 720" in ass and "PlayResY: 1280" in ass
    assert "Style: Default,DejaVu Sans," in ass
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(events) >= 3
    assert events[0].startswith("Dialogue: 0,0:00:00.00,0:00:02.00,Default,")
    assert "TORO" in events[0] and "Hola (mundo)" in events[0] and "{mundo}" not in events[0]
    assert all("OSA" in e for e in events[1:])
    assert events[1].split(",")[1] == "0:00:02.00"
    assert events[-1].split(",")[2] == "0:00:12.00"  # el último trozo acaba con el segmento
    # Cada bloque: nombre + como mucho 2 filas.
    assert all(e.count("\\N") <= video.SUB_MAX_ROWS for e in events)
    assert video.build_ass([], (720, 1280), {}).rstrip().endswith("Text")


# ── MP4 real (integración, ~1 s) ───────────────────────────────────────────────────


def _probe(path: Path) -> tuple[float, tuple[int, int], str]:
    proc = subprocess.run([podcast.ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    err = proc.stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err).groups()  # type: ignore[union-attr]
    w, hh = re.search(r"Video: .*?, (\d{2,5})x(\d{2,5})", err).groups()  # type: ignore[union-attr]
    return int(h) * 3600 + int(m) * 60 + float(s), (int(w), int(hh)), err


def _png(path: Path, size: tuple[int, int], color: str) -> Path:
    from PIL import Image

    Image.new("RGB", size, color).save(path)
    return path


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg (imageio-ffmpeg) no disponible")
def test_make_video_real_mp4(tmp_path: Path) -> None:
    wav = write_silence_wav(tmp_path / "podcast.wav", duration_s=2.5)
    audio = AudioAsset(path=wav, duration_s=2.5, segments=[
        _seg("A", "Santander sube: C:\\ruta {raro}", 0.0, 1.2),
        _seg("B", "Voces sintéticas.", 1.2, 2.5),
    ])
    imgs = [_png(tmp_path / "overview_change.png", (320, 180), "#224466"),
            _png(tmp_path / "SAN_MC_price.png", (320, 180), "#664422")]
    out = tmp_path / "sub dir" / "briefing.mp4"
    asset = video.make_video(audio, imgs, out, title="Titular de prueba")
    assert isinstance(asset, VideoAsset)
    assert asset.path == out and out.is_file() and out.stat().st_size > 1000
    assert asset.duration_s == pytest.approx(2.5)
    duration, size, info = _probe(out)
    assert duration == pytest.approx(2.5, abs=0.3)
    assert size == (720, 1280)
    assert "Audio: aac" in info
    assert "Voces sintéticas generadas por IA" in info  # metadatos (comment)


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg (imageio-ffmpeg) no disponible")
def test_make_video_without_images_or_segments(tmp_path: Path) -> None:
    wav = write_silence_wav(tmp_path / "podcast.wav", duration_s=1.5)
    asset = video.make_video(AudioAsset(path=wav, duration_s=1.5), [tmp_path / "no_existe.png"],
                             tmp_path / "v.mp4", size=(360, 640))
    duration, size, _ = _probe(asset.path)
    assert size == (360, 640) and duration == pytest.approx(1.5, abs=0.3)


def test_make_video_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="No existe el audio"):
        video.make_video(AudioAsset(path=tmp_path / "nada.mp3", duration_s=3.0), [], tmp_path / "v.mp4")
    wav = write_silence_wav(tmp_path / "a.wav", duration_s=0.5)
    with pytest.raises(ValueError, match="pares"):
        video.make_video(AudioAsset(path=wav, duration_s=0.5), [], tmp_path / "v.mp4", size=(721, 1280))

    def no_ffmpeg() -> str:
        raise RuntimeError("No se encontró ffmpeg")

    monkeypatch.setattr(video, "ffmpeg_exe", no_ffmpeg)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        video.make_video(AudioAsset(path=wav, duration_s=0.5), [], tmp_path / "v.mp4")


def test_make_video_cleans_temp_dir_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = write_silence_wav(tmp_path / "a.wav", duration_s=0.5)
    created: list[Path] = []
    real_mkdtemp = video.tempfile.mkdtemp

    def tracking_mkdtemp(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(dir=tmp_path, prefix="w_")
        created.append(Path(path))
        return path

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("ffmpeg falló al montar el vídeo")

    monkeypatch.setattr(video.tempfile, "mkdtemp", tracking_mkdtemp)
    monkeypatch.setattr(video, "_run_ffmpeg", boom)
    with pytest.raises(RuntimeError):
        video.make_video(AudioAsset(path=wav, duration_s=0.5), [], tmp_path / "v.mp4")
    assert created and not created[0].exists()
    assert not (tmp_path / "v.mp4").exists()
