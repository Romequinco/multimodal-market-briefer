"""Precios y variaciones con yfinance (o sintéticos para el modo offline).

Carril A. Salida: ``list[PriceSnapshot]`` con último precio, variación diaria (%) e
histórico corto (para ``media.charts``).
"""

from __future__ import annotations

from briefer.schemas import PriceSnapshot


def get_price_snapshot(ticker: str, period: str = "1mo") -> PriceSnapshot:
    """Snapshot de un ticker."""
    # TODO:
    # 1. import yfinance as yf; hist = yf.Ticker(ticker).history(period=period, interval="1d").
    # 2. last = hist["Close"].iloc[-1]; prev = hist["Close"].iloc[-2];
    #    change_pct = (last / prev - 1) * 100.
    # 3. currency = yf.Ticker(ticker).fast_info.get("currency", "EUR" si termina en .MC).
    # 4. history = [(idx.date(), float(close)) for idx, close in hist["Close"].items()].
    # Casos borde: ticker inválido o mercado sin datos (hist vacío) -> ValueError claro;
    # festivos; un solo día de histórico (change_pct = 0.0).
    raise NotImplementedError("get_price_snapshot: pendiente (carril A)")


def get_price_snapshots(tickers: list[str], period: str = "1mo") -> list[PriceSnapshot]:
    """Snapshots de varios tickers; los que fallen se omiten con aviso (no rompen el briefing)."""
    # TODO: yf.download(tickers, period=period, group_by="ticker") en una sola llamada es
    # más rápido que uno a uno; capturar errores por ticker y log.warning.
    raise NotImplementedError("get_price_snapshots: pendiente (carril A)")


def synthetic_snapshots(tickers: list[str], days: int = 30, seed: int = 0) -> list[PriceSnapshot]:
    """Precios sintéticos deterministas (modo demo offline / tests). Marcar como ficticios."""
    # TODO: random.Random(seed + hash estable del ticker); paseo aleatorio desde 100;
    # fechas hábiles hacia atrás desde hoy; currency "EUR" para .MC y "USD" para el resto.
    raise NotImplementedError("synthetic_snapshots: pendiente (carril A)")
