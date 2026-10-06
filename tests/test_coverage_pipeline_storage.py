"""Cobertura de ramas de error de la orquestación (``pipeline``) y de la persistencia (``storage``),
sin red y con proveedores mock: pasos núcleo/opcionales que fallan, callbacks rotos, subidas no
soportadas, guardado que falla a medias, histórico ilegible y borrado defensivo."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from briefer import pipeline, storage
from briefer.config import Settings
from briefer.providers.mock import MockLLM
from briefer.schemas import Briefing, ChartAsset, Portfolio, Position, StepMetric

# ── utilidades de pasos ───────────────────────────────────────────────────────────


def test_usage_meter_and_llm_cost() -> None:
    meter = pipeline._UsageMeter()
    meter.add({"input_tokens": 10, "output_tokens": None, "cache_read_input_tokens": 5})  # type: ignore[dict-item]
    meter.add({"input_tokens": 1, "output_tokens": 2})
    assert (meter.calls, meter.input_tokens, meter.output_tokens) == (2, 11, 2)
    assert meter.usage["cache_read_input_tokens"] == 5

    llm = MockLLM()
    llm.last_usage = {"input_tokens": 100, "output_tokens": 100}
    assert pipeline._llm_cost(llm) == 0.0  # mock: sin coste
    metered = pipeline._MeteredLLM(llm)
    assert pipeline._llm_cost(metered) == 0.0


def test_core_step_wraps_errors() -> None:
    metrics: list[StepMetric] = []
    with pytest.raises(pipeline.StepNotImplementedError) as pending:
        with pipeline._core_step("media.x", "p", "m", metrics):
            raise NotImplementedError("pendiente")
    assert pending.value.step == "media.x" and isinstance(pending.value, NotImplementedError)

    inner = pipeline.PipelineStepError("otro", ValueError("v"))
    with pytest.raises(pipeline.PipelineStepError) as same:
        with pipeline._core_step("media.y", "p", "m", metrics):
            raise inner
    assert same.value is inner  # no se envuelve dos veces

    with pytest.raises(pipeline.PipelineStepError, match="media.z"):
        with pipeline._core_step("media.z", "p", "m", metrics):
            raise KeyError("k")
    assert [m.step for m in metrics] == ["media.x", "media.y", "media.z"]
    assert all(m.error for m in metrics)


def test_run_core_without_fallback_and_failing_fallback() -> None:
    metrics: list[StepMetric] = []

    def pending(_h):
        raise NotImplementedError("aún no")

    with pytest.raises(pipeline.StepNotImplementedError):
        pipeline._run_core("agents.x", "p", "m", metrics, pending)
    assert len(metrics) == 1

    def boom(_h):
        raise RuntimeError("también falla")

    fallback = pipeline._Fallback("mock", "mock-llm", boom, "mock")
    metrics.clear()
    with pytest.raises(pipeline.PipelineStepError, match="también falla"):
        pipeline._run_core("agents.y", "anthropic", "m", metrics, pending, fallback)
    assert [m.provider for m in metrics] == ["anthropic", "mock"]  # se registran los dos intentos


def test_optional_step_pending_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    metrics: list[StepMetric] = []

    def pending(_h):
        raise NotImplementedError("vídeo pendiente")

    with caplog.at_level("WARNING", logger="briefer.pipeline"):
        assert pipeline._optional_step("media.video", "moviepy", "-", metrics, pending) is None
    assert metrics[0].error and any("pendiente de implementar" in r.getMessage() for r in caplog.records)


def test_progress_callback_errors_are_swallowed() -> None:
    seen: list[str] = []

    def broken(text: str) -> None:
        seen.append(text)
        raise RuntimeError("la UI se cayó")

    progress = pipeline._Progress(broken, total=2)
    progress("uno")
    progress("dos")
    progress("tres")  # no pasa del total
    progress("fin", advance=False)
    assert seen == ["(1/2) uno", "(2/2) dos", "(2/2) tres", "(2/2) fin"]


def test_portfolio_chart_dir_purges_old_folders() -> None:
    first = pipeline._portfolio_chart_dir("20261005-000000-viejo")
    old = time.time() - (pipeline.PORTFOLIO_CHART_TTL_H + 1) * 3600
    os.utime(first, (old, old))
    second = pipeline._portfolio_chart_dir("20261005-000000-nuevo")
    try:
        assert not first.exists() and second.is_dir()
    finally:
        second.rmdir()


def test_process_upload_rejects_unknown_types(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "notas.docx"
    path.write_bytes(b"PK")
    metrics: list[StepMetric] = []
    with pytest.raises(ValueError, match="no soportado"):
        pipeline.process_upload(path, pipeline.get_providers(settings, use_mock=True), metrics)
    assert metrics[0].step == "ingest.upload" and metrics[0].error


def test_demo_voice_tts_is_edge(settings: Settings) -> None:
    assert pipeline.demo_voice_tts(settings).provider_name == "edge"


def test_resolve_mode_rejects_unknown() -> None:
    assert pipeline.resolve_mode(" MOCK ") == "mock"
    with pytest.raises(ValueError, match="Modo desconocido"):
        pipeline.resolve_mode("turbo")


# ── run_briefing: ramas opcionales ────────────────────────────────────────────────


def test_sample_news_without_matches_uses_all(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Solo noticias de empresas (ninguna de índices que rellene el filtro) y ninguna del ticker pedido.
    company_news = [n for n in pipeline.news_mod.load_sample_news() if not n.tickers[0].startswith("^")]
    monkeypatch.setattr(pipeline.news_mod, "load_sample_news", lambda: company_news)
    no_index = settings.model_copy(update={"briefer_context_tickers": ""})
    with caplog.at_level("INFO", logger="briefer.pipeline"):
        briefing = pipeline.run_briefing(["ZZZZ.MC"], settings=no_index, use_mock=True)
    assert len(briefing.context.news) == len(company_news)  # ficticias, aunque no citen el ticker
    assert any("se usan todas" in r.getMessage() for r in caplog.records)


def test_portfolio_chart_failure_does_not_break_briefing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("matplotlib roto")

    monkeypatch.setattr(pipeline.charts_mod, "make_portfolio_chart", boom)
    pf = Portfolio(name="P", positions=[Position(ticker="SAN.MC", weight=1.0)])
    briefing = pipeline.run_briefing([], portfolio=pf, settings=settings, use_mock=True)
    assert not any(c.kind == "portfolio_pie" for c in briefing.charts)
    assert briefing.charts  # los de precios sí


def test_cover_step_success(settings: Settings) -> None:
    briefing = pipeline.run_briefing(["SAN.MC"], settings=settings, use_mock=True, make_cover=True)
    cover_metric = next(m for m in briefing.metrics if m.step == "media.cover")
    assert briefing.cover_path and briefing.cover_path.is_file() and not cover_metric.error


def test_second_save_failure_keeps_first_json(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    real_save = storage.save_briefing
    calls: list[int] = []

    def flaky(briefing: Briefing, base_dir: Path | None = None) -> Path:
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disco lleno")
        return real_save(briefing, base_dir=base_dir)

    monkeypatch.setattr(pipeline.storage, "save_briefing", flaky)
    briefing = pipeline.run_briefing(["SAN.MC"], settings=settings, use_mock=True)
    assert len(calls) == 2
    saved = storage.load_briefing(briefing.id, base_dir=settings.output_path)
    assert not any(m.step == "storage.save" for m in saved.metrics)  # se quedó la 1.ª versión
    assert any(m.step == "storage.save" for m in briefing.metrics)


def test_answer_question_rejects_blank_text(settings: Settings) -> None:
    with pytest.raises(ValueError, match="vacía"):
        pipeline.answer_question("   ", settings=settings, use_mock=True)


def test_warmup_import_failure_is_logged(settings: Settings, monkeypatch: pytest.MonkeyPatch,
                                         caplog: pytest.LogCaptureFixture) -> None:
    edge = settings.model_copy(update={"briefer_tts_provider": "edge"})

    real_import = pipeline.importlib.import_module

    def no_edge_tts(name: str, *args):
        if name == "edge_tts":
            raise ImportError("No module named edge_tts")
        return real_import(name, *args)

    monkeypatch.setattr(pipeline.importlib, "import_module", no_edge_tts)
    with caplog.at_level("WARNING", logger="briefer.pipeline"):
        timings = pipeline.warmup(edge, mode="real")
    assert "tts" not in timings and "total" in timings
    assert any("warmup de tts" in r.getMessage() for r in caplog.records)


# ── storage ───────────────────────────────────────────────────────────────────────


def test_relative_paths_are_saved_as_posix(sample_briefing: Briefing, tmp_path: Path) -> None:
    rel = sample_briefing.model_copy(
        update={"charts": [ChartAsset(path=Path("charts") / "a.png", ticker="SAN.MC", kind="price_line")]}
    )
    path = storage.save_briefing(rel, base_dir=tmp_path)
    assert '"charts/a.png"' in path.read_text(encoding="utf-8")


def test_is_simulated_detects_fallback_errors(sample_briefing: Briefing) -> None:
    real = StepMetric(step="agents.analyst", provider="anthropic", model="m", latency_s=1, est_cost_eur=0.01)
    fallback = real.model_copy(update={"error": "Fallback a data/samples tras ConnectionError: x"})
    assert not storage.is_simulated_briefing(sample_briefing.model_copy(update={"metrics": [real]}))
    assert storage.is_simulated_briefing(sample_briefing.model_copy(update={"metrics": [real, fallback]}))
    assert not storage.is_simulated_briefing(sample_briefing.model_copy(update={"metrics": []}))


def test_prune_unknown_fields_passes_through_non_dicts() -> None:
    assert storage.prune_unknown_fields("texto", Briefing) == "texto"
    assert storage.prune_unknown_fields([1], Briefing) == [1]


def test_list_briefings_survives_scandir_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "20261005-090000-abcdef").mkdir()

    def denied(_path):
        raise PermissionError("acceso denegado")

    monkeypatch.setattr(storage.os, "scandir", denied)
    assert storage.list_briefings(tmp_path) == []
    assert storage.list_briefings(tmp_path, limit=0) == []


def test_summaries_mark_non_object_json(tmp_path: Path) -> None:
    folder = tmp_path / "20261005-090000-abcdef"
    folder.mkdir()
    (folder / storage.BRIEFING_FILE).write_text("[1, 2]", encoding="utf-8")
    (row,) = storage.briefing_summaries(tmp_path)
    assert row.error and row.id == "20261005-090000-abcdef"


def test_unlink_link_falls_back_to_rmdir(tmp_path: Path) -> None:
    empty = tmp_path / "vacia"
    empty.mkdir()
    assert storage._unlink_link(empty) and not empty.exists()  # unlink falla en carpetas: rmdir
    full = tmp_path / "llena"
    full.mkdir()
    (full / "f.txt").write_text("x", encoding="utf-8")
    assert storage._unlink_link(full) is False and full.exists()


def test_remove_entry_refuses_outside_root_and_reports_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, outside = tmp_path / "root", tmp_path / "fuera"
    root.mkdir()
    outside.mkdir()
    assert storage._remove_entry(outside, root.resolve()) is False and outside.exists()

    (root / "a").mkdir()
    (root / "a" / "x.bin").write_bytes(b"x")
    (root / "b.txt").write_text("y", encoding="utf-8")
    import shutil

    def locked(_path, *a, **k):
        raise PermissionError("en uso")

    monkeypatch.setattr(shutil, "rmtree", locked)
    dirs, files, failed = storage._clear_dir(root.resolve())
    assert (dirs, files, failed) == (0, 1, ["a"])  # el fichero suelto sí se borró


def test_delete_briefing_removes_links_without_following(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs, samples = tmp_path / "outputs", tmp_path / "samples"
    samples.mkdir()
    link = outputs / "20261005-090000-enlace"
    link.mkdir(parents=True)
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == link.name or real_is_symlink(self))
    assert storage.delete_briefing(link.name, base_dir=outputs, samples_dir=samples) is True
    assert not link.exists()

    link.mkdir()
    monkeypatch.setattr(storage, "_unlink_link", lambda _p: False)
    with pytest.raises(OSError, match="No se pudo quitar el enlace"):
        storage.delete_briefing(link.name, base_dir=outputs, samples_dir=samples)


def test_delete_user_data_with_nested_cache(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    outputs, samples = tmp_path / "outputs", tmp_path / "samples"
    cache = outputs / "cache"
    cache.mkdir(parents=True)
    samples.mkdir()
    (cache / "news.json").write_text("[]", encoding="utf-8")
    (outputs / "20261005-090000-abcdef").mkdir()
    with caplog.at_level("INFO", logger="briefer.storage"):
        report = storage.delete_user_data(output_dir=outputs, cache_dir=cache, samples_dir=samples)
    assert not report.failed and not any(outputs.iterdir())
    assert any("se solapan" in r.getMessage() for r in caplog.records)
