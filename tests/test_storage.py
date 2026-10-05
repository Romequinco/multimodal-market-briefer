"""Persistencia de briefings: round-trip JSON exacto, rutas portables y listado."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from briefer import storage
from briefer.schemas import AudioAsset, Briefing, ChartAsset, Transcript


def _inside(briefing: Briefing, folder: Path) -> Briefing:
    """Copia del briefing con sus ficheros dentro de ``folder`` (como los deja el pipeline)."""
    return briefing.model_copy(
        update={
            "audio": AudioAsset(path=folder / "podcast.mp3", duration_s=2.0, segments=briefing.audio.segments),
            "transcript": Transcript(text="A: Hola", srt_path=folder / "podcast.srt"),
            "charts": [ChartAsset(path=folder / "charts" / "SAN_MC_price.png", ticker="SAN.MC", kind="price_line")],
            "cover_path": folder / "cover.png",
        }
    )


def test_briefing_dir_creates_and_validates(tmp_path: Path) -> None:
    d = storage.briefing_dir("20261005-090000-abcdef", base_dir=tmp_path)
    assert d == tmp_path / "20261005-090000-abcdef" and d.is_dir()
    for bad in ("../fuera", "a/b", "a\\b", "..", ""):
        with pytest.raises(ValueError):
            storage.briefing_dir(bad, base_dir=tmp_path)


def test_round_trip_exact(sample_briefing: Briefing, tmp_path: Path) -> None:
    base = tmp_path / "outputs"
    briefing = _inside(sample_briefing, base / sample_briefing.id)
    path = storage.save_briefing(briefing, base_dir=base)

    assert path == base / briefing.id / "briefing.json"
    assert storage.load_briefing(path) == briefing
    assert storage.load_briefing(briefing.id, base_dir=base) == briefing
    assert storage.load_briefing(path.parent) == briefing


def test_round_trip_paths_outside_folder_stay_absolute(sample_briefing: Briefing, tmp_path: Path) -> None:
    # El fixture apunta a ficheros en tmp_path (fuera de la carpeta del briefing).
    path = storage.save_briefing(sample_briefing, base_dir=tmp_path / "outputs")
    assert storage.load_briefing(path) == sample_briefing


def test_saved_paths_are_relative_and_portable(sample_briefing: Briefing, tmp_path: Path) -> None:
    base = tmp_path / "outputs"
    briefing = _inside(sample_briefing, base / sample_briefing.id)
    path = storage.save_briefing(briefing, base_dir=base)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["audio"]["path"] == "podcast.mp3"
    assert data["charts"][0]["path"] == "charts/SAN_MC_price.png"
    assert data["cover_path"] == "cover.png"

    # Mover la carpeta: las rutas se resuelven contra la nueva ubicación
    moved = tmp_path / "otra_maquina" / briefing.id
    shutil.move(str(path.parent), str(moved))
    loaded = storage.load_briefing(moved / "briefing.json")
    assert loaded.audio.path == moved / "podcast.mp3"
    assert loaded.charts[0].path == moved / "charts" / "SAN_MC_price.png"
    assert loaded.model_dump(exclude={"audio", "transcript", "charts", "cover_path"}) == briefing.model_dump(
        exclude={"audio", "transcript", "charts", "cover_path"}
    )


def test_save_does_not_mutate_and_leaves_no_tmp(sample_briefing: Briefing, tmp_path: Path) -> None:
    before = sample_briefing.model_copy(deep=True)
    path = storage.save_briefing(sample_briefing, base_dir=tmp_path)
    assert sample_briefing == before
    assert [p.name for p in path.parent.iterdir()] == ["briefing.json"]


def test_list_briefings_newest_first(sample_briefing: Briefing, tmp_path: Path) -> None:
    assert storage.list_briefings(base_dir=tmp_path / "no_existe") == []
    ids = ["20261003-080000-aaaaaa", "20261005-090000-cccccc", "20261004-070000-bbbbbb"]
    for briefing_id in ids:
        storage.save_briefing(sample_briefing.model_copy(update={"id": briefing_id}), base_dir=tmp_path)
    (tmp_path / "carpeta_sin_json").mkdir()

    listed = storage.list_briefings(base_dir=tmp_path)
    assert [p.parent.name for p in listed] == sorted(ids, reverse=True)
    assert len(storage.list_briefings(base_dir=tmp_path, limit=2)) == 2


def test_default_base_dir_uses_settings(sample_briefing: Briefing, tmp_path: Path) -> None:
    # conftest apunta BRIEFER_OUTPUT_DIR a tmp_path / "outputs"
    path = storage.save_briefing(sample_briefing)
    assert path == tmp_path / "outputs" / sample_briefing.id / "briefing.json"
    assert storage.list_briefings() == [path]


def test_load_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        storage.load_briefing("20261005-090000-ffffff", base_dir=tmp_path)
