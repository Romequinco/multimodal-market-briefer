"""Tests SIN red ni ``torch`` del «impacto de la noticia» (Haiku traduce + FinBERT clasifica).

FinBERT se sustituye por un clasificador falso y Haiku por un LLM falso que «traduce». Se comprueba
también el paso ``ingest.impact`` del pipeline: corre en paralelo con el Analista, deja su métrica
en la traza y escribe ``news_impact.json``.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from briefer import pipeline
from briefer.config import Settings
from briefer.ingest import prices as prices_mod
from briefer.ingest import sentiment
from briefer.schemas import NewsItem

NOW = datetime.now(UTC)


def news(title: str, summary: str = "", language: str = "es", nid: str = "n1", tickers=("SAN.MC",)) -> NewsItem:
    return NewsItem(
        id=nid,
        title=title,
        summary=summary,
        source="Expansión",
        url=f"https://www.expansion.com/{nid}",
        published_at=NOW - timedelta(hours=2),
        tickers=list(tickers),
        language=language,
    )


class FakeLLM:
    """LLM real «de mentira»: devuelve una traducción por id y cuenta las llamadas."""

    provider_name = "anthropic"
    model = "fake-haiku"

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}

    def complete(self, system, messages, response_model=None):
        self.calls += 1
        content = messages[-1]["content"]
        ids = [line.split("id: ", 1)[1] for line in content.splitlines() if "id: " in line]
        return response_model(items=[{"id": i, "en": f"translated {i}"} for i in ids])


def fake_classify(texts: list[str]) -> list[dict[str, float]]:
    return [
        {"positive": 0.8, "negative": 0.1, "neutral": 0.1}
        if "beats" in t
        else {"positive": 0.1, "negative": 0.7, "neutral": 0.2}
        for t in texts
    ]


# ── módulo ───────────────────────────────────────────────────────────────────────


def test_news_text_joins_title_and_excerpt_and_truncates():
    assert sentiment.news_text(news("Titular", "Extracto")) == "Titular. Extracto"
    assert sentiment.news_text(news("Titular")) == "Titular"
    assert len(sentiment.news_text(news("x" * 1000))) == sentiment.MAX_TEXT_CHARS


def test_translate_only_non_english_in_one_call():
    es = news("Santander gana un 10 % más", nid="es1")
    en = news("Apple beats estimates", language="en", nid="en1")
    llm = FakeLLM()
    texts = sentiment.translate_to_english([es, en], llm)
    assert texts == {"en1": "Apple beats estimates", "es1": "translated es1"}
    assert llm.calls == 1


def test_translate_batches_and_ignores_unknown_ids(monkeypatch):
    monkeypatch.setattr(sentiment, "TRANSLATE_BATCH", 2)
    items = [news(f"Noticia {i}", nid=f"es{i}") for i in range(5)]
    llm = FakeLLM()
    assert len(sentiment.translate_to_english(items, llm)) == 5
    assert llm.calls == 3


def test_translate_skips_with_mock_no_llm_or_error():
    es = news("Santander gana", nid="es1")
    en = news("Apple beats", language="en", nid="en1")
    assert set(sentiment.translate_to_english([es, en], None)) == {"en1"}

    class Mock:
        provider_name = "mock"

    assert set(sentiment.translate_to_english([es, en], Mock())) == {"en1"}

    class Broken(FakeLLM):
        def complete(self, *a, **k):
            raise RuntimeError("API caída")

    assert set(sentiment.translate_to_english([es, en], Broken())) == {"en1"}


def test_news_impact_with_fake_finbert(monkeypatch):
    monkeypatch.setattr(sentiment, "finbert_available", lambda: True)
    monkeypatch.setattr(sentiment, "classify", fake_classify)
    items = [news("Apple beats estimates", language="en", nid="en1"), news("Santander cae", nid="es1")]
    stats: dict = {}
    result = sentiment.news_impact(items, FakeLLM(), stats_out=stats)
    assert result["en1"].impact == "positivo" and not result["en1"].translated
    assert result["es1"].impact == "negativo" and result["es1"].translated
    assert result["es1"].probs == {"positivo": 0.1, "negativo": 0.7, "neutral": 0.2}
    assert stats["status"] == "ok" and stats["classified"] == 2 and stats["translated"] == 1
    detail = sentiment.impact_detail(stats)
    assert "▲ 1" in detail and "▼ 1" in detail and "1 traducidas con Haiku" in detail


def test_news_impact_degrades_gracefully(monkeypatch):
    items = [news("x", language="en", nid="a")]
    stats: dict = {}
    assert sentiment.news_impact(items, enabled=False, stats_out=stats) == {}
    assert sentiment.impact_detail(stats) == "FinBERT: desactivado"
    assert sentiment.news_impact([], stats_out=stats) == {} and stats["status"] == "sin noticias"
    monkeypatch.setattr(sentiment, "finbert_available", lambda: False)
    assert sentiment.news_impact(items, stats_out=stats) == {}
    assert sentiment.impact_detail(stats) == "FinBERT: no instalado"
    monkeypatch.setattr(sentiment, "finbert_available", lambda: True)

    def boom(texts):
        raise RuntimeError("modelo roto")

    monkeypatch.setattr(sentiment, "classify", boom)
    assert sentiment.news_impact(items, stats_out=stats) == {}
    assert sentiment.impact_detail(stats) == "FinBERT: error: RuntimeError"
    assert sentiment.impact_detail({}) == ""


# ── pipeline: paso ingest.impact ─────────────────────────────────────────────────


@pytest.fixture
def finbert_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        briefer_llm_provider="mock",
        briefer_vision_provider="mock",
        briefer_stt_provider="mock",
        briefer_tts_provider="mock",
        briefer_image_gen_provider="none",
        briefer_image_classifier_provider="none",
        briefer_output_dir=tmp_path / "outputs",
        briefer_cache_dir=tmp_path / "cache",
        briefer_finbert=True,
    )


@pytest.fixture
def real_news(monkeypatch: pytest.MonkeyPatch) -> list[NewsItem]:
    """Noticias «reales» (no de ejemplo) en inglés: FinBERT las clasifica sin traducir."""
    items = [
        news("Santander beats estimates in Brazil", language="en", nid="r1"),
        news("Santander shares fall after the election", language="en", nid="r2"),
    ]
    monkeypatch.setattr(pipeline.news_mod, "fetch_news", lambda *a, **k: list(items))
    monkeypatch.setattr(
        pipeline.prices_mod, "get_price_snapshots", lambda t, *a, **k: prices_mod.synthetic_snapshots(t)
    )
    monkeypatch.setattr(sentiment, "finbert_available", lambda: True)
    return items


def test_pipeline_impact_runs_in_parallel_with_analyst(finbert_settings, real_news, monkeypatch):
    """FinBERT y el Analista se esperan mutuamente en una barrera: solo pasa si van en paralelo."""
    barrier = threading.Barrier(2, timeout=10)
    analyze = pipeline.analyst.analyze

    def classify(texts):
        barrier.wait()
        return fake_classify(texts)

    def slow_analyze(*a, **k):
        barrier.wait()
        return analyze(*a, **k)

    monkeypatch.setattr(sentiment, "classify", classify)
    monkeypatch.setattr(pipeline.analyst, "analyze", slow_analyze)
    briefing = pipeline.run_briefing(["SAN.MC"], settings=finbert_settings, mode="real")

    steps = [m.step for m in briefing.metrics]
    assert steps.index("ingest.impact") == steps.index("agents.analyst") + 1
    impact = next(m for m in briefing.metrics if m.step == "ingest.impact")
    assert impact.error is None and impact.model == sentiment.FINBERT_MODEL
    assert impact.detail == "FinBERT: 2 noticias (0 traducidas con Haiku) · ▲ 1 · ▼ 1 · ● 0"
    saved = json.loads((finbert_settings.output_path / briefing.id / "news_impact.json").read_text("utf-8"))
    assert {row["news_id"]: row["impact"] for row in saved} == {"r1": "positivo", "r2": "negativo"}


def test_pipeline_without_flag_or_with_sample_news_skips_impact(finbert_settings, real_news, monkeypatch):
    monkeypatch.setattr(sentiment, "classify", fake_classify)
    off = finbert_settings.model_copy(update={"briefer_finbert": False})
    briefing = pipeline.run_briefing(["SAN.MC"], settings=off, mode="real")
    assert "ingest.impact" not in {m.step for m in briefing.metrics}
    demo = pipeline.run_briefing(["SAN.MC"], settings=finbert_settings, mode="mock")
    assert "ingest.impact" not in {m.step for m in demo.metrics}


def test_pipeline_impact_failure_does_not_break_briefing(finbert_settings, real_news, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(sentiment, "news_impact", boom)
    briefing = pipeline.run_briefing(["SAN.MC"], settings=finbert_settings, mode="real")
    impact = next(m for m in briefing.metrics if m.step == "ingest.impact")
    assert impact.error and "fallo inesperado" in impact.error
    assert briefing.analysis.headline


def test_failures_are_logged_without_secrets(monkeypatch):
    """Los avisos del log usan ``error_text``: una clave dentro del error no llega al log."""
    secret = "sk-ant-api03-" + "x" * 40
    logged: list[str] = []

    class Log:
        def warning(self, msg, *args):
            logged.append(msg % args)

        info = warning

    monkeypatch.setattr(sentiment, "log", Log())

    class Broken(FakeLLM):
        def complete(self, *a, **k):
            raise RuntimeError(f"401 invalid x-api-key {secret}")

    sentiment.translate_to_english([news("Santander gana", nid="es1")], Broken())
    monkeypatch.setattr(sentiment, "finbert_available", lambda: True)

    def boom(texts):
        raise RuntimeError(f"fallo con {secret}")

    monkeypatch.setattr(sentiment, "classify", boom)
    sentiment.news_impact([news("x", language="en", nid="a")])
    warnings = [m for m in logged if "fall" in m.lower()]
    assert len(warnings) == 2 and all(secret not in m for m in warnings)
