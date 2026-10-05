"""Tests contra las fuentes reales (Google News, Yahoo, prensa, yfinance). Requieren red.

Excluidos por defecto (``addopts = -m "not live"`` en ``pyproject.toml``); se ejecutan con
``python -m pytest -m live tests/test_ingest_live.py``. No usan claves ni tienen coste. Usan la
caché temporal del ``conftest`` (no tocan ``data/cache``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from briefer.ingest import news, prices

pytestmark = pytest.mark.live

TICKERS = ["SAN.MC", "ITX.MC", "AAPL"]


def test_live_fetch_news_spanish_and_cited() -> None:
    items = news.fetch_news(TICKERS, max_items=20, use_cache=False)
    assert len(items) >= 5
    assert all(i.source and i.url.startswith("http") for i in items)
    assert all(i.published_at.tzinfo is not None for i in items)
    assert any(i.language == "es" for i in items)
    for t in TICKERS:
        assert any(t in i.tickers for i in items), f"sin noticias para {t}"
    oldest_allowed = datetime.now(UTC) - timedelta(days=max(news.WINDOWS_HOURS) / 24 + 1)
    assert all(i.published_at >= oldest_allowed for i in items)


def test_live_google_news_per_company() -> None:
    items = news.fetch_google_news("ITX.MC", max_items=10)
    assert len(items) >= 3
    assert all(i.tickers == ["ITX.MC"] and i.language == "es" for i in items)


def test_live_price_snapshots_us_and_mc() -> None:
    snaps = prices.get_price_snapshots(["SAN.MC", "AAPL", "NOEXISTE123"], use_cache=False)
    by_ticker = {s.ticker: s for s in snaps}
    assert set(by_ticker) == {"SAN.MC", "AAPL"}
    assert by_ticker["SAN.MC"].currency == "EUR" and by_ticker["AAPL"].currency == "USD"
    for snap in snaps:
        assert snap.last > 0 and len(snap.history) >= 10
        assert abs(snap.change_pct) < 50
