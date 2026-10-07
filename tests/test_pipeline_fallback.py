"""Tests de orquestación robusta del pipeline (carril B), sin red:

- caída de un paso núcleo con proveedor real a su sustituto (mock / data/samples / sintéticos),
  marcada en ``StepMetric`` (``provider`` + ``error`` con prefijo ``"Fallback a "``);
- Guionista con el LLM barato y métricas con coste y notas de calidad;
- noticias y precios en paralelo.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from test_llm_providers import FakeAnthropicClient, _analysis_json, _resp

from briefer import pipeline
from briefer.config import Settings
from briefer.logging_utils import step_failed, step_fell_back
from briefer.providers.llm.anthropic_llm import AnthropicLLM
from briefer.schemas import Briefing, QAAnswer


@pytest.fixture
def real_settings(tmp_path: Path) -> Settings:
    """LLM "real" (Anthropic con cliente falso o roto), resto mock; fallback activado."""
    return Settings(
        _env_file=None,
        briefer_llm_provider="anthropic",
        anthropic_api_key="sk-test-no-real",
        briefer_vision_provider="mock",
        briefer_stt_provider="mock",
        briefer_tts_provider="mock",
        briefer_image_gen_provider="none",
        briefer_image_classifier_provider="none",
        briefer_output_dir=tmp_path / "outputs",
        briefer_cache_dir=tmp_path / "cache",
    )


@pytest.fixture
def offline_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin red: la ingesta real falla (como si yfinance/RSS estuvieran caídos)."""

    def down(*_a, **_k):
        raise ConnectionError("sin red en tests")

    monkeypatch.setattr(pipeline.news_mod, "fetch_news", down)
    monkeypatch.setattr(pipeline.prices_mod, "get_price_snapshots", down)


def _broken_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, *a, **k):
        raise RuntimeError("529 overloaded_error")

    monkeypatch.setattr(AnthropicLLM, "complete", boom)


def _by_step(briefing: Briefing) -> dict:
    return {m.step: m for m in briefing.metrics}


def test_core_steps_fall_back_and_are_marked(
    real_settings: Settings, offline_ingest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _broken_llm(monkeypatch)
    briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], settings=real_settings)

    assert briefing.analysis.key_points and briefing.script.lines and briefing.audio
    steps = _by_step(briefing)
    news, prices = steps["ingest.news"], steps["ingest.prices"]
    assert news.provider == "samples" and step_fell_back(news)
    assert news.error.startswith("Fallback a data/samples tras ConnectionError")
    assert prices.provider == "synthetic" and step_fell_back(prices)

    analyst_m = steps["agents.analyst"]
    assert (analyst_m.provider, analyst_m.model) == ("mock", "mock-llm")
    assert analyst_m.error == "Fallback a mock tras RuntimeError: 529 overloaded_error"

    # El Guionista absorbe el fallo con su guion de respaldo determinista, marcado igual.
    script_m = steps["agents.scriptwriter"]
    assert (script_m.provider, script_m.model) == ("local", "fallback_script")
    assert step_fell_back(script_m) and "529" in script_m.error

    for name in ("media.podcast", "media.transcript", "media.charts", "storage.save"):
        assert not step_failed(steps[name])
    saved = Briefing.model_validate_json(
        (real_settings.output_path / briefing.id / "briefing.json").read_text(encoding="utf-8")
    )
    assert step_fell_back(_by_step(saved)["agents.analyst"])


def test_without_fallback_core_failure_raises(
    real_settings: Settings, offline_ingest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_settings.briefer_fallback_to_mock = False
    with pytest.raises(pipeline.PipelineStepError) as info:
        pipeline.run_briefing(["SAN.MC"], settings=real_settings)
    assert info.value.step in {"ingest.news", "ingest.prices"}


def test_fallback_that_also_fails_raises(
    real_settings: Settings, offline_ingest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _broken_llm(monkeypatch)
    monkeypatch.setattr(pipeline.news_mod, "load_sample_news", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(pipeline.PipelineStepError) as info:
        pipeline.run_briefing(["SAN.MC"], settings=real_settings)
    assert info.value.step == "ingest.news"


def test_real_llm_path_metrics_cost_and_cheap_scriptwriter(
    real_settings: Settings, offline_ingest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM Anthropic con SDK simulado: analista en Sonnet, guionista en Haiku, coste > 0."""
    script = {
        "title": "Episodio",
        "lines": [{"speaker": "A" if i % 2 == 0 else "B", "text": "palabra " * 40} for i in range(14)],
    }
    clients: dict[str, FakeAnthropicClient] = {}

    def fake_client(self):
        key = "cheap" if self.cheap else "main"
        if key not in clients:
            payload = json.dumps(script) if self.cheap else _analysis_json(
                key_points=[{
                    "title": "Mercado", "explanation": "Sesión sin cifras destacadas.",
                    "tickers": ["SAN.MC"], "sentiment": "neutral", "sources": [],
                }]
            )
            clients[key] = FakeAnthropicClient([_resp(payload, inp=4000, out=900)])
        return clients[key]

    monkeypatch.setattr(AnthropicLLM, "_get_client", fake_client)
    briefing = pipeline.run_briefing(["SAN.MC"], settings=real_settings)
    steps = _by_step(briefing)
    analyst_m, script_m = steps["agents.analyst"], steps["agents.scriptwriter"]
    assert (analyst_m.provider, analyst_m.model, analyst_m.error) == ("anthropic", "claude-sonnet-5-5", None)
    assert script_m.model == "claude-haiku-4-5-20251001" and script_m.error is None
    assert analyst_m.est_cost_eur > 0 and script_m.est_cost_eur > 0
    assert analyst_m.detail and "grounding" in analyst_m.detail
    assert script_m.detail and "guion:" in script_m.detail
    assert clients["cheap"].messages.calls[0]["model"] == "claude-haiku-4-5-20251001"


def test_tts_failure_falls_back_to_mock(
    real_settings: Settings, offline_ingest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from briefer.providers.mock import MockTTS

    class BrokenTTS(MockTTS):
        provider_name = "edge"
        model = "edge-tts"

        def synthesize(self, text, voice, out_path):
            raise ConnectionError("edge-tts 403")

    _broken_llm(monkeypatch)
    real_get_providers = pipeline.get_providers

    def providers_with_broken_tts(settings, use_mock=False):
        prov = real_get_providers(settings, use_mock=use_mock)
        prov.tts = BrokenTTS()
        return prov

    monkeypatch.setattr(pipeline, "get_providers", providers_with_broken_tts)
    briefing = pipeline.run_briefing(["SAN.MC"], settings=real_settings)
    podcast_m = _by_step(briefing)["media.podcast"]
    assert podcast_m.provider == "mock" and step_fell_back(podcast_m)
    assert briefing.audio is not None and Path(briefing.audio.path).exists()


def test_answer_question_falls_back_to_mock(
    real_settings: Settings, sample_briefing: Briefing, monkeypatch: pytest.MonkeyPatch
) -> None:
    _broken_llm(monkeypatch)
    answer = pipeline.answer_question("¿Qué ha pasado hoy?", sample_briefing, speak=False, settings=real_settings)
    assert isinstance(answer, QAAnswer) and answer.answer_text
    qa_m = answer.metrics[0]
    assert qa_m.step == "agents.qa" and qa_m.provider == "mock" and step_fell_back(qa_m)
    assert answer.response_kind == "demo_excerpt"
    assert sample_briefing.analysis.key_points[0].explanation in answer.answer_text
    assert "Pregunta recibida" not in answer.answer_text


def test_mock_mode_never_falls_back(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline.analyst, "analyze", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    with pytest.raises(pipeline.PipelineStepError):
        pipeline.run_briefing(["SAN.MC"], use_mock=True, settings=settings)


def test_news_and_prices_run_in_parallel(real_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Las dos descargas se esperan mutuamente en una barrera: solo pasa si van en paralelo."""
    from briefer.ingest import news as news_mod
    from briefer.ingest import prices as prices_mod

    barrier = threading.Barrier(2, timeout=5)
    samples = news_mod.load_sample_news()

    def fetch_news(*_a, **_k):
        barrier.wait()
        return samples

    def get_prices(tickers, *_a, **_k):
        barrier.wait()
        return prices_mod.synthetic_snapshots(tickers)

    monkeypatch.setattr(pipeline.news_mod, "fetch_news", fetch_news)
    monkeypatch.setattr(pipeline.prices_mod, "get_price_snapshots", get_prices)
    _broken_llm(monkeypatch)
    briefing = pipeline.run_briefing(["SAN.MC"], settings=real_settings)
    steps = _by_step(briefing)
    assert steps["ingest.news"].provider == "yfinance+rss" and not step_failed(steps["ingest.news"])
    assert steps["ingest.prices"].provider == "yfinance" and not step_failed(steps["ingest.prices"])
