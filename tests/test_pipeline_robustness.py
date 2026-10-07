"""Regresiones de orquestación del carril B (sin red):

- coste: ``last_usage`` obsoleto no se cuenta dos veces cuando el proveedor falla;
- subidas pendientes canceladas si falla la ingesta núcleo, y lo ya gastado queda en
  ``PipelineStepError.metrics``;
- Q&A en dos tiempos (``answer_question(speak=False)`` + ``speak_answer``) y ``warmup``;
- cliente de Anthropic compartido y precalentado sin coste;
- modelo configurable del Guionista;
- coste de la portada anotado aunque falle el título superpuesto.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from briefer import costs, pipeline
from briefer.config import Settings
from briefer.providers.base import ImageGenProvider, LLMProvider
from briefer.providers.llm import _anthropic_common as common
from briefer.providers.llm.anthropic_llm import AnthropicLLM
from briefer.providers.mock import MockLLM
from briefer.schemas import Briefing, DocumentInsight

# ── Coste: uso obsoleto ───────────────────────────────────────────────────────────


class FlakyLLM(LLMProvider):
    """Rellena ``last_usage`` solo cuando responde; la 2.ª llamada falla ANTES de tocarlo."""

    provider_name = "anthropic"
    model = "claude-haiku-4-5"

    def __init__(self) -> None:
        super().__init__()
        self.n = 0

    def complete(self, system: str, messages: list[dict], response_model: type[BaseModel] | None = None):
        self.n += 1
        if self.n == 2:
            raise ConnectionError("red caída")
        self.last_usage = {"input_tokens": 1_000, "output_tokens": 100}
        return "ok"


def test_metered_llm_does_not_double_count_stale_usage() -> None:
    metered = pipeline._MeteredLLM(FlakyLLM())
    metered.complete("s", [{"role": "user", "content": "x"}])
    with pytest.raises(ConnectionError):
        metered.complete("s", [{"role": "user", "content": "x"}])
    assert metered.meter.usage == {"input_tokens": 1_000, "output_tokens": 100}  # antes: 2_000/200
    assert metered.meter.calls == 2 and len(metered.errors) == 1


def test_anthropic_text_call_resets_usage_before_calling(tmp_path: Path) -> None:
    from test_llm_providers import FakeAnthropicClient, _resp

    s = Settings(_env_file=None, briefer_llm_provider="anthropic", anthropic_api_key="sk-test-no-real")
    llm = AnthropicLLM(s, cheap=True)
    llm._client = FakeAnthropicClient([_resp("hola", inp=50, out=5), ConnectionError("caída")])
    llm.complete("s", [{"role": "user", "content": "x"}])
    with pytest.raises(ConnectionError):
        llm.complete("s", [{"role": "user", "content": "x"}])
    assert llm.last_usage == {"input_tokens": 0, "output_tokens": 0}


# ── Subidas canceladas si falla la ingesta ─────────────────────────────────────────


def test_pending_uploads_are_cancelled_when_core_ingest_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started: list[str] = []
    release = threading.Event()

    def slow_upload(path, providers, metrics, language="es"):
        started.append(path.name)
        with pipeline.track_step("ingest.pdf", "mock", "-", metrics) as step:
            step.est_cost_eur = 0.01
            release.wait(1.0)  # sigue en curso cuando la ingesta núcleo falla
        return DocumentInsight(source_type="pdf", source_name=path.name, summary="x")

    def news_down(_h=None):
        time.sleep(0.2)  # la 1.ª subida ya ha empezado; las otras esperan en cola
        raise RuntimeError("feed caído")

    monkeypatch.setattr(pipeline, "UPLOAD_WORKERS", 1)
    monkeypatch.setattr(pipeline, "process_upload", slow_upload)
    monkeypatch.setattr(pipeline.news_mod, "load_sample_news", news_down)
    uploads = [tmp_path / f"doc{i}.pdf" for i in range(4)]

    with pytest.raises(pipeline.PipelineStepError) as info:
        pipeline.run_briefing(["SAN.MC"], uploads=uploads, mode="mock", settings=settings)

    assert info.value.step == "ingest.news"
    time.sleep(1.2)  # sin cancelación, doc1 empezaría al terminar doc0 (hilo huérfano pagando visión)
    assert started == ["doc0.pdf"]  # las 3 pendientes se cancelan: no se paga visión de más
    steps = [m.step for m in info.value.metrics]
    assert "ingest.news" in steps and "ingest.pdf" in steps  # lo gastado se ve en el error
    assert sum(m.est_cost_eur for m in info.value.metrics) == pytest.approx(0.01)


def test_core_failure_after_ingest_carries_metrics(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("analista roto")

    monkeypatch.setattr(pipeline.analyst, "analyze", boom)
    with pytest.raises(pipeline.PipelineStepError) as info:
        pipeline.run_briefing(["SAN.MC"], mode="mock", settings=settings)
    assert info.value.step == "agents.analyst"
    assert [m.step for m in info.value.metrics][:3] == ["ingest.news", "ingest.prices", "ingest.tickers"]
    assert info.value.metrics[-1].step == "agents.analyst" and info.value.metrics[-1].error


def test_tickers_without_price_are_noted(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    real_synth = pipeline.prices_mod.synthetic_snapshots
    monkeypatch.setattr(
        pipeline.prices_mod, "synthetic_snapshots",
        lambda tickers, *a, **k: [p for p in real_synth(tickers, *a, **k) if p.ticker != "XYZFAKE"],
    )
    briefing = pipeline.run_briefing(["SAN.MC", "XYZFAKE"], mode="mock", settings=settings)
    step = next(m for m in briefing.metrics if m.step == "ingest.tickers")
    assert "sin precio: XYZFAKE" in (step.detail or "")


# ── Q&A en dos tiempos y precalentado ─────────────────────────────────────────────


def test_answer_text_first_then_speak(settings: Settings, sample_briefing: Briefing) -> None:
    text_only = pipeline.answer_question("¿Qué tal el Santander?", sample_briefing, speak=False, mode="mock", settings=settings)
    assert text_only.audio_path is None
    assert [m.step for m in text_only.metrics] == ["agents.qa"]
    assert text_only.metrics[0].detail and "fuentes citadas" in text_only.metrics[0].detail

    spoken = pipeline.speak_answer(text_only, sample_briefing, mode="mock", settings=settings)
    assert spoken.audio_path is not None and spoken.audio_path.exists()
    assert [m.step for m in spoken.metrics] == ["agents.qa", "qa.tts"]
    assert spoken.answer_text == text_only.answer_text
    assert pipeline.speak_answer(spoken, sample_briefing, mode="mock", settings=settings) is spoken


def test_speak_answer_tolerates_tts_failure(
    settings: Settings, sample_briefing: Briefing, monkeypatch: pytest.MonkeyPatch
) -> None:
    from briefer.providers.mock import MockTTS

    def broken(self, *a, **k):
        raise RuntimeError("tts caído")

    monkeypatch.setattr(MockTTS, "synthesize", broken)
    ans = pipeline.answer_question("¿Qué dice el briefing sobre Santander?", sample_briefing,
                                   speak=False, mode="mock", settings=settings)
    spoken = pipeline.speak_answer(ans, sample_briefing, mode="mock", settings=settings)
    assert spoken.audio_path is None and spoken.metrics[-1].step == "qa.tts" and spoken.metrics[-1].error


def test_qa_failure_carries_metrics(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("q&a roto")

    monkeypatch.setattr(pipeline.qa, "demo_answer", boom)
    with pytest.raises(pipeline.PipelineStepError) as info:
        pipeline.answer_question("Hola", None, mode="mock", settings=settings)
    assert [m.step for m in info.value.metrics] == ["agents.qa"]


def test_warmup_in_mock_is_noop_and_never_raises(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    assert set(pipeline.warmup(settings, mode="mock")) == {"total"}

    def broken(*_a, **_k):
        raise RuntimeError("config rota")

    monkeypatch.setattr(pipeline, "_providers_for_mode", broken)
    assert "total" in pipeline.warmup(settings, mode="real")


def test_warmup_imports_stt_and_tts_sdks(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """El STT real (whisper_api -> ``openai``) también se precalienta: la 1.ª pregunta por voz
    pagaba el import del SDK en ``qa.stt`` (7-15 s en frío, medido con measure_qa_voice.py)."""
    providers = pipeline.get_providers(settings, use_mock=True)
    providers.stt.provider_name = "openai"  # instancia: no toca la clase MockSTT
    providers.tts.provider_name = "edge"
    monkeypatch.setattr(pipeline, "_providers_for_mode", lambda *_a: providers)
    imported: list[str] = []
    monkeypatch.setattr(pipeline.importlib, "import_module", lambda name: imported.append(name))
    timings = pipeline.warmup(settings, mode="real")
    assert imported == ["openai", "edge_tts"]
    assert {"stt", "tts", "total"} <= set(timings)


@pytest.fixture
def anthropic_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        briefer_llm_provider="anthropic",
        briefer_vision_provider="claude",
        briefer_tts_provider="mock",
        anthropic_api_key="sk-test-no-real",
        briefer_output_dir=tmp_path / "outputs",
    )


class _FakeModels:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def retrieve(self, model: str):
        self.calls.append(model)
        if self.fail:
            raise ConnectionError("sin red")
        return SimpleNamespace(id=model)


def test_shared_client_and_warmup_are_free(anthropic_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[object] = []
    models = _FakeModels()

    def fake_make_client(_settings):
        client = SimpleNamespace(models=models, messages=None)
        created.append(client)
        return client

    common.reset_clients()
    monkeypatch.setattr(common, "make_client", fake_make_client)
    try:
        a, b = AnthropicLLM(anthropic_settings), AnthropicLLM(anthropic_settings, cheap=True)
        assert a._get_client() is b._get_client()  # un solo cliente (y pool HTTP) por proceso
        timings = pipeline.warmup(anthropic_settings, mode="real")
        assert {"llm", "vision", "total"} <= set(timings)
        assert models.calls == ["claude-haiku-4-5-20251001", "claude-sonnet-5-5"]  # sin tokens
        assert len(created) == 1
    finally:
        common.reset_clients()


def test_warmup_swallows_provider_errors(anthropic_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    common.reset_clients()
    monkeypatch.setattr(common, "make_client", lambda _s: SimpleNamespace(models=_FakeModels(fail=True)))
    try:
        timings = pipeline.warmup(anthropic_settings, mode="real")
        assert "llm" not in timings and "total" in timings
    finally:
        common.reset_clients()


def test_client_cache_key_never_contains_the_secret(anthropic_settings: Settings) -> None:
    key = common._client_key(anthropic_settings)
    assert "sk-test" not in key and len(key) == 16


# ── Modelo del Guionista ──────────────────────────────────────────────────────────


def test_scriptwriter_llm_defaults_to_cheap_and_is_configurable(anthropic_settings: Settings) -> None:
    providers = pipeline.get_providers(anthropic_settings)
    assert pipeline.scriptwriter_llm(anthropic_settings, providers) is providers.llm_cheap
    custom = anthropic_settings.model_copy(update={"briefer_scriptwriter_model": "claude-sonnet-5-5"})
    llm = pipeline.scriptwriter_llm(custom, pipeline.get_providers(custom))
    assert llm.model == "claude-sonnet-5-5" and llm.provider_name == "anthropic"
    mock_providers = pipeline.get_providers(custom, use_mock=True)
    assert isinstance(pipeline.scriptwriter_llm(custom, mock_providers), MockLLM)


# ── Coste de la portada: se anota en cuanto la imagen se ha generado ──────────────


class _PaidImageGen(ImageGenProvider):
    """Generador falso «de pago» (tarifa de Gemini) que escribe un PNG sin red."""

    provider_name, model = "gemini", "gemini-3.1-flash-lite-image"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def generate(self, prompt: str, out_path: Path) -> Path:
        if self.fail:
            raise RuntimeError("cuota agotada")
        from briefer.providers.mock import write_solid_png

        return write_solid_png(out_path)


@pytest.mark.parametrize(("gen_fails", "charged"), [(False, True), (True, False)])
def test_cover_cost_is_recorded_even_if_overlay_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, gen_fails: bool, charged: bool
) -> None:
    providers = pipeline.get_providers(settings, use_mock=True)
    providers.image_gen = _PaidImageGen(fail=gen_fails)
    monkeypatch.setattr(pipeline, "_providers_for_mode", lambda *_a: providers)

    def broken_overlay(*_a, **_k):
        raise OSError("fuente rota")

    monkeypatch.setattr(pipeline.cover_mod, "overlay_title", broken_overlay)
    briefing = pipeline.run_briefing(["SAN.MC"], settings=settings, use_mock=True, make_cover=True)
    cover_metric = next(m for m in briefing.metrics if m.step == "media.cover")
    assert cover_metric.error  # el paso falló (opcional: el briefing sale igual)
    expected = costs.estimate_image_cost_eur("gemini", 1, "gemini-3.1-flash-lite-image") if charged else 0.0
    assert expected > 0 or not charged
    assert cover_metric.est_cost_eur == pytest.approx(expected)
