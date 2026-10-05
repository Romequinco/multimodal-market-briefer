"""Tests de la columna vertebral: schemas, proveedores mock, registry, costes y métricas."""

from __future__ import annotations

import csv
import json
import wave
from pathlib import Path

import pytest
from pydantic import ValidationError

from briefer import costs, schemas
from briefer.config import ROOT_DIR, Settings
from briefer.logging_utils import track_step
from briefer.providers import mock, registry
from briefer.providers.base import LLMProvider
from briefer.schemas import (
    Analysis,
    Briefing,
    DeliveryResult,
    DocumentInsight,
    NewsItem,
    PodcastScript,
    Position,
    QAAnswer,
    StepMetric,
)

SAMPLES_DIR = ROOT_DIR / "data" / "samples"


# ── Schemas ───────────────────────────────────────────────────────────────────────


def test_briefing_roundtrip_json(sample_briefing: Briefing) -> None:
    data = sample_briefing.model_dump_json()
    restored = Briefing.model_validate_json(data)
    assert restored == sample_briefing
    assert restored.analysis.disclaimer == schemas.DISCLAIMER_ES


MODEL_NAMES = [
    name
    for name in schemas.__all__
    if isinstance(getattr(schemas, name), type) and issubclass(getattr(schemas, name), schemas.BaseModel)
]


@pytest.mark.parametrize("model_name", MODEL_NAMES)
def test_every_schema_can_be_built_and_serialized(model_name: str) -> None:
    obj = getattr(schemas, model_name)
    instance = mock.fake_instance(obj)
    assert type(instance).model_validate_json(instance.model_dump_json()) == instance


def test_position_normalizes_ticker() -> None:
    assert Position(ticker=" san.mc ").ticker == "SAN.MC"


def test_invalid_literals_rejected() -> None:
    with pytest.raises(ValidationError):
        DocumentInsight(source_type="excel", source_name="x", extracted_text="", summary="")
    with pytest.raises(ValidationError):
        DeliveryResult(channel="fax", ok=True)


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        QAAnswer(question="q", answer_text="a", inventado=1)


# ── Datos de ejemplo ──────────────────────────────────────────────────────────────


def test_sample_news_match_schema() -> None:
    data = json.loads((SAMPLES_DIR / "noticias_ejemplo.json").read_text(encoding="utf-8"))
    items = [NewsItem.model_validate(x) for x in data]
    assert 4 <= len(items) <= 6
    assert all("EJEMPLO" in item.title.upper() for item in items)


def test_sample_portfolio_csv_matches_schema() -> None:
    with (SAMPLES_DIR / "portfolio_ejemplo.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    positions = [
        Position(ticker=r["ticker"], weight=float(r["weight"]), quantity=float(r["quantity"]))
        for r in rows
    ]
    assert 5 <= len(positions) <= 8
    assert abs(sum(p.weight or 0 for p in positions) - 1.0) < 0.01


# ── Registry y mocks ──────────────────────────────────────────────────────────────


def test_registry_returns_mocks(settings: Settings) -> None:
    assert isinstance(registry.get_llm(settings), mock.MockLLM)
    assert isinstance(registry.get_vision(settings), mock.MockVision)
    assert isinstance(registry.get_stt(settings), mock.MockSTT)
    assert isinstance(registry.get_tts(settings), mock.MockTTS)
    assert isinstance(registry.get_image_gen(settings), mock.MockImageGen)
    assert isinstance(registry.get_image_classifier(settings), mock.MockImageClassifier)


def test_registry_uses_env_settings() -> None:
    # Sin argumentos usa get_settings(); conftest fuerza mock por variables de entorno.
    assert isinstance(registry.get_llm(), mock.MockLLM)


def test_registry_none_providers(settings: Settings) -> None:
    s = settings.model_copy(
        update={"briefer_image_gen_provider": "none", "briefer_image_classifier_provider": "none"}
    )
    assert registry.get_image_gen(s) is None
    assert registry.get_image_classifier(s) is None


def test_registry_fallback_to_mock_without_key() -> None:
    s = Settings(_env_file=None, briefer_llm_provider="anthropic", anthropic_api_key=None)
    assert isinstance(registry.get_llm(s), mock.MockLLM)


def test_registry_raises_without_key_when_no_fallback() -> None:
    s = Settings(
        _env_file=None,
        briefer_llm_provider="anthropic",
        anthropic_api_key=None,
        briefer_fallback_to_mock=False,
    )
    with pytest.raises(registry.ProviderConfigError):
        registry.get_llm(s)


def test_registry_loads_real_class_lazily() -> None:
    s = Settings(_env_file=None, briefer_llm_provider="anthropic", anthropic_api_key="sk-test")
    llm = registry.get_llm(s, cheap=True)
    assert isinstance(llm, LLMProvider)
    assert llm.provider_name == "anthropic"
    assert llm.model == s.briefer_llm_model_cheap


def test_mock_llm_structured_and_text() -> None:
    llm = mock.MockLLM()
    analysis = llm.complete("sys", [{"role": "user", "content": "hola"}], response_model=Analysis)
    assert isinstance(analysis, Analysis) and analysis.key_points
    script = llm.complete("sys", [{"role": "user", "content": "hola"}], response_model=PodcastScript)
    assert isinstance(script, PodcastScript) and {l.speaker for l in script.lines} == {"A", "B"}
    insight = llm.complete("sys", [{"role": "user", "content": "x"}], response_model=DocumentInsight)
    assert isinstance(insight, DocumentInsight)
    text = llm.complete("sys", [{"role": "user", "content": "¿Qué tal el IBEX?"}])
    assert isinstance(text, str) and "IBEX" in text
    assert llm.last_usage["input_tokens"] > 0
    # Determinista
    assert llm.complete("s", [{"role": "user", "content": "a"}], Analysis) == analysis


def test_mock_tts_writes_valid_wav(tmp_path: Path) -> None:
    out = mock.MockTTS().synthesize("Hola mundo", "es-ES-AlvaroNeural", tmp_path / "x.mp3")
    assert out.suffix == ".wav" and out.exists()
    with wave.open(str(out)) as w:
        assert w.getnframes() > 0 and w.getframerate() == 16_000


def test_mock_image_gen_writes_png(tmp_path: Path) -> None:
    out = mock.MockImageGen().generate("portada", tmp_path / "cover")
    assert out.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_mock_classifier_vision_stt(tmp_path: Path) -> None:
    probs = mock.MockImageClassifier().classify(b"img", ["a", "b", "c"])
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert isinstance(mock.MockVision().describe(b"img", "describe"), str)
    assert isinstance(mock.MockSTT().transcribe(tmp_path / "a.wav"), str)


# ── Costes y métricas ─────────────────────────────────────────────────────────────


def test_costs() -> None:
    assert costs.estimate_cost_eur("mock", "mock-llm", input_tokens=10_000) == 0.0
    cost = costs.estimate_cost_eur("anthropic", "claude-sonnet-5-5", input_tokens=1_000_000)
    assert cost > 0
    assert costs.estimate_cost_eur("openai", "whisper-1", duration_s=60) > 0
    assert costs.estimate_cost_eur("edge", "edge-tts", n_chars=5000) == 0.0
    summary = costs.summarize_metrics(
        [StepMetric(step="a", provider="p", model="m", latency_s=1.0, est_cost_eur=0.5)] * 2
    )
    assert summary == {"steps": 2.0, "total_latency_s": 2.0, "total_cost_eur": 1.0}


def test_track_step_records_metric_even_on_error() -> None:
    metrics: list[StepMetric] = []
    with track_step("ok", "mock", "m", metrics) as step:
        step.est_cost_eur = 0.01
    with pytest.raises(RuntimeError), track_step("fallo", "mock", "m", metrics):
        raise RuntimeError("boom")
    assert [m.step for m in metrics] == ["ok", "fallo"]
    assert metrics[0].est_cost_eur == 0.01 and metrics[0].latency_s >= 0
