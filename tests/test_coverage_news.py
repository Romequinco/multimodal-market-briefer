"""Cobertura de ramas de ``ingest.news`` sin red: lectura HTTP acotada, fechas raras, cortocircuito
de la API de noticias de yfinance, caídas de Bing/Google News, caché incompatible y muestras mal
formadas."""

from __future__ import annotations

import json
import sys
import time
import types
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from briefer.ingest import cache, news
from briefer.schemas import NewsItem


class _FakeResp:
    def __init__(self, chunks: list[bytes], status_error: Exception | None = None) -> None:
        self.chunks = chunks
        self.status_error = status_error
        self.read = 0

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_error:
            raise self.status_error

    def iter_content(self, chunk_size: int = 0):
        for chunk in self.chunks:
            self.read += 1
            yield chunk


def _fake_requests(resp: _FakeResp) -> types.ModuleType:
    mod = types.ModuleType("requests")
    mod.get = lambda url, **kw: resp  # type: ignore[attr-defined]
    return mod


def test_http_get_truncates_big_feeds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    resp = _FakeResp([b"a" * 6, b"b" * 6, b"c" * 6])
    monkeypatch.setitem(sys.modules, "requests", _fake_requests(resp))
    monkeypatch.setattr(news, "MAX_FEED_BYTES", 10)
    with caplog.at_level("WARNING", logger="briefer.ingest.news"):
        assert news._http_get("https://feeds.example/rss") == b"a" * 6 + b"b" * 6
    assert resp.read == 2 and any("truncada" in r.getMessage() for r in caplog.records)


def test_http_get_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResp([], status_error=RuntimeError("403 Forbidden"))
    monkeypatch.setitem(sys.modules, "requests", _fake_requests(resp))
    with pytest.raises(RuntimeError, match="403"):
        news._http_get("https://feeds.example/rss")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 8, 0, tzinfo=UTC)),
        ("1759651200000", datetime(2025, 10, 5, 8, 0, tzinfo=UTC)),  # epoch en ms
        ("2026-10-05T08:00:00Z", datetime(2026, 10, 5, 8, 0, tzinfo=UTC)),
        ("2026-10-05T08:00:00", datetime(2026, 10, 5, 8, 0, tzinfo=UTC)),
        ("ayer por la tarde", None),
        (10**20, None),  # fuera de rango
        ([1, 2], None),
        ("", None),
    ],
)
def test_parse_datetime_variants(value: object, expected: datetime | None) -> None:
    assert news._parse_datetime(value) == expected


def test_parse_yfinance_item_rejects_non_dicts() -> None:
    assert news.parse_yfinance_item(["no", "dict"], "SAN.MC") is None  # type: ignore[arg-type]


# ── cortocircuito de yfinance ─────────────────────────────────────────────────────


def test_yf_news_state_resets_on_new_day_and_reads_cache() -> None:
    news._yf_news.update(day=date.today() - timedelta(days=1), off=True)
    assert not news._yf_news_disabled()  # nuevo día: se vuelve a intentar
    cache.write_cache("news-yfinance", "disabled", True)
    assert news._yf_news_disabled() and news._yf_news["off"]


def _yfinance(get_news) -> types.ModuleType:
    mod = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def get_news(self, count: int = 10):
            return get_news(self.symbol)

    mod.Ticker = Ticker  # type: ignore[attr-defined]
    return mod


def test_yfinance_errors_count_towards_shortcircuit_and_fall_back_to_rss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(symbol: str):
        raise RuntimeError("404 Not Found")

    monkeypatch.setitem(sys.modules, "yfinance", _yfinance(boom))
    rss_calls: list[str] = []

    def rss(ticker: str, max_items: int) -> list[NewsItem]:
        rss_calls.append(ticker)
        return []

    monkeypatch.setattr(news, "_yahoo_rss_news", rss)
    for ticker in ("A", "B", "C"):
        assert news._yahoo_news(ticker, 5) == []
    assert rss_calls == ["A", "B", "C"]
    assert news._yf_news["off"] and cache.read_cache("news-yfinance", "disabled") is True
    assert news._yfinance_lib_news("D", 5) == []  # desactivado: ni se llama


# ── fuentes que fallan y cachés ───────────────────────────────────────────────────


def test_bing_and_google_failures_return_empty(monkeypatch: pytest.MonkeyPatch,
                                               caplog: pytest.LogCaptureFixture) -> None:
    def down(*_a, **_k):
        raise ConnectionError("sin red")

    monkeypatch.setattr(news, "_bing_news", down)
    monkeypatch.setattr(news, "_google_news", down)
    with caplog.at_level("WARNING", logger="briefer.ingest.news"):
        assert news.fetch_bing_news("santander") == []
        assert news.fetch_google_news("santander") == []
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "Bing News falló para SAN.MC" in messages and "Google News falló para SAN.MC" in messages


def test_cached_source_ignores_incompatible_cache() -> None:
    ck = cache.cache_key("bing", "SAN.MC")
    cache.write_cache("news-bing", ck, [{"titulo": "esquema antiguo"}])
    fresh = [NewsItem(id="n-1", title="T", summary="", source="M", url="https://m.es/1",
                      published_at=datetime.now(UTC), tickers=["SAN.MC"])]
    items, from_cache = news._cached_source("bing", "SAN.MC", lambda: fresh, use_cache=True)
    assert items == fresh and from_cache is False
    items, from_cache = news._cached_source("bing", "SAN.MC", lambda: [], use_cache=True)
    assert from_cache is True and items == fresh  # ahora sí, la caché nueva


def test_load_sample_news_rejects_bad_files(tmp_path: Path) -> None:
    obj = tmp_path / "obj.json"
    obj.write_text(json.dumps({"noticias": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="debe contener una lista"):
        news.load_sample_news(obj)
    broken = tmp_path / "roto.json"
    broken.write_text("[{", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON de noticias no válido"):
        news.load_sample_news(broken)


def test_parse_feed_drops_summary_that_repeats_title() -> None:
    now = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    rss = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Medio</title>
    <item><title>Santander gana más</title><link>https://medio.es/a</link>
    <description>Santander gana más</description><pubDate>{now}</pubDate></item>
    <item><title>Sin enlace</title></item>
    </channel></rss>"""
    (item,) = news.parse_feed(rss, "https://medio.es/rss")
    assert item.summary == "" and item.source == "Medio"
