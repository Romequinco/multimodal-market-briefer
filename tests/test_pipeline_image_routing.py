"""Enrutado de imágenes subidas al briefing (router CLIP en ``pipeline.process_upload``), sin red."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from briefer import pipeline
from briefer.config import Settings
from briefer.ingest import chart_reader
from briefer.providers.base import ImageClassifier
from briefer.schemas import StepMetric


class FixedClassifier(ImageClassifier):
    """Clasificador falso que siempre elige ``label`` con probabilidad 0,95."""

    provider_name = "fake"
    model = "fake"

    def __init__(self, label: str) -> None:
        self.label = label

    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
        rest = 0.05 / max(1, len(labels) - 1)
        return {lb: (0.95 if lb == self.label else rest) for lb in labels}


class CountingVision:
    """Visión mock que cuenta las llamadas."""

    def __init__(self, inner) -> None:
        self.inner, self.calls = inner, 0
        self.provider_name, self.model = inner.provider_name, inner.model

    def describe(self, image: bytes, prompt: str) -> str:
        self.calls += 1
        return self.inner.describe(image, prompt)


@pytest.fixture
def chart_png(settings: Settings) -> Path:
    return settings.samples_path / "grafico_ejemplo.png"


def _providers(settings: Settings, label: str) -> tuple[pipeline.Providers, CountingVision]:
    base = pipeline.get_providers(settings, use_mock=True)
    vision = CountingVision(base.vision)
    return replace(base, classifier=FixedClassifier(label), vision=vision), vision  # type: ignore[arg-type]


def test_portfolio_screenshot_is_diverted_without_vision(settings: Settings, chart_png: Path) -> None:
    providers, vision = _providers(settings, chart_reader.PORTFOLIO_LABEL)
    metrics: list[StepMetric] = []
    with pytest.raises(ValueError, match="Mi cartera"):
        pipeline.process_upload(chart_png, providers, metrics)
    assert vision.calls == 0
    assert metrics[-1].step == "ingest.chart" and "cartera" in (metrics[-1].detail or "")


def test_non_financial_image_is_rejected_without_vision(settings: Settings, chart_png: Path) -> None:
    providers, vision = _providers(settings, chart_reader.NOT_CHART_LABEL)
    metrics: list[StepMetric] = []
    with pytest.raises(ValueError, match="no parece un gráfico financiero"):
        pipeline.process_upload(chart_png, providers, metrics)
    assert vision.calls == 0


def test_chart_goes_to_vision_with_route_in_trace(settings: Settings, chart_png: Path) -> None:
    providers, vision = _providers(settings, chart_reader.CANDLES_LABEL)
    metrics: list[StepMetric] = []
    insight = pipeline.process_upload(chart_png, providers, metrics)
    assert insight.source_type == "chart" and vision.calls >= 1
    assert (metrics[-1].detail or "").startswith("Clasificador fake: gráfico de velas")


def test_video_never_includes_portfolio_chart(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """El vídeo se guarda en data/outputs y se envía: el gráfico de la cartera no entra (ADR-005)."""
    from briefer.schemas import Portfolio, Position

    seen: list[list[Path]] = []

    def fake_video(audio, images, out_path, transcript=None, **_kw):
        seen.append(list(images))
        raise RuntimeError("sin vídeo en el test")

    monkeypatch.setattr(pipeline.video_mod, "make_video", fake_video)
    pf = Portfolio(name="P", positions=[Position(ticker="SAN.MC", weight=0.6), Position(ticker="AAPL", weight=0.4)])
    briefing = pipeline.run_briefing([], portfolio=pf, settings=settings, use_mock=True, make_video=True)
    pie = [c.path for c in briefing.charts if c.kind == "portfolio_pie"]
    assert seen and seen[0]
    assert not set(seen[0]) & set(pie)
    assert all("portfolio" not in p.name for p in seen[0])


# ── Sin router: la propia visión clasifica la captura de cartera (ADR-005) ─────────

#: Lo que contestaría un modelo de visión desobediente: marcador + nombres e importes.
LEAKY_PORTFOLIO_ANSWER = "TIPO: cartera\nBanco Santander | SAN | 1.500 | 6.780,00 €"


class ScriptedVision:
    """Visión falsa que responde ``answer`` y cuenta las llamadas (sin red)."""

    provider_name, model = "fake", "fake-vision"

    def __init__(self, answer: str) -> None:
        self.answer, self.calls, self.last_usage = answer, 0, {"input_tokens": 0, "output_tokens": 0}

    def describe(self, image: bytes, prompt: str) -> str:
        self.calls += 1
        assert chart_reader.PORTFOLIO_MARKER in prompt  # el prompt pide clasificar
        return self.answer


class SpyLLM:
    provider_name, model = "fake", "fake-llm"

    def __init__(self) -> None:
        self.calls, self.last_usage = 0, {"input_tokens": 0, "output_tokens": 0}

    def complete(self, system, messages, response_model=None):
        self.calls += 1
        raise AssertionError("no debe llamarse al LLM de estructura con una captura de cartera")


@pytest.mark.parametrize("answer", ["TIPO: cartera", LEAKY_PORTFOLIO_ANSWER, "**Tipo:** Cartera"])
def test_vision_classifies_portfolio_without_router(answer: str, chart_png: Path) -> None:
    llm = SpyLLM()
    with pytest.raises(ValueError) as info:
        chart_reader.read_chart(chart_png.read_bytes(), "cartera.png", ScriptedVision(answer), llm)  # type: ignore[arg-type]
    assert str(info.value) == chart_reader.PORTFOLIO_REDIRECT_MSG and llm.calls == 0


def test_type_line_is_removed_from_chart_description(chart_png: Path) -> None:
    vision = ScriptedVision("TIPO: grafico\nGráfico de velas de SAN.MC en septiembre. Cierre 4,52 €.")
    insight = chart_reader.read_chart(chart_png.read_bytes(), "g.png", vision)  # type: ignore[arg-type]
    assert "TIPO" not in insight.extracted_text and insight.extracted_text.startswith("Gráfico de velas")
    assert insight.summary == "Gráfico de velas de SAN.MC en septiembre."


def test_mock_vision_still_reads_charts(chart_png: Path) -> None:
    from briefer.providers.mock import MockLLM, MockVision

    insight = chart_reader.read_chart(chart_png.read_bytes(), "g.png", MockVision(), MockLLM())
    assert insight.source_type == "chart" and insight.extracted_text.startswith("[MOCK]")


def test_chart_structured_output_error_is_masked(chart_png: Path) -> None:
    from pydantic import ValidationError

    from briefer.schemas import DocumentInsight

    class BadLLM(SpyLLM):
        def complete(self, system, messages, response_model=None):
            DocumentInsight.model_validate({"source_type": "chart", "summary": "CIFRA-SECRETA"})

    vision = ScriptedVision("TIPO: grafico\nGráfico.")
    with pytest.raises(ValueError) as info:
        chart_reader.read_chart(chart_png.read_bytes(), "g.png", vision, BadLLM())  # type: ignore[arg-type]
    assert not isinstance(info.value, ValidationError) and "CIFRA-SECRETA" not in str(info.value)
    assert info.value.__suppress_context__


def test_portfolio_upload_without_router_is_never_persisted(
    settings: Settings, chart_png: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Captura de cartera subida en «Briefing» sin CLIP: no llega a ``briefing.json``."""
    base = pipeline.get_providers(settings, use_mock=True)
    providers = replace(base, classifier=None, vision=ScriptedVision(LEAKY_PORTFOLIO_ANSWER))  # type: ignore[arg-type]
    metrics: list[StepMetric] = []
    with pytest.raises(ValueError, match="Mi cartera"):
        pipeline.process_upload(chart_png, providers, metrics)
    assert metrics[-1].error and "Santander" not in metrics[-1].error

    monkeypatch.setattr(pipeline, "_providers_for_mode", lambda *_a: providers)
    upload = tmp_path / "cartera.png"
    upload.write_bytes(chart_png.read_bytes())
    briefing = pipeline.run_briefing(["SAN.MC"], uploads=[upload], settings=settings, use_mock=True)
    assert briefing.context.insights == []
    saved = "".join(p.read_text(encoding="utf-8") for p in settings.output_path.rglob("*.json"))
    assert "6.780" not in saved and "Banco Santander" not in saved
