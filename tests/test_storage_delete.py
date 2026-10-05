"""«Borrar mis datos» (RGPD): ``storage.delete_user_data`` y ``storage.delete_briefing``.

Siempre con carpetas temporales; se comprueba que ``data/samples`` (el pregenerado) nunca se toca y
que las rutas peligrosas se rechazan antes de borrar nada.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from briefer import storage
from briefer.config import ROOT_DIR


def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    outputs, cache, samples = tmp_path / "outputs", tmp_path / "cache", tmp_path / "samples"
    for i in range(2):
        d = outputs / f"2026100{i}-090000-abcdef"
        (d / "charts").mkdir(parents=True)
        (d / storage.BRIEFING_FILE).write_text("{}", encoding="utf-8")
        (d / "podcast.mp3").write_bytes(b"x")
        (d / "charts" / "a.png").write_bytes(b"x")
    (cache / "uploads" / "run_1").mkdir(parents=True)
    (cache / "uploads" / "run_1" / "doc.pdf").write_bytes(b"x")
    (cache / "news_2026-10-05.json").write_text("[]", encoding="utf-8")
    (samples / storage.DEMO_BRIEFING_DIRNAME).mkdir(parents=True)
    (samples / storage.DEMO_BRIEFING_DIRNAME / storage.BRIEFING_FILE).write_text("{}", encoding="utf-8")
    return outputs, cache, samples


def test_delete_user_data_empties_outputs_and_cache(tmp_path: Path) -> None:
    outputs, cache, samples = _tree(tmp_path)
    report = storage.delete_user_data(output_dir=outputs, cache_dir=cache, samples_dir=samples)
    assert report.briefings == 2 and report.output_files == 6 and report.cache_files == 2
    assert report.total_files == 8 and not report.failed
    assert outputs.is_dir() and not any(outputs.iterdir())  # la carpeta se queda, vacía
    assert cache.is_dir() and not any(cache.iterdir())
    assert (samples / storage.DEMO_BRIEFING_DIRNAME / storage.BRIEFING_FILE).is_file()


def test_delete_user_data_only_selected_parts(tmp_path: Path) -> None:
    outputs, cache, samples = _tree(tmp_path)
    report = storage.delete_user_data(outputs=False, output_dir=outputs, cache_dir=cache, samples_dir=samples)
    assert report.briefings == 0 and report.cache_files == 2
    assert len(storage.list_briefings(outputs)) == 2
    report = storage.delete_user_data(cache=False, output_dir=outputs, cache_dir=cache, samples_dir=samples)
    assert report.briefings == 2 and storage.list_briefings(outputs) == []


def test_delete_user_data_missing_dirs_is_noop(tmp_path: Path) -> None:
    report = storage.delete_user_data(output_dir=tmp_path / "nope", cache_dir=tmp_path / "nada",
                                      samples_dir=tmp_path / "samples")
    assert report == storage.DeletionReport()


def test_delete_user_data_uses_settings_by_default(tmp_path: Path) -> None:
    # conftest apunta BRIEFER_OUTPUT_DIR / BRIEFER_CACHE_DIR a tmp_path; samples es el del repo
    folder = storage.briefing_dir("20261005-090000-abcdef")
    (folder / storage.BRIEFING_FILE).write_text("{}", encoding="utf-8")
    report = storage.delete_user_data()
    assert report.briefings == 1 and storage.list_briefings() == []
    assert (ROOT_DIR / "data" / "samples").is_dir()


@pytest.mark.parametrize("which", ["samples", "inside_samples", "parent_of_samples"])
def test_delete_user_data_refuses_samples(tmp_path: Path, which: str) -> None:
    outputs, cache, samples = _tree(tmp_path)
    target = {"samples": samples, "inside_samples": samples / storage.DEMO_BRIEFING_DIRNAME,
              "parent_of_samples": tmp_path}[which]
    with pytest.raises(ValueError):
        storage.delete_user_data(output_dir=target, cache_dir=cache, samples_dir=samples)
    with pytest.raises(ValueError):
        storage.delete_user_data(output_dir=outputs, cache_dir=target, samples_dir=samples)
    # nada se ha borrado: la validación va antes que el borrado
    assert len(storage.list_briefings(outputs)) == 2 and (cache / "news_2026-10-05.json").is_file()
    assert (samples / storage.DEMO_BRIEFING_DIRNAME / storage.BRIEFING_FILE).is_file()


@pytest.mark.parametrize("danger", ["anchor", "home", "repo", "repo_data"])
def test_delete_user_data_refuses_dangerous_roots(tmp_path: Path, danger: str) -> None:
    target = {"anchor": Path(tmp_path.anchor), "home": Path.home(), "repo": ROOT_DIR,
              "repo_data": ROOT_DIR / "data"}[danger]
    with pytest.raises(ValueError):
        storage.delete_user_data(output_dir=target, cache=False, samples_dir=tmp_path / "samples")


def test_delete_user_data_does_not_follow_symlinks(tmp_path: Path) -> None:
    outputs, cache, samples = _tree(tmp_path)
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "importante.txt").write_text("no borrar", encoding="utf-8")
    try:
        os.symlink(outside, outputs / "enlace", target_is_directory=True)
    except (OSError, NotImplementedError):
        try:  # Windows sin privilegios: un junction es el enlace equivalente y no los necesita
            import _winapi

            _winapi.CreateJunction(str(outside), str(outputs / "enlace"))
        except (ImportError, OSError):
            pytest.skip("este sistema no permite crear enlaces")
    storage.delete_user_data(output_dir=outputs, cache_dir=cache, samples_dir=samples)
    assert not (outputs / "enlace").exists()
    assert (outside / "importante.txt").read_text(encoding="utf-8") == "no borrar"


def test_delete_briefing_removes_only_that_folder(tmp_path: Path) -> None:
    outputs, _cache, samples = _tree(tmp_path)
    assert storage.delete_briefing("20261000-090000-abcdef", outputs, samples_dir=samples) is True
    assert [p.parent.name for p in storage.list_briefings(outputs)] == ["20261001-090000-abcdef"]
    assert storage.delete_briefing("20261000-090000-abcdef", outputs, samples_dir=samples) is False


@pytest.mark.parametrize("bad_id", ["", "..", "../samples", "a/b", "a\\b", ".oculto"])
def test_delete_briefing_rejects_bad_ids(tmp_path: Path, bad_id: str) -> None:
    outputs, _cache, samples = _tree(tmp_path)
    with pytest.raises(ValueError):
        storage.delete_briefing(bad_id, outputs, samples_dir=samples)
    assert len(storage.list_briefings(outputs)) == 2


def test_delete_briefing_refuses_samples_as_output_dir(tmp_path: Path) -> None:
    _outputs, _cache, samples = _tree(tmp_path)
    with pytest.raises(ValueError):
        storage.delete_briefing(storage.DEMO_BRIEFING_DIRNAME, samples, samples_dir=samples)
    assert (samples / storage.DEMO_BRIEFING_DIRNAME / storage.BRIEFING_FILE).is_file()
