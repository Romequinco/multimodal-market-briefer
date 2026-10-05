"""``scripts/metrics_report.py``: informe de latencia y coste con briefings sintéticos (sin red)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from briefer import storage
from briefer.config import ROOT_DIR
from briefer.schemas import Briefing, StepMetric

_SPEC = importlib.util.spec_from_file_location("metrics_report", ROOT_DIR / "scripts" / "metrics_report.py")
assert _SPEC and _SPEC.loader
mr = importlib.util.module_from_spec(_SPEC)
sys.modules["metrics_report"] = mr
_SPEC.loader.exec_module(mr)


def _m(step: str, provider: str, latency: float, cost: float = 0.0, model: str = "-",
       error: str | None = None) -> StepMetric:
    return StepMetric(step=step, provider=provider, model=model, latency_s=latency, est_cost_eur=cost, error=error)


def _real_metrics(analyst_latency: float = 10.0, analyst_cost: float = 0.02, uploads: bool = False) -> list[StepMetric]:
    metrics = [
        _m("ingest.news", "yfinance+rss", 5.0),
        _m("ingest.prices", "yfinance", 4.0),
    ]
    if uploads:
        metrics.append(_m("ingest.pdf", "anthropic", 20.0, 0.015, "claude-sonnet-5-5"))
    metrics += [
        _m("agents.analyst", "anthropic", analyst_latency, analyst_cost, "claude-sonnet-5-5"),
        _m("agents.scriptwriter", "anthropic", 12.0, 0.009, "claude-haiku-4-5"),
        _m("media.podcast", "edge", 15.0, model="edge-tts"),
        _m("storage.save", "local", 0.5),
    ]
    return metrics


def _save(sample: Briefing, base: Path, start: datetime, wall_s: float, metrics: list[StepMetric],
          suffix: str = "aaaaaa") -> Briefing:
    briefing = sample.model_copy(update={
        "id": f"{start:%Y%m%d-%H%M%S}-{suffix}",
        "created_at": start + timedelta(seconds=wall_s),
        "metrics": metrics,
    })
    storage.save_briefing(briefing, base_dir=base)
    return briefing


T0 = datetime(2026, 10, 5, 9, 0, 0)


# ── Percentiles ────────────────────────────────────────────────────────────────────


def test_percentile_linear_interpolation() -> None:
    assert mr.percentile([], 50) is None
    assert mr.percentile([7.0], 95) == 7.0
    assert mr.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert mr.percentile([10, 20], 95) == pytest.approx(19.5)
    assert mr.percentile([3, 1, 2], 0) == 1 and mr.percentile([3, 1, 2], 100) == 3
    # Igual que numpy.percentile(method="linear") para 1..10
    assert mr.percentile(list(range(1, 11)), 95) == pytest.approx(9.55)


# ── Modo, pared y subidas ──────────────────────────────────────────────────────────


def test_infer_mode(sample_briefing: Briefing) -> None:
    real = sample_briefing.model_copy(update={"metrics": _real_metrics()})
    mock = sample_briefing.model_copy(update={"metrics": [
        _m("ingest.news", "samples", 0.1), _m("agents.analyst", "mock", 0.1), _m("media.podcast", "mock", 0.1)]})
    demo = sample_briefing.model_copy(update={"metrics": [
        _m("ingest.news", "samples", 0.1), _m("agents.analyst", "mock", 0.1), _m("media.podcast", "edge", 3.0)]})
    fell_back = sample_briefing.model_copy(update={"metrics": [
        _m("ingest.news", "samples", 0.1, error="Fallback a data/samples tras Timeout: x"),
        _m("agents.analyst", "anthropic", 9.0, 0.02)]})
    no_news = sample_briefing.model_copy(update={"metrics": [_m("agents.analyst", "mock", 0.1)]})
    assert mr.infer_mode(real) == "real"
    assert mr.infer_mode(mock) == "mock"
    assert mr.infer_mode(demo) == "demo_voices"
    assert mr.infer_mode(fell_back) == "real"
    assert mr.infer_mode(no_news) == "mock"


def test_wall_clock_from_id_and_created_at(sample_briefing: Briefing) -> None:
    b = sample_briefing.model_copy(update={
        "id": "20261005-090000-abcdef", "created_at": T0 + timedelta(seconds=60),
        "metrics": [_m("agents.analyst", "anthropic", 10), _m("delivery.email", "email", 2.0),
                    _m("storage.save", "local", 0.5)],
    })
    assert mr.estimate_wall_clock_s(b) == pytest.approx(62.5)
    assert mr.estimate_wall_clock_s(b.model_copy(update={"id": "sin-fecha"})) is None
    assert mr.estimate_wall_clock_s(b.model_copy(update={"created_at": T0 - timedelta(seconds=5)})) is None


def test_uploads_label(sample_briefing: Briefing) -> None:
    assert mr.uploads_label(sample_briefing.model_copy(update={"metrics": _real_metrics()})) == "sin subidas"
    assert mr.uploads_label(sample_briefing.model_copy(update={"metrics": _real_metrics(uploads=True)})) == "pdf"


# ── Recogida y agregados ───────────────────────────────────────────────────────────


def test_collect_and_report_only_real_by_default(sample_briefing: Briefing, tmp_path: Path) -> None:
    _save(sample_briefing, tmp_path, T0, 40.0, _real_metrics(10.0, 0.02), "aaaaaa")
    _save(sample_briefing, tmp_path, T0 + timedelta(hours=1), 60.0, _real_metrics(20.0, 0.04, uploads=True), "bbbbbb")
    _save(sample_briefing, tmp_path, T0 + timedelta(hours=2), 1.0,
          [_m("ingest.news", "samples", 0.1), _m("agents.analyst", "mock", 0.1), _m("media.podcast", "mock", 0.1)],
          "cccccc")
    col = mr.collect([tmp_path])
    assert len(col.rows) == 3 and not col.warnings
    report = mr.build_report(col)
    assert report["counts_by_mode"] == {"real": 2, "demo_voices": 0, "mock": 1}
    assert report["n_selected"] == 2
    totals = report["totals"]
    assert totals["wall_clock_s"]["p50"] == pytest.approx(50.5)  # (40,5 + 60,5) / 2 (incluye storage.save)
    assert totals["cost_eur"]["total"] == pytest.approx(0.02 + 0.009 + 0.04 + 0.009 + 0.015)
    analyst = next(s for s in report["steps"] if s["step"] == "agents.analyst")
    assert analyst["latency_s"]["n"] == 2
    assert analyst["latency_s"]["p50"] == pytest.approx(15.0)
    assert analyst["latency_s"]["p95"] == pytest.approx(19.5)
    assert analyst["cost_eur"]["p95"] == pytest.approx(0.039)
    pdf = next(s for s in report["steps"] if s["step"] == "ingest.pdf")
    assert pdf["latency_s"]["n"] == 1
    assert {g["uploads"] for g in report["by_uploads"]} == {"pdf", "sin subidas"}
    assert report["fallbacks"]["steps"] == 0
    assert report["qa"]["metrics_persisted"] is False
    assert mr.build_report(col, "mock")["n_selected"] == 1
    assert mr.build_report(col, "todos")["n_selected"] == 3


def test_fallbacks_and_errors_are_counted(sample_briefing: Briefing, tmp_path: Path) -> None:
    metrics = _real_metrics()
    metrics[0] = _m("ingest.news", "samples", 0.2, error="Fallback a data/samples tras Timeout: x")
    metrics.append(_m("delivery.telegram", "telegram", 1.0, error="ConnectionError: caído"))
    _save(sample_briefing, tmp_path, T0, 30.0, metrics)
    report = mr.build_report(mr.collect([tmp_path]))
    assert report["fallbacks"] == {"steps": 1, "briefings_with_fallback": 1, "by_step": {"ingest.news": 1}}
    assert report["errors"]["by_step"] == {"delivery.telegram": 1}


def test_collect_skips_corrupt_and_empty_folders(sample_briefing: Briefing, tmp_path: Path) -> None:
    _save(sample_briefing, tmp_path, T0, 40.0, _real_metrics())
    (tmp_path / "20261005-100000-rotoxx").mkdir()
    (tmp_path / "20261005-100000-rotoxx" / storage.BRIEFING_FILE).write_text("{no json", encoding="utf-8")
    (tmp_path / "20261005-110000-faltan").mkdir()
    (tmp_path / "20261005-110000-faltan" / storage.BRIEFING_FILE).write_text(json.dumps({"id": "x"}), encoding="utf-8")
    empty = tmp_path / "20261005-120000-vaciox"
    (empty / "qa").mkdir(parents=True)
    (empty / "qa" / "respuesta_1.mp3").write_bytes(b"x")
    col = mr.collect([tmp_path, tmp_path / "no-existe"])
    assert len(col.rows) == 1
    assert len(col.warnings) == 4
    assert col.qa_audio_orphans == 1


def test_duplicate_ids_counted_once_and_qa_audio_attributed(sample_briefing: Briefing, tmp_path: Path) -> None:
    outputs, demo = tmp_path / "outputs", tmp_path / "demo_briefing"
    b = _save(sample_briefing, outputs, T0, 40.0, _real_metrics())
    storage.export_briefing(b, demo)  # el pregenerado: misma id, carpeta que contiene el JSON
    # Carpeta original sin JSON pero con audios del Q&A (como en data/outputs real)
    (outputs / b.id / storage.BRIEFING_FILE).unlink()
    (outputs / b.id / "qa").mkdir()
    (outputs / b.id / "qa" / "respuesta_1.mp3").write_bytes(b"x")
    col = mr.collect([outputs, demo])
    assert [r.id for r in col.rows] == [b.id]
    assert col.rows[0].qa_audio_files == 1 and col.qa_audio_orphans == 0
    # Y con las dos copias del JSON: se cuenta una vez
    storage.save_briefing(b, base_dir=outputs)
    col = mr.collect([outputs, demo])
    assert len(col.rows) == 1 and any("repetido" in w for w in col.warnings)


# ── Salidas ────────────────────────────────────────────────────────────────────────


def test_render_text_uses_decimal_comma_and_markdown(sample_briefing: Briefing, tmp_path: Path) -> None:
    _save(sample_briefing, tmp_path, T0, 40.0, _real_metrics(10.25, 0.0213))
    report = mr.build_report(mr.collect([tmp_path]))
    text = mr.render_text(report)
    assert "0,0303 €" in text  # 0,0213 + 0,009
    assert "40,5 s" in text
    assert "orientativo" in text  # N < 5
    md = mr.render_text(report, markdown=True)
    assert "| Paso | Proveedor/modelo |" in md and "| --- |" in md
    assert "| agents.analyst | anthropic/claude-sonnet-5-5 | 1 |" in md


def test_render_empty_report() -> None:
    text = mr.render_text(mr.build_report(mr.Collection()))
    assert "nada que medir" in text


def test_main_json_and_include_demo(sample_briefing: Briefing, tmp_path: Path,
                                    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    _save(sample_briefing, tmp_path, T0, 40.0, _real_metrics())
    samples = tmp_path / "samples"
    demo = _save(sample_briefing, tmp_path / "otro", T0 + timedelta(hours=3), 80.0, _real_metrics(uploads=True), "dddddd")
    storage.export_briefing(demo, samples / storage.DEMO_BRIEFING_DIRNAME)
    monkeypatch.setattr(storage, "demo_briefing_dir", lambda samples_dir=None: samples / storage.DEMO_BRIEFING_DIRNAME)
    assert mr.main(["--dir", str(tmp_path / "20261005-090000-aaaaaa"), "--include-demo", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["n_selected"] == 2
    assert data["percentile_method"].startswith("interpolación lineal")
    assert mr.main(["--dir", str(tmp_path / "nada"), "--markdown"]) == 0
    captured = capsys.readouterr()
    assert "nada que medir" in captured.out and "no existe" in captured.err
