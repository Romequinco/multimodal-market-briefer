"""Gráficos del día en PNG (matplotlib) a partir de los precios.

Carril C. Entrada: ``list[PriceSnapshot]`` (+ ``Portfolio`` opcional). Salida:
``list[ChartAsset]`` guardados en ``out_dir``. Se usan en la UI, el email y el vídeo.
"""

from __future__ import annotations

from pathlib import Path

from briefer.schemas import ChartAsset, Portfolio, PriceSnapshot


def make_price_chart(snapshot: PriceSnapshot, out_dir: Path) -> ChartAsset:
    """Línea de cotización del histórico de un ticker (kind="price_line")."""
    # TODO:
    # 1. import matplotlib; matplotlib.use("Agg") (sin pantalla; necesario en Docker/Streamlit).
    # 2. fechas, cierres = zip(*snapshot.history); plot con título "<ticker> · <+x,xx %>"
    #    (verde si sube, rojo si baja); formato de números español si se puede.
    # 3. Guardar en out_dir / f"{ticker_seguro}_price.png" (dpi=150, bbox_inches="tight");
    #    plt.close(fig) para no fugar memoria.
    # Casos borde: history vacío -> ValueError; tickers con "^" o "." en el nombre de fichero.
    raise NotImplementedError("make_price_chart: pendiente (carril C)")


def make_overview_chart(snapshots: list[PriceSnapshot], out_dir: Path) -> ChartAsset:
    """Barras horizontales con la variación diaria (%) de todos los tickers (kind="overview_bar")."""
    # TODO: ordenar por change_pct; colores por signo; etiqueta con el % al final de cada barra.
    raise NotImplementedError("make_overview_chart: pendiente (carril C)")


def make_portfolio_chart(portfolio: Portfolio, out_dir: Path) -> ChartAsset:
    """Reparto de la cartera por pesos (kind="portfolio_pie"). Opcional."""
    # TODO: donut con matplotlib; solo posiciones con weight; agrupar < 3 % en "Otros".
    raise NotImplementedError("make_portfolio_chart: pendiente (carril C, opcional)")


def make_charts(
    prices: list[PriceSnapshot], out_dir: Path, portfolio: Portfolio | None = None
) -> list[ChartAsset]:
    """Genera todos los gráficos del briefing (overview + uno por ticker + cartera)."""
    # TODO: out_dir.mkdir(...); overview si hay >= 2 tickers; price_line por ticker con
    # histórico; portfolio si hay pesos. Un fallo en un gráfico no debe tumbar el resto
    # (capturar y log.warning).
    raise NotImplementedError("make_charts: pendiente (carril C)")
