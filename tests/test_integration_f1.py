"""Integración de la Fase 1 (sin red): modos de ejecución, índices de contexto, caché, TTS del
Q&A normalizado, paralelismo del podcast, compatibilidad de contratos v0.2 -> v0.3 y traza de la UI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from briefer import pipeline, storage
from briefer.config import Settings
from briefer.logging_utils import step_fell_back
from briefer.providers.mock import MockTTS
from briefer.schemas import CONTRACTS_VERSION, Briefing, StepMetric

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.trace import build_nodes, fallback_tag, has_real_voices, is_demo_run, node_label  # noqa: E402


class RecordingTTS(MockTTS):
    """TTS falso que se hace pasar por edge-tts y guarda los textos que recibe."""

    provider_name = "edge"
    model = "edge-tts"

    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    def synthesize(self, text, voice, out_path):
        self.texts.append(text)
        return super().synthesize(text, voice, out_path)


def _by_step(metrics: list[StepMetric]) -> dict[str, StepMetric]:
    return {m.step: m for m in metrics}


# ── Contratos ─────────────────────────────────────────────────────────────────────


def test_contracts_version_is_0_3() -> None:
    assert CONTRACTS_VERSION == "0.3"
    assert StepMetric(step="x", provider="p", model="m", latency_s=0.0).detail is None


def test_v02_briefing_json_without_detail_still_loads(sample_briefing: Briefing, tmp_path: Path) -> None:
    path = storage.save_briefing(sample_briefing, base_dir=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    for metric in data["metrics"]:  # un briefing.json v0.2 no tiene «detail»
        metric.pop("detail", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = storage.load_briefing(path)
    assert loaded.metrics and all(m.detail is None for m in loaded.metrics)


# ── Modos ─────────────────────────────────────────────────────────────────────────


def test_resolve_mode() -> None:
    assert pipeline.resolve_mode(None, use_mock=False) == "real"
    assert pipeline.resolve_mode(None, use_mock=True) == "mock"
    assert pipeline.resolve_mode("demo_voices", use_mock=False) == "demo_voices"
    assert pipeline.resolve_mode("MOCK") == "mock"
    with pytest.raises(ValueError):
        pipeline.resolve_mode("turbo")


def test_demo_voices_mode_uses_real_tts_with_sample_data(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tts = RecordingTTS()
    monkeypatch.setattr(pipeline, "demo_voice_tts", lambda _s: tts)
    briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], mode="demo_voices", settings=settings)
    steps = _by_step(briefing.metrics)
    assert steps["ingest.news"].provider == "samples"
    assert steps["ingest.prices"].provider == "synthetic"
    assert steps["agents.analyst"].provider == "mock"
    assert steps["media.podcast"].provider == "edge" and not steps["media.podcast"].error
    assert tts.texts, "el podcast debe pasar por el TTS real"
    assert is_demo_run(briefing.metrics) and has_real_voices(briefing.metrics)


def test_demo_voices_falls_back_to_mock_tts_when_edge_is_down(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DownTTS(RecordingTTS):
        def synthesize(self, text, voice, out_path):
            raise ConnectionError("sin red")

    monkeypatch.setattr(pipeline, "demo_voice_tts", lambda _s: DownTTS())
    briefing = pipeline.run_briefing(["SAN.MC"], mode="demo_voices", settings=settings)
    podcast_m = _by_step(briefing.metrics)["media.podcast"]
    assert podcast_m.provider == "mock" and step_fell_back(podcast_m)
    assert briefing.audio is not None and Path(briefing.audio.path).exists()


def test_use_mock_still_means_full_mock(settings: Settings) -> None:
    briefing = pipeline.run_briefing(["SAN.MC"], use_mock=True, settings=settings)
    assert _by_step(briefing.metrics)["media.podcast"].provider == "mock"


# ── Índices de contexto, caché y paralelismo ──────────────────────────────────────


def test_context_indices_are_fetched_but_not_user_tickers(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from briefer.ingest import news as news_mod, prices as prices_mod

    calls: dict[str, object] = {}

    def fetch_news(tickers, *_a, use_cache=True, **_k):
        calls["news"] = (list(tickers), use_cache)
        return news_mod.load_sample_news()

    def get_prices(tickers, *_a, use_cache=True, **_k):
        calls["prices"] = (list(tickers), use_cache)
        return prices_mod.synthetic_snapshots(tickers)

    monkeypatch.setattr(pipeline.news_mod, "fetch_news", fetch_news)
    monkeypatch.setattr(pipeline.prices_mod, "get_price_snapshots", get_prices)
    real = settings.model_copy(update={"briefer_llm_provider": "mock"})
    briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], mode="real", use_cache=False, settings=real)

    assert calls["news"] == (["SAN.MC", "AAPL", "^IBEX", "^GSPC"], False)
    assert calls["prices"] == (["SAN.MC", "AAPL", "^IBEX", "^GSPC"], False)
    assert briefing.context.tickers == ["SAN.MC", "AAPL"]
    assert {p.ticker for p in briefing.context.prices} == {"SAN.MC", "AAPL", "^IBEX", "^GSPC"}
    line_charts = {c.ticker for c in briefing.charts if c.kind == "price_line"}
    assert line_charts == {"SAN.MC", "AAPL"}  # los índices solo en el gráfico de variación
    assert any(c.kind == "overview_bar" for c in briefing.charts)
    assert _by_step(briefing.metrics)["ingest.tickers"].detail


def test_context_tickers_can_be_disabled(settings: Settings) -> None:
    s = settings.model_copy(update={"briefer_context_tickers": ""})
    briefing = pipeline.run_briefing(["SAN.MC"], use_mock=True, settings=s)
    assert [p.ticker for p in briefing.context.prices] == ["SAN.MC"]


def test_podcast_is_synthesized_with_six_workers(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int] = {}
    real = pipeline.podcast.synthesize_podcast

    def spy(*args, **kwargs):
        seen["max_workers"] = kwargs.get("max_workers")
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline.podcast, "synthesize_podcast", spy)
    pipeline.run_briefing(["SAN.MC"], use_mock=True, settings=settings)
    assert seen["max_workers"] == pipeline.PODCAST_TTS_WORKERS == 6


def test_qa_answer_is_normalized_before_tts(
    settings: Settings, sample_briefing: Briefing, monkeypatch: pytest.MonkeyPatch
) -> None:
    from briefer.agents import qa
    from briefer.schemas import QAAnswer

    tts = RecordingTTS()
    monkeypatch.setattr(pipeline, "demo_voice_tts", lambda _s: tts)
    monkeypatch.setattr(
        qa, "answer",
        lambda question, briefing, llm, history=None: QAAnswer(
            question=question, answer_text="SAN.MC sube un 2,5 % hasta 4,3 €."
        ),
    )
    answer = pipeline.answer_question("¿Qué tal el Santander?", sample_briefing, mode="demo_voices", settings=settings)
    assert answer.answer_text == "SAN.MC sube un 2,5 % hasta 4,3 €."  # el texto mostrado no cambia
    spoken = tts.texts[-1]
    assert "SAN.MC" not in spoken and "%" not in spoken and "€" not in spoken
    assert answer.audio_path is not None
    assert _by_step(answer.metrics)["qa.tts"].provider == "edge"


# ── Traza de la UI ────────────────────────────────────────────────────────────────


def _m(step: str, provider: str, error: str | None = None, detail: str | None = None) -> StepMetric:
    return StepMetric(step=step, provider=provider, model="-", latency_s=0.1, error=error, detail=detail)


def test_trace_marks_sample_and_synthetic_fallbacks_not_errors() -> None:
    metrics = [
        _m("ingest.news", "samples", error="Fallback a data/samples tras ConnectionError: x"),
        _m("ingest.prices", "synthetic", error="Fallback a precios sintéticos tras ConnectionError: x"),
        _m("agents.analyst", "anthropic"),
        _m("agents.scriptwriter", "local", error="Fallback a guion de respaldo tras RuntimeError: x"),
        _m("media.video", "moviepy", error="RuntimeError: ffmpeg"),
    ]
    status = {n.metric.step: n.status for n in build_nodes(metrics)}
    assert status["ingest.news"] == status["ingest.prices"] == status["agents.scriptwriter"] == "fallback"
    assert status["media.video"] == "error"
    assert fallback_tag(metrics[0]).startswith("DATOS DE EJEMPLO")
    assert fallback_tag(metrics[1]).startswith("PRECIOS SINTÉTICOS")


def test_trace_label_shows_detail() -> None:
    node = build_nodes([_m("agents.analyst", "anthropic", detail="grounding: 2 cifras no trazables; 1 reintento")])[0]
    assert "grounding" in node_label(node)


# ── Salida estructurada: dict libres como lista de pares ─────────────────────────


def test_dict_fields_travel_as_pairs_in_strict_schema() -> None:
    anthropic = pytest.importorskip("anthropic")
    from briefer.providers.llm._structured import dict_fields, encode_dict_fields, parse_json_model
    from briefer.schemas import DocumentInsight

    fields = dict_fields(DocumentInsight)
    assert fields == ["key_figures"]
    schema = encode_dict_fields(anthropic.transform_schema(DocumentInsight), fields)
    assert schema["properties"]["key_figures"]["type"] == "array"
    text = json.dumps({
        "source_type": "pdf", "source_name": "x.pdf", "extracted_text": "t", "summary": "s",
        "key_figures": [{"label": "Ingresos", "value": "1.245 M€ (+8,4 %)"}, {"label": " ", "value": "x"}],
    })
    insight = parse_json_model(text, DocumentInsight, fields)
    assert insight.key_figures == {"Ingresos": "1.245 M€ (+8,4 %)"}
    # Un dict normal (Gemini, mock) se sigue aceptando
    data = json.loads(text)
    data["key_figures"] = {"EBITDA": "312 M"}
    plain = parse_json_model(json.dumps(data), DocumentInsight, fields)
    assert plain.key_figures == {"EBITDA": "312 M"}


def test_scriptwriter_fixes_cyrillic_homoglyphs() -> None:
    from briefer.agents.scriptwriter import fix_homoglyphs

    assert fix_homoglyphs("aunque suба hoy") == "aunque suba hoy"  # caso real (Haiku)
    assert fix_homoglyphs("Telefоnica") == "Telefonica"
