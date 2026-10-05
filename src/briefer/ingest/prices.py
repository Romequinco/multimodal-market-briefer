"""Precios y variaciones con yfinance (o sintéticos para el modo offline).

Carril A. Salida: ``list[PriceSnapshot]`` con último precio, variación diaria (%) e
histórico corto (para ``media.charts``).

Modo real: una sola descarga en lote (``yf.download``) para todos los tickers que no estén en la
caché del día (``settings.cache_path``, ver ``ingest.cache``); la divisa se pide a yfinance
(``fast_info``, con espera máxima ``CURRENCY_TIMEOUT``) y, si no la da, se deduce con
``currency_for``. Mercado cerrado o fin de semana: ``last`` es el último cierre disponible y
``change_pct`` su variación frente al cierre anterior (las filas sin cierre, p. ej. la sesión de
hoy antes de la apertura, se descartan). Un ticker sin datos se omite con
aviso; nunca se rellena con precios sintéticos.
"""

from __future__ import annotations

import hashlib
import math
import random
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from typing import Any

from briefer.ingest import cache
from briefer.ingest.tickers import normalize_ticker
from briefer.logging_utils import get_logger
from briefer.schemas import PriceSnapshot

log = get_logger("ingest.prices")

#: Timeout (s) de la descarga de yfinance.
DOWNLOAD_TIMEOUT = 10
#: Espera máxima (s) para la divisa de yfinance (``fast_info`` no tiene timeout propio); si no
#: llega, se deduce con ``currency_for``.
CURRENCY_TIMEOUT = 5.0
#: Si el último cierre tiene más de estos días se avisa en el log (valor suspendido o excluido).
STALE_DAYS = 7


class PriceFetchError(RuntimeError):
    """No se ha podido obtener el precio de ninguno de los tickers pedidos."""


def _close_series(df: Any, ticker: str) -> Any | None:
    """Serie de cierres (``Close``) de ``ticker`` en un DataFrame de yfinance, sin NaN ni ceros.

    Soporta columnas planas (un ticker, yfinance antiguo) y ``MultiIndex`` en cualquier orden
    (``(Ticker, Price)`` con ``group_by="ticker"`` o ``(Price, Ticker)`` por defecto).
    """
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return None
    sub = df
    if isinstance(df.columns, pd.MultiIndex):
        for level in range(df.columns.nlevels):
            if ticker in df.columns.get_level_values(level):
                sub = df.xs(ticker, axis=1, level=level)
                break
        else:
            return None
    column = next((c for c in ("Close", "Adj Close", "close") if c in sub.columns), None)
    if column is None:
        return None
    series = sub[column]
    if isinstance(series, pd.DataFrame):  # columnas duplicadas
        series = series.iloc[:, 0]
    series = pd.to_numeric(series, errors="coerce").dropna()
    series = series[series > 0]
    return series if len(series) else None


def snapshot_from_closes(ticker: str, closes: Any, currency: str) -> PriceSnapshot:
    """Construye un ``PriceSnapshot`` desde una serie de cierres indexada por fecha.

    ``change_pct`` = último cierre frente al anterior (en %); con un solo día, ``0.0``.
    Si hay varias filas con la misma fecha (barra intradía duplicada), se queda la última.

    Raises:
        ValueError: si no hay ningún cierre válido.
    """
    by_day: dict[date, float] = {}
    for idx, value in closes.items():
        day = idx.date() if isinstance(idx, datetime) or hasattr(idx, "date") else idx
        if isinstance(day, datetime):
            day = day.date()
        by_day[day] = round(float(value), 4)
    if not by_day:
        raise ValueError(f"Sin cierres válidos para {ticker}")
    history = sorted(by_day.items())
    last = history[-1][1]
    change = round((last / history[-2][1] - 1) * 100, 2) if len(history) >= 2 else 0.0
    return PriceSnapshot(ticker=ticker, last=last, change_pct=change, currency=currency, history=history)


def _download(tickers: list[str], period: str) -> Any:
    """Descarga en lote de cierres diarios (una petición para todos los tickers)."""
    import yfinance as yf

    return yf.download(
        tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
        timeout=DOWNLOAD_TIMEOUT,
    )


def _history(ticker: str, period: str) -> Any:
    """Respaldo uno a uno: ``yf.Ticker(t).history`` (si la descarga en lote falla entera)."""
    import yfinance as yf

    return yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)


def _currency(ticker: str) -> str:
    """Divisa que reporta yfinance (``fast_info``); si no hay, ``currency_for``."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).fast_info
        value = info.get("currency") if hasattr(info, "get") else info["currency"]
        if value and isinstance(value, str):
            return value.strip()
    except Exception as exc:  # noqa: BLE001 - red, 404, campo ausente
        log.debug("Divisa de %s no disponible en yfinance (%s); se deduce", ticker, exc)
    return currency_for(ticker)


def get_price_snapshots(
    tickers: list[str], period: str = "1mo", *, use_cache: bool = True
) -> list[PriceSnapshot]:
    """Snapshots de varios tickers; los que no tengan datos se omiten con aviso.

    Lee primero la caché del día (clave: ticker + periodo + fecha) y descarga en una sola
    llamada solo los que falten; si la descarga en lote falla entera, prueba ticker a ticker.

    Args:
        tickers: tickers (se normalizan con ``normalize_ticker``; sin repetir).
        period: histórico de yfinance (``"1mo"``, ``"3mo"``…).
        use_cache: ``False`` ignora la caché del día (vuelve a descargar y la refresca).

    Returns:
        Snapshots en el orden de ``tickers`` (solo los que tienen datos).

    Raises:
        PriceFetchError: si se pidieron tickers y no se obtuvo precio de ninguno.
    """
    wanted = list(dict.fromkeys(normalize_ticker(t) for t in tickers if str(t).strip()))
    found: dict[str, PriceSnapshot] = {}
    for t in wanted:
        if not use_cache:
            break
        cached = cache.read_cache("prices", cache.cache_key(t, period))
        if cached:
            try:
                found[t] = PriceSnapshot.model_validate(cached)
            except Exception as exc:  # noqa: BLE001 - caché de otra versión del schema
                log.warning("Caché de precios incompatible para %s: %s", t, exc)

    missing = [t for t in wanted if t not in found]
    if missing:
        closes: dict[str, Any] = {}
        try:
            df = _download(missing, period)
            closes = {t: _close_series(df, t) for t in missing}
        except Exception as exc:  # noqa: BLE001 - red, rate limit, cambios de yfinance
            log.warning("Descarga en lote de precios falló (%s); se prueba uno a uno", exc)
            for t in missing:
                try:
                    closes[t] = _close_series(_history(t, period), t)
                except Exception as exc_t:  # noqa: BLE001
                    log.warning("Sin precios para %s: %s", t, exc_t)
                    closes[t] = None
        with_data = [t for t in missing if closes.get(t) is not None]
        for t in missing:
            if t not in with_data:
                log.warning("Ticker sin datos de precio en yfinance: %s (se omite)", t)
        if with_data:
            pool = ThreadPoolExecutor(max_workers=min(8, len(with_data)), thread_name_prefix="currency")
            try:
                futures = {t: pool.submit(_currency, t) for t in with_data}
                done, _pending = wait(futures.values(), timeout=CURRENCY_TIMEOUT)
                currencies = {t: f.result() if f in done else currency_for(t) for t, f in futures.items()}
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            for t in with_data:
                try:
                    snap = snapshot_from_closes(t, closes[t], currencies[t])
                except ValueError as exc:
                    log.warning("%s; se omite", exc)
                    continue
                found[t] = snap
                last_day = snap.history[-1][0] if snap.history else None
                if last_day and (date.today() - last_day).days > STALE_DAYS:
                    log.warning("Último cierre de %s es del %s: dato antiguo (¿suspendido?)", t, last_day)
                cache.write_cache("prices", cache.cache_key(t, period), snap.model_dump(mode="json"))

    if wanted and not found:
        raise PriceFetchError(
            f"No se pudo obtener el precio de ninguno de {', '.join(wanted)} "
            "(¿sin conexión, tickers inválidos o límite de Yahoo?)"
        )
    return [found[t] for t in wanted if t in found]


def get_price_snapshot(ticker: str, period: str = "1mo", *, use_cache: bool = True) -> PriceSnapshot:
    """Snapshot de un ticker (último cierre, variación diaria en % e histórico de ``period``).

    Raises:
        ValueError: ticker inválido o sin datos en yfinance.
    """
    t = normalize_ticker(ticker)
    try:
        snaps = get_price_snapshots([t], period, use_cache=use_cache)
    except PriceFetchError as exc:
        raise ValueError(f"Sin datos de precio para {t}") from exc
    return snaps[0]


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
