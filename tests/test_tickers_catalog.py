"""Catálogo ampliado de activos y buscador (``ingest.tickers`` + ``pipeline.search_assets``), sin red."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from briefer import pipeline
from briefer.ingest import news, tickers


def test_catalog_loads_csv_and_keeps_curated_universe() -> None:
    assert len(tickers.CATALOG) >= 150
    for t, info in tickers.TICKER_UNIVERSE.items():
        assert tickers.CATALOG[t]["aliases"] == info["aliases"], "el universo curado conserva sus alias"
    assert sum(1 for m in tickers.CATALOG_MARKET.values() if m == "IBEX") == 35
    for t in ("KO", "BTC-USD", "GC=F", "^GDAXI", "SAB.MC", "ASML.AS"):
        assert t in tickers.CATALOG, t
    # El universo que etiqueta todas las noticias no crece (falsos positivos).
    assert 15 <= len(tickers.TICKER_UNIVERSE) <= 25


def test_catalog_csv_is_well_formed() -> None:
    import csv

    with tickers.CATALOG_FILE.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows and set(rows[0]) == {"ticker", "name", "aliases", "market"}
    symbols = [r["ticker"] for r in rows]
    assert len(symbols) == len(set(symbols)), "tickers duplicados en el catálogo"
    assert all(r["name"].strip() and r["market"] for r in rows)


@pytest.mark.parametrize("query,expected", [
    ("santa", "SAN.MC"), ("coca", "KO"), ("bitcoin", "BTC-USD"), ("sabadell", "SAB.MC"),
    ("TELEFONICA", "TEF.MC"), ("asml", "ASML.AS"), ("dax", "^GDAXI"),
])
def test_search_catalog_finds_by_name_alias_or_ticker(query: str, expected: str) -> None:
    found = [m.ticker for m in tickers.search_catalog(query)]
    assert expected in found[:5], (query, found)


def test_search_catalog_ranks_exact_ticker_first_and_handles_empty() -> None:
    assert tickers.search_catalog("KO")[0].ticker == "KO"
    assert tickers.search_catalog("   ") == []
    assert tickers.search_catalog("zzzzqqq") == []


def test_normalize_and_names_use_catalog() -> None:
    assert tickers.normalize_ticker("Banco Sabadell") == "SAB.MC"
    assert tickers.normalize_ticker("santander") == "SAN.MC"  # el universo curado manda en las raíces
    assert tickers.ticker_name("KO").lower().startswith("coca")
    assert tickers.ticker_name("XYZ.MC") == "XYZ"
    assert news.google_news_query("SAB.MC").startswith('"Banco Sabadell"')


@pytest.fixture
def fake_yahoo(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    class FakeSearch:
        def __init__(self, query, **_kw):
            calls.append(query)
            self.quotes = [
                {"symbol": "RYA.IR", "shortname": "Ryanair Holdings plc", "quoteType": "EQUITY", "exchDisp": "Irish"},
                {"symbol": "RYAAY", "shortname": "Ryanair ADR", "quoteType": "EQUITY", "exchDisp": "NASDAQ"},
                {"symbol": "RY00=F", "shortname": "Futuro raro", "quoteType": "FUTURE"},
                {"symbol": "KO", "shortname": "Coca-Cola", "quoteType": "EQUITY", "exchDisp": "NYSE"},
            ]

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Search=FakeSearch))
    return calls


def test_search_assets_offline_does_not_touch_yahoo(fake_yahoo: list[str]) -> None:
    assert [m.ticker for m in pipeline.search_assets("coca")][:1] == ["KO"]
    assert fake_yahoo == []


def test_search_assets_online_adds_yahoo_without_duplicates_or_futures(fake_yahoo: list[str]) -> None:
    found = pipeline.search_assets("ryanair", online=True)
    symbols = [m.ticker for m in found]
    assert "RYA.IR" in symbols and "RYAAY" in symbols
    assert "RY00=F" not in symbols, "los futuros sueltos de Yahoo no se ofrecen"
    assert symbols.count("KO") <= 1
    assert all(m.source == "Yahoo Finance" for m in found if m.ticker.startswith("RYA"))


def test_search_online_error_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_kw):
        raise ConnectionError("sin red")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Search=boom))
    with pytest.raises(RuntimeError, match="Yahoo Finance"):
        pipeline.search_assets("lo que sea", online=True)


def test_remember_asset_registers_once_and_feeds_news_query() -> None:
    try:
        assert pipeline.remember_asset("rya.ir", "Ryanair Holdings", "Irish") == "RYA.IR"
        assert tickers.ticker_name("RYA.IR") == "Ryanair Holdings"
        assert tickers.normalize_ticker("ryanair holdings") == "RYA.IR"
        assert news.google_news_query("RYA.IR").startswith('"Ryanair Holdings"')
        pipeline.remember_asset("SAN.MC", "Otro nombre")  # nunca sobrescribe lo conocido
        assert tickers.ticker_name("SAN.MC") == "Banco Santander"
        with pytest.raises(ValueError):
            pipeline.remember_asset("  ", "x")
    finally:
        tickers.CATALOG.pop("RYA.IR", None)
        tickers._lookup.cache_clear()
