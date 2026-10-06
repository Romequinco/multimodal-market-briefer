"""Router de imágenes: CLIP zero-shot (``providers.image.clip_classifier``) + ``chart_reader``.

Sin red ni torch: la lógica de enrutado se prueba con clasificadores falsos. El test ``live``
carga CLIP de verdad (``-m live``; ~600 MB la primera vez en la caché de Hugging Face, 0 €) y
clasifica las imágenes sintéticas de ``tests/fixtures/images`` (``generar_imagenes.py``).
"""

from __future__ import annotations

import builtins
import time
from pathlib import Path
from typing import Any

import pytest

from briefer.config import Settings
from briefer.ingest import chart_reader
from briefer.providers.base import ImageClassifier
from briefer.providers.image import clip_classifier
from briefer.providers.image.clip_classifier import LABEL_PROMPTS, CLIPClassifier, prompts_for
from briefer.providers.mock import MockImageClassifier, MockLLM, MockVision

IMAGES = Path(__file__).parent / "fixtures" / "images"
SAMPLE_PNG = IMAGES.parents[2] / "data" / "samples" / "grafico_ejemplo.png"


class FixedClassifier(ImageClassifier):
    """Clasificador falso: da ``top`` a una etiqueta y reparte el resto."""

    provider_name = "clip"

    def __init__(self, label: str, top: float = 0.9) -> None:
        self.label, self.top, self.model = label, top, "fake-clip"
        self.calls = 0

    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
        self.calls += 1
        rest = (1 - self.top) / (len(labels) - 1)
        return {lb: (self.top if lb == self.label else rest) for lb in labels}


class BrokenClassifier(ImageClassifier):
    provider_name = "clip"
    model = "fake-clip"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def classify(self, image: bytes, labels: list[str]) -> dict[str, float]:
        raise self.exc


class SpyVision(MockVision):
    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def describe(self, image: bytes, prompt: str) -> str:
        self.prompts.append(prompt)
        return super().describe(image, prompt)


class NoVision(MockVision):
    def describe(self, image: bytes, prompt: str) -> str:  # pragma: no cover - no debe llamarse
        raise AssertionError("no debe llamarse a visión")


@pytest.fixture
def chart_png() -> bytes:
    return SAMPLE_PNG.read_bytes()


# ── etiquetas y decisión ──────────────────────────────────────────────────────────


def test_every_chart_label_has_english_prompts() -> None:
    assert set(chart_reader.CHART_LABELS) == set(LABEL_PROMPTS)
    assert all(len(LABEL_PROMPTS[lb]) >= 2 for lb in chart_reader.CHART_LABELS)
    assert prompts_for("un gato") == tuple(t.format("un gato") for t in clip_classifier.GENERIC_TEMPLATES)


def test_mock_classifier_still_routes_to_chart() -> None:
    """El camino mock (sin red) sigue llegando a visión: la primera etiqueta es un gráfico."""
    route = chart_reader.classify_image(b"x", MockImageClassifier())
    assert route.kind == "grafico" and route.label == chart_reader.CANDLES_LABEL


def test_decide_route_sums_not_financial_labels() -> None:
    probs = dict.fromkeys(chart_reader.CHART_LABELS, 0.0)
    probs.update(
        {chart_reader.NOT_CHART_LABEL: 0.25, chart_reader.MEME_LABEL: 0.4, chart_reader.LINES_LABEL: 0.35}
    )
    route = chart_reader.decide_route(probs)
    assert route.rejected and route.label == chart_reader.MEME_LABEL and route.prob == pytest.approx(0.65)


def test_decide_route_table_and_low_confidence_hint() -> None:
    probs = dict.fromkeys(chart_reader.CHART_LABELS, 0.05)
    probs[chart_reader.TABLE_LABEL] = 0.7
    assert chart_reader.decide_route(probs).kind == "tabla"
    flat = dict.fromkeys(chart_reader.CHART_LABELS, 1 / len(chart_reader.CHART_LABELS))
    route = chart_reader.decide_route(flat)
    assert route.kind == "grafico" and route.hint() == ""  # confianza baja: sin pista


# ── read_chart con el router ──────────────────────────────────────────────────────


def test_non_financial_image_rejected_without_vision(chart_png: bytes) -> None:
    stats: dict[str, Any] = {}
    with pytest.raises(ValueError, match="no parece un gráfico financiero"):
        chart_reader.read_chart(
            chart_png,
            "foto.png",
            NoVision(),
            classifier=FixedClassifier(chart_reader.NOT_CHART_LABEL),
            stats_out=stats,
        )
    assert stats["kind"] == "no_financiera" and stats["status"] == "ok"
    assert "rechazada sin visión" in (chart_reader.format_route_stats(stats) or "")


def test_portfolio_screenshot_detected(chart_png: bytes) -> None:
    clf = FixedClassifier(chart_reader.PORTFOLIO_LABEL, 0.8)
    stats: dict[str, Any] = {}
    route = chart_reader.route_image(chart_png, clf, stats_out=stats)
    assert route is not None and route.is_portfolio and route.label == chart_reader.PORTFOLIO_LABEL
    assert stats["kind"] == "cartera"
    assert (chart_reader.format_route_stats(stats) or "").startswith("CLIP: captura de cartera")
    # Si el llamante no la enruta, se lee como gráfico con la pista y sin reclasificar.
    vision = SpyVision()
    insight = chart_reader.read_chart(chart_png, "cartera.png", vision, classifier=clf, route=route)
    assert insight.source_type == "chart" and clf.calls == 1
    assert chart_reader.PORTFOLIO_LABEL in vision.prompts[0]


def test_chart_goes_to_vision_with_hint(chart_png: bytes) -> None:
    vision, stats = SpyVision(), {}  # type: ignore[var-annotated]
    insight = chart_reader.read_chart(
        chart_png,
        "velas.png",
        vision,
        llm=MockLLM(),
        classifier=FixedClassifier(chart_reader.CANDLES_LABEL),
        stats_out=stats,
    )
    assert insight.source_type == "chart" and insight.source_name == "velas.png"
    assert "Pista" in vision.prompts[0] and chart_reader.CANDLES_LABEL in vision.prompts[0]
    detail = chart_reader.format_route_stats(stats)
    assert detail is not None and detail.startswith("CLIP: gráfico de velas japonesas (90 %)")


@pytest.mark.parametrize(
    ("exc", "status"),
    [(ImportError("sin torch"), "no instalado"), (RuntimeError("boom"), "error: RuntimeError")],
)
def test_classifier_failure_does_not_break(chart_png: bytes, exc: Exception, status: str) -> None:
    vision, stats = SpyVision(), {}  # type: ignore[var-annotated]
    insight = chart_reader.read_chart(
        chart_png, "g.png", vision, classifier=BrokenClassifier(exc), stats_out=stats
    )
    assert insight.summary and "Pista" not in vision.prompts[0]
    assert stats["status"] == status
    assert chart_reader.format_route_stats(stats) == f"CLIP: {status} (sin clasificar)"


def test_without_classifier_no_trace() -> None:
    stats: dict[str, Any] = {}
    assert chart_reader.route_image(b"x", None, stats_out=stats) is None
    assert chart_reader.format_route_stats(stats) is None and chart_reader.format_route_stats(None) is None


# ── CLIPClassifier sin torch ──────────────────────────────────────────────────────


def test_clip_empty_labels_and_missing_deps(monkeypatch: pytest.MonkeyPatch, chart_png: bytes) -> None:
    clf = CLIPClassifier(Settings())
    assert clf.model == "openai/clip-vit-base-patch32"
    assert clf.classify(chart_png, []) == {}
    monkeypatch.setattr(clip_classifier, "_models", {})
    monkeypatch.setattr(clip_classifier, "clip_available", lambda: False)
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] in {"torch", "transformers"}:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="requirements-local"):
        clf.classify(chart_png, chart_reader.CHART_LABELS)
    # Y read_chart sigue adelante sin clasificar.
    insight = chart_reader.read_chart(chart_png, "g.png", MockVision(), classifier=clf)
    assert insight.source_type == "chart"


# ── CLIP real (red la primera vez; 0 €) ───────────────────────────────────────────

EXPECTED = [
    ("velas.png", "grafico", chart_reader.CANDLES_LABEL),
    ("lineas.png", "grafico", chart_reader.LINES_LABEL),
    ("tabla.png", "tabla", chart_reader.TABLE_LABEL),
    ("cartera.png", "cartera", chart_reader.PORTFOLIO_LABEL),
    ("paisaje.jpg", "no_financiera", None),  # cualquiera de las no financieras
]


@pytest.mark.live
def test_clip_real_routes_fixture_images() -> None:
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    clf = CLIPClassifier(Settings())
    for name, kind, label in [
        *EXPECTED,
        ("../../../data/samples/grafico_ejemplo.png", "grafico", chart_reader.CANDLES_LABEL),
    ]:
        start = time.perf_counter()
        route = chart_reader.classify_image((IMAGES / name).read_bytes(), clf)
        elapsed = time.perf_counter() - start
        print(f"{name}: {route.kind} · {route.label} ({route.prob:.3f}) · {elapsed * 1000:.0f} ms")
        assert route.kind == kind, (name, route)
        if label is not None:
            assert route.label == label, (name, route)
        assert abs(sum(route.probs.values()) - 1) < 1e-3
