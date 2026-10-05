"""Briefing destacado de la portada: pregenerado (``data/samples/demo_briefing``) y último guardado."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from briefer import storage
from briefer.schemas import Briefing


def _with_files(briefing: Briefing, folder: Path) -> Briefing:
    """Copia del briefing con ficheros reales (audio, SRT, gráfico) en ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "podcast.mp3"
    audio.write_bytes(b"ID3fake")
    srt = folder / "podcast.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n", encoding="utf-8")
    chart = folder / "charts" / "SAN.MC_price.png"
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return briefing.model_copy(
        update={
            "audio": briefing.audio.model_copy(update={"path": audio}),
            "transcript": briefing.transcript.model_copy(update={"srt_path": srt}),
            "charts": [briefing.charts[0].model_copy(update={"path": chart})],
            "video": None,
        }
    )


def test_demo_briefing_dir_default_is_in_samples(settings) -> None:
    assert storage.demo_briefing_dir(settings.samples_path) == settings.samples_path / "demo_briefing"


def test_load_demo_briefing_missing_returns_none(tmp_path: Path) -> None:
    assert storage.load_demo_briefing(tmp_path / "samples") is None


def test_export_briefing_is_self_contained_and_portable(sample_briefing: Briefing, tmp_path: Path) -> None:
    src = _with_files(sample_briefing, tmp_path / "gen")
    samples = tmp_path / "samples"
    json_path = storage.export_briefing(src, storage.demo_briefing_dir(samples))

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["audio"]["path"] == "podcast.mp3"
    assert data["transcript"]["srt_path"] == "podcast.srt"
    assert data["charts"][0]["path"] == "charts/SAN.MC_price.png"
    assert data["video"] is None and data["cover_path"] is None

    # Se mueve la carpeta de samples entera (otra máquina / Docker): sigue cargando.
    moved = tmp_path / "otra_maquina" / "samples"
    shutil.move(str(samples), str(moved))
    shutil.rmtree(tmp_path / "gen")
    loaded = storage.load_demo_briefing(moved)
    assert loaded is not None
    assert loaded.id == sample_briefing.id
    assert Path(loaded.audio.path).read_bytes() == b"ID3fake"
    assert Path(loaded.transcript.srt_path).exists()
    assert all(Path(c.path).exists() for c in loaded.charts)


def test_export_drops_missing_files(sample_briefing: Briefing, tmp_path: Path) -> None:
    # sample_briefing apunta a ficheros que no existen
    loaded = storage.load_briefing(storage.export_briefing(sample_briefing, tmp_path / "demo"))
    assert loaded.audio is None
    assert loaded.charts == []
    assert loaded.video is None
    assert loaded.transcript is not None and loaded.transcript.srt_path is None


def test_featured_none_when_nothing(tmp_path: Path) -> None:
    assert storage.load_featured_briefing(tmp_path / "outputs", tmp_path / "samples") is None


def test_featured_falls_back_to_demo(sample_briefing: Briefing, tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    storage.export_briefing(_with_files(sample_briefing, tmp_path / "gen"), storage.demo_briefing_dir(samples))
    featured = storage.load_featured_briefing(tmp_path / "outputs", samples)
    assert featured is not None
    briefing, origin = featured
    assert origin == "pregenerado" and briefing.id == sample_briefing.id


def test_featured_prefers_latest_saved_and_skips_corrupt(sample_briefing: Briefing, tmp_path: Path) -> None:
    outputs, samples = tmp_path / "outputs", tmp_path / "samples"
    storage.export_briefing(_with_files(sample_briefing, tmp_path / "gen"), storage.demo_briefing_dir(samples))
    older = sample_briefing.model_copy(update={"id": "20261005-080000-aaaaaa"})
    storage.save_briefing(older, outputs)
    corrupt = outputs / "20261006-090000-bbbbbb"
    corrupt.mkdir(parents=True)
    (corrupt / storage.BRIEFING_FILE).write_text("{ roto", encoding="utf-8")

    briefing, origin = storage.load_featured_briefing(outputs, samples)
    assert origin == "guardado"
    assert briefing.id == "20261005-080000-aaaaaa"  # el corrupto (más reciente) se salta


def test_corrupt_demo_is_ignored_by_featured(tmp_path: Path) -> None:
    demo = storage.demo_briefing_dir(tmp_path / "samples")
    demo.mkdir(parents=True)
    (demo / storage.BRIEFING_FILE).write_text("[]", encoding="utf-8")
    with pytest.raises(Exception):
        storage.load_demo_briefing(tmp_path / "samples")
    assert storage.load_featured_briefing(tmp_path / "outputs", tmp_path / "samples") is None
