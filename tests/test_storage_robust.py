"""Robustez de ``storage`` (D2): briefings de otra versión o corruptos, listado rápido, ZIP portable y
escrituras atómicas sin restos."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from briefer import storage
from briefer.schemas import Briefing


def _save(briefing: Briefing, base: Path, **update) -> Path:
    return storage.save_briefing(briefing.model_copy(update=update), base_dir=base)


def test_load_ignores_unknown_fields_from_newer_contract(sample_briefing: Briefing, tmp_path: Path) -> None:
    path = _save(sample_briefing, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["campo_futuro"] = 1
    data["analysis"]["key_points"][0]["impacto"] = "alto"
    data["metrics"][0]["tokens"] = 12
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = storage.load_briefing(path)
    assert loaded.id == sample_briefing.id
    assert loaded.analysis.key_points[0].title == sample_briefing.analysis.key_points[0].title


def test_load_still_fails_on_missing_required_fields(sample_briefing: Briefing, tmp_path: Path) -> None:
    path = _save(sample_briefing, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["analysis"]
    data["extra"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        storage.load_briefing(path)


def test_load_accepts_utf8_bom(sample_briefing: Briefing, tmp_path: Path) -> None:
    path = _save(sample_briefing, tmp_path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())  # guardado con el Bloc de notas
    assert storage.load_briefing(path).id == sample_briefing.id


def test_load_rejects_non_object_json(tmp_path: Path) -> None:
    folder = tmp_path / "20261005-000000-aaaaaa"
    folder.mkdir()
    (folder / storage.BRIEFING_FILE).write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        storage.load_briefing(folder)


def test_prune_unknown_fields_reports_paths(sample_briefing: Briefing) -> None:
    data = sample_briefing.model_dump(mode="json")
    data["x"] = 1
    data["charts"][0]["y"] = 2
    dropped: list[str] = []
    pruned = storage.prune_unknown_fields(data, Briefing, dropped)
    assert sorted(dropped) == ["charts[].y", "x"]
    assert Briefing.model_validate(pruned).id == sample_briefing.id


def test_list_briefings_fast_and_ignores_noise(sample_briefing: Briefing, tmp_path: Path) -> None:
    ids = [f"20261005-0900{i:02d}-abcdef" for i in range(30)]
    for briefing_id in ids:
        _save(sample_briefing, tmp_path, id=briefing_id)
    (tmp_path / "zz_sin_json").mkdir()            # carpeta sin briefing.json
    (tmp_path / "suelto.txt").write_text("x")      # fichero suelto
    listed = storage.list_briefings(tmp_path, limit=5)
    assert [p.parent.name for p in listed] == sorted(ids, reverse=True)[:5]
    assert storage.list_briefings(tmp_path, limit=0) == []
    assert storage.list_briefings(tmp_path / "no_existe") == []


def test_briefing_summaries_marks_corrupt_rows(sample_briefing: Briefing, tmp_path: Path) -> None:
    good = _save(sample_briefing, tmp_path, id="20261005-090000-aaaaaa")
    bad_dir = tmp_path / "20261005-100000-bbbbbb"
    bad_dir.mkdir()
    (bad_dir / storage.BRIEFING_FILE).write_text("{ roto", encoding="utf-8")
    rows = storage.briefing_summaries(tmp_path)
    assert [r.id for r in rows] == ["20261005-100000-bbbbbb", "20261005-090000-aaaaaa"]
    corrupt, ok = rows
    assert corrupt.error and "JSONDecodeError" in corrupt.error
    assert ok.error is None and ok.path == good
    assert ok.headline == sample_briefing.analysis.headline
    assert ok.tickers == ["SAN.MC"] and ok.duration_s == 2.0 and ok.n_charts == 1
    assert ok.has_audio is False  # el fichero de audio del fixture no existe
    assert ok.demo is False       # el fixture no tiene pasos de agentes


def test_export_zip_is_portable(sample_briefing: Briefing, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    audio = src / "podcast.mp3"
    audio.write_bytes(b"ID3fake")
    srt = src / "podcast.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n", encoding="utf-8")
    chart = src / "c.png"
    chart.write_bytes(b"\x89PNG")
    briefing = sample_briefing.model_copy(update={
        "audio": sample_briefing.audio.model_copy(update={"path": audio}),
        "transcript": sample_briefing.transcript.model_copy(update={"srt_path": srt}),
        "charts": [sample_briefing.charts[0].model_copy(update={"path": chart})],
    })
    data = storage.export_briefing_zip(briefing)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert f"{briefing.id}/briefing.json" in names
        assert f"{briefing.id}/podcast.mp3" in names and f"{briefing.id}/charts/c.png" in names
        raw = json.loads(zf.read(f"{briefing.id}/briefing.json"))
        assert raw["audio"]["path"] == "podcast.mp3"  # rutas relativas
        dest = tmp_path / "otra_maquina"
        zf.extractall(dest)
    loaded = storage.load_briefing(dest / briefing.id)
    assert loaded.audio.path.read_bytes() == b"ID3fake"
    assert loaded.charts[0].path.exists()


def test_export_zip_rejects_bad_id(sample_briefing: Briefing) -> None:
    with pytest.raises(ValueError):
        storage.export_briefing_zip(sample_briefing.model_copy(update={"id": "../fuera"}))


def test_failed_write_leaves_no_temp(sample_briefing: Briefing, tmp_path: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        storage.save_briefing(sample_briefing, base_dir=tmp_path)
    folder = tmp_path / sample_briefing.id
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]
    assert not (folder / storage.BRIEFING_FILE).exists()
