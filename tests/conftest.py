"""Fixtures comunes: fuerza proveedores mock y rutas temporales para que los tests no
usen red, claves reales ni escriban en ``data/outputs``."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from briefer.config import ROOT_DIR, Settings, reset_settings_cache
from briefer.schemas import (
    Analysis,
    AudioAsset,
    AudioSegment,
    Briefing,
    ChartAsset,
    DocumentInsight,
    KeyPoint,
    MarketContext,
    NewsItem,
    PodcastScript,
    Portfolio,
    Position,
    PriceSnapshot,
    ScriptLine,
    StepMetric,
    Transcript,
    VideoAsset,
)

SAMPLES_DIR = ROOT_DIR / "data" / "samples"

_PROVIDER_ENV = {
    "BRIEFER_LLM_PROVIDER": "mock",
    "BRIEFER_VISION_PROVIDER": "mock",
    "BRIEFER_STT_PROVIDER": "mock",
    "BRIEFER_TTS_PROVIDER": "mock",
    "BRIEFER_IMAGE_GEN_PROVIDER": "mock",
    "BRIEFER_IMAGE_CLASSIFIER_PROVIDER": "mock",
}


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Todos los proveedores en mock y salidas en un directorio temporal."""
    for key, value in _PROVIDER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BRIEFER_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("BRIEFER_CACHE_DIR", str(tmp_path / "cache"))
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings explícitos (sin leer .env) con todo en mock."""
    return Settings(
        _env_file=None,
        briefer_llm_provider="mock",
        briefer_vision_provider="mock",
        briefer_stt_provider="mock",
        briefer_tts_provider="mock",
        briefer_image_gen_provider="mock",
        briefer_image_classifier_provider="mock",
        briefer_output_dir=tmp_path / "outputs",
        briefer_cache_dir=tmp_path / "cache",
    )


@pytest.fixture
def sample_context() -> MarketContext:
    news = NewsItem(
        id="ejemplo-001",
        title="[EJEMPLO] El banco sube",
        summary="Noticia ficticia para tests.",
        source="Ejemplo",
        url="https://example.com/1",
        published_at=datetime(2026, 10, 5, 8, 0),
        tickers=["SAN.MC"],
    )
    price = PriceSnapshot(
        ticker="SAN.MC",
        last=5.1,
        change_pct=1.2,
        currency="EUR",
        history=[(date(2026, 10, 2), 5.0), (date(2026, 10, 5), 5.1)],
    )
    insight = DocumentInsight(
        source_type="pdf",
        source_name="resultados.pdf",
        extracted_text="Ingresos 100",
        key_figures={"Ingresos": "100 M€"},
        summary="Resultados ficticios.",
    )
    portfolio = Portfolio(name="Test", positions=[Position(ticker="san.mc", weight=1.0)])
    return MarketContext(
        date=date(2026, 10, 5),
        tickers=["SAN.MC"],
        news=[news],
        prices=[price],
        insights=[insight],
        portfolio=portfolio,
    )


@pytest.fixture
def sample_briefing(sample_context: MarketContext, tmp_path: Path) -> Briefing:
    analysis = Analysis(
        date=date(2026, 10, 5),
        headline="Titular",
        key_points=[
            KeyPoint(
                title="Punto",
                explanation="Explicación",
                tickers=["SAN.MC"],
                sentiment="positivo",
                sources=["ejemplo-001"],
            )
        ],
        market_mood="Neutral",
    )
    script = PodcastScript(
        title="Episodio",
        lines=[ScriptLine(speaker="A", text="Hola"), ScriptLine(speaker="B", text="Buenas")],
        est_duration_s=2.0,
    )
    audio = AudioAsset(
        path=tmp_path / "podcast.mp3",
        duration_s=2.0,
        segments=[
            AudioSegment(speaker="A", text="Hola", start_s=0.0, end_s=1.0),
            AudioSegment(speaker="B", text="Buenas", start_s=1.0, end_s=2.0),
        ],
    )
    return Briefing(
        id="20261005-090000-abcdef",
        created_at=datetime(2026, 10, 5, 9, 0),
        context=sample_context,
        analysis=analysis,
        script=script,
        audio=audio,
        transcript=Transcript(text="A: Hola\nB: Buenas", srt_path=tmp_path / "podcast.srt"),
        charts=[ChartAsset(path=tmp_path / "c.png", ticker="SAN.MC", kind="price_line")],
        cover_path=None,
        video=VideoAsset(path=tmp_path / "v.mp4", duration_s=2.0),
        metrics=[StepMetric(step="x", provider="mock", model="m", latency_s=0.1, est_cost_eur=0.0)],
    )
