"""Tests del camino real del carril A (noticias y precios) SIN red.

Se sustituyen ``news._http_get`` (RSS de Google News, Bing News, Yahoo y prensa) y el módulo
``yfinance`` por dobles con respuestas realistas (formatos antiguo y nuevo de yfinance). La red de
``ingest.article_meta`` (enriquecimiento con ``og:description``) queda cortada por defecto: sus
tests con páginas de *fixture* están en ``tests/test_ingest_news_quality.py``. La caché va a un
directorio temporal (``conftest._mock_env`` fija ``BRIEFER_CACHE_DIR``).
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from briefer.ingest import article_meta, news, prices

NOW = datetime.now(timezone.utc)


def _rfc822(hours_ago: float) -> str:
    return format_datetime(NOW - timedelta(hours=hours_ago))


# ── fixtures de red ────────────────────────────────────────────────────────────────


def google_rss(entries: list[tuple[str, str, str, float]]) -> bytes:
    """RSS con la forma real de Google News: título «… - Medio», <source> y resumen = enlace."""
    items = "".join(
        f"""<item><title>{title} - {source}</title>
<link>https://news.google.com/rss/articles/{slug}?oc=5</link>
<guid isPermaLink="false">{slug}</guid>
<pubDate>{_rfc822(hours)}</pubDate>
<description>&lt;a href="https://news.google.com/rss/articles/{slug}?oc=5" target="_blank"&gt;{title}&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;{source}&lt;/font&gt;</description>
<source url="https://www.{slug}.es">{source}</source></item>"""
        for title, source, slug, hours in entries
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><generator>NFE/5.0</generator>
<title>"query" - Google News</title><link>https://news.google.com/</link><language>es</language>
{items}</channel></rss>""".encode()


GOOGLE_BY_NAME = {
    "Banco Santander": google_rss(
        [
            ("Banco Santander rebota en bolsa tras el soporte de 11,60 euros", "El Español", "san1", 3),
            ("Análisis de BBVA, Iberdrola, Inditex y Banco Santander", "Investing.com España", "multi", 5),
            ("JP Morgan revisa su precio objetivo para Santander", "Estrategias de Inversión", "san2", 20),
            ("Santander: noticia antigua de hace diez días", "Cinco Días", "sanold", 240),
        ]
    ),
    "Inditex": google_rss(
        [
            ("Análisis de BBVA, Iberdrola, Inditex y Banco Santander", "Investing.com España", "multi", 5),
            ("Inditex reactiva su calendario de dividendos", "Expansión", "itx1", 10),
            ("Inditex gana cuota frente a Shein", "Economía Digital", "itx2", 30),
        ]
    ),
    "Apple": google_rss([("Apple sube en Wall Street por la IA", "Bolsamanía", "aapl1", 8)]),
}

YAHOO_RSS = f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Yahoo! Finance: AAPL News</title><language>en-US</language>
<item><title>Apple's AI advantage faces a privacy challenge</title>
<link>https://finance.yahoo.com/news/apple-ai-privacy-180300.html</link>
<description>The race to make AI agents useful complicates one of Apple&#8217;s promises.</description>
<pubDate>{_rfc822(12)}</pubDate><guid isPermaLink="false">apple-ai-privacy</guid></item>
</channel></rss>""".encode()

MARKET_RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Mercados // expansion</title><language>es-ES</language>
<item><title>El Ibex duda con la deuda y el euro</title>
<link>https://www.expansion.com/mercados/ibex-duda.html</link>
<description><![CDATA[<p>La semana comienza con <b>varios frentes</b> abiertos.&nbsp;El euro cae a m&iacute;nimos.</p><img src="x.jpg"/>]]></description>
<pubDate>{_rfc822(2)}</pubDate></item>
<item><title>Iberdrola cierra una alianza para vender seguros</title>
<link>https://www.expansion.com/empresas/iberdrola-seguros.html</link>
<description>Acuerdo comercial de la eléctrica.</description>
<pubDate>{_rfc822(6)}</pubDate></item>
</channel></rss>""".encode()

BING_EMPTY = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Bing</title></channel></rss>"""

YF_NEWS_OLD = [
    {
        "uuid": "a1",
        "title": "Apple shares rise after record iPhone sales",
        "publisher": "Reuters",
        "link": "https://finance.yahoo.com/news/apple-shares-rise.html",
        "providerPublishTime": int((NOW - timedelta(hours=4)).timestamp()),
        "type": "STORY",
        "relatedTickers": ["AAPL"],
    }
]
YF_NEWS_NEW = [
    {
        "id": "b2",
        "content": {
            "id": "b2",
            "contentType": "STORY",
            "title": "Apple &amp; suppliers: what to watch this week",
            "summary": "<p>Suppliers are <b>ramping</b> production.</p>",
            "pubDate": (NOW - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "provider": {"displayName": "Bloomberg", "url": "https://bloomberg.com"},
            "canonicalUrl": {"url": "https://finance.yahoo.com/news/apple-suppliers.html", "lang": "en-US"},
            "clickThroughUrl": None,
        },
    },
    {"id": "ad", "content": {"title": "Sin URL: se descarta"}},
]


class FakeHTTP:
    """Sustituye ``news._http_get``: enruta por host y cuenta llamadas."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail or set()

    def __call__(self, url: str, timeout: float = news.HTTP_TIMEOUT) -> bytes:
        self.calls.append(url)
        host = urlsplit(url).netloc
        if any(f in url for f in self.fail):
            raise ConnectionError(f"caído: {host}")
        if host == "news.google.com":
            q = parse_qs(urlsplit(url).query)["q"][0]
            assert parse_qs(urlsplit(url).query)["hl"] == ["es"]
            for name, body in GOOGLE_BY_NAME.items():
                if f'"{name}"' in q:
                    return body
            return google_rss([])
        if host == "www.bing.com":
            return BING_EMPTY
        if host == "feeds.finance.yahoo.com":
            return YAHOO_RSS if "AAPL" in url else YAHOO_RSS.replace(b"<item>", b"<x>").replace(b"</item>", b"</x>")
        if "expansion" in host:
            return MARKET_RSS
        raise AssertionError(f"URL inesperada en test: {url}")


def fake_yfinance(
    news_by_ticker: dict[str, list] | None = None,
    frame: pd.DataFrame | None = None,
    currencies: dict[str, str] | None = None,
    download_error: Exception | None = None,
    histories: dict[str, pd.DataFrame] | None = None,
) -> types.ModuleType:
    """Módulo ``yfinance`` falso con ``Ticker`` (get_news, fast_info, history) y ``download``."""
    mod = types.ModuleType("yfinance")
    mod.calls = {"download": 0, "news": 0, "history": 0}  # type: ignore[attr-defined]

    class Ticker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def get_news(self, count: int = 10, tab: str = "news") -> list:
            mod.calls["news"] += 1
            return (news_by_ticker or {}).get(self.symbol, [])

        @property
        def fast_info(self) -> dict:
            if currencies is None or self.symbol not in currencies:
                raise KeyError("currency")
            return {"currency": currencies[self.symbol]}

        def history(self, **kwargs) -> pd.DataFrame:
            mod.calls["history"] += 1
            return (histories or {}).get(self.symbol, pd.DataFrame())

    def download(tickers, **kwargs) -> pd.DataFrame:
        mod.calls["download"] += 1
        if download_error is not None:
            raise download_error
        return frame if frame is not None else pd.DataFrame()

    mod.Ticker = Ticker  # type: ignore[attr-defined]
    mod.download = download  # type: ignore[attr-defined]
    return mod


def _no_network(*_a, **_k):
    raise ConnectionError("sin red en tests")


@pytest.fixture(autouse=True)
def _reset_news_state(monkeypatch: pytest.MonkeyPatch):
    news._reset_yf_news_state()
    article_meta._reset_robots_state()
    article_meta._reset_google_state()
    monkeypatch.setenv("BRIEFER_NEWS_RSS_FEEDS", "")
    # El enriquecimiento (URL final + og:description) nunca sale a la red en estos tests.
    monkeypatch.setattr(article_meta, "_http_fetch", _no_network)
    monkeypatch.setattr(article_meta, "_http_post", _no_network)
    yield


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> FakeHTTP:
    fake = FakeHTTP()
    monkeypatch.setattr(news, "_http_get", fake)
    return fake


@pytest.fixture
def yf_news(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    mod = fake_yfinance(news_by_ticker={"AAPL": YF_NEWS_NEW})
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return mod


FEEDS = ["https://e00-expansion.uecdn.es/rss/mercados.xml"]


# ── parseo ────────────────────────────────────────────────────────────────────────


def test_parse_yfinance_old_format() -> None:
    item = news.parse_yfinance_item(YF_NEWS_OLD[0], "AAPL")
    assert item is not None
    assert item.title == "Apple shares rise after record iPhone sales"
    assert item.source == "Reuters"
    assert item.url.endswith("apple-shares-rise.html")
    assert item.published_at.tzinfo is not None
    assert abs((item.published_at - (NOW - timedelta(hours=4))).total_seconds()) < 2
    assert item.tickers == ["AAPL"] and item.language == "en"
    assert item.id == news.news_id(item.url) and item.id.startswith("n-")


def test_parse_yfinance_new_format_and_invalid() -> None:
    item = news.parse_yfinance_item(YF_NEWS_NEW[0], "AAPL")
    assert item is not None
    assert item.title == "Apple & suppliers: what to watch this week"
    assert item.summary == "Suppliers are ramping production."
    assert item.source == "Bloomberg"
    assert item.url == "https://finance.yahoo.com/news/apple-suppliers.html"
    assert item.published_at.tzinfo is not None and item.language == "en"
    assert news.parse_yfinance_item(YF_NEWS_NEW[1], "AAPL") is None
    assert news.parse_yfinance_item("no es un dict", "AAPL") is None  # type: ignore[arg-type]
    # epoch en milisegundos y cadenas numéricas
    ms = {**YF_NEWS_OLD[0], "providerPublishTime": str(int(NOW.timestamp() * 1000))}
    assert news.parse_yfinance_item(ms, "AAPL").published_at.year == NOW.year


def test_parse_google_news_feed() -> None:
    items = news.parse_feed(GOOGLE_BY_NAME["Banco Santander"], "google")
    first = items[0]
    assert first.title == "Banco Santander rebota en bolsa tras el soporte de 11,60 euros"
    assert first.source == "El Español"
    assert first.summary == ""  # el «resumen» de Google solo repite el título
    assert first.url.startswith("https://news.google.com/rss/articles/")
    assert first.published_at.tzinfo is not None
    assert first.language == "es" and first.tickers == []
    assert len({i.id for i in items}) == len(items)


def test_parse_market_feed_cleans_html_and_language() -> None:
    items = news.parse_feed(MARKET_RSS, "expansion")
    assert items[0].summary == "La semana comienza con varios frentes abiertos. El euro cae a mínimos."
    assert items[0].source == "Mercados // expansion"
    assert items[0].language == "es"
    assert len(news.parse_feed(MARKET_RSS, max_items=1)) == 1


def test_parse_feed_invalid_raises() -> None:
    with pytest.raises(ValueError):
        news.parse_feed(b"<html><body>Error 503</body", "roto")


def test_clean_html_and_truncation() -> None:
    assert news.clean_html("<p>A &amp; B&nbsp;&nbsp;<br/>C</p>") == "A & B C"
    long = news.clean_html("palabra " * 200, max_chars=50)
    assert len(long) <= 50 and long.endswith("…")
    assert news.clean_html(None) == ""


def test_google_news_query_and_url() -> None:
    q = news.google_news_query("SAN.MC")
    assert q.startswith('"Banco Santander"') and "bolsa" in q
    assert news.google_news_query("XYZ.MC").startswith('"XYZ"')
    url = news.google_news_url(q)
    params = parse_qs(urlsplit(url).query)
    assert params["hl"] == ["es"] and params["gl"] == ["ES"] and params["ceid"] == ["ES:es"]
    assert params["q"][0].endswith("when:7d")


def test_fetch_rss_news_skips_broken_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHTTP(fail={"caido.example"})
    monkeypatch.setattr(news, "_http_get", fake)
    out = news.fetch_rss_news(["https://caido.example/rss", FEEDS[0]])
    assert [i.title for i in out][:1] == ["El Ibex duda con la deuda y el euro"]
    assert len(fake.calls) == 2


def test_fetch_yfinance_news_falls_back_to_yahoo_rss(http: FakeHTTP, monkeypatch) -> None:
    mod = fake_yfinance(news_by_ticker={})
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    out = news.fetch_yfinance_news("aapl")
    assert [i.source for i in out] == ["Yahoo Finance"]
    assert out[0].tickers == ["AAPL"] and out[0].language == "en"
    # cortocircuito: tras 3 tickers sin nada (y ningún éxito) no se vuelve a llamar hoy
    for t in ("NVDA", "MSFT", "TSLA"):
        news.fetch_yfinance_news(t)
    assert mod.calls["news"] == 3
    assert news.cache.read_cache("news-yfinance", "disabled") is True


def test_yfinance_breaker_not_tripped_after_success(monkeypatch, http: FakeHTTP) -> None:
    mod = fake_yfinance(news_by_ticker={"AAPL": YF_NEWS_OLD})
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    assert news.fetch_yfinance_news("AAPL")[0].source == "Reuters"
    for t in ("NVDA", "MSFT", "TSLA", "AMZN"):
        news.fetch_yfinance_news(t)
    assert mod.calls["news"] == 5


def test_fetch_yfinance_news_never_raises(monkeypatch) -> None:
    monkeypatch.setattr(news, "_http_get", FakeHTTP(fail={"yahoo"}))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance())
    assert news.fetch_yfinance_news("AAPL") == []


# ── fetch_news ────────────────────────────────────────────────────────────────────


def test_fetch_news_combines_dedupes_and_tags(http: FakeHTTP, yf_news) -> None:
    stats: dict = {}
    out = news.fetch_news(["SAN.MC", "itx.mc", "AAPL"], max_items=20, rss_feeds=FEEDS, stats_out=stats)
    titles = [i.title for i in out]
    # deduplicado: el análisis multi-valor aparece en las búsquedas de SAN.MC e ITX.MC
    assert titles.count("Análisis de BBVA, Iberdrola, Inditex y Banco Santander") == 1
    multi = next(i for i in out if i.title.startswith("Análisis de BBVA"))
    assert {"SAN.MC", "ITX.MC", "IBE.MC", "BBVA.MC"} <= set(multi.tickers)
    # ventana: lo de hace 10 días no entra
    assert not any("antigua" in t for t in titles)
    # yfinance (formato nuevo) + RSS de Yahoo + feed general (etiquetado por extract_tickers)
    assert "Apple & suppliers: what to watch this week" in titles
    assert "Apple's AI advantage faces a privacy challenge" in titles
    iberdrola = next(i for i in out if i.title.startswith("Iberdrola cierra"))
    assert iberdrola.tickers == ["IBE.MC"]
    # orden, zona horaria e ids
    dates = [i.published_at for i in out]
    assert dates == sorted(dates, reverse=True)
    assert all(d.tzinfo is not None for d in dates)
    assert len({i.id for i in out}) == len(out)
    assert all(i.source and i.url for i in out)
    fetch = stats["fetch"]
    assert fetch["google:SAN.MC"]["items"] == 4 and fetch["google:SAN.MC"]["error"] is None


def test_fetch_news_limits_per_ticker_and_total(http: FakeHTTP, yf_news) -> None:
    out = news.fetch_news(["SAN.MC", "ITX.MC", "AAPL"], max_items=4, rss_feeds=FEEDS, max_per_ticker=2)
    assert len(out) == 4
    for t in ("SAN.MC", "ITX.MC", "AAPL"):
        assert any(t in i.tickers for i in out), t  # el reparto llega a todos los tickers
    # español primero dentro de cada ticker: el primer AAPL elegido es el de Google News
    aapl = [i for i in out if "AAPL" in i.tickers]
    assert aapl[0].language == "es"


def test_fetch_news_survives_failing_sources(monkeypatch, yf_news) -> None:
    fake = FakeHTTP(fail={"news.google.com", "yahoo"})
    monkeypatch.setattr(news, "_http_get", fake)
    stats: dict = {}
    out = news.fetch_news(["SAN.MC", "AAPL"], rss_feeds=FEEDS, stats_out=stats)
    assert out  # el feed general y yfinance siguen funcionando
    assert stats["fetch"]["google:SAN.MC"]["error"].startswith("ConnectionError")


def test_fetch_news_all_sources_fail(monkeypatch) -> None:
    monkeypatch.setattr(news, "_http_get", FakeHTTP(fail={"http"}))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance())
    with pytest.raises(news.NewsFetchError, match="fuentes"):
        news.fetch_news(["SAN.MC"], rss_feeds=FEEDS)


def test_fetch_news_uses_daily_cache(http: FakeHTTP, yf_news) -> None:
    first = news.fetch_news(["SAN.MC", "AAPL"], rss_feeds=FEEDS)
    n_calls = len(http.calls)
    assert n_calls > 0
    stats: dict = {}
    second = news.fetch_news(["SAN.MC", "AAPL"], rss_feeds=FEEDS, stats_out=stats)
    assert len(http.calls) == n_calls  # sin red la segunda vez
    assert [i.id for i in second] == [i.id for i in first]
    assert all(v["cached"] for k, v in stats["fetch"].items() if not k.startswith("yfinance:"))
    news.fetch_news(["SAN.MC", "AAPL"], rss_feeds=FEEDS, use_cache=False)
    assert len(http.calls) == 2 * n_calls


def test_fetch_news_widens_window_and_respects_since(monkeypatch, http: FakeHTTP) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance())
    # titulares distintos (si solo cambiara un número, dedupe_news los fusionaría como casi idénticos)
    titles = ["Inditex abre su mayor tienda en Tokio", "Inditex sube un 2 % en bolsa", "Inditex reparte dividendo en noviembre"]
    old_only = google_rss([(title, "Medio", f"w{n}", 50 + n) for n, title in enumerate(titles)])
    monkeypatch.setitem(GOOGLE_BY_NAME, "Inditex", old_only)
    out = news.fetch_news(["ITX.MC"], rss_feeds=FEEDS)
    assert sum("ITX.MC" in i.tickers for i in out) == 3  # 48 h no basta -> se amplía a 72 h
    recent = news.fetch_news(["ITX.MC"], rss_feeds=FEEDS, since=NOW - timedelta(hours=24))
    assert not any("ITX.MC" in i.tickers for i in recent)
    naive = news.fetch_news(["ITX.MC"], rss_feeds=FEEDS, since=(NOW - timedelta(hours=24)).replace(tzinfo=None))
    assert [i.id for i in naive] == [i.id for i in recent]


def test_fetch_news_default_feeds_from_settings(monkeypatch, http: FakeHTTP) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance())
    monkeypatch.setattr(news, "DEFAULT_MARKET_FEEDS", tuple(FEEDS))
    out = news.fetch_news([], max_items=5)
    assert out and all("expansion" in i.url for i in out)


# ── precios ───────────────────────────────────────────────────────────────────────


def _frame(closes: dict[str, list[float | None]], days: int | None = None, layout: str = "ticker") -> pd.DataFrame:
    n = days or len(next(iter(closes.values())))
    index = pd.bdate_range(end="2026-10-05", periods=n)
    data = {}
    for t, values in closes.items():
        for field in ("Open", "Close", "Adj Close", "Volume"):
            key = (t, field) if layout == "ticker" else (field, t)
            data[key] = [v if field != "Volume" else 1000 for v in values]
    df = pd.DataFrame(data, index=index)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def test_price_snapshots_batch_multiindex(monkeypatch) -> None:
    frame = _frame({"SAN.MC": [11.0, 11.5, 12.0], "AAPL": [300.0, 330.0, 333.0], "BAD": [None, None, None]})
    mod = fake_yfinance(frame=frame, currencies={"SAN.MC": "EUR"})
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    snaps = prices.get_price_snapshots(["san.mc", "BAD", "AAPL"])
    assert [s.ticker for s in snaps] == ["SAN.MC", "AAPL"]  # BAD se omite, orden respetado
    san, aapl = snaps
    assert san.last == 12.0 and san.change_pct == round((12.0 / 11.5 - 1) * 100, 2)
    assert san.currency == "EUR"
    assert aapl.currency == "USD"  # fast_info sin divisa -> currency_for
    assert len(san.history) == 3 and san.history[0][0] < san.history[-1][0]
    assert mod.calls["download"] == 1


def test_price_snapshots_price_ticker_layout_and_single_row(monkeypatch) -> None:
    frame = _frame({"NVDA": [200.0]}, layout="price")
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance(frame=frame, currencies={"NVDA": "USD"}))
    snap = prices.get_price_snapshot("NVDA")
    assert snap.last == 200.0 and snap.change_pct == 0.0 and len(snap.history) == 1


def test_price_snapshots_flat_columns(monkeypatch) -> None:
    flat = pd.DataFrame({"Close": [10.0, 9.0]}, index=pd.bdate_range(end="2026-10-05", periods=2))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance(frame=flat))
    snap = prices.get_price_snapshot("ITX.MC")
    assert snap.change_pct == -10.0 and snap.currency == "EUR"


def test_price_snapshots_fallback_to_history(monkeypatch) -> None:
    hist = pd.DataFrame(
        {"Close": [5.0, 5.5]},
        index=pd.DatetimeIndex(["2026-10-02", "2026-10-05"]).tz_localize("Europe/Madrid"),
    )
    mod = fake_yfinance(download_error=RuntimeError("429 Too Many Requests"), histories={"IBE.MC": hist})
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    snaps = prices.get_price_snapshots(["IBE.MC", "AAPL"])
    assert [s.ticker for s in snaps] == ["IBE.MC"]
    assert snaps[0].change_pct == 10.0
    assert snaps[0].history[-1][0].isoformat() == "2026-10-05"
    assert mod.calls["history"] == 2


def test_price_snapshots_all_fail(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance(frame=pd.DataFrame()))
    with pytest.raises(prices.PriceFetchError):
        prices.get_price_snapshots(["XXXX"])
    with pytest.raises(ValueError, match="XXXX"):
        prices.get_price_snapshot("XXXX")
    assert prices.get_price_snapshots([]) == []


def test_price_snapshots_daily_cache(monkeypatch) -> None:
    mod = fake_yfinance(frame=_frame({"SAN.MC": [11.0, 12.0], "AAPL": [1.0, 2.0]}))
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    first = prices.get_price_snapshots(["SAN.MC", "AAPL"])
    second = prices.get_price_snapshots(["SAN.MC", "AAPL"])
    assert mod.calls["download"] == 1  # segunda vez desde la caché del día
    assert second == first
    prices.get_price_snapshots(["SAN.MC"], use_cache=False)
    assert mod.calls["download"] == 2


def test_tests_never_reach_the_network() -> None:
    """Guarda de ``conftest``: cualquier conexión fuera de localhost falla como «sin red»."""
    import socket

    with pytest.raises(ConnectionError, match="Red bloqueada"):
        socket.create_connection(("example.com", 80), timeout=1)
    with pytest.raises(OSError, match="Red bloqueada"):  # requests.ConnectionError es un OSError
        news._http_get("https://news.google.com/rss/search?q=x")  # el GET real tampoco sale
