"""Ingesta de noticias de mercado: yfinance + RSS (feedparser), o ejemplos offline.

Carril A. Salida: ``list[NewsItem]`` deduplicada y ordenada por fecha (más reciente primero).
El filtrado por tickers lo hace ``ingest.tickers.filter_by_tickers``.
Fuentes: ``yfinance.Ticker(t).news`` por ticker y feeds de ``BRIEFER_NEWS_RSS_FEEDS``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from briefer.schemas import NewsItem


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
    raise NotImplementedError("fetch_yfinance_news: pendiente (carril A)")


def fetch_rss_news(feeds: list[str], max_items: int = 20) -> list[NewsItem]:
    """Noticias de feeds RSS/Atom (prensa económica en español)."""
    # TODO:
    # 1. import feedparser; for url in feeds: d = feedparser.parse(url).
    # 2. entry.title, entry.summary (limpiar HTML con re o html.unescape), entry.link,
    #    entry.published_parsed -> datetime UTC; source = d.feed.title.
    # 3. tickers=[] (se rellenan luego con ingest.tickers.extract_tickers).
    # Casos borde: feed caído (d.bozo) -> saltar con aviso; entradas sin fecha -> now().
    raise NotImplementedError("fetch_rss_news: pendiente (carril A)")


def dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    """Elimina duplicados por URL y por título normalizado; fusiona listas de tickers."""
    # TODO: clave = url sin query; segunda pasada por título en minúsculas sin signos.
    # Al fusionar, unir tickers (sin repetir) y conservar el resumen más largo.
    raise NotImplementedError("dedupe_news: pendiente (carril A)")


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
    raise NotImplementedError("fetch_news: pendiente (carril A)")


def load_sample_news(path: Path | None = None) -> list[NewsItem]:
    """Carga ``data/samples/noticias_ejemplo.json`` (modo offline / demo con mocks)."""
    # TODO: path = path or get_settings().samples_path / "noticias_ejemplo.json";
    # json.loads(path.read_text("utf-8")) y [NewsItem.model_validate(x) for x in data].
    raise NotImplementedError("load_sample_news: pendiente (carril A)")
