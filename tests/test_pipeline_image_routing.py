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
