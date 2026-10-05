"""Ingesta de noticias de mercado: yfinance + RSS (feedparser), o ejemplos offline.

Carril A. Salida: ``list[NewsItem]`` deduplicada y ordenada por fecha (más reciente primero).
El filtrado por tickers lo hace ``ingest.tickers.filter_by_tickers``.
Fuentes: ``yfinance.Ticker(t).news`` por ticker y feeds de ``BRIEFER_NEWS_RSS_FEEDS``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from briefer.config import get_settings
from briefer.logging_utils import get_logger
from briefer.schemas import NewsItem

log = get_logger("ingest.news")

SAMPLE_NEWS_FILE = "noticias_ejemplo.json"


def fetch_yfinance_news(ticker: str, max_items: int = 10) -> list[NewsItem]:
    """Noticias recientes de un ticker vía yfinance."""
    # TODO:
    # 1. import yfinance as yf (perezoso); raw = yf.Ticker(ticker).news or [].
    # 2. El formato del dict cambia entre versiones de yfinance: soportar tanto
    #    item["title"] como item["content"]["title"], fechas en epoch
    #    (providerPublishTime) o ISO (content.pubDate), url en link o canonicalUrl.url.
    # 3. NewsItem(id=uuid estable (hash de la url), title, summary (o "" si no hay),
    #    source=publisher, url, published_at (tz-aware UTC), tickers=[ticker], language="en").
    # Casos borde: sin red / rate limit de Yahoo -> devolver [] y log.warning (no romper).
    raise NotImplementedError("fetch_yfinance_news: pendiente (carril A, D1: requiere red)")


def fetch_rss_news(feeds: list[str], max_items: int = 20) -> list[NewsItem]:
    """Noticias de feeds RSS/Atom (prensa económica en español)."""
    # TODO:
    # 1. import feedparser; for url in feeds: d = feedparser.parse(url).
    # 2. entry.title, entry.summary (limpiar HTML con re o html.unescape), entry.link,
    #    entry.published_parsed -> datetime UTC; source = d.feed.title.
    # 3. tickers=[] (se rellenan luego con ingest.tickers.extract_tickers).
    # Casos borde: feed caído (d.bozo) -> saltar con aviso; entradas sin fecha -> now().
    raise NotImplementedError("fetch_rss_news: pendiente (carril A, D1: requiere red)")


def _url_key(url: str) -> str:
    """URL sin query, fragmento ni barra final, en minúsculas (clave de duplicado)."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")).lower()


def _title_key(title: str) -> str:
    """Título en minúsculas, sin tildes ni signos y con espacios simples (clave de duplicado)."""
    folded = unicodedata.normalize("NFKD", title)
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", folded).split())


def _sort_key(item: NewsItem) -> datetime:
    """Fecha comparable aunque se mezclen datetimes con y sin zona horaria (naive = UTC)."""
    dt = item.published_at
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    """Elimina duplicados por URL y por título normalizado; fusiona listas de tickers.

    Se conserva la primera aparición (posición y ``id``), uniendo los tickers de los duplicados y
    quedándose con el resumen más largo. No muta la entrada.
    """
    result: list[NewsItem] = []
    index_by_key: dict[str, int] = {}
    for item in items:
        keys = [k for k in (f"url:{_url_key(item.url)}", f"title:{_title_key(item.title)}") if k.split(":", 1)[1]]
        pos = next((index_by_key[k] for k in keys if k in index_by_key), None)
        if pos is None:
            pos = len(result)
            result.append(item.model_copy())
        else:
            kept = result[pos]
            update: dict[str, object] = {"tickers": list(dict.fromkeys([*kept.tickers, *item.tickers]))}
            if len(item.summary) > len(kept.summary):
                update["summary"] = item.summary
            result[pos] = kept.model_copy(update=update)
        for k in keys:
            index_by_key.setdefault(k, pos)
    return result


def fetch_news(
    tickers: list[str],
    max_items: int = 20,
    since: datetime | None = None,
    rss_feeds: list[str] | None = None,
) -> list[NewsItem]:
    """Punto de entrada: yfinance por ticker + RSS, deduplicado, filtrado por fecha y recortado.

    Args:
        tickers: tickers de interés (se consulta yfinance para cada uno).
        max_items: máximo de noticias devueltas.
        since: descartar noticias anteriores (por defecto, últimas 24-48 h).
        rss_feeds: feeds adicionales (por defecto ``settings.rss_feeds``).
    """
    # TODO:
    # 1. items = [*fetch_yfinance_news(t) for t in tickers] + fetch_rss_news(feeds).
    # 2. Rellenar tickers de noticias RSS con tickers.extract_tickers(title + summary).
    # 3. dedupe_news; filtrar por since; ordenar por published_at desc; recortar a max_items.
    # 4. Cachear en settings.cache_path / "news_<fecha>.json" para no repetir llamadas
    #    durante la demo (TTL ~30 min).
    raise NotImplementedError("fetch_news: pendiente (carril A, D1: requiere red)")


def load_sample_news(path: Path | None = None) -> list[NewsItem]:
    """Carga ``data/samples/noticias_ejemplo.json`` (modo offline / demo con mocks).

    Devuelve las noticias validadas contra ``NewsItem`` y ordenadas por fecha (más reciente
    primero). El filtrado por tickers se hace después con ``ingest.tickers.filter_by_tickers``.

    Raises:
        FileNotFoundError: si no existe el fichero.
        ValueError: si el JSON no es una lista de noticias válidas.
    """
    path = Path(path) if path else get_settings().samples_path / SAMPLE_NEWS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON de noticias no válido en {path.name}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"{path.name} debe contener una lista de noticias")
    items = [NewsItem.model_validate(x) for x in data]
    return sorted(items, key=_sort_key, reverse=True)
