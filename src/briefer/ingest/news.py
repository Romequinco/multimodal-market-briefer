"""Ingesta de noticias de mercado: yfinance/Yahoo, Google News RSS y prensa económica, u offline.

Carril A. Salida: ``list[NewsItem]`` deduplicada y ordenada por fecha (más reciente primero).
El filtrado final por tickers lo hace ``ingest.tickers.filter_by_tickers``.

Fuentes (todas sin clave):

- **yfinance** (``yf.Ticker(t).get_news``), en inglés. Su API de noticias cambia de formato entre
  versiones (planos ``title``/``providerPublishTime`` o anidados ``content.title``/``content.pubDate``)
  y a veces deja de responder (si no da nada, se desactiva hasta el día siguiente). Se complementa
  siempre con el **RSS de titulares de Yahoo Finance** del ticker.
- **Google News RSS en español** por nombre de empresa (``TICKER_UNIVERSE``) más términos de
  mercado, para que los valores ``.MC`` tengan cobertura en español.
- **Feeds generalistas de mercados** en español (``DEFAULT_MARKET_FEEDS`` o ``BRIEFER_NEWS_RSS_FEEDS``).

``fetch_news`` combina las fuentes en paralelo, tolera que fallen algunas, filtra por ventana
temporal (48 h ampliable a 72 h / 7 días si hay pocas) y reparte el cupo por ticker. Cada respuesta
de red se cachea por día en ``settings.cache_path`` (ver ``ingest.cache``).
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
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from briefer.config import get_settings
from briefer.ingest import cache
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
#: Longitud máxima del resumen limpio.
SUMMARY_MAX_CHARS = 600

#: Estadísticas de la última llamada a ``fetch_news`` (por fuente): ``items``, ``latency_s``,
#: ``cached`` y ``error``. Solo informativo (trazas, UI, informe de latencias).
last_fetch_stats: dict[str, dict[str, Any]] = {}


class NewsFetchError(RuntimeError):
    """Todas las fuentes de noticias han fallado (sin red, bloqueo, etc.)."""


# ── utilidades ────────────────────────────────────────────────────────────────────


def _http_get(url: str, timeout: float = HTTP_TIMEOUT) -> bytes:
    """GET con User-Agent de navegador y timeout corto. Lanza si el estado no es 2xx."""
    import requests

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.content


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
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, time.struct_time):
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e12 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        text = str(value).strip()
        if text.isdigit():
            return _parse_datetime(int(text))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError, TypeError):
        return None


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
    published = (
        _parse_datetime(content.get("pubDate"))
        or _parse_datetime(content.get("displayTime"))
        or _parse_datetime(raw.get("providerPublishTime"))
        or datetime.now(timezone.utc)
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
    if _yf_news["off"]:
        return True
    if cache.read_cache("news-yfinance", "disabled"):
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
    items = [parse_yfinance_item(r, ticker) for r in (raw or [])]
    items = [i for i in items if i is not None][:max_items]
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
    - Resumen sin HTML; si solo repite el título (caso Google News) queda vacío.
    - Fecha ``published``/``updated`` en UTC; si no hay, ahora.

    Raises:
        ValueError: si el contenido no es un feed legible (sin entradas y con error de parseo).
    """
    import feedparser

    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Feed no legible ({feed_url or 'contenido'}): {parsed.get('bozo_exception')}")
    feed_title = clean_html(parsed.feed.get("title"), max_chars=120)
    lang = _language(parsed.feed.get("language"), default_language)
    items: list[NewsItem] = []
    for entry in parsed.entries:
        title = clean_html(entry.get("title"), max_chars=300)
        url = (entry.get("link") or "").strip()
        if not title or not url:
            continue
        source = clean_html(_as_dict(entry.get("source")).get("title"), max_chars=120)
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].rstrip()
        source = source or default_source or feed_title or urlsplit(url).netloc
        summary = clean_html(entry.get("summary") or entry.get("description"))
        if summary and _title_key(summary).startswith(_title_key(title)) and len(summary) < len(title) + 80:
            summary = ""  # Google News: el «resumen» es el enlace con el título y el medio
        published = (
            _parse_datetime(entry.get("published_parsed"))
            or _parse_datetime(entry.get("updated_parsed"))
            or datetime.now(timezone.utc)
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


# ── deduplicado (ya implementado en F0) ───────────────────────────────────────────


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
    items: list[NewsItem], wanted: list[str], max_items: int, per_ticker: int
) -> list[NewsItem]:
    """Reparte el cupo: ronda por ticker (español primero, luego más reciente) y rellena con generales."""
    by_recency = sorted(items, key=_sort_key, reverse=True)
    queues = {
        t: sorted((i for i in by_recency if t in i.tickers), key=lambda i: i.language != "es")
        for t in wanted
    }
    chosen: dict[str, NewsItem] = {}
    counts = dict.fromkeys(wanted, 0)
    progress = True
    while progress and len(chosen) < max_items:
        progress = False
        for t in wanted:
            if len(chosen) >= max_items or counts[t] >= per_ticker:
                continue
            queue = queues[t]
            while queue and queue[0].id in chosen:
                queue.pop(0)
            if not queue:
                continue
            item = queue.pop(0)
            chosen[item.id] = item
            for tk in item.tickers:
                if tk in counts:
                    counts[tk] += 1
            progress = True
    if len(chosen) < max_items:  # contexto general de mercado (índices primero)
        rest = [i for i in by_recency if i.id not in chosen and not set(i.tickers) & set(wanted)]
        rest.sort(key=lambda i: not any(t.startswith("^") for t in i.tickers))
        for item in rest[: max_items - len(chosen)]:
            chosen[item.id] = item
    return sorted(chosen.values(), key=_sort_key, reverse=True)


def fetch_news(
    tickers: list[str],
    max_items: int = 20,
    since: datetime | None = None,
    rss_feeds: list[str] | None = None,
    *,
    max_per_ticker: int | None = None,
    use_cache: bool = True,
) -> list[NewsItem]:
    """Punto de entrada: yfinance/Yahoo + Google News por ticker + feeds de mercado.

    Pasos: descarga en paralelo (timeouts cortos, caché diaria por fuente y ticker) -> etiqueta
    tickers con ``extract_tickers`` -> ``dedupe_news`` -> ventana temporal -> cupo por ticker y total.

    Args:
        tickers: tickers de interés (se normalizan con ``normalize_ticker``).
        max_items: máximo de noticias devueltas.
        since: descartar noticias anteriores. Por defecto se prueban las ventanas de
            ``WINDOWS_HOURS`` (48 h, 72 h, 7 días) hasta que cada ticker tenga ``MIN_PER_TICKER``.
        rss_feeds: feeds generalistas; si es ``None`` o vacío, ``settings.rss_feeds`` o, en su
            defecto, ``DEFAULT_MARKET_FEEDS``.
        max_per_ticker: cupo por ticker (por defecto ``max(MIN_PER_TICKER, ceil(max_items / n))``).
        use_cache: ``False`` ignora la caché del día (vuelve a llamar a red y la refresca).

    Returns:
        Noticias más recientes primero. Puede ser ``[]`` si las fuentes responden sin noticias.

    Raises:
        NewsFetchError: si fallan todas las fuentes (sin red, bloqueos…).
    """
    wanted = list(dict.fromkeys(normalize_ticker(t) for t in tickers if str(t).strip()))
    feeds = list(rss_feeds or get_settings().rss_feeds or DEFAULT_MARKET_FEEDS)
    per_source = max(10, max_items)

    tasks: dict[str, tuple[str, str, Any]] = {}
    for t in wanted:
        tasks[f"yfinance:{t}"] = ("yfinance", t, lambda t=t: _yfinance_lib_news(t, per_source))
        tasks[f"yahoo_rss:{t}"] = ("yahoo_rss", t, lambda t=t: _yahoo_rss_news(t, per_source))
        tasks[f"google:{t}"] = ("google", t, lambda t=t: _google_news(t, per_source))
    for url in feeds:
        tasks[f"rss:{urlsplit(url).netloc or url}"] = ("rss", url, lambda u=url: _fetch_feed(u, per_source))

    def run(label: str) -> tuple[list[NewsItem], bool, float]:
        source, key, fetch = tasks[label]
        start = time.perf_counter()
        items, cached = _cached_source(source, key, fetch, use_cache)
        return items, cached, time.perf_counter() - start

    last_fetch_stats.clear()
    collected: list[NewsItem] = []
    failures = 0
    pool = ThreadPoolExecutor(max_workers=min(8, max(1, len(tasks))), thread_name_prefix="news")
    try:
        futures = {pool.submit(run, label): label for label in tasks}
        done, pending = wait(futures, timeout=TOTAL_TIMEOUT)
        for fut in futures:
            label = futures[fut]
            if fut in pending:
                failures += 1
                last_fetch_stats[label] = {"items": 0, "latency_s": TOTAL_TIMEOUT, "cached": False, "error": "timeout"}
                log.warning("Fuente de noticias %s: sin respuesta en %.0f s", label, TOTAL_TIMEOUT)
                continue
            try:
                items, cached, latency = fut.result()
            except Exception as exc:  # noqa: BLE001 - una fuente caída no rompe el resto
                failures += 1
                last_fetch_stats[label] = {"items": 0, "latency_s": None, "cached": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
                log.warning("Fuente de noticias %s falló: %s", label, exc)
                continue
            last_fetch_stats[label] = {"items": len(items), "latency_s": round(latency, 3), "cached": cached, "error": None}
            collected.extend(items)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # yfinance es auxiliar: sin red puede devolver [] sin lanzar, así que no cuenta como «viva».
    essential = [k for k in tasks if not k.startswith("yfinance:")]
    if essential and all(last_fetch_stats[k]["error"] for k in essential):
        raise NewsFetchError(
            f"No se pudo obtener ninguna noticia: fallaron las {len(tasks)} fuentes "
            "(¿sin conexión o bloqueo temporal?). Usa el modo de ejemplo o reinténtalo."
        )

    universe = list(dict.fromkeys([*wanted, *TICKER_UNIVERSE]))
    tagged = [
        item.model_copy(
            update={"tickers": list(dict.fromkeys([*item.tickers, *extract_tickers(f"{item.title} {item.summary}", universe)]))}
        )
        for item in collected
    ]
    unique = dedupe_news(sorted(tagged, key=_sort_key, reverse=True))

    now = datetime.now(timezone.utc)
    if since is not None:
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        in_window = [i for i in unique if _sort_key(i) >= since]
    else:
        in_window = []
        for hours in WINDOWS_HOURS:
            in_window = [i for i in unique if _sort_key(i) >= now - timedelta(hours=hours)]
            counts = {t: sum(t in i.tickers for i in in_window) for t in wanted}
            if all(c >= MIN_PER_TICKER for c in counts.values()) and len(in_window) >= min(max_items, 3):
                break
            log.info("Pocas noticias en %d h (%s); se amplía la ventana", hours, counts)

    per_ticker = max_per_ticker or (max(MIN_PER_TICKER, math.ceil(max_items / len(wanted))) if wanted else max_items)
    selected = _select(in_window, wanted, max_items, per_ticker)
    log.info(
        "Noticias: %d obtenidas, %d únicas, %d en ventana, %d seleccionadas (%d fuentes, %d fallidas)",
        len(collected), len(unique), len(in_window), len(selected), len(tasks), failures,
    )
    return selected


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
