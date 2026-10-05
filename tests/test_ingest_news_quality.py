"""Calidad de noticias del carril A SIN red: extractos, URL final, relevancia, casi duplicados,
fichas de cotización, Bing News, metadatos de artículo (``ingest.article_meta``) y casos borde.

La red se sustituye por dobles: ``news._http_get`` (feeds) y ``article_meta._http_fetch`` /
``article_meta._http_post`` (páginas, ``robots.txt`` y descodificación de Google News).
"""

from __future__ import annotations

import json
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import quote, urlsplit

import pytest

from briefer.ingest import article_meta, cache, news
from briefer.schemas import NewsItem

NOW = datetime.now(timezone.utc)


def _rfc822(hours_ago: float) -> str:
    return format_datetime(NOW - timedelta(hours=hours_ago))


def _item(title: str, url: str, summary: str = "", hours: float = 1, tickers=None, language: str = "es") -> NewsItem:
    return NewsItem(
        id=news.news_id(url, title), title=title, summary=summary, source="Medio", url=url,
        published_at=NOW - timedelta(hours=hours), tickers=tickers or [], language=language,
    )


def _no_yfinance() -> types.ModuleType:
    mod = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def get_news(self, count: int = 10, tab: str = "news") -> list:
            return []

    mod.Ticker = Ticker  # type: ignore[attr-defined]
    return mod


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch):
    """Estado limpio y ninguna petición real (lo que no se simule, falla como «sin red»)."""
    news._reset_yf_news_state()
    article_meta._reset_robots_state()
    article_meta._reset_google_state()
    monkeypatch.setenv("BRIEFER_NEWS_RSS_FEEDS", "")
    monkeypatch.setitem(sys.modules, "yfinance", _no_yfinance())

    def offline(*_a, **_k):
        raise ConnectionError("sin red en tests")

    monkeypatch.setattr(news, "_http_get", offline)
    monkeypatch.setattr(article_meta, "_http_fetch", offline)
    monkeypatch.setattr(article_meta, "_http_post", offline)
    yield


# ── doble de la web de los medios ─────────────────────────────────────────────────

GOOGLE_PAGE = b'<html><body>' + b"x" * 1000 + b'<c-wiz><div data-n-a-sg="SIG123" data-n-a-ts="1759600000"></div></c-wiz></body></html>'


def batch_response(url: str) -> str:
    inner = json.dumps(["garturlres", url, 1])
    return ")]}'\n\n123\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, None, None, "generic"]]) + "\n25\n[[\"e\",4]]"


def article_page(description: str, charset: str = "utf-8", canonical: str = "") -> bytes:
    head = f'<html><head><meta charset="{charset}"><title>T</title>'
    head += f'<meta property="og:description" content="{description}">'
    head += '<meta name="description" content="Descripción genérica del medio">'
    if canonical:
        head += f'<link rel="canonical" href="{canonical}">'
    head += "</head><body><p>CUERPO DEL ARTÍCULO QUE NUNCA SE LEE</p>"
    head += '<meta property="og:description" content="meta en el cuerpo: se ignora"></body></html>'
    return head.encode(charset)


class FakeWeb:
    """Sustituye ``article_meta._http_fetch``/``_http_post``: Google News, robots y páginas."""

    def __init__(self, pages: dict[str, tuple[str, bytes] | Exception], robots: dict[str, str | int] | None = None,
                 google: dict[str, str] | None = None, delay: float = 0.0, google_status: int | None = None) -> None:
        self.pages = pages              # url -> (content_type, body) o excepción
        self.robots = robots or {}      # host -> texto de robots.txt o código HTTP
        self.google = google or {}      # id de artículo -> URL del medio
        self.delay = delay
        self.google_status = google_status
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def fetch(self, url: str, *, max_bytes: int = 0, timeout: float = 0, cookies=None, stop_marker=None):
        with self.lock:
            self.calls.append(url)
        if self.delay:
            time.sleep(self.delay)
        parts = urlsplit(url)
        if parts.netloc == "news.google.com":
            if self.google_status:
                raise article_meta.MetaHTTPError(self.google_status, url)
            assert cookies == article_meta.GOOGLE_CONSENT_COOKIES  # solo cookies esenciales
            return url, "text/html", GOOGLE_PAGE
        if parts.path == "/robots.txt":
            rule = self.robots.get(parts.netloc, 404)
            if isinstance(rule, int):
                raise article_meta.MetaHTTPError(rule, url)
            return url, "text/plain", rule.encode()
        page = self.pages.get(url)
        if page is None:
            raise article_meta.MetaHTTPError(404, url)
        if isinstance(page, Exception):
            raise page
        ctype, body = page
        return url, ctype, body

    def post(self, url: str, data: dict, *, timeout: float = 0, cookies=None) -> str:
        with self.lock:
            self.calls.append(url)
        req = json.loads(data["f.req"])
        inner = json.loads(req[0][0][1])
        assert inner[0] == "garturlreq" and inner[3] == 1759600000 and inner[4] == "SIG123"
        return batch_response(self.google[inner[2]])

    def install(self, monkeypatch: pytest.MonkeyPatch) -> "FakeWeb":
        monkeypatch.setattr(article_meta, "_http_fetch", self.fetch)
        monkeypatch.setattr(article_meta, "_http_post", self.post)
        return self


G1 = "https://news.google.com/rss/articles/CBMiAAA111?oc=5"
G2 = "https://news.google.com/rss/articles/CBMiBBB222?oc=5"
SAN_URL = "https://www.medio.es/mercados/2026/10/05/santander-sube-en-bolsa.html"
ITX_URL = "https://www.otro.es/empresas/inditex-gana-cuota-frente-a-shein.html"
SAN_DESC = "El banco cántabro sube un 2 % tras mejorar su precio objetivo varias firmas de análisis."


# ── article_meta: metadatos HTML ──────────────────────────────────────────────────


def test_parse_head_meta_priority_charset_and_only_head() -> None:
    meta = article_meta.parse_head_meta(article_page("Señal de compra &amp; venta", "iso-8859-1",
                                                     canonical="https://www.medio.es/x.html"))
    assert meta["description"] == "Señal de compra & venta"  # og > description; latin-1 bien leído
    assert meta["canonical"] == "https://www.medio.es/x.html"
    body_only = b"<html><head></head><body><meta property='og:description' content='no'></body></html>"
    assert article_meta.parse_head_meta(body_only)["description"] == ""
    twitter = b'<head><meta content="Del tuit" name="twitter:description"><meta name="description" content="meta"></head>'
    assert article_meta.parse_head_meta(twitter)["description"] == "Del tuit"
    assert article_meta.parse_head_meta(b"")["description"] == ""


def test_google_news_helpers_and_batch_parsing() -> None:
    assert article_meta.is_google_news_url(G1)
    assert not article_meta.is_google_news_url("https://news.google.com/rss/search?q=x")
    assert article_meta.google_article_id(G1) == "CBMiAAA111"
    assert article_meta._parse_batch_response(batch_response("https://medio.es/a")) == "https://medio.es/a"
    assert article_meta._parse_batch_response("basura") is None


def test_fetch_article_meta_resolves_google_and_reads_description(monkeypatch) -> None:
    web = FakeWeb({SAN_URL: ("text/html; charset=utf-8", article_page(SAN_DESC))},
                  google={"CBMiAAA111": SAN_URL}).install(monkeypatch)
    meta = article_meta.fetch_article_meta(G1)
    assert meta == {"url": SAN_URL, "description": SAN_DESC, "error": None}
    n = len(web.calls)
    assert article_meta.fetch_article_meta(G1) == meta  # caché del día: sin red
    assert len(web.calls) == n


def test_fetch_article_meta_respects_robots(monkeypatch) -> None:
    web = FakeWeb({SAN_URL: ("text/html", article_page(SAN_DESC))},
                  robots={"www.medio.es": "User-agent: *\nDisallow: /mercados/\n"}).install(monkeypatch)
    meta = article_meta.fetch_article_meta(SAN_URL)
    assert meta["description"] == "" and "robots" in meta["error"]
    assert SAN_URL not in web.calls  # la página no se pide
    # agente propio permitido aunque el resto no
    article_meta._reset_robots_state()
    web2 = FakeWeb({ITX_URL: ("text/html", article_page("Inditex gana cuota frente a Shein en Europa este trimestre"))},
                   robots={"www.otro.es": "User-agent: *\nDisallow: /\n\nUser-agent: market-briefer\nAllow: /\n"})
    web2.install(monkeypatch)
    assert article_meta.fetch_article_meta(ITX_URL)["description"].startswith("Inditex gana")


def test_robots_server_error_blocks_but_is_not_memoized(monkeypatch) -> None:
    web = FakeWeb({SAN_URL: ("text/html", article_page(SAN_DESC))}, robots={"www.medio.es": 503}).install(monkeypatch)
    assert not article_meta.robots_allows(SAN_URL)
    web.robots["www.medio.es"] = "User-agent: *\nAllow: /\n"
    assert article_meta.robots_allows(SAN_URL)  # el 503 no se recordó


def test_fetch_article_meta_non_html_and_errors(monkeypatch) -> None:
    pdf_url = "https://www.medio.es/informe-anual-2026.pdf"
    FakeWeb({pdf_url: ("application/pdf", b"%PDF-1.7"), SAN_URL: TimeoutError("lento")}).install(monkeypatch)
    assert "no es HTML" in article_meta.fetch_article_meta(pdf_url)["error"]
    meta = article_meta.fetch_article_meta(SAN_URL)
    assert meta["url"] == SAN_URL and meta["error"].startswith("transient")
    assert article_meta.fetch_article_meta("https://www.medio.es/no-existe")["error"] == "HTTP 404 en www.medio.es"


def test_transient_errors_expire(monkeypatch) -> None:
    web = FakeWeb({SAN_URL: ConnectionError("caída")}).install(monkeypatch)
    assert article_meta.fetch_article_meta(SAN_URL)["error"].startswith("transient")
    web.pages[SAN_URL] = ("text/html", article_page(SAN_DESC))
    assert article_meta.fetch_article_meta(SAN_URL)["error"].startswith("transient")  # aún dentro del TTL
    monkeypatch.setattr(article_meta, "TRANSIENT_TTL_S", 0)
    assert article_meta.fetch_article_meta(SAN_URL)["description"] == SAN_DESC  # caducó: se reintenta


def test_google_429_pauses_decoding(monkeypatch) -> None:
    web = FakeWeb({}, google_status=429).install(monkeypatch)
    first = article_meta.fetch_article_meta(G1)
    assert first["url"] == G1 and "429" in first["error"]
    assert article_meta.google_blocked()
    n = len(web.calls)
    article_meta.fetch_article_meta(G2)
    assert len(web.calls) == n  # en pausa: no vuelve a llamar a Google


# ── news: extractos, enriquecimiento y relevancia ─────────────────────────────────


def test_summary_limit_is_short_for_copyright() -> None:
    assert news.SUMMARY_MAX_CHARS <= 200
    long = news.clean_html("palabra " * 100)
    assert len(long) <= news.SUMMARY_MAX_CHARS and long.endswith("…")


def test_enrich_news_fills_summary_and_final_url(monkeypatch) -> None:
    FakeWeb({SAN_URL: ("text/html", article_page(SAN_DESC + " " + "x" * 300))},
            google={"CBMiAAA111": SAN_URL}).install(monkeypatch)
    items = [_item("Santander sube en bolsa", G1), _item("Ya tiene resumen", ITX_URL, summary="Resumen propio del feed.")]
    stats: dict = {}
    out = news.enrich_news(items, stats_out=stats)
    assert out[0].url == SAN_URL and out[0].summary.startswith("El banco cántabro")
    assert len(out[0].summary) <= news.SUMMARY_MAX_CHARS
    assert out[0].id == items[0].id  # el id no cambia
    assert out[1] == items[1]  # con resumen y URL directa: no se toca
    assert stats["candidates"] == 1 and stats["resolved"] == 1 and stats["summaries"] == 1


def test_enrich_news_discards_generic_and_title_only_descriptions(monkeypatch) -> None:
    generic = "Toda la actualidad económica y financiera, en directo y con el mejor análisis."
    a = "https://www.medio.es/mercados/noticia-uno-sobre-bolsa.html"
    b = "https://www.medio.es/mercados/noticia-dos-sobre-bolsa.html"
    c = "https://www.otro.es/mercados/titular-repetido-en-la-descripcion.html"
    FakeWeb({a: ("text/html", article_page(generic)), b: ("text/html", article_page(generic)),
             c: ("text/html", article_page("Iberdrola cierra una alianza con GIC"))}).install(monkeypatch)
    out = news.enrich_news([_item("Noticia uno sobre bolsa", a), _item("Noticia dos sobre bolsa", b),
                            _item("Iberdrola cierra una alianza con GIC", c)])
    assert [i.summary for i in out] == ["", "", ""]


def test_enrich_news_respects_budget(monkeypatch) -> None:
    FakeWeb({SAN_URL: ("text/html", article_page(SAN_DESC))}, delay=1.0).install(monkeypatch)
    items = [_item("Santander sube en bolsa", SAN_URL)]
    start = time.perf_counter()
    stats: dict = {}
    out = news.enrich_news(items, budget_s=0.2, stats_out=stats)
    assert time.perf_counter() - start < 0.9  # no espera a la petición lenta
    assert out == items and stats["timed_out"] == 1
    assert news.enrich_news(items, budget_s=0) == items


def test_relevance_title_beats_summary_and_language_and_freshness() -> None:
    title = _item("Inditex dispara sus ventas", "https://a.es/1-a-b.html", hours=10)
    summary = _item("El textil europeo gana cuota", "https://a.es/2-a-b.html", summary="Inditex lidera.", hours=1)
    none = _item("Moda rápida: el sector se mueve", "https://a.es/3-a-b.html", hours=1)
    english = _item("Inditex sales jump", "https://a.es/4-a-b.html", hours=10, language="en")
    old = _item("Inditex dispara sus ventas otra vez", "https://a.es/5-a-b.html", hours=70)
    many = _item("Análisis de BBVA, Iberdrola, Inditex y Santander", "https://a.es/6-a-b.html", hours=10,
                 tickers=["ITX.MC", "BBVA.MC", "IBE.MC", "SAN.MC"])
    score = {k: news.relevance_score(v, "ITX.MC", NOW) for k, v in
             dict(title=title, summary=summary, none=none, english=english, old=old, many=many).items()}
    assert score["title"] > score["summary"] > score["none"]
    assert score["title"] > score["english"] and score["title"] > score["old"] and score["title"] > score["many"]


def test_select_prioritises_relevance_over_recency() -> None:
    passing = _item("La moda europea sube en bolsa", "https://a.es/moda-europea-sube.html", hours=1, tickers=["ITX.MC"])
    direct = _item("Inditex reparte un dividendo récord", "https://a.es/inditex-dividendo-record.html", hours=20,
                   tickers=["ITX.MC"])
    scores: dict[str, float] = {}
    out = news._select([passing, direct], ["ITX.MC"], max_items=1, per_ticker=1, scores=scores)
    assert out == [direct] and scores[direct.id] > 0


# ── deduplicado y filtros ─────────────────────────────────────────────────────────


def test_near_duplicate_titles_are_merged_and_prefer_direct_url() -> None:
    a = _item("Iberdrola supera a BBVA y recupera el tercer puesto por capitalización", G1, tickers=["IBE.MC"])
    b = _item("Iberdrola supera a BBVA y recupera el tercer puesto por capitalización en el Ibex",
              "https://www.merca2.es/2026/10/05/iberdrola-bbva-capitalizacion.html", summary="Extracto.",
              tickers=["BBVA.MC"])
    c = _item("Iberdrola reabre el troceo de Red Eléctrica", "https://www.merca2.es/2026/10/05/troceo.html")
    out = news.dedupe_news([a, b, c])
    assert len(out) == 2
    assert out[0].id == a.id and out[0].url == b.url and out[0].summary == "Extracto."
    assert out[0].tickers == ["IBE.MC", "BBVA.MC"]
    assert len(news.dedupe_news([a, b, c], near_threshold=None)) == 3
    assert not news.titles_similar("Inditex sube", "Inditex baja")  # titulares cortos: nunca aproximado


def test_url_key_keeps_article_params_and_drops_tracking() -> None:
    one = "https://medio.es/noticia.php?id=1&utm_source=rss"
    two = "https://medio.es/noticia.php?id=2"
    assert news._url_key(one) == news._url_key("https://medio.es/noticia.php?id=1#arriba")
    assert news.news_id(one) != news.news_id(two)
    assert news._url_key("https://finance.yahoo.com/news/x.html?.tsrc=rss") == news._url_key("https://finance.yahoo.com/news/x.html")
    items = [_item("Primera noticia del día sobre bolsa", one), _item("Segunda noticia del día sobre bolsa", two)]
    assert len(news.dedupe_news(items)) == 2  # antes se fusionaban por quitar toda la query


@pytest.mark.parametrize(
    ("title", "url", "landing"),
    [
        ("Inditex (ITX)", "https://es.investing.com/equities/inditex-ratios", True),
        ("NVDA Pro Research (inglés)", "https://es.investing.com/equities/nvidia-corp-earnings", True),
        ("Cotización Iberdrola", "https://www.bolsamania.com/accion/IBERDROLA", True),
        ("Banco Santander", "https://www.libertaddigital.com/empresas/banco-santander/", True),
        ("Las noticias de Banco Santander hoy", "https://www.libertaddigital.com/empresas/banco-santander/", True),
        ("De Indra a Pharmamar: las acciones favoritas", "https://www.elconfidencial.com/mercados/2026-09-30/cotizacion-x_443.html", False),
        ("El Ibex duda con la deuda y el euro", "https://www.expansion.com/mercados/ibex-duda.html", False),
        ("Santander rebota en bolsa tras el soporte", G1, False),
    ],
)
def test_is_landing_page(title: str, url: str, landing: bool) -> None:
    assert news.is_landing_page(_item(title, url)) is landing


def test_future_dates_are_clamped() -> None:
    future = format_datetime(NOW + timedelta(hours=5))
    feed = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>X</title>
<item><title>Noticia con hora mal declarada</title><link>https://a.es/n-1-2.html</link><pubDate>{future}</pubDate></item>
</channel></rss>""".encode()
    item = news.parse_feed(feed)[0]
    assert item.published_at <= datetime.now(timezone.utc) + timedelta(seconds=5)


# ── feeds: Google News, Bing News y respuestas raras ──────────────────────────────


def test_google_cluster_description_is_dropped() -> None:
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>G</title>
<item><title>Santander sube - El Pais</title><link>https://news.google.com/rss/articles/CBMiZZZ?oc=5</link>
<description>&lt;ol&gt;&lt;li&gt;&lt;a href="x"&gt;Santander sube&lt;/a&gt; El Pais&lt;/li&gt;&lt;li&gt;&lt;a href="y"&gt;Otro titular de otro medio distinto y largo&lt;/a&gt; Cinco Dias&lt;/li&gt;&lt;/ol&gt;</description>
<source url="https://elpais.com">El Pais</source></item></channel></rss>"""
    item = news.parse_feed(feed)[0]
    assert item.title == "Santander sube" and item.summary == ""


def bing_rss(entries: list[tuple[str, str, str, str, float]]) -> bytes:
    items = "".join(
        f"""<item><title>{title}</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=abc&amp;url={quote(url, safe='')}&amp;c=1&amp;mkt=es-es</link>
<description>{desc}</description><pubDate>{_rfc822(hours)}</pubDate><News:Source>{source}</News:Source></item>"""
        for title, url, desc, source, hours in entries
    )
    return f"""<?xml version="1.0" encoding="utf-8"?><rss xmlns:News="https://www.bing.com/news/search?q=x&amp;format=rss" version="2.0">
<channel><title>Bing</title><language>es-ES</language>{items}</channel></rss>""".encode()


def test_parse_bing_feed_unwraps_url_and_source() -> None:
    feed = bing_rss([("Santander sube en bolsa", SAN_URL, SAN_DESC, "El Español on MSN", 2)])
    item = news.parse_feed(feed, default_source="Bing News")[0]
    assert item.url == SAN_URL and item.source == "El Español" and item.summary == SAN_DESC
    assert news.unwrap_redirect("https://medio.es/a") == "https://medio.es/a"
    q = news.parse_qsl(urlsplit(news.bing_news_url(news.google_news_query("SAN.MC"))).query)
    assert ("format", "rss") in q and ("mkt", "es-ES") in q


@pytest.mark.parametrize(
    "body",
    [
        b"<!doctype html><html><head><title>Before you continue</title></head><body><p>Cookies</p></body></html>",
        b"<html><body>Error 503</body",
        b"",
        b'{"error": "rate limited"}',
    ],
)
def test_parse_feed_rejects_html_error_pages(body: bytes) -> None:
    with pytest.raises(ValueError):
        news.parse_feed(body, "https://news.google.com/rss/search?q=x")


def test_empty_valid_feed_is_not_an_error() -> None:
    assert news.parse_feed(b'<?xml version="1.0"?><rss version="2.0"><channel><title>V</title></channel></rss>') == []


GOOGLE_SAN = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>G</title><language>es</language>
<item><title>Santander sube en bolsa - Medio</title><link>{G1}</link><pubDate>{_rfc822(2)}</pubDate>
<description>enlace</description><source url="https://www.medio.es">Medio</source></item>
<item><title>Santander abre oficinas en Brasil y México - Otro</title><link>{G2}</link><pubDate>{_rfc822(3)}</pubDate>
<description>enlace</description><source url="https://www.otro.es">Otro</source></item>
</channel></rss>""".encode()
EMPTY_RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>E</title></channel></rss>'
MARKET_RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Mercados</title><language>es-ES</language>
<item><title>El Ibex abre plano a la espera de la Fed</title><link>https://www.expansion.com/mercados/2026/10/05/ibex-abre.html</link>
<description>Los inversores esperan a la Reserva Federal.</description><pubDate>{_rfc822(1)}</pubDate></item>
</channel></rss>""".encode()
FEEDS = ["https://e00-expansion.uecdn.es/rss/mercados.xml"]


class FeedHTTP:
    def __init__(self, routes: dict[str, bytes | Exception]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float = 0) -> bytes:
        self.calls.append(url)
        host = urlsplit(url).netloc
        for key, value in self.routes.items():
            if key in host or key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        return EMPTY_RSS


def test_fetch_news_end_to_end_with_bing_and_enrichment(monkeypatch) -> None:
    bing = bing_rss([
        ("Santander sube en bolsa", SAN_URL, SAN_DESC, "Medio", 2.5),
        ("Banco Santander (SAN)", "https://es.investing.com/equities/banco-santander", "Ficha de cotización con ratios.", "Investing", 1),
    ])
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"news.google.com": GOOGLE_SAN, "www.bing.com": bing,
                                                     "expansion": MARKET_RSS}))
    other = "https://www.otro.es/2026/10/05/santander-abre-oficinas-brasil-mexico.html"
    FakeWeb({other: ("text/html", article_page("La entidad refuerza su red en Latinoamérica con 40 nuevas oficinas."))},
            google={"CBMiBBB222": other}).install(monkeypatch)
    stats: dict = {}
    out = news.fetch_news(["SAN.MC"], rss_feeds=FEEDS, stats_out=stats)
    by_title = {i.title: i for i in out}
    sube = by_title["Santander sube en bolsa"]  # Google + Bing fusionadas: enlace directo y extracto de Bing
    assert sube.url == SAN_URL and sube.summary == SAN_DESC
    abre = by_title["Santander abre oficinas en Brasil y México"]  # solo Google: resuelta y con og:description
    assert abre.url == other and abre.summary.startswith("La entidad refuerza")
    assert not any("(SAN)" in t for t in by_title)  # la ficha de cotización se descarta
    q = stats["quality"]
    assert q["landing_pages"] == 1 and q["google_urls"] == 0 and q["with_summary"] == len(out)
    assert all(len(i.summary) <= news.SUMMARY_MAX_CHARS for i in out)
    assert stats["fetch"]["bing:SAN.MC"]["items"] == 2


def test_fetch_news_stats_out_per_call(monkeypatch) -> None:
    """``stats_out`` devuelve las estadísticas de ESTA llamada (ya no hay globales de «última llamada»)."""
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"news.google.com": GOOGLE_SAN, "expansion": MARKET_RSS}))
    FakeWeb({}).install(monkeypatch)
    stats: dict = {}
    out = news.fetch_news(["SAN.MC"], rss_feeds=FEEDS, stats_out=stats)
    assert out
    assert not hasattr(news, "last_fetch_stats") and not hasattr(news, "last_quality_stats")
    assert set(stats["fetch"]) >= {"google:SAN.MC", "bing:SAN.MC"}
    assert stats["quality"]["selected"] == len(out)
    assert stats["quality"]["enrich"]["candidates"] >= 0
    assert "scores" not in stats["quality"] and "explain" not in stats["quality"]
    line = news.format_news_stats(stats)
    assert f"{len(stats['fetch'])} fuentes" in line and f"{len(out)} seleccionadas" in line


def test_concurrent_fetches_do_not_mix_stats(monkeypatch) -> None:
    """Dos briefings simultáneos (dos sesiones de la UI): cada uno recibe SOLO sus estadísticas."""
    barrier = threading.Barrier(3, timeout=5)  # Google News de SAN.MC, AAPL y NVDA a la vez
    google_apple = GOOGLE_SAN.replace(b"Santander sube en bolsa", b"Apple sube en Wall Street por la IA") \
        .replace(b"Santander abre oficinas en Brasil y M\xc3\xa9xico", b"Apple presenta resultados con ventas al alza")

    class SyncedHTTP(FeedHTTP):
        def __call__(self, url: str, timeout: float = 0) -> bytes:
            if "news.google.com" in url:
                barrier.wait()  # las descargas de Google News de los dos briefings coinciden en el tiempo
                if "Apple" in url:
                    return google_apple
                return GOOGLE_SAN if "Santander" in url else EMPTY_RSS
            return super().__call__(url, timeout)

    monkeypatch.setattr(news, "_http_get", SyncedHTTP({"expansion": MARKET_RSS}))
    results: dict[str, tuple[list, dict]] = {}

    def run(name: str, tickers: list[str]) -> None:
        stats: dict = {}
        results[name] = (news.fetch_news(tickers, rss_feeds=FEEDS, enrich=False, stats_out=stats), stats)

    threads = [threading.Thread(target=run, args=("san", ["SAN.MC"])),
               threading.Thread(target=run, args=("apple", ["AAPL", "NVDA"]))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    (san_out, san), (apple_out, apple) = results["san"], results["apple"]
    assert {k.split(":", 1)[1] for k in san["fetch"] if not k.startswith("rss:")} == {"SAN.MC"}
    assert {k.split(":", 1)[1] for k in apple["fetch"] if not k.startswith("rss:")} == {"AAPL", "NVDA"}
    for out, stats in ((san_out, san), (apple_out, apple)):
        assert not any(v["error"] for v in stats["fetch"].values())  # la barrera no se rompió
        assert stats["quality"]["selected"] == len(out)
        assert [s["id"] for s in stats["quality"]["selection"]] == [i.id for i in out]
    assert any("Santander" in s["title"] for s in san["quality"]["selection"])
    assert not any("Santander" in s["title"] for s in apple["quality"]["selection"])


def test_news_stats_explain_relevance_in_spanish(monkeypatch) -> None:
    """``StepMetric.detail`` de ``ingest.news``: fuentes por tipo, % con extracto, descartes y por qué entra cada una."""
    bing = bing_rss([
        ("Santander sube en bolsa", SAN_URL, SAN_DESC, "Medio", 2.5),
        ("Banco Santander (SAN)", "https://es.investing.com/equities/banco-santander", "Ficha de cotización.", "Investing", 1),
    ])
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"news.google.com": GOOGLE_SAN, "www.bing.com": bing,
                                                     "expansion": MARKET_RSS}))
    stats: dict = {}
    out = news.fetch_news(["SAN.MC"], rss_feeds=FEEDS, enrich=False, stats_out=stats)
    q = stats["quality"]
    sube = next(s for s in q["selection"] if s["title"] == "Santander sube en bolsa")
    assert sube["ticker"] == "SAN.MC" and sube["score"] > 4 and sube["has_summary"]
    assert sube["reasons"][0] == "titular" and "es" in sube["reasons"] and "extracto" in sube["reasons"]
    ibex = next(s for s in q["selection"] if s["title"].startswith("El Ibex"))
    assert ibex["ticker"] is None and ibex["reasons"] == ["contexto general"]
    assert q["landing_pages"] == 1 and q["near_duplicates"] + q["exact_duplicates"] >= 1
    line = news.format_news_stats(stats)
    assert "Google News 2" in line and "Bing News 2" in line and "prensa 1" in line
    pct = round(100 * q["with_summary"] / len(out))
    assert f"extracto en el {pct} %" in line
    assert "descartadas: 1 fichas de cotización" in line
    assert "relevancia: " in line and f"SAN.MC {sube['score']:.1f} «Santander sube en bolsa» (titular" in line
    assert "general «El Ibex abre plano" in line
    # el resumen va primero (el nodo del grafo de «Cómo se hizo» recorta el detalle)
    assert line.index("seleccionadas") < line.index("relevancia:")


def test_relevance_explained_matches_score() -> None:
    item = _item("Inditex dispara sus ventas", "https://a.es/1-a-b.html", hours=10,
                 tickers=["ITX.MC", "SAN.MC", "BBVA.MC", "IBE.MC"])
    score, reasons = news.relevance_explained(item, "ITX.MC", NOW)
    assert score == news.relevance_score(item, "ITX.MC", NOW)
    assert reasons == ["titular", "10 h", "es", "lista de valores"]


def test_enrichment_is_prefetched_while_slow_sources_finish(monkeypatch) -> None:
    """Mientras yfinance (lenta) termina, se adelantan los metadatos de la selección provisional
    y ``enrich_news`` reutiliza esas peticiones (sin repetirlas)."""
    slow = _no_yfinance()

    class SlowTicker(slow.Ticker):  # type: ignore[name-defined, misc]
        def get_news(self, count: int = 10, tab: str = "news") -> list:
            time.sleep(0.8)
            return []

    slow.Ticker = SlowTicker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", slow)
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"news.google.com": GOOGLE_SAN, "expansion": MARKET_RSS}))
    web = FakeWeb({SAN_URL: ("text/html", article_page(SAN_DESC))}, google={"CBMiAAA111": SAN_URL}).install(monkeypatch)
    stats: dict = {}
    out = news.fetch_news(["SAN.MC"], rss_feeds=FEEDS, stats_out=stats)
    sube = next(i for i in out if i.title == "Santander sube en bolsa")
    assert sube.url == SAN_URL and sube.summary.startswith("El banco cántabro")
    enrich = stats["quality"]["enrich"]
    assert enrich["prefetched"] == enrich["candidates"] >= 1
    assert web.calls.count(SAN_URL) == 1  # la página se pidió una sola vez
    assert "adelantados" in news.format_news_stats(stats)


def test_fetch_news_enrich_false_makes_no_page_requests(monkeypatch) -> None:
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"news.google.com": GOOGLE_SAN}))
    web = FakeWeb({}).install(monkeypatch)
    stats: dict = {}
    out = news.fetch_news(["SAN.MC"], rss_feeds=FEEDS, enrich=False, stats_out=stats)
    assert out and web.calls == []
    assert stats["quality"]["enrich"]["candidates"] == 0


def test_fetch_news_google_html_error_is_a_failure_not_cached(monkeypatch) -> None:
    consent = b"<!doctype html><html><head><title>Antes de ir a Google</title></head><body>cookies</body></html>"
    http = FeedHTTP({"news.google.com": consent, "expansion": MARKET_RSS})
    monkeypatch.setattr(news, "_http_get", http)
    stats: dict = {}
    news.fetch_news(["SAN.MC"], rss_feeds=FEEDS, enrich=False, stats_out=stats)
    assert stats["fetch"]["google:SAN.MC"]["error"].startswith("ValueError")
    assert cache.read_cache("news-google", cache.cache_key("google", "SAN.MC")) is None  # no se cachea
    http.routes["news.google.com"] = GOOGLE_SAN
    out = news.fetch_news(["SAN.MC"], rss_feeds=FEEDS, enrich=False)
    assert any("Santander sube" in i.title for i in out)


@pytest.mark.parametrize("tickers", [["$", "  ", "SAN.MC"], ["san"], ["ZZZZ.XX", "SAN.MC"], ["brk-b", "SAN.MC"]])
def test_fetch_news_odd_tickers(monkeypatch, tickers: list[str]) -> None:
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"news.google.com": GOOGLE_SAN}))
    stats: dict = {}
    out = news.fetch_news(tickers, rss_feeds=FEEDS, enrich=False, stats_out=stats)
    assert any("SAN.MC" in i.tickers for i in out)
    assert not any(k.startswith("google:$") for k in stats["fetch"])


def test_fetch_news_ticker_without_news_returns_market_context(monkeypatch) -> None:
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"expansion": MARKET_RSS}))
    out = news.fetch_news(["ZZZZ.XX"], rss_feeds=FEEDS, enrich=False)  # ninguna fuente sabe nada de él
    assert [i.title for i in out] == ["El Ibex abre plano a la espera de la Fed"]


def test_fetch_news_only_yfinance_alive_is_failure(monkeypatch) -> None:
    monkeypatch.setattr(news, "_http_get", FeedHTTP({"http": ConnectionError("sin red")}))
    with pytest.raises(news.NewsFetchError):
        news.fetch_news(["SAN.MC", "AAPL"], rss_feeds=FEEDS)
