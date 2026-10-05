"""Ingesta de noticias de mercado: yfinance/Yahoo, Google News y Bing News RSS y prensa económica, u offline.

Carril A. Salida: ``list[NewsItem]`` deduplicada y ordenada por fecha (más reciente primero).
El filtrado final por tickers lo hace ``ingest.tickers.filter_by_tickers``.

Fuentes (todas sin clave):

- **yfinance** (``yf.Ticker(t).get_news``), en inglés. Su API de noticias cambia de formato entre
  versiones (planos ``title``/``providerPublishTime`` o anidados ``content.title``/``content.pubDate``)
  y a veces deja de responder (si no da nada, se desactiva hasta el día siguiente). Se complementa
  siempre con el **RSS de titulares de Yahoo Finance** del ticker.
- **Google News RSS en español** por nombre de empresa (``TICKER_UNIVERSE``) más términos de
  mercado, para que los valores ``.MC`` tengan cobertura en español.
- **Bing News RSS en español** con la misma consulta: trae extracto y enlace directo al medio
  (dentro de su redirección ``apiclick``), así que complementa a Google News, que no trae ninguno.
- **Feeds generalistas de mercados** en español (``DEFAULT_MARKET_FEEDS`` o ``BRIEFER_NEWS_RSS_FEEDS``).

``fetch_news`` combina las fuentes en paralelo, tolera que fallen algunas, deduplica (también
titulares casi idénticos entre medios), filtra por ventana temporal (48 h ampliable a 72 h / 7 días
si hay pocas) y reparte el cupo por ticker priorizando por **relevancia** (``relevance_score``:
mención en el titular > en el resumen, frescura, español). Después **enriquece** las seleccionadas
(``enrich_news``): URL final del medio en lugar de la redirección de Google News y extracto breve de
``og:description`` si el feed no trae resumen (``ingest.article_meta``: solo metadatos, respeta
``robots.txt``, con presupuesto de tiempo). Ese enriquecimiento se **adelanta** (``prefetch_meta``)
con una selección provisional en cuanto solo quedan por responder las fuentes lentas (yfinance), así
que en frío casi todas las elegidas llegan con extracto sin alargar la ingesta. Cada respuesta de
red se cachea por día en ``settings.cache_path`` (ver ``ingest.cache``). Las estadísticas (fuentes,
descartes, relevancia y motivos de cada elegida) se devuelven por llamada en ``stats_out`` y
``format_news_stats`` las resume para la traza «Cómo se hizo».

Derechos de autor: de cada noticia solo se guarda titular + extracto breve (``SUMMARY_MAX_CHARS``)
+ fuente + enlace; nunca el cuerpo del artículo.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import json
import math
import re
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from briefer.config import get_settings
from briefer.ingest import article_meta, cache
from briefer.ingest.tickers import TICKER_UNIVERSE, extract_tickers, normalize_ticker
from briefer.logging_utils import get_logger
from briefer.schemas import NewsItem

log = get_logger("ingest.news")

SAMPLE_NEWS_FILE = "noticias_ejemplo.json"

#: Timeout (s) de cada petición HTTP y tiempo máximo total de ``fetch_news`` esperando fuentes.
HTTP_TIMEOUT = 8.0
TOTAL_TIMEOUT = 25.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 market-briefer/0.1"
)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
YAHOO_HEADLINES_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
#: Términos que acotan la búsqueda de Google News a noticias de mercado (evita «Liga Iberdrola»,
#: reseñas del iPhone u ofertas de empleo).
GOOGLE_MARKET_TERMS = '(acciones OR bolsa OR resultados OR mercado OR Ibex OR "Wall Street" OR inversores)'
#: Días hacia atrás que se piden a Google News (``when:Nd``): cubre la ventana más amplia.
GOOGLE_NEWS_DAYS = 7
#: RSS de búsqueda de Bing News (es-ES): trae extracto (``description``) y el enlace real del medio
#: dentro del parámetro ``url`` de su redirección, así que no hace falta visitar el artículo.
BING_NEWS_RSS = "https://www.bing.com/news/search"

#: Feeds generalistas de mercados en español (verificados el 05-oct-2026). Se usan si
#: ``BRIEFER_NEWS_RSS_FEEDS`` está vacío.
DEFAULT_MARKET_FEEDS: tuple[str, ...] = (
    "https://e00-expansion.uecdn.es/rss/mercados.xml",
    "https://www.europapress.es/rss/rss.aspx?ch=00136",
)

#: Ventanas temporales (horas) que se prueban en orden hasta tener suficientes noticias.
WINDOWS_HOURS: tuple[int, ...] = (48, 72, 168)
#: Mínimo de noticias por ticker para no ampliar la ventana.
MIN_PER_TICKER = 3
#: Longitud máxima del resumen limpio (derechos de autor: extracto breve, ver docs/04 §5).
SUMMARY_MAX_CHARS = 200
#: Máximo de bytes que se leen de un feed (un servidor roto no llena la memoria).
MAX_FEED_BYTES = 5_000_000
#: Margen tolerado para fechas en el futuro (zonas horarias mal declaradas); más allá, se usa «ahora».
FUTURE_TOLERANCE = timedelta(minutes=15)
#: Similitud (Jaccard de palabras del titular) a partir de la cual dos titulares son la misma noticia.
NEAR_DUP_THRESHOLD = 0.75
#: Hilos para descargar fuentes (E/S de red: más hilos que núcleos).
FETCH_WORKERS = 32
#: Presupuesto total (s) y paralelismo del enriquecimiento (URL final + ``og:description``).
ENRICH_BUDGET_S = 3.0
ENRICH_WORKERS = 12

# Las estadísticas de cada llamada (fuentes, calidad, enriquecimiento, relevancia de las elegidas)
# se devuelven SOLO por ``stats_out``: no hay globales de «última llamada», que dos briefings
# simultáneos (dos sesiones de Streamlit) se pisarían.

#: Parámetros de URL de seguimiento que no identifican el artículo (se ignoran al deduplicar).
_TRACKING_PARAMS = {
    "oc", "ocid", "guccounter", "guce_referrer", "guce_referrer_sig", "tsrc", ".tsrc", "ref", "ref_src",
    "fbclid", "gclid", "mc_cid", "mc_eid", "cmpid", "smid", "ito", "src", "source", "rss", "feed",
}


class NewsFetchError(RuntimeError):
    """Todas las fuentes de noticias han fallado (sin red, bloqueo, etc.)."""


# ── utilidades ────────────────────────────────────────────────────────────────────


def _http_get(url: str, timeout: float = HTTP_TIMEOUT) -> bytes:
    """GET con User-Agent de navegador y timeout corto. Lanza si el estado no es 2xx.

    Lee como mucho ``MAX_FEED_BYTES`` (un feed más grande se trunca y feedparser lo marcará roto).
    """
    import requests

    with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, stream=True) as resp:
        resp.raise_for_status()
        chunks: list[bytes] = []
        size = 0
        for chunk in resp.iter_content(chunk_size=65_536):
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_FEED_BYTES:
                log.warning("Respuesta de %s truncada a %d bytes", urlsplit(url).netloc, MAX_FEED_BYTES)
                break
        return b"".join(chunks)


_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(text: str | None, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """Quita etiquetas HTML y entidades, normaliza espacios y recorta a ``max_chars``."""
    if not text:
        return ""
    plain = html.unescape(_TAG_RE.sub(" ", html.unescape(str(text))))
    plain = " ".join(plain.replace("\xa0", " ").split())
    if len(plain) > max_chars:
        plain = plain[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return plain


def news_id(url: str, title: str = "") -> str:
    """Id estable de una noticia: ``n-`` + sha1 de la URL normalizada (o del título si no hay URL)."""
    basis = _url_key(url) if url.strip() else _title_key(title)
    return "n-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _parse_datetime(value: Any) -> datetime | None:
    """Fecha a ``datetime`` UTC con zona: epoch (s o ms), ISO 8601, ``struct_time`` o datetime."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, time.struct_time):
            return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e12 else value
            return datetime.fromtimestamp(seconds, tz=UTC)
        text = str(value).strip()
        if text.isdigit():
            return _parse_datetime(int(text))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def _not_future(dt: datetime, now: datetime | None = None) -> datetime:
    """Fechas en el futuro (zona horaria mal declarada en el feed) -> ahora, para no colarse primeras."""
    now = now or datetime.now(UTC)
    return now if dt > now + FUTURE_TOLERANCE else dt


def _language(code: str | None, default: str) -> str:
    """``"es-ES"`` -> ``"es"``; vacío -> ``default``."""
    code = (code or "").strip().lower()
    return code.split("-", 1)[0].split("_", 1)[0] if code else default


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


# ── yfinance / Yahoo ──────────────────────────────────────────────────────────────


def parse_yfinance_item(raw: dict, ticker: str) -> NewsItem | None:
    """Convierte una noticia de yfinance (formato antiguo o nuevo) en ``NewsItem``.

    - Antiguo (yfinance < 0.2.48): ``title``, ``publisher``, ``link``, ``providerPublishTime`` (epoch).
    - Nuevo: ``content.title``, ``content.summary``, ``content.provider.displayName``,
      ``content.canonicalUrl.url`` (o ``clickThroughUrl.url``), ``content.pubDate`` (ISO).

    Devuelve ``None`` si falta título o URL (no se puede citar).
    """
    if not isinstance(raw, dict):
        return None
    content = _as_dict(raw.get("content")) or raw
    title = clean_html(content.get("title") or raw.get("title"), max_chars=300)
    url = (
        _as_dict(content.get("canonicalUrl")).get("url")
        or _as_dict(content.get("clickThroughUrl")).get("url")
        or content.get("link")
        or raw.get("link")
        or ""
    )
    if not title or not url:
        return None
    summary = clean_html(content.get("summary") or content.get("description") or raw.get("summary"))
    provider = _as_dict(content.get("provider"))
    source = provider.get("displayName") or content.get("publisher") or raw.get("publisher") or "Yahoo Finance"
    published = _not_future(
        _parse_datetime(content.get("pubDate"))
        or _parse_datetime(content.get("displayTime"))
        or _parse_datetime(raw.get("providerPublishTime"))
        or datetime.now(UTC)
    )
    lang = _language(_as_dict(content.get("canonicalUrl")).get("lang"), "en")
    return NewsItem(
        id=news_id(url, title),
        title=title,
        summary=summary,
        source=str(source),
        url=str(url),
        published_at=published,
        tickers=[ticker],
        language=lang,
    )


#: Errores/vacíos seguidos de la API de noticias de yfinance (de tickers distintos) a partir de los
#: cuales se desactiva hasta el día siguiente, si hoy no ha devuelto nada para ningún ticker.
YF_NEWS_MAX_EMPTY = 3

_yf_lock = threading.Lock()
_yf_news: dict[str, Any] = {"day": None, "empty": set(), "ok": False, "off": False}


def _reset_yf_news_state() -> None:
    """Reinicia el cortocircuito de yfinance (nuevo día o tests)."""
    with _yf_lock:
        _yf_news.update(day=date.today(), empty=set(), ok=False, off=False)


def _yf_news_disabled() -> bool:
    """True si hoy ya se comprobó que la API de noticias de yfinance no responde (memoria o caché)."""
    if _yf_news["day"] != date.today():
        _reset_yf_news_state()
    with _yf_lock:
        if _yf_news["off"]:
            return True
    if cache.read_cache("news-yfinance", "disabled"):
        with _yf_lock:
            _yf_news["off"] = True
        return True
    return False


def _record_yf_news(ticker: str, ok: bool) -> None:
    """Anota el resultado; con ``YF_NEWS_MAX_EMPTY`` tickers sin nada y ninguno con éxito, se desactiva."""
    with _yf_lock:
        if ok:
            _yf_news["ok"] = True
            return
        _yf_news["empty"].add(ticker)
        if _yf_news["ok"] or _yf_news["off"] or len(_yf_news["empty"]) < YF_NEWS_MAX_EMPTY:
            return
        _yf_news["off"] = True
    log.info("La API de noticias de yfinance no devuelve nada; se desactiva hasta mañana")
    cache.write_cache("news-yfinance", "disabled", True)


def _yfinance_lib_news(ticker: str, max_items: int) -> list[NewsItem]:
    """Noticias vía la librería yfinance (lanza si falla la llamada).

    Cortocircuito: si falla o no devuelve nada para ``YF_NEWS_MAX_EMPTY`` tickers distintos sin
    ningún éxito, no se vuelve a llamar hasta mañana (en oct-2026 su endpoint de noticias responde
    404 y yfinance devuelve ``[]`` tras 3-5 s). El estado se guarda también en la caché del día.
    """
    if _yf_news_disabled():
        return []
    import yfinance as yf

    try:
        tk = yf.Ticker(ticker)
        raw = tk.get_news(count=max_items) if hasattr(tk, "get_news") else tk.news
    except Exception:
        _record_yf_news(ticker, ok=False)
        raise
    parsed = [parse_yfinance_item(r, ticker) for r in (raw or [])]
    items = [i for i in parsed if i is not None][:max_items]
    _record_yf_news(ticker, ok=bool(items))
    return items


def _yahoo_rss_news(ticker: str, max_items: int) -> list[NewsItem]:
    """Respaldo: RSS de titulares de Yahoo Finance del ticker (lanza si falla)."""
    url = YAHOO_HEADLINES_RSS.format(ticker=quote(ticker))
    items = _fetch_feed(url, max_items, default_language="en", default_source="Yahoo Finance")
    return [i.model_copy(update={"tickers": [ticker]}) for i in items]


def _yahoo_news(ticker: str, max_items: int) -> list[NewsItem]:
    """yfinance y, si no devuelve nada o falla, el RSS de Yahoo. Lanza si fallan ambos."""
    try:
        items = _yfinance_lib_news(ticker, max_items)
        if items:
            return items
        log.info("yfinance no devuelve noticias para %s; se usa el RSS de Yahoo", ticker)
    except Exception as exc:  # noqa: BLE001 - yfinance lanza tipos muy variados (429, JSON, red)
        log.info("yfinance news falló para %s (%s); se usa el RSS de Yahoo", ticker, type(exc).__name__)
    return _yahoo_rss_news(ticker, max_items)


def fetch_yfinance_news(ticker: str, max_items: int = 10) -> list[NewsItem]:
    """Noticias recientes (en inglés) de un ticker vía yfinance, con respaldo en el RSS de Yahoo.

    Nunca lanza por problemas de red: devuelve ``[]`` y deja un aviso en el log.
    """
    ticker = normalize_ticker(ticker)
    try:
        return _yahoo_news(ticker, max_items)
    except Exception as exc:  # noqa: BLE001
        log.warning("Sin noticias de Yahoo para %s: %s", ticker, exc)
        return []


# ── RSS (Google News y prensa) ────────────────────────────────────────────────────


def parse_feed(
    content: bytes | str,
    feed_url: str = "",
    max_items: int = 20,
    default_language: str = "es",
    default_source: str = "",
) -> list[NewsItem]:
    """Parsea un RSS/Atom (bytes o texto) y devuelve ``NewsItem`` limpios (sin tickers).

    - Título sin el sufijo «- Medio» de Google News; ``source`` = medio de la entrada
      (``<source>`` en Google News) o título del feed.
    - Resumen sin HTML y recortado a ``SUMMARY_MAX_CHARS``; si solo repite el título queda vacío.
      En Google News siempre queda vacío (su «resumen» es el enlace o una lista de titulares de
      otros medios); lo rellena después ``enrich_news``.
    - Fecha ``published``/``updated`` en UTC; si no hay, ahora; si está en el futuro, ahora.

    Raises:
        ValueError: si el contenido no es un feed legible: sin entradas y con error de parseo, o
            sin entradas y sin formato RSS/Atom reconocido (p. ej. una página HTML de error,
            de cookies o de *captcha* servida con estado 200). Así no se cachea como «sin noticias».
    """
    import feedparser

    parsed = feedparser.parse(content)
    if not parsed.entries and (parsed.bozo or not parsed.get("version")):
        reason = parsed.get("bozo_exception") or "no es RSS/Atom (¿página HTML de error?)"
        raise ValueError(f"Feed no legible ({feed_url or 'contenido'}): {reason}")
    feed_title = clean_html(parsed.feed.get("title"), max_chars=120)
    lang = _language(parsed.feed.get("language"), default_language)
    items: list[NewsItem] = []
    for entry in parsed.entries:
        title = clean_html(entry.get("title"), max_chars=300)
        url = unwrap_redirect((entry.get("link") or "").strip())
        if not title or not url:
            continue
        source = clean_html(
            _as_dict(entry.get("source")).get("title") or entry.get("news_source"), max_chars=120
        )
        source = re.sub(r"\s+on MSN$", "", source)  # Bing: «Medio on MSN»
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].rstrip()
        source = source or default_source or feed_title or urlsplit(url).netloc
        summary = clean_html(entry.get("summary") or entry.get("description"))
        if article_meta.is_google_news_url(url):
            summary = ""  # Google News: el «resumen» es el enlace o una lista de titulares de otros medios
        elif summary and _title_key(summary).startswith(_title_key(title)) and len(summary) < len(title) + 80:
            summary = ""  # el «resumen» solo repite el título
        published = _not_future(
            _parse_datetime(entry.get("published_parsed"))
            or _parse_datetime(entry.get("updated_parsed"))
            or datetime.now(UTC)
        )
        items.append(
            NewsItem(
                id=news_id(url, title),
                title=title,
                summary=summary,
                source=source,
                url=url,
                published_at=published,
                tickers=[],
                language=_language(entry.get("language"), lang),
            )
        )
        if len(items) >= max_items:
            break
    return items


def unwrap_redirect(url: str) -> str:
    """Enlace real de una redirección de agregador que lo lleva en la query (Bing News ``apiclick``).

    ``http://www.bing.com/news/apiclick.aspx?…&url=https%3a%2f%2fmedio.es%2fnoticia`` ->
    ``https://medio.es/noticia``. Cualquier otro enlace se devuelve igual (Google News no lleva la
    URL en claro: la resuelve ``enrich_news``).
    """
    parts = urlsplit(url)
    if parts.netloc.lower().endswith("bing.com") and parts.path.lower().endswith("/apiclick.aspx"):
        target = dict(parse_qsl(parts.query)).get("url", "")
        if target.startswith(("http://", "https://")):
            return target
    return url


def _fetch_feed(
    url: str, max_items: int = 20, default_language: str = "es", default_source: str = ""
) -> list[NewsItem]:
    """Descarga y parsea un feed (lanza si falla la red o el feed es ilegible)."""
    return parse_feed(_http_get(url), url, max_items, default_language, default_source)


def fetch_rss_news(feeds: list[str], max_items: int = 20) -> list[NewsItem]:
    """Noticias de feeds RSS/Atom (prensa económica en español), ``max_items`` por feed.

    Un feed caído o ilegible se salta con un aviso. ``tickers`` queda vacío (lo rellena
    ``fetch_news`` o ``ingest.tickers.filter_by_tickers``).
    """
    items: list[NewsItem] = []
    for url in feeds:
        try:
            items.extend(_fetch_feed(url, max_items))
        except Exception as exc:  # noqa: BLE001 - red, HTTP o feed roto: no rompe la ingesta
            log.warning("Feed RSS caído o ilegible (%s): %s", urlsplit(url).netloc or url, exc)
    return items


def google_news_query(ticker: str) -> str:
    """Consulta de Google News para un ticker: nombre de la empresa entre comillas + términos de mercado.

    ``"SAN.MC"`` -> ``'"Banco Santander" (acciones OR bolsa OR …)'``. Un ticker fuera del universo
    usa su símbolo sin sufijo.
    """
    info = TICKER_UNIVERSE.get(ticker)
    name = str(info["name"]) if info else ticker.lstrip("^").split(".", 1)[0]
    return f'"{name}" {GOOGLE_MARKET_TERMS}'


def google_news_url(query: str, days: int | None = GOOGLE_NEWS_DAYS) -> str:
    """URL del RSS de búsqueda de Google News en español de España."""
    q = f"{query} when:{days}d" if days else query
    return f"{GOOGLE_NEWS_RSS}?{urlencode({'q': q, 'hl': 'es', 'gl': 'ES', 'ceid': 'ES:es'})}"


def _google_news(ticker: str, max_items: int, days: int = GOOGLE_NEWS_DAYS) -> list[NewsItem]:
    """Google News RSS para un ticker (lanza si falla), etiquetado con el ticker."""
    url = google_news_url(google_news_query(ticker), days)
    items = _fetch_feed(url, max_items=100, default_language="es", default_source="Google News")
    items.sort(key=_sort_key, reverse=True)  # Google ordena por relevancia, no por fecha
    return [i.model_copy(update={"tickers": [ticker]}) for i in items[:max_items]]


def bing_news_url(query: str) -> str:
    """URL del RSS de búsqueda de Bing News en español de España."""
    return f"{BING_NEWS_RSS}?{urlencode({'q': query, 'format': 'rss', 'setlang': 'es', 'cc': 'ES', 'mkt': 'es-ES'})}"


def _bing_news(ticker: str, max_items: int) -> list[NewsItem]:
    """Bing News RSS para un ticker (lanza si falla), etiquetado con el ticker."""
    items = _fetch_feed(bing_news_url(google_news_query(ticker)), 100, "es", "Bing News")
    items.sort(key=_sort_key, reverse=True)  # Bing también ordena por relevancia
    return [i.model_copy(update={"tickers": [ticker]}) for i in items[:max_items]]


def fetch_bing_news(ticker: str, max_items: int = 15) -> list[NewsItem]:
    """Noticias en español de Bing News para un ticker, con extracto y enlace directo al medio.

    Misma consulta que Google News (``google_news_query``). Nunca lanza: ``[]`` y aviso en el log.
    """
    ticker = normalize_ticker(ticker)
    try:
        return _bing_news(ticker, max_items)
    except Exception as exc:  # noqa: BLE001
        log.warning("Bing News falló para %s: %s", ticker, exc)
        return []


def fetch_google_news(ticker: str, max_items: int = 15, days: int = GOOGLE_NEWS_DAYS) -> list[NewsItem]:
    """Noticias en español de Google News para un ticker (por nombre de empresa).

    Nunca lanza por problemas de red: devuelve ``[]`` y deja un aviso en el log.
    """
    ticker = normalize_ticker(ticker)
    try:
        return _google_news(ticker, max_items, days)
    except Exception as exc:  # noqa: BLE001
        log.warning("Google News falló para %s: %s", ticker, exc)
        return []


# ── deduplicado y relevancia ──────────────────────────────────────────────────────


def _url_key(url: str) -> str:
    """URL normalizada (clave de duplicado): sin fragmento, barra final ni parámetros de seguimiento.

    Se conservan los parámetros que identifican el artículo (``?id=123``), ordenados; se quitan
    ``utm_*`` y los de ``_TRACKING_PARAMS``. Host y esquema en minúsculas.
    """
    parts = urlsplit(url.strip())
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), "")
    ).lower()


def _title_key(title: str) -> str:
    """Título en minúsculas, sin tildes ni signos y con espacios simples (clave de duplicado)."""
    folded = unicodedata.normalize("NFKD", title)
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", folded).split())


_STOPWORDS = frozenset(
    "de la el en y a los las del por con para un una al se su sus lo que es o e the of to and in on for "
    "is at as by with from its after".split()
)


def _title_tokens(title: str) -> frozenset[str]:
    """Palabras significativas del titular (sin tildes ni palabras vacías)."""
    return frozenset(w for w in _title_key(title).split() if w not in _STOPWORDS and len(w) > 1)


def titles_similar(a: str, b: str, threshold: float = NEAR_DUP_THRESHOLD) -> bool:
    """True si dos titulares son casi idénticos (misma noticia en dos medios).

    Jaccard de palabras significativas ≥ ``threshold`` (con ≥ 4 palabras en ambos), o el más
    corto contenido casi entero (≥ 90 %) en el otro con ≥ 6 palabras.
    """
    return _tokens_similar(_title_tokens(a), _title_tokens(b), threshold)


def _tokens_similar(ta: frozenset[str], tb: frozenset[str], threshold: float) -> bool:
    small = min(len(ta), len(tb))
    if small < 4:
        return False
    inter = len(ta & tb)
    return inter / len(ta | tb) >= threshold or (small >= 6 and inter / small >= 0.9)


def _sort_key(item: NewsItem) -> datetime:
    """Fecha comparable aunque se mezclen datetimes con y sin zona horaria (naive = UTC)."""
    dt = item.published_at
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def dedupe_news(items: list[NewsItem], near_threshold: float | None = NEAR_DUP_THRESHOLD) -> list[NewsItem]:
    """Elimina duplicados por URL, por título normalizado y por titular casi idéntico.

    Se conserva la primera aparición (posición y ``id``), uniendo los tickers de los duplicados y
    quedándose con el resumen más largo y con el enlace directo del medio si el conservado era de
    Google News (el ``id`` no cambia). ``near_threshold=None`` desactiva la comparación
    aproximada (``titles_similar``). No muta la entrada.
    """
    result: list[NewsItem] = []
    tokens: list[frozenset[str]] = []
    index_by_key: dict[str, int] = {}
    for item in items:
        keys = [k for k in (f"url:{_url_key(item.url)}", f"title:{_title_key(item.title)}") if k.split(":", 1)[1]]
        pos = next((index_by_key[k] for k in keys if k in index_by_key), None)
        item_tokens = _title_tokens(item.title)
        if pos is None and near_threshold is not None and len(item_tokens) >= 4:
            pos = next(
                (
                    n for n, kept_tokens in enumerate(tokens)
                    if _tokens_similar(kept_tokens, item_tokens, near_threshold)
                ),
                None,
            )
        if pos is None:
            pos = len(result)
            result.append(item.model_copy())
            tokens.append(item_tokens)
        else:
            kept = result[pos]
            update: dict[str, object] = {"tickers": list(dict.fromkeys([*kept.tickers, *item.tickers]))}
            if len(item.summary) > len(kept.summary):
                update["summary"] = item.summary
            if article_meta.is_google_news_url(kept.url) and not article_meta.is_google_news_url(item.url):
                update["url"] = item.url  # mejor el enlace directo del medio que la redirección de Google
            result[pos] = kept.model_copy(update=update)
        for k in keys:
            index_by_key.setdefault(k, pos)
    return result


#: Tramos de ruta de fichas de cotización (no son noticias): Investing, Bolsamanía, Yahoo…
_LANDING_SEGMENTS = frozenset({"equities", "indices", "accion", "quote"})


def is_landing_page(item: NewsItem) -> bool:
    """True si parece una ficha de cotización o portada de sección, no una noticia.

    Criterios: titular con < 3 palabras significativas («Inditex (ITX)», «Cotización Iberdrola»),
    ruta de ficha (un tramo de ``_LANDING_SEGMENTS``, p. ej. ``/equities/inditex-ratios``) o ruta
    corta sin *slug* de artículo (≤ 3 tramos y el último sin extensión, sin cifras y con < 2
    guiones, p. ej. ``/empresas/banco-santander/``). Los enlaces de Google
    News solo se juzgan por el titular.
    """
    if len(_title_tokens(item.title)) < 3:
        return True
    if article_meta.is_google_news_url(item.url):
        return False
    segments = [seg for seg in urlsplit(item.url).path.lower().split("/") if seg]
    if not segments or _LANDING_SEGMENTS & set(segments):
        return True
    last = segments[-1]
    if "." in last:  # «noticia.html», «.htm», «.shtml»: es un documento, no una portada de sección
        return False
    return len(segments) <= 3 and not any(c.isdigit() for c in last) and last.count("-") < 2


def relevance_score(item: NewsItem, ticker: str, now: datetime | None = None) -> float:
    """Relevancia de una noticia para un ticker (mayor = más relevante). Heurística simple:

    - Mención del ticker (símbolo, nombre o alias) en el **titular**: +3; solo en el resumen: +1;
      ninguna (llegó por la búsqueda de la fuente): +0.
    - **Frescura**: hasta +2, decae con la edad (``2·e^(-horas/24)``).
    - **Español**: +1 (el podcast es en español). **Con extracto**: +0,5 (más útil para el Analista).
    - Lista de ≥ 3 valores más (mención de pasada, «Análisis de BBVA, CaixaBank, …»): -1.

    ``relevance_explained`` devuelve además los motivos en texto (para la traza «Cómo se hizo»).
    """
    return relevance_explained(item, ticker, now)[0]


def relevance_explained(item: NewsItem, ticker: str, now: datetime | None = None) -> tuple[float, list[str]]:
    """``(relevance_score, motivos)``: los motivos son etiquetas breves en español de cada término.

    Ej.: ``(5.4, ["titular", "3 h", "es", "extracto"])`` o ``(1.2, ["sin mención", "30 h", "en",
    "lista de valores"])``.
    """
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    if ticker in extract_tickers(item.title, [ticker]):
        score, reasons = 3.0, ["titular"]
    elif item.summary and ticker in extract_tickers(item.summary, [ticker]):
        score, reasons = 1.0, ["resumen"]
    else:
        score, reasons = 0.0, ["sin mención"]
    age_h = max(0.0, (now - _sort_key(item)).total_seconds() / 3600)
    score += 2.0 * math.exp(-age_h / 24)
    reasons.append(f"{age_h:.0f} h")
    if item.language == "es":
        score += 1.0
    reasons.append(item.language or "?")
    if item.summary.strip():
        score += 0.5
        reasons.append("extracto")
    others = [t for t in item.tickers if t != ticker and not t.startswith("^")]
    if len(others) >= 3:
        score -= 1.0
        reasons.append("lista de valores")
    return round(score, 3), reasons


# ── combinación ───────────────────────────────────────────────────────────────────


def _cached_source(
    source: str, key: str, fetch: Any, use_cache: bool
) -> tuple[list[NewsItem], bool]:
    """Ejecuta ``fetch()`` con caché diaria. Devuelve ``(items, venía_de_caché)``.

    Se cachea todo resultado que no lance (también una lista vacía: la fuente respondió y no hay
    noticias); los errores no se cachean, así que la siguiente ejecución reintenta.
    """
    ck = cache.cache_key(source, key)
    if use_cache:
        cached = cache.read_cache(f"news-{source}", ck)
        if isinstance(cached, list):
            try:
                return [NewsItem.model_validate(x) for x in cached], True
            except Exception as exc:  # noqa: BLE001 - caché de otra versión del schema
                log.warning("Caché de noticias incompatible (%s/%s): %s", source, key, exc)
    items = fetch()
    cache.write_cache(f"news-{source}", ck, [i.model_dump(mode="json") for i in items])
    return items, False


def _select(
    items: list[NewsItem], wanted: list[str], max_items: int, per_ticker: int,
    scores: dict[str, float] | None = None,
    explain: dict[str, dict[str, Any]] | None = None,
) -> list[NewsItem]:
    """Reparte el cupo: ronda por ticker (por ``relevance_score``; empate, más reciente) y rellena con generales.

    Si se pasa ``scores``, se anota ahí la relevancia de cada noticia elegida para su ticker. Si se
    pasa ``explain``, ``id -> {"ticker", "score", "reasons"}`` de cada elegida (las de contexto
    general llevan ``ticker=None`` y el motivo ``"contexto general"``).
    """
    now = datetime.now(UTC)
    by_recency = sorted(items, key=_sort_key, reverse=True)
    queues: dict[str, list[tuple[float, NewsItem]]] = {}
    reasons: dict[tuple[str, str], list[str]] = {}
    for t in wanted:
        scored: list[tuple[float, NewsItem]] = []
        for i in by_recency:
            if t in i.tickers:
                score, why = relevance_explained(i, t, now)
                scored.append((score, i))
                reasons[(t, i.id)] = why
        queues[t] = sorted(scored, key=lambda pair: pair[0], reverse=True)  # estable: empate -> más reciente
    chosen: dict[str, NewsItem] = {}
    counts = dict.fromkeys(wanted, 0)
    progress = True
    while progress and len(chosen) < max_items:
        progress = False
        for t in wanted:
            if len(chosen) >= max_items or counts[t] >= per_ticker:
                continue
            queue = queues[t]
            while queue and queue[0][1].id in chosen:
                queue.pop(0)
            if not queue:
                continue
            score, item = queue.pop(0)
            chosen[item.id] = item
            if scores is not None:
                scores[item.id] = score
            if explain is not None:
                explain[item.id] = {"ticker": t, "score": score, "reasons": reasons[(t, item.id)]}
            for tk in item.tickers:
                if tk in counts:
                    counts[tk] += 1
            progress = True
    if len(chosen) < max_items:  # contexto general de mercado (índices primero)
        rest = [i for i in by_recency if i.id not in chosen and not set(i.tickers) & set(wanted)]
        rest.sort(key=lambda i: not any(t.startswith("^") for t in i.tickers))
        for item in rest[: max_items - len(chosen)]:
            chosen[item.id] = item
            if explain is not None:
                explain[item.id] = {"ticker": None, "score": None, "reasons": ["contexto general"]}
    return sorted(chosen.values(), key=_sort_key, reverse=True)


def _useful_description(description: str, title: str) -> bool:
    """Descarta descripciones vacías, muy cortas o que solo repiten el titular."""
    if len(description) < article_meta.MIN_DESCRIPTION_CHARS:
        return False
    d, t = _title_key(description), _title_key(title)
    return not (d == t or (d.startswith(t) and len(d) < len(t) + 20))


def _empty_enrich_stats() -> dict[str, Any]:
    return {"candidates": 0, "done": 0, "resolved": 0, "summaries": 0, "timed_out": 0, "prefetched": 0,
            "latency_s": 0.0}


_meta_slots: dict[int, threading.BoundedSemaphore] = {}
_meta_slots_lock = threading.Lock()


def _start_meta_fetch(url: str, use_cache: bool, max_workers: int) -> Future:
    """Lanza ``article_meta.fetch_article_meta`` en un hilo *daemon* y devuelve su ``Future``.

    Hilos *daemon* (no un ``ThreadPoolExecutor``): las peticiones que no llegan al presupuesto
    siguen y dejan su resultado en la caché, pero no retienen la salida de un proceso de CLI
    (``concurrent.futures`` espera a sus hilos al terminar el intérprete). ``max_workers``
    peticiones a la vez como mucho (semáforo compartido).
    """
    with _meta_slots_lock:
        slots = _meta_slots.setdefault(max(1, max_workers), threading.BoundedSemaphore(max(1, max_workers)))
    fut: Future = Future()

    def work() -> None:
        with slots:
            if not fut.set_running_or_notify_cancel():
                return
            try:
                fut.set_result(article_meta.fetch_article_meta(url, use_cache=use_cache))
            except BaseException as exc:  # noqa: BLE001 - se entrega al que espera
                fut.set_exception(exc)

    threading.Thread(target=work, name="news-meta", daemon=True).start()
    return fut


def enrich_news(
    items: list[NewsItem],
    *,
    use_cache: bool = True,
    budget_s: float = ENRICH_BUDGET_S,
    max_workers: int = ENRICH_WORKERS,
    stats_out: dict[str, Any] | None = None,
    prefetched: dict[str, Future] | None = None,
) -> list[NewsItem]:
    """Completa las noticias con la URL final del medio y un extracto breve (``og:description``).

    Solo trabaja con las que lo necesitan (enlace de Google News o resumen vacío), en paralelo
    (``max_workers``) y con un presupuesto total de ``budget_s`` segundos: lo que no llegue a
    tiempo se queda como estaba (las peticiones ya en curso terminan y dejan su resultado en la
    caché para la siguiente ejecución). Nunca lanza ni retrasa la ingesta más de ``budget_s``.

    - ``summary``: solo se rellena si estaba vacío, con la descripción limpia y recortada a
      ``SUMMARY_MAX_CHARS``; se descartan las genéricas (la misma en ≥ 2 artículos del mismo
      medio) y las que solo repiten el titular.
    - ``url``: la del medio si se pudo resolver; si no, la original. ``id`` no cambia (se calculó
      con la URL de origen).

    ``prefetched`` (``url -> Future``): peticiones lanzadas antes por ``fetch_news`` mientras
    esperaba a las fuentes lentas (``prefetch_meta``); se reutilizan en lugar de repetirlas, así
    que el presupuesto rinde más. Deja el resumen en ``stats_out`` si se pasa (propio de esta
    llamada: sin carreras entre briefings simultáneos). Conserva el orden de ``items``.
    """
    start = time.perf_counter()
    todo = [i for i in items if article_meta.is_google_news_url(i.url) or not i.summary.strip()]
    stats = {**_empty_enrich_stats(), "candidates": len(todo)}
    if not todo or budget_s <= 0:
        if stats_out is not None:
            stats_out.update(stats)
        return list(items)

    metas: dict[str, dict[str, Any]] = {}
    prefetched = prefetched or {}
    jobs: list[tuple[Future, str]] = []
    for i in todo:
        fut = prefetched.get(i.url)
        if fut is not None:
            stats["prefetched"] += 1
        else:
            fut = _start_meta_fetch(i.url, use_cache, max_workers)
        jobs.append((fut, i.id))
    done, pending = wait({f for f, _ in jobs}, timeout=budget_s)
    stats["timed_out"] = sum(1 for f, _ in jobs if f in pending)
    for fut, item_id in jobs:
        if fut not in done:
            continue
        try:
            metas[item_id] = fut.result()
        except Exception as exc:  # noqa: BLE001 - fetch_article_meta no debería lanzar
            log.debug("Metadatos: fallo inesperado: %s", exc)
    stats["done"] = len(metas)

    def _host(u: str) -> str:
        return urlsplit(u).netloc.lower()

    cleaned = {k: clean_html(m.get("description") or "") for k, m in metas.items()}
    repeated = Counter((_host(str(metas[k].get("url") or "")), _title_key(d)) for k, d in cleaned.items() if d)

    out: list[NewsItem] = []
    for item in items:
        meta = metas.get(item.id)
        if not meta:
            out.append(item)
            continue
        update: dict[str, Any] = {}
        new_url = str(meta.get("url") or "")
        if new_url and new_url != item.url and not article_meta.is_google_news_url(new_url):
            update["url"] = new_url
            if article_meta.is_google_news_url(item.url):
                stats["resolved"] += 1
        desc = cleaned[item.id]
        generic = repeated[(_host(new_url or item.url), _title_key(desc))] > 1
        if desc and not item.summary.strip() and not generic and _useful_description(desc, item.title):
            update["summary"] = desc
            stats["summaries"] += 1
        out.append(item.model_copy(update=update) if update else item)
    stats["latency_s"] = round(time.perf_counter() - start, 3)
    if stats_out is not None:
        stats_out.update(stats)
    log.info(
        "Enriquecimiento de noticias: %d candidatas, %d URL resueltas, %d extractos, %d sin tiempo (%.1f s)",
        stats["candidates"], stats["resolved"], stats["summaries"], stats["timed_out"], stats["latency_s"],
    )
    return out


def _valid_tickers(tickers: list[str]) -> list[str]:
    """Normaliza y quita repetidos; descarta entradas vacías o inválidas (``"$"``) con aviso."""
    out: list[str] = []
    for raw in tickers:
        if not str(raw).strip():
            continue
        try:
            out.append(normalize_ticker(raw))
        except (ValueError, TypeError):
            log.warning("Ticker inválido ignorado: %r", raw)
    return list(dict.fromkeys(out))


def fetch_news(
    tickers: list[str],
    max_items: int = 20,
    since: datetime | None = None,
    rss_feeds: list[str] | None = None,
    *,
    max_per_ticker: int | None = None,
    use_cache: bool = True,
    enrich: bool = True,
    stats_out: dict[str, Any] | None = None,
) -> list[NewsItem]:
    """Punto de entrada: Google News + Bing News + yfinance/Yahoo por ticker + feeds de mercado.

    Pasos: descarga en paralelo (timeouts cortos, caché diaria por fuente y ticker) -> etiqueta
    tickers con ``extract_tickers`` -> descarta fichas de cotización (``is_landing_page``) ->
    ``dedupe_news`` (URL, título y titulares casi idénticos) ->
    ventana temporal -> cupo por ticker y total priorizando por ``relevance_score`` ->
    ``enrich_news`` (URL final y extracto breve, con presupuesto ``ENRICH_BUDGET_S``).

    Args:
        tickers: tickers de interés (se normalizan con ``normalize_ticker``; los inválidos se ignoran).
        max_items: máximo de noticias devueltas.
        since: descartar noticias anteriores. Por defecto se prueban las ventanas de
            ``WINDOWS_HOURS`` (48 h, 72 h, 7 días) hasta que cada ticker tenga ``MIN_PER_TICKER``.
        rss_feeds: feeds generalistas; si es ``None`` o vacío, ``settings.rss_feeds`` o, en su
            defecto, ``DEFAULT_MARKET_FEEDS``.
        max_per_ticker: cupo por ticker (por defecto ``max(MIN_PER_TICKER, ceil(max_items / n))``).
        use_cache: ``False`` ignora la caché del día (vuelve a llamar a red y la refresca).
        enrich: ``False`` no busca URL final ni ``og:description`` (más rápido, sin extractos).
        stats_out: si se pasa, recibe las estadísticas **de esta llamada** (sin globales: dos
            briefings simultáneos no se mezclan): ``{"fetch": {fuente: {items, latency_s, cached,
            error}}, "quality": {collected, landing_pages, exact_duplicates, near_duplicates,
            out_of_window, window_h, over_quota, sources_latency_s, selected, with_summary,
            google_urls, enrich: {...}, selection: [{id, title, ticker, score, reasons,
            has_summary}]}}``. ``format_news_stats`` lo resume para ``StepMetric.detail``.

    Returns:
        Noticias más recientes primero. Puede ser ``[]`` si las fuentes responden sin noticias.

    Raises:
        NewsFetchError: si fallan todas las fuentes (sin red, bloqueos…).
    """
    wanted = _valid_tickers(tickers)
    feeds = list(rss_feeds or get_settings().rss_feeds or DEFAULT_MARKET_FEEDS)
    per_source = max(10, max_items)

    # Orden de envío = prioridad: las fuentes rápidas primero y yfinance (lenta: 3-5 s por ticker
    # cuando su API no responde) al final, para que no acapare los hilos.
    tasks: dict[str, tuple[str, str, Any]] = {}
    for t in wanted:
        tasks[f"google:{t}"] = ("google", t, lambda t=t: _google_news(t, per_source))
        tasks[f"bing:{t}"] = ("bing", t, lambda t=t: _bing_news(t, per_source))
        tasks[f"yahoo_rss:{t}"] = ("yahoo_rss", t, lambda t=t: _yahoo_rss_news(t, per_source))
    for url in feeds:
        tasks[f"rss:{urlsplit(url).netloc or url}"] = ("rss", url, lambda u=url: _fetch_feed(u, per_source))
    for t in wanted:
        tasks[f"yfinance:{t}"] = ("yfinance", t, lambda t=t: _yfinance_lib_news(t, per_source))

    def run(label: str) -> tuple[list[NewsItem], bool, float]:
        source, key, fetch = tasks[label]
        start = time.perf_counter()
        items, cached = _cached_source(source, key, fetch, use_cache)
        return items, cached, time.perf_counter() - start

    stats: dict[str, dict[str, Any]] = {}
    collected: list[NewsItem] = []
    failures = 0
    prefetched: dict[str, Future] = {}
    fetch_start = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, max(1, len(tasks))), thread_name_prefix="news")
    try:
        futures = {pool.submit(run, label): label for label in tasks}
        pending: set[Future] = set(futures)
        deadline = fetch_start + TOTAL_TIMEOUT
        while pending:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            _done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if enrich and not prefetched and pending and all(futures[f].startswith("yfinance:") for f in pending):
                # Solo quedan las fuentes lentas (yfinance: 3-6 s por ticker cuando su API no
                # responde): se adelanta el enriquecimiento de la selección provisional con lo ya
                # descargado. No retrasa nada (se esperaba igual) y ``enrich_news`` lo reutiliza.
                early = [i for f in futures if f.done() and not f.exception() for i in f.result()[0]]
                provisional, _q = _choose(early, wanted, since, max_items, max_per_ticker, quiet=True)
                prefetched = prefetch_meta(provisional, use_cache=use_cache)
        for fut in futures:
            label = futures[fut]
            if fut in pending:
                failures += 1
                stats[label] = {"items": 0, "latency_s": TOTAL_TIMEOUT, "cached": False, "error": "timeout"}
                log.warning("Fuente de noticias %s: sin respuesta en %.0f s", label, TOTAL_TIMEOUT)
                continue
            try:
                items, cached, latency = fut.result()
            except Exception as exc:  # noqa: BLE001 - una fuente caída no rompe el resto
                failures += 1
                stats[label] = {"items": 0, "latency_s": None, "cached": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
                log.warning("Fuente de noticias %s falló: %s", label, exc)
                continue
            stats[label] = {"items": len(items), "latency_s": round(latency, 3), "cached": cached, "error": None}
            collected.extend(items)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    sources_latency = time.perf_counter() - fetch_start
    if stats_out is not None:
        stats_out["fetch"] = dict(stats)

    # yfinance es auxiliar: sin red puede devolver [] sin lanzar, así que no cuenta como «viva».
    essential = [k for k in tasks if not k.startswith("yfinance:")]
    if essential and all(stats[k]["error"] for k in essential):
        raise NewsFetchError(
            f"No se pudo obtener ninguna noticia: fallaron las {len(tasks)} fuentes "
            "(¿sin conexión o bloqueo temporal?). Usa el modo de ejemplo o reinténtalo."
        )

    selected, quality = _choose(collected, wanted, since, max_items, max_per_ticker)
    quality["sources_latency_s"] = round(sources_latency, 3)
    enrich_stats: dict[str, Any] = _empty_enrich_stats()
    if enrich and selected:
        # 2 enlaces -> mismo artículo
        selected = dedupe_news(
            enrich_news(selected, use_cache=use_cache, budget_s=ENRICH_BUDGET_S, stats_out=enrich_stats,
                        prefetched=prefetched)
        )
    quality["enrich"] = enrich_stats
    selected.sort(key=_sort_key, reverse=True)
    explain: dict[str, dict[str, Any]] = quality.pop("explain")
    quality.update(
        selected=len(selected),
        with_summary=sum(1 for i in selected if i.summary.strip()),
        google_urls=sum(1 for i in selected if article_meta.is_google_news_url(i.url)),
        selection=[
            {
                "id": i.id,
                "title": i.title,
                "ticker": explain.get(i.id, {}).get("ticker"),
                "score": explain.get(i.id, {}).get("score"),
                "reasons": list(explain.get(i.id, {}).get("reasons", [])),
                "has_summary": bool(i.summary.strip()),
            }
            for i in selected
        ],
    )
    if stats_out is not None:
        stats_out["quality"] = quality
    log.info(
        "Noticias: %d obtenidas, %d casi duplicadas, %d fuera de ventana, %d seleccionadas "
        "(%d con extracto; %d fuentes, %d fallidas)",
        quality["collected"], quality["near_duplicates"], quality["out_of_window"], len(selected),
        quality["with_summary"], len(tasks), failures,
    )
    return selected


def _choose(
    collected: list[NewsItem],
    wanted: list[str],
    since: datetime | None,
    max_items: int,
    max_per_ticker: int | None,
    *,
    quiet: bool = False,
) -> tuple[list[NewsItem], dict[str, Any]]:
    """Etiquetado -> fichas de cotización fuera -> duplicados -> ventana temporal -> cupo por relevancia.

    Devuelve ``(seleccionadas, calidad)``; ``calidad`` cuenta lo descartado en cada etapa
    (``landing_pages``, ``exact_duplicates``, ``near_duplicates``, ``out_of_window`` con
    ``window_h``, ``over_quota``) y ``explain`` (``id -> ticker, score, reasons``). ``quiet``
    silencia el log (selección provisional del pre-enriquecimiento).
    """
    universe = list(dict.fromkeys([*wanted, *TICKER_UNIVERSE]))
    tagged = [
        item.model_copy(
            update={"tickers": list(dict.fromkeys([*item.tickers, *extract_tickers(f"{item.title} {item.summary}", universe)]))}
        )
        for item in collected
    ]
    articles = [i for i in tagged if not is_landing_page(i)]
    exact = dedupe_news(sorted(articles, key=_sort_key, reverse=True), near_threshold=None)
    unique = dedupe_news(exact)

    now = datetime.now(UTC)
    window_h: int | None = None
    if since is not None:
        since = since if since.tzinfo else since.replace(tzinfo=UTC)
        in_window = [i for i in unique if _sort_key(i) >= since]
    else:
        in_window = []
        for hours in WINDOWS_HOURS:
            window_h = hours
            in_window = [i for i in unique if _sort_key(i) >= now - timedelta(hours=hours)]
            counts = {t: sum(t in i.tickers for i in in_window) for t in wanted}
            if all(c >= MIN_PER_TICKER for c in counts.values()) and len(in_window) >= min(max_items, 3):
                break
            if not quiet:
                log.info("Pocas noticias en %d h (%s); se amplía la ventana", hours, counts)

    per_ticker = max_per_ticker or (max(MIN_PER_TICKER, math.ceil(max_items / len(wanted))) if wanted else max_items)
    explain: dict[str, dict[str, Any]] = {}
    selected = _select(in_window, wanted, max_items, per_ticker, explain=explain)
    quality: dict[str, Any] = {
        "collected": len(collected),
        "landing_pages": len(tagged) - len(articles),
        "exact_duplicates": len(articles) - len(exact),
        "near_duplicates": len(exact) - len(unique),
        "out_of_window": len(unique) - len(in_window),
        "window_h": window_h,
        "over_quota": len(in_window) - len(selected),
        "explain": explain,
    }
    return selected, quality


def prefetch_meta(items: list[NewsItem], *, use_cache: bool = True) -> dict[str, Future]:
    """Lanza ya (hilos *daemon*) la búsqueda de metadatos de las noticias que la necesitarán.

    Mismo criterio que ``enrich_news`` (enlace de Google News o sin resumen). Devuelve
    ``url -> Future`` para pasarlo a ``enrich_news(prefetched=...)``. Nunca lanza.
    """
    out: dict[str, Future] = {}
    for item in items:
        if item.url not in out and (article_meta.is_google_news_url(item.url) or not item.summary.strip()):
            out[item.url] = _start_meta_fetch(item.url, use_cache, ENRICH_WORKERS)
    if out:
        log.debug("Pre-enriquecimiento: %d noticias mientras terminan las fuentes lentas", len(out))
    return out


#: Nombre legible de cada tipo de fuente en ``format_news_stats``.
_SOURCE_LABELS = {
    "google": "Google News", "bing": "Bing News", "yahoo_rss": "Yahoo RSS", "rss": "prensa", "yfinance": "yfinance",
}
#: Longitud máxima del titular de cada noticia en la explicación de relevancia.
_EXPLAIN_TITLE_CHARS = 48


def _short_title(title: str, max_chars: int = _EXPLAIN_TITLE_CHARS) -> str:
    return title if len(title) <= max_chars else title[: max_chars - 1].rstrip() + "…"


def format_news_stats(stats: dict[str, Any]) -> str | None:
    """Resumen legible de ``fetch_news(stats_out=...)`` para ``StepMetric.detail`` («Cómo se hizo»).

    Ej.: ``"22 fuentes (0 fallidas, 3 de caché) en 6.4 s: Google News 100, Bing News 57, … ·
    20 seleccionadas (17 con extracto) · extracto en el 85 % · descartadas: 8 fichas de cotización,
    4 casi duplicadas, 12 fuera de ventana (48 h), 90 por cupo de relevancia · extractos: 6 URL
    resueltas, 4 nuevos (0 sin tiempo) · relevancia: SAN.MC 5.4 «Santander rebota…» (titular, 3 h,
    es, extracto); …"``. Lo primero es el resumen (el grafo lo recorta); la explicación de cada
    elegida va al final. ``None`` si no hay estadísticas.
    """
    fetch = stats.get("fetch") or {}
    quality = stats.get("quality") or {}
    if not fetch and not quality:
        return None
    parts: list[str] = []
    if fetch:
        failed = sum(1 for v in fetch.values() if v.get("error"))
        cached = sum(1 for v in fetch.values() if v.get("cached"))
        by_kind: Counter[str] = Counter()
        for label, v in fetch.items():
            by_kind[label.split(":", 1)[0]] += int(v.get("items") or 0)
        lat = quality.get("sources_latency_s")
        parts.append(
            f"{len(fetch)} fuentes ({failed} fallidas, {cached} de caché)"
            + (f" en {float(lat):.1f} s" if lat is not None else "")
            + (": " + ", ".join(f"{_SOURCE_LABELS.get(k, k)} {n}" for k, n in by_kind.items()) if by_kind else "")
        )
    if quality:
        selected, with_summary = int(quality.get("selected", 0)), int(quality.get("with_summary", 0))
        parts.append(f"{selected} seleccionadas ({with_summary} con extracto)")
        if selected:
            parts.append(f"extracto en el {round(100 * with_summary / selected)} %")
        dropped = [
            (quality.get("landing_pages"), "fichas de cotización"),
            ((quality.get("exact_duplicates") or 0) or None, "duplicadas"),
            (quality.get("near_duplicates"), "casi duplicadas"),
            (quality.get("out_of_window"),
             f"fuera de ventana ({quality['window_h']} h)" if quality.get("window_h") else "fuera de ventana"),
            (quality.get("over_quota"), "por cupo de relevancia"),
        ]
        dropped_text = ", ".join(f"{n} {label}" for n, label in dropped if n)
        if dropped_text:
            parts.append(f"descartadas: {dropped_text}")
        enrich = quality.get("enrich") or {}
        if enrich.get("candidates"):
            parts.append(
                f"extractos: {enrich.get('resolved', 0)} URL resueltas, {enrich.get('summaries', 0)} nuevos "
                f"({enrich.get('timed_out', 0)} sin tiempo"
                + (f", {enrich['prefetched']} adelantados" if enrich.get("prefetched") else "")
                + ")"
            )
        explained = []
        for sel in quality.get("selection") or []:
            who = sel.get("ticker") or "general"
            score = sel.get("score")
            reasons = list(sel.get("reasons") or [])
            if sel.get("has_summary") and "extracto" not in reasons:
                reasons.append("extracto añadido")
            explained.append(
                f"{who}{f' {float(score):.1f}' if score is not None else ''} "
                f"«{_short_title(str(sel.get('title', '')))}» ({', '.join(reasons)})"
            )
        if explained:
            parts.append("relevancia: " + "; ".join(explained))
    return " · ".join(parts)


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
