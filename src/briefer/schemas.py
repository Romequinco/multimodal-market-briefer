"""Contratos de datos compartidos (Pydantic v2) — fuente única de verdad entre carriles.

Transversal: todos los carriles (A entradas, B agentes, C salidas/UI) producen y consumen
estos modelos. **Se modifica solo acordándolo en grupo**: cambiar un campo rompe a los demás.

Flujo resumido:
    NewsItem / PriceSnapshot / Portfolio / DocumentInsight  (carril A)
        -> MarketContext -> Analysis -> PodcastScript      (carril B)
        -> AudioAsset / Transcript / ChartAsset / VideoAsset (carril C)
        -> Briefing (+ StepMetric por paso) ; QAAnswer ; DeliveryResult

Todos los modelos son serializables a JSON (``model_dump_json``) para guardarlos en
``data/outputs/<id>/briefing.json`` (ver ``storage.py``).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Disclaimer MiFID II: el producto informa, no asesora. Se muestra en la UI, en el
# análisis, en el email/Telegram y se lee al final del podcast.
DISCLAIMER_ES = (
    "Contenido generado automáticamente con IA con fines exclusivamente informativos y "
    "educativos. No constituye asesoramiento financiero ni una recomendación personalizada "
    "de inversión (MiFID II). Puede contener errores: contrasta siempre con fuentes oficiales."
)

Sentiment = Literal["positivo", "negativo", "neutral"]
Speaker = Literal["A", "B"]
SourceType = Literal["pdf", "chart", "voice", "text"]
Channel = Literal["web", "email", "telegram"]


class _Model(BaseModel):
    """Base común: valida también al asignar y prohíbe campos desconocidos."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")


# ── Entradas (carril A) ────────────────────────────────────────────────────────────


class NewsItem(_Model):
    """Noticia de mercado normalizada (yfinance, RSS o ejemplo)."""

    id: str
    title: str
    summary: str
    source: str
    url: str
    published_at: datetime
    tickers: list[str] = Field(default_factory=list)
    language: str = "es"


class PriceSnapshot(_Model):
    """Foto de precio de un ticker con histórico corto (para gráficos)."""

    ticker: str
    last: float
    change_pct: float
    currency: str
    history: list[tuple[date, float]] = Field(default_factory=list)


class Position(_Model):
    """Posición de la cartera. Basta con ``weight`` (0-1) o ``quantity``."""

    ticker: str
    weight: float | None = None
    quantity: float | None = None

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()


class Portfolio(_Model):
    """Cartera del usuario (dato personal: RGPD, no se persiste sin consentimiento)."""

    name: str
    positions: list[Position] = Field(default_factory=list)


class DocumentInsight(_Model):
    """Información extraída de un PDF, captura de gráfico, nota de voz o texto libre."""

    source_type: SourceType
    source_name: str
    extracted_text: str
    key_figures: dict[str, str] = Field(default_factory=dict)
    summary: str


class MarketContext(_Model):
    """Todo lo que el Agente Analista necesita para interpretar el día."""

    date: date
    tickers: list[str]
    news: list[NewsItem] = Field(default_factory=list)
    prices: list[PriceSnapshot] = Field(default_factory=list)
    insights: list[DocumentInsight] = Field(default_factory=list)
    portfolio: Portfolio | None = None


# ── Agentes (carril B) ─────────────────────────────────────────────────────────────


class KeyPoint(_Model):
    """Idea clave del día, trazable a sus fuentes (ids/URLs de noticias o documentos)."""

    title: str
    explanation: str
    tickers: list[str] = Field(default_factory=list)
    sentiment: Sentiment = "neutral"
    sources: list[str] = Field(default_factory=list)


class Analysis(_Model):
    """Salida del Agente Analista."""

    date: date
    headline: str
    key_points: list[KeyPoint] = Field(default_factory=list)
    market_mood: str
    disclaimer: str = DISCLAIMER_ES


class ScriptLine(_Model):
    """Una intervención del diálogo. A y B se mapean a voces en config."""

    speaker: Speaker
    text: str


class PodcastScript(_Model):
    """Salida del Agente Guionista: diálogo a 2 voces (~3-5 min)."""

    title: str
    lines: list[ScriptLine] = Field(default_factory=list)
    est_duration_s: float = 0.0


# ── Salidas (carril C) ─────────────────────────────────────────────────────────────


class AudioSegment(_Model):
    """Tramo de audio de una línea del guion (para SRT y subtítulos del vídeo)."""

    speaker: Speaker
    text: str
    start_s: float
    end_s: float


class AudioAsset(_Model):
    """Podcast final concatenado."""

    path: Path
    duration_s: float
    segments: list[AudioSegment] = Field(default_factory=list)


class Transcript(_Model):
    """Transcripción completa + fichero SRT con tiempos."""

    text: str
    srt_path: Path | None = None


class ChartAsset(_Model):
    """Gráfico PNG generado. ``kind``: p. ej. "price_line", "overview_bar", "portfolio_pie"."""

    path: Path
    ticker: str | None = None
    kind: str


class VideoAsset(_Model):
    """Vídeo corto (imágenes + audio + subtítulos)."""

    path: Path
    duration_s: float


class StepMetric(_Model):
    """Métrica de un paso del pipeline (latencia y coste estimado)."""

    step: str
    provider: str
    model: str
    latency_s: float
    est_cost_eur: float = 0.0


class DeliveryResult(_Model):
    """Resultado de entregar el briefing por un canal."""

    channel: Channel
    ok: bool
    detail: str = ""


def new_briefing_id(now: datetime | None = None) -> str:
    """Id legible y ordenable: ``YYYYMMDD-HHMMSS-xxxxxx``."""
    now = now or datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"


class Briefing(_Model):
    """Resultado completo de ``pipeline.run_briefing``."""

    id: str = Field(default_factory=new_briefing_id)
    created_at: datetime = Field(default_factory=datetime.now)
    context: MarketContext
    analysis: Analysis
    script: PodcastScript
    audio: AudioAsset | None = None
    transcript: Transcript | None = None
    charts: list[ChartAsset] = Field(default_factory=list)
    cover_path: Path | None = None
    video: VideoAsset | None = None
    metrics: list[StepMetric] = Field(default_factory=list)
    # Añadido respecto a la spec inicial (opcional): resultados de entrega por canal.
    deliveries: list[DeliveryResult] = Field(default_factory=list)


class QAAnswer(_Model):
    """Respuesta del Agente Q&A (texto + audio opcional)."""

    question: str
    answer_text: str
    audio_path: Path | None = None
    sources: list[str] = Field(default_factory=list)


__all__ = [
    "DISCLAIMER_ES",
    "Analysis",
    "AudioAsset",
    "AudioSegment",
    "Briefing",
    "ChartAsset",
    "DeliveryResult",
    "DocumentInsight",
    "KeyPoint",
    "MarketContext",
    "NewsItem",
    "PodcastScript",
    "Portfolio",
    "Position",
    "PriceSnapshot",
    "QAAnswer",
    "ScriptLine",
    "StepMetric",
    "Transcript",
    "VideoAsset",
    "new_briefing_id",
]
