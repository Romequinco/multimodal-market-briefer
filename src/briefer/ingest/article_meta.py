"""Metadatos de artículos de noticias: URL final del medio y descripción breve (``og:description``).

Carril A. Lo usa ``ingest.news.enrich_news`` para que las noticias seleccionadas lleguen al Analista
con un extracto útil y con el enlace real del medio en lugar del de redirección de Google News.

Reglas (derechos de autor y ToS, ver docs/04 §5):

- Solo se leen **metadatos** de la cabecera HTML (``<head>``: ``og:description``,
  ``twitter:description``, ``description``, ``canonical``); nunca el cuerpo del artículo. La descarga
  se corta al encontrar ``</head>`` (o a ``MAX_HEAD_BYTES``).
- Se respeta el ``robots.txt`` del medio para el agente ``ROBOTS_AGENT`` (``*`` si no hay reglas
  propias). ``robots.txt`` inexistente (4xx) = permitido; inaccesible (5xx, red) = no se lee la página.
- Enlaces de Google News (``news.google.com/rss/articles/…``): no redirigen por HTTP (llevan al aviso
  de cookies), así que se descodifican con el mismo patrón que usa su web (página del artículo +
  ``batchexecute``/``garturlreq``), enviando la cookie de consentimiento **solo esenciales**
  (``SOCS``). Es un mecanismo no documentado: si falla, se deja el enlace de Google.
- Peticiones con *timeout* corto (``META_TIMEOUT``) y sesión HTTP compartida; resultado cacheado por
  URL y día (``ingest.cache``, fuentes ``news-meta`` y ``news-gurl``); los errores transitorios (red,
  429, 5xx) solo se recuerdan ``TRANSIENT_TTL_S``. Un 429 de Google pausa su descodificación
  ``GOOGLE_BACKOFF_S``.

Nunca lanza: ``fetch_article_meta`` devuelve siempre un dict ``{"url", "description", "error"}``.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from briefer.ingest import cache
from briefer.logging_utils import get_logger

log = get_logger("ingest.article_meta")

#: User-Agent de navegador + identificador del producto (algunos medios bloquean UAs no navegador).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 market-briefer/0.2"
)
#: Nombre con el que se consultan las reglas de ``robots.txt``.
ROBOTS_AGENT = "market-briefer"
#: Timeout (s) de cada petición de metadatos (conexión y lectura).
META_TIMEOUT = 4.0
#: Máximo de bytes leídos de la página de un artículo (se corta antes al ver ``</head>``).
MAX_HEAD_BYTES = 400_000
#: Máximo de bytes de la página intermedia de Google News (los tokens van al final, ~600 KB).
MAX_GOOGLE_PAGE_BYTES = 2_000_000
#: Máximo de bytes de un ``robots.txt``.
MAX_ROBOTS_BYTES = 300_000
#: Descripciones más cortas se consideran inútiles.
MIN_DESCRIPTION_CHARS = 40

GOOGLE_NEWS_HOST = "news.google.com"
GOOGLE_BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
#: Cookie de consentimiento de Google con la opción «rechazar todo» (solo cookies esenciales).
GOOGLE_CONSENT_COOKIES = {"SOCS": "CAESEwgDEgk0ODE3Nzk3MjQaAmVzIAEaBgiA_LyaBg"}

#: Segundos durante los que se reutiliza un fallo transitorio (red, 429, 5xx) antes de reintentar:
#: evita que cada ejecución seguida vuelva a gastar el presupuesto en lo mismo.
TRANSIENT_TTL_S = 900
#: Pausa (s) de la descodificación de Google News tras un 429 (límite de peticiones).
GOOGLE_BACKOFF_S = 1800
#: Días que se reutiliza un ``robots.txt`` descargado y la URL final de un enlace de Google News
#: (no cambia nunca): la primera ejecución de cada día no repite esas peticiones.
ROBOTS_CACHE_DAYS = 7
GOOGLE_URL_CACHE_DAYS = 7

_TRANSIENT = "transient"  # prefijo de errores transitorios (caché corta, ``TRANSIENT_TTL_S``)


class MetaHTTPError(RuntimeError):
    """Error HTTP con código (``status``) para distinguir 4xx definitivos de fallos transitorios."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} en {urlsplit(url).netloc}")
        self.status = status


# ── red (puntos de inyección para tests) ─────────────────────────────────────────────

_session_lock = threading.Lock()
_session: Any = None


def _get_session() -> Any:
    """Sesión HTTP compartida (reutiliza conexiones TLS: Google News recibe 2 peticiones por noticia).

    El *pool* de conexiones de ``requests``/urllib3 es seguro entre hilos; las cookies se pasan por
    petición y no se guardan en la sesión.
    """
    global _session
    with _session_lock:
        if _session is None:
            import requests
            from requests.adapters import HTTPAdapter

            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=32, pool_maxsize=16, max_retries=0)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,en;q=0.7"})
            _session = session
        return _session


def _http_fetch(
    url: str,
    *,
    max_bytes: int = MAX_HEAD_BYTES,
    timeout: float = META_TIMEOUT,
    cookies: dict[str, str] | None = None,
    stop_marker: bytes | None = None,
) -> tuple[str, str, bytes]:
    """GET siguiendo redirecciones, leyendo como mucho ``max_bytes`` (o hasta ``stop_marker``).

    Returns:
        ``(url_final, content_type, cuerpo_parcial)``.

    Raises:
        MetaHTTPError: estado no 2xx. Otras excepciones de ``requests`` por red/timeout.
    """
    session = _get_session()
    with session.get(url, cookies=cookies, timeout=timeout, stream=True, allow_redirects=True) as resp:
        session.cookies.clear()  # no se arrastran cookies de un medio a otro
        if resp.status_code >= 400:
            raise MetaHTTPError(resp.status_code, url)
        chunks: list[bytes] = []
        size = 0
        for chunk in resp.iter_content(chunk_size=16_384):
            chunks.append(chunk)
            size += len(chunk)
            if size >= max_bytes:
                break
            if stop_marker and stop_marker in chunk.lower():
                break
        return resp.url, resp.headers.get("Content-Type", ""), b"".join(chunks)[:max_bytes]


def _http_post(url: str, data: dict[str, str], *, timeout: float = META_TIMEOUT,
               cookies: dict[str, str] | None = None) -> str:
    """POST de formulario; devuelve el texto (lanza ``MetaHTTPError`` si no es 2xx)."""
    session = _get_session()
    resp = session.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        cookies=cookies,
        timeout=timeout,
    )
    session.cookies.clear()
    if resp.status_code >= 400:
        raise MetaHTTPError(resp.status_code, url)
    return resp.text


# ── Google News ───────────────────────────────────────────────────────────────────────


def is_google_news_url(url: str) -> bool:
    """True si es un enlace de artículo de Google News (``/rss/articles/…`` o ``/articles/…``)."""
    parts = urlsplit(url or "")
    return parts.netloc.lower() == GOOGLE_NEWS_HOST and "/articles/" in parts.path


def google_article_id(url: str) -> str | None:
    """Identificador del artículo en un enlace de Google News (``None`` si no lo es)."""
    if not is_google_news_url(url):
        return None
    article = urlsplit(url).path.split("/articles/", 1)[1].strip("/")
    return article or None


_SG_RE = re.compile(rb'data-n-a-sg="([^"]+)"')
_TS_RE = re.compile(rb'data-n-a-ts="(\d+)"')


def _parse_batch_response(text: str) -> str | None:
    """URL del medio en la respuesta de ``batchexecute`` (``["garturlres", url, …]``)."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("[["):
            continue
        try:
            rows = json.loads(line)
        except json.JSONDecodeError:
            continue
        for row in rows:
            if isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr" and isinstance(row[2], str):
                try:
                    inner = json.loads(row[2])
                except json.JSONDecodeError:
                    continue
                if isinstance(inner, list) and len(inner) > 1 and inner[0] == "garturlres":
                    return str(inner[1])
    match = re.search(r'\\"garturlres\\",\\"(https?://[^\\"]+)\\"', text)
    return match[1] if match else None


_google_lock = threading.Lock()
_google_state: dict[str, float] = {"blocked_until": 0.0}


def _reset_google_state() -> None:
    """Levanta la pausa por 429 de Google News (tests)."""
    with _google_lock:
        _google_state["blocked_until"] = 0.0


def google_blocked() -> bool:
    """True si Google News respondió 429 hace menos de ``GOOGLE_BACKOFF_S`` (memoria o caché del día)."""
    now = time.time()
    with _google_lock:
        if _google_state["blocked_until"] > now:
            return True
    cached = cache.read_cache("news-meta", "google-blocked")
    until = float(cached.get("until", 0)) if isinstance(cached, dict) else 0.0
    if until > now:
        with _google_lock:
            _google_state["blocked_until"] = until
        return True
    return False


def _block_google() -> None:
    until = time.time() + GOOGLE_BACKOFF_S
    with _google_lock:
        _google_state["blocked_until"] = until
    cache.write_cache("news-meta", "google-blocked", {"until": until})
    log.info("Google News limita las peticiones (429): descodificación de enlaces en pausa %d min", GOOGLE_BACKOFF_S // 60)


def resolve_google_news_url(url: str) -> str | None:
    """URL final del medio para un enlace de Google News, o ``None`` si no se puede resolver.

    Dos peticiones: página del artículo (tokens ``data-n-a-sg``/``data-n-a-ts``) + ``batchexecute``.
    La resolución se cachea por día (fuente ``news-gurl``). Tras un 429 se pausa
    ``GOOGLE_BACKOFF_S`` (lanza ``MetaHTTPError(429)`` sin llamar a la red).
    Lanza en errores de red/HTTP (los clasifica ``fetch_article_meta``).
    """
    article = google_article_id(url)
    if not article:
        return None
    key = cache.cache_key(article)
    cached = cache.read_recent("news-gurl", key, GOOGLE_URL_CACHE_DAYS)
    if isinstance(cached, str) and cached.startswith(("http://", "https://")):
        return cached
    if google_blocked():
        raise MetaHTTPError(429, url)
    try:
        resolved = _resolve_google(article)
    except MetaHTTPError as exc:
        if exc.status == 429:
            _block_google()
        raise
    if resolved:
        cache.write_cache("news-gurl", key, resolved)
    return resolved


def _resolve_google(article: str) -> str | None:
    _final, _ctype, body = _http_fetch(
        f"https://{GOOGLE_NEWS_HOST}/rss/articles/{article}?hl=es&gl=ES&ceid=ES:es",  # sin el 302 de idioma
        max_bytes=MAX_GOOGLE_PAGE_BYTES,
        cookies=GOOGLE_CONSENT_COOKIES,
    )
    sg, ts = _SG_RE.search(body), _TS_RE.search(body)
    if not (sg and ts):
        return None
    inner = [
        "garturlreq",
        [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
         "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
        article,
        int(ts[1]),
        sg[1].decode("ascii", "ignore"),
    ]
    payload = [[["Fbv4je", json.dumps(inner), None, "generic"]]]
    text = _http_post(GOOGLE_BATCH_URL, {"f.req": json.dumps(payload)}, cookies=GOOGLE_CONSENT_COOKIES)
    resolved = _parse_batch_response(text)
    if not resolved or not resolved.startswith(("http://", "https://")):
        return None
    if urlsplit(resolved).netloc.lower().endswith("google.com"):
        return None
    return resolved


# ── robots.txt ────────────────────────────────────────────────────────────────────────

_robots_lock = threading.Lock()
#: ``(día, host) -> reglas``; solo resultados definitivos (un fallo de red se reintenta).
_robots_mem: dict[tuple[date, str], RobotFileParser | bool] = {}


def _reset_robots_state() -> None:
    """Vacía la memoria de ``robots.txt`` (tests)."""
    with _robots_lock:
        _robots_mem.clear()


def robots_allows(url: str) -> bool:
    """True si el ``robots.txt`` del host permite leer ``url`` a ``ROBOTS_AGENT``.

    4xx -> permitido (no hay reglas); 5xx o error de red -> no permitido (conservador, RFC 9309).
    Se guarda por host en memoria y en la caché del día.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    host = f"{parts.scheme}://{parts.netloc.lower()}"
    mem_key = (date.today(), host)
    with _robots_lock:
        known = _robots_mem.get(mem_key)
    if known is None:
        known, definitive = _load_robots(host)
        if definitive:
            with _robots_lock:
                _robots_mem[mem_key] = known
    if isinstance(known, bool):
        return known
    return known.can_fetch(ROBOTS_AGENT, url)


def _load_robots(host: str) -> tuple[RobotFileParser | bool, bool]:
    """Reglas de ``robots.txt`` de ``host`` y si el resultado es definitivo (cacheable)."""
    key = cache.cache_key(host)
    cached = cache.read_recent("news-robots", key, ROBOTS_CACHE_DAYS)
    if isinstance(cached, dict) and "allow_all" in cached:
        if cached["allow_all"] is not None:
            return bool(cached["allow_all"]), True
        parser = RobotFileParser()
        parser.parse(str(cached.get("text", "")).splitlines())
        return parser, True
    try:
        _final, _ctype, body = _http_fetch(urljoin(host, "/robots.txt"), max_bytes=MAX_ROBOTS_BYTES)
    except MetaHTTPError as exc:
        if 400 <= exc.status < 500 and exc.status != 429:
            cache.write_cache("news-robots", key, {"allow_all": True})
            return True, True
        return False, False  # 5xx/429: hoy no se lee la página; se reintenta en otra ejecución
    except Exception:  # noqa: BLE001 - red/timeout: igual que 5xx
        return False, False
    text = _decode(body, "")
    if "<html" in text[:500].lower():  # algunos hosts responden 200 con una página HTML
        cache.write_cache("news-robots", key, {"allow_all": True})
        return True, True
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    cache.write_cache("news-robots", key, {"allow_all": None, "text": text})
    return parser, True


# ── metadatos HTML ────────────────────────────────────────────────────────────────────

_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.IGNORECASE)
_DESCRIPTION_KEYS = ("og:description", "twitter:description", "description")


def _attrs(tag: str) -> dict[str, str]:
    return {m[1].lower(): html.unescape(m[2] or m[3] or m[4] or "") for m in _ATTR_RE.finditer(tag)}


def _decode(body: bytes, content_type: str) -> str:
    """Decodifica con el charset de la cabecera HTTP o del ``<meta charset>``; si no, UTF-8/cp1252."""
    candidates: list[str] = []
    match = re.search(r"charset=([\w-]+)", content_type or "", re.IGNORECASE)
    if match:
        candidates.append(match[1])
    meta = _CHARSET_RE.search(body[:4096])
    if meta:
        candidates.append(meta[1].decode("ascii", "ignore"))
    candidates += ["utf-8", "cp1252"]
    for enc in candidates:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def parse_head_meta(body: bytes, content_type: str = "") -> dict[str, str]:
    """Extrae ``description`` (og > twitter > meta) y ``canonical`` de la cabecera de una página.

    Solo mira las etiquetas ``<meta>``/``<link>`` anteriores a ``</head>`` (nunca el cuerpo).
    """
    end = body.lower().find(b"</head>")
    head = body[: end if end >= 0 else len(body)]
    text_head = _decode(head, content_type)
    found: dict[str, str] = {}
    for tag in _META_RE.findall(text_head):
        attrs = _attrs(tag)
        name = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content", "").strip()
        if content and name in (*_DESCRIPTION_KEYS, "og:url"):
            found.setdefault(name, content)
    canonical = ""
    for tag in _LINK_RE.findall(text_head):
        attrs = _attrs(tag)
        if "canonical" in attrs.get("rel", "").lower().split() and attrs.get("href"):
            canonical = attrs["href"].strip()
            break
    description = next((found[k] for k in _DESCRIPTION_KEYS if k in found), "")
    return {"description": description, "canonical": canonical or found.get("og:url", "")}


def _same_site(a: str, b: str) -> bool:
    """Mismo host, ignorando prefijos ``www.``/``amp.``/``m.`` (la canónica no puede saltar de medio)."""
    def host(u: str) -> str:
        h = urlsplit(u).netloc.lower().split(":")[0]
        for prefix in ("www.", "amp.", "m."):
            h = h.removeprefix(prefix)
        return h
    return bool(host(a)) and host(a) == host(b)


# ── punto de entrada ──────────────────────────────────────────────────────────────────


def _classify(exc: Exception) -> str:
    """Texto de error; con prefijo ``transient`` si merece reintento otro día/ejecución."""
    if isinstance(exc, MetaHTTPError):
        transient = exc.status == 429 or exc.status >= 500
        return f"{_TRANSIENT + ': ' if transient else ''}{exc}"
    return f"{_TRANSIENT}: {type(exc).__name__}"


def fetch_article_meta(url: str, *, use_cache: bool = True) -> dict[str, Any]:
    """URL final y descripción de un artículo. Nunca lanza.

    Returns:
        ``{"url": url_final, "description": str (sin limpiar), "error": str | None}``. Si no se
        pudo resolver Google News, ``url`` es la original. ``description`` puede venir vacía.
    """
    key = cache.cache_key(url)
    if use_cache:
        cached = cache.read_cache("news-meta", key)
        if isinstance(cached, dict) and "url" in cached:
            error = cached.get("error")
            fresh = time.time() - float(cached.get("ts", 0)) < TRANSIENT_TTL_S
            if not str(error or "").startswith(_TRANSIENT) or fresh:
                return {"url": cached["url"], "description": cached.get("description", ""), "error": error}

    result: dict[str, Any] = {"url": url, "description": "", "error": None}
    try:
        target = url
        if is_google_news_url(url):
            resolved = resolve_google_news_url(url)
            if not resolved:
                result["error"] = "google: sin URL final"
                return _store(key, result)
            target = result["url"] = resolved
        if not robots_allows(target):
            result["error"] = "robots.txt no permite leer la página"
            return _store(key, result)
        final, ctype, body = _http_fetch(target, stop_marker=b"</head>")
        if final and final.startswith(("http://", "https://")) and not is_google_news_url(final):
            result["url"] = final
        if ctype and "html" not in ctype.lower():
            result["error"] = f"no es HTML ({ctype.split(';')[0]})"
            return _store(key, result)
        meta = parse_head_meta(body, ctype)
        canonical = meta["canonical"]
        if canonical.startswith(("http://", "https://")) and _same_site(canonical, result["url"]):
            result["url"] = canonical
        result["description"] = meta["description"]
        if not meta["description"]:
            result["error"] = "sin descripción en la cabecera"
    except Exception as exc:  # noqa: BLE001 - nunca rompe la ingesta
        result["error"] = _classify(exc)
        log.debug("Metadatos no disponibles para %s: %s", urlsplit(url).netloc, result["error"])
    return _store(key, result)


def _store(key: str, result: dict[str, Any]) -> dict[str, Any]:
    """Cachea el resultado del día; los fallos transitorios solo valen ``TRANSIENT_TTL_S``."""
    cache.write_cache("news-meta", key, {**result, "ts": time.time()})
    return result
