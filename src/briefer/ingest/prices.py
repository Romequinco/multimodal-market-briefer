"""Precios y variaciones con yfinance (o sintéticos para el modo offline).

Carril A. Salida: ``list[PriceSnapshot]`` con último precio, variación diaria (%) e
histórico corto (para ``media.charts``).
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, timedelta

from briefer.ingest.tickers import normalize_ticker
from briefer.schemas import PriceSnapshot


def get_price_snapshot(ticker: str, period: str = "1mo") -> PriceSnapshot:
    """Snapshot de un ticker."""
    # TODO:
    # 1. import yfinance as yf; hist = yf.Ticker(ticker).history(period=period, interval="1d").
    # 2. last = hist["Close"].iloc[-1]; prev = hist["Close"].iloc[-2];
    #    change_pct = (last / prev - 1) * 100.
    # 3. currency = yf.Ticker(ticker).fast_info.get("currency") o currency_for(ticker).
    # 4. history = [(idx.date(), float(close)) for idx, close in hist["Close"].items()].
    # Casos borde: ticker inválido o mercado sin datos (hist vacío) -> ValueError claro;
    # festivos; un solo día de histórico (change_pct = 0.0).
    raise NotImplementedError("get_price_snapshot: pendiente (carril A, D1: requiere red)")


def get_price_snapshots(tickers: list[str], period: str = "1mo") -> list[PriceSnapshot]:
    """Snapshots de varios tickers; los que fallen se omiten con aviso (no rompen el briefing)."""
    # TODO: yf.download(tickers, period=period, group_by="ticker") en una sola llamada es
    # más rápido que uno a uno; capturar errores por ticker y log.warning.
    raise NotImplementedError("get_price_snapshots: pendiente (carril A, D1: requiere red)")


def currency_for(ticker: str) -> str:
    """Divisa por sufijo de mercado: ``.MC`` (Bolsa de Madrid) e ``^IBEX`` -> EUR; resto -> USD."""
    t = ticker.upper()
    return "EUR" if t.endswith(".MC") or t == "^IBEX" else "USD"


def _ticker_seed(ticker: str, seed: int) -> int:
    """Semilla estable por ticker (``hash()`` de Python cambia entre procesos; md5 no)."""
    digest = hashlib.md5(ticker.upper().encode("utf-8")).hexdigest()
    return int(digest[:12], 16) + seed


def _business_days(end: date, days: int) -> list[date]:
    """Días hábiles (lunes-viernes) en la ventana ``(end - days, end]``, en orden ascendente."""
    start = end - timedelta(days=days)
    out: list[date] = []
    current = end
    while current > start:
        if current.weekday() < 5:
            out.append(current)
        current -= timedelta(days=1)
    return out[::-1]


def synthetic_snapshots(
    tickers: list[str], days: int = 30, seed: int = 0, end: date | None = None
) -> list[PriceSnapshot]:
    """Precios sintéticos deterministas (modo demo offline / tests). Son ficticios.

    Cada ticker tiene su propia semilla (md5 del ticker + ``seed``): el mismo ticker da siempre la
    misma serie, independientemente del resto de la lista. Paseo aleatorio geométrico con
    volatilidad diaria ~1,5 % desde un precio inicial plausible.

    Args:
        tickers: tickers (se normalizan con ``ingest.tickers.normalize_ticker``; sin repetir).
        days: ventana en días naturales hacia atrás (30 -> ~22 sesiones hábiles).
        seed: semilla global adicional.
        end: última sesión (por defecto hoy; si cae en fin de semana, el viernes anterior).

    Returns:
        Un ``PriceSnapshot`` por ticker con ``history`` ascendente, ``last`` = último cierre y
        ``change_pct`` = variación del último cierre frente al anterior (en %).
    """
    end = end or date.today()
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    sessions = _business_days(end, max(days, 2))
    if len(sessions) < 2:  # ventana mínima para poder calcular la variación
        sessions = _business_days(end, 4)

    snapshots: list[PriceSnapshot] = []
    for ticker in dict.fromkeys(normalize_ticker(t) for t in tickers if str(t).strip()):
        rng = random.Random(_ticker_seed(ticker, seed))
        if ticker.startswith("^"):
            price = rng.uniform(5_000, 12_000)  # nivel de índice
        else:
            price = rng.choice([rng.uniform(3, 30), rng.uniform(30, 120), rng.uniform(120, 600)])
        drift = rng.uniform(-0.002, 0.002)
        history: list[tuple[date, float]] = []
        for day in sessions:
            price *= math.exp(rng.gauss(drift, 0.015))
            history.append((day, round(price, 2)))
        last, prev = history[-1][1], history[-2][1]
        snapshots.append(
            PriceSnapshot(
                ticker=ticker,
                last=last,
                change_pct=round((last / prev - 1) * 100, 2),
                currency=currency_for(ticker),
                history=history,
            )
        )
    return snapshots
