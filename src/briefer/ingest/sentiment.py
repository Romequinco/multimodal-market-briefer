"""«Impacto de la noticia» con FinBERT (modelo abierto de Hugging Face), segunda opinión al LLM.

Carril A (opcional, detrás de ``BRIEFER_FINBERT``). Encadena dos modelos sobre las noticias ya
seleccionadas y enriquecidas por ``ingest.news.fetch_news`` (titular + extracto):

1. **Claude Haiku** (LLM barato del proyecto) traduce al inglés, en **una sola llamada** con salida
   estructurada, las noticias que no están en inglés. Las que ya lo están pasan directas.
2. **FinBERT** (``ProsusAI/finbert``, BERT ajustado con noticias financieras, solo inglés)
   clasifica cada noticia en positivo / negativo / neutral con su probabilidad.

Por qué «impacto de la noticia» y no «sentimiento del valor»: etiquetar valores como positivos o
negativos puede leerse como recomendación implícita (MAR, ver ``docs/04``). Aquí se clasifica el
**tono de la noticia**; no se agrega por ticker ni se dice qué hacer con la acción.

Dependencias pesadas (``torch`` + ``transformers``, en ``requirements-local.txt``): si no están
instaladas, ``finbert_available()`` devuelve ``False`` y ``news_impact`` devuelve ``{}`` sin romper
nada. El modelo (~440 MB) se descarga la primera vez y queda en la caché de Hugging Face.

Sin globales: las estadísticas de cada llamada se devuelven en ``stats_out`` (como
``ingest.news.fetch_news``) y ``impact_detail`` las resume para la traza «Cómo se hizo».
No cambia el contrato: el resultado es un ``dict[id_noticia, NewsImpact]`` aparte.
"""

from __future__ import annotations

import importlib.util
import threading
import time
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from briefer.logging_utils import error_text, get_logger
from briefer.providers.base import LLMProvider
from briefer.schemas import NewsItem

log = get_logger("ingest.sentiment")

FINBERT_MODEL = "ProsusAI/finbert"
#: Caracteres máximos por noticia que se traducen / clasifican (titular + extracto).
MAX_TEXT_CHARS = 400
#: Noticias máximas por llamada de traducción (una llamada suele bastar para un briefing).
TRANSLATE_BATCH = 25

Impact = Literal["positivo", "negativo", "neutral"]
_LABELS: dict[str, Impact] = {"positive": "positivo", "negative": "negativo", "neutral": "neutral"}


class NewsImpact(BaseModel):
    """Tono de una noticia según FinBERT."""

    news_id: str
    impact: Impact
    score: float = Field(ge=0, le=1, description="Probabilidad de la etiqueta ganadora")
    probs: dict[str, float] = Field(default_factory=dict)
    text_en: str = Field(description="Texto en inglés que se clasificó")
    translated: bool = False
    model: str = FINBERT_MODEL


class _Translation(BaseModel):
    id: str
    en: str


class _Translations(BaseModel):
    items: list[_Translation]


TRANSLATE_SYSTEM = (
    "You are a professional financial translator. Translate each news snippet into natural, "
    "concise English, preserving company names, tickers, figures and the original tone. If a "
    "snippet is already in English, return it unchanged. Do not add or remove information, "
    "opinions or explanations. Return exactly one item per input id."
)


def news_text(item: NewsItem) -> str:
    """Titular + extracto, recortado a ``MAX_TEXT_CHARS``."""
    text = item.title.strip()
    if item.summary:
        text = f"{text}. {item.summary.strip()}"
    return text[:MAX_TEXT_CHARS]


def _is_english(item: NewsItem) -> bool:
    return item.language.lower().startswith("en")


# ── traducción (Claude Haiku) ─────────────────────────────────────────────────────


def translate_to_english(items: list[NewsItem], llm: LLMProvider | None) -> dict[str, str]:
    """``{id: texto_en_inglés}`` para todas las noticias que se puedan clasificar.

    Las que ya están en inglés pasan sin traducir. Las demás se traducen con ``llm`` en lotes de
    ``TRANSLATE_BATCH``; sin LLM (o con el mock, o si la llamada falla) se omiten.
    """
    out = {i.id: news_text(i) for i in items if _is_english(i)}
    pending = [i for i in items if i.id not in out]
    if not pending:
        return out
    if llm is None or getattr(llm, "provider_name", "") == "mock":
        log.info("Sin LLM real para traducir: FinBERT solo clasifica %d noticias en inglés", len(out))
        return out
    for start in range(0, len(pending), TRANSLATE_BATCH):
        batch = pending[start : start + TRANSLATE_BATCH]
        lines = "\n".join(f"- id: {i.id}\n  text: {news_text(i)}" for i in batch)
        try:
            result = llm.complete(
                TRANSLATE_SYSTEM,
                [{"role": "user", "content": f"Translate these news snippets:\n{lines}"}],
                response_model=_Translations,
            )
        except Exception as exc:  # noqa: BLE001 - sin traducción, esas noticias se omiten
            log.warning("Traducción para FinBERT fallida (%d noticias): %s", len(batch), error_text(exc))
            continue
        valid = {i.id for i in batch}
        for t in getattr(result, "items", []):
            if t.id in valid and t.en.strip():
                out[t.id] = t.en.strip()[:MAX_TEXT_CHARS]
    return out


# ── FinBERT ───────────────────────────────────────────────────────────────────────

_pipeline: Any = None
_pipeline_lock = threading.Lock()


def finbert_available() -> bool:
    """``True`` si ``transformers`` y ``torch`` están instalados (no descarga nada)."""
    return all(importlib.util.find_spec(m) is not None for m in ("transformers", "torch"))


def _get_pipeline() -> Any:
    """Carga FinBERT una sola vez por proceso (CPU). Lanza ``ImportError`` si faltan dependencias."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            from transformers import pipeline

            start = time.perf_counter()
            _pipeline = pipeline("text-classification", model=FINBERT_MODEL, top_k=None, device=-1)
            log.info("FinBERT cargado en %.1f s", time.perf_counter() - start)
    return _pipeline


def classify(texts: list[str]) -> list[dict[str, float]]:
    """Probabilidades ``{"positive", "negative", "neutral"}`` por texto (en lotes de 16)."""
    if not texts:
        return []
    clf = _get_pipeline()
    raw = clf(texts, batch_size=16, truncation=True, max_length=128)
    return [{d["label"].lower(): float(d["score"]) for d in row} for row in raw]


def to_impact(news_id: str, probs: dict[str, float], text_en: str, translated: bool) -> NewsImpact:
    label = max(probs, key=lambda k: probs[k]) if probs else "neutral"
    return NewsImpact(
        news_id=news_id,
        impact=_LABELS.get(label, "neutral"),
        score=round(probs.get(label, 0.0), 4),
        probs={_LABELS.get(k, k): round(v, 4) for k, v in probs.items()},
        text_en=text_en,
        translated=translated,
    )


def news_impact(
    items: list[NewsItem],
    llm: LLMProvider | None = None,
    *,
    enabled: bool = True,
    stats_out: dict[str, Any] | None = None,
) -> dict[str, NewsImpact]:
    """Pipeline completo: traducción (Haiku) → FinBERT. Devuelve ``{id_noticia: NewsImpact}``.

    Nunca lanza: si FinBERT no está instalado o falla, devuelve ``{}``. Si se pasa ``stats_out``,
    recibe las estadísticas de esta llamada: ``status`` (``ok`` / ``desactivado`` /
    ``sin noticias`` / ``no instalado`` / ``error: …``) y, si fue bien, ``classified``, ``skipped``,
    ``translated``, ``positivo``, ``negativo``, ``neutral``, ``translate_s`` y ``total_s``.
    """
    stats: dict[str, Any] = stats_out if stats_out is not None else {}
    stats.clear()
    if not enabled or not items:
        stats["status"] = "desactivado" if not enabled else "sin noticias"
        return {}
    if not finbert_available():
        log.info("FinBERT no instalado (pip install -r requirements-local.txt); se omite")
        stats["status"] = "no instalado"
        return {}
    start = time.perf_counter()
    texts = translate_to_english(items, llm)
    t_translate = time.perf_counter() - start
    ids = [i.id for i in items if i.id in texts]
    english = {i.id for i in items if _is_english(i)}
    try:
        probs = classify([texts[i] for i in ids])
    except Exception as exc:  # noqa: BLE001
        log.warning("FinBERT falló: %s", error_text(exc))
        stats["status"] = f"error: {type(exc).__name__}"
        return {}
    result = {nid: to_impact(nid, p, texts[nid], nid not in english) for nid, p in zip(ids, probs, strict=True)}
    counts = Counter(r.impact for r in result.values())
    stats.update(
        status="ok",
        classified=len(result),
        skipped=len(items) - len(result),
        translated=sum(r.translated for r in result.values()),
        positivo=counts.get("positivo", 0),
        negativo=counts.get("negativo", 0),
        neutral=counts.get("neutral", 0),
        translate_s=round(t_translate, 2),
        total_s=round(time.perf_counter() - start, 2),
    )
    return result


def impact_detail(stats: dict[str, Any]) -> str:
    """Una línea para ``StepMetric.detail`` a partir de las estadísticas de ``news_impact``."""
    if not stats:
        return ""
    if stats.get("status") != "ok":
        return f"FinBERT: {stats.get('status')}"
    text = (
        f"FinBERT: {stats['classified']} noticias ({stats['translated']} traducidas con Haiku) · "
        f"▲ {stats['positivo']} · ▼ {stats['negativo']} · ● {stats['neutral']}"
    )
    if stats.get("skipped"):
        text += f" · {stats['skipped']} sin clasificar"
    return text
