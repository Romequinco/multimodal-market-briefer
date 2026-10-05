"""Gráficos del día en PNG (matplotlib) a partir de los precios.

Carril C. Entrada: ``list[PriceSnapshot]`` (+ ``Portfolio`` opcional). Salida:
``list[ChartAsset]`` guardados en ``out_dir``. Se usan en la UI, el email y el vídeo.

Estilo común: lienzo 16:9 de 1920×1080 px (apto para vídeo sin reescalar), tipografía grande,
rejilla discreta y colores aptos para daltonismo: azul = sube, rojo = baja, siempre
acompañados de signo y flecha (▲/▼) para que el color no sea la única pista. Números en
formato español (``+1,23 %``).
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin pantalla: necesario en Docker y en los hilos de Streamlit

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from briefer.logging_utils import get_logger  # noqa: E402
from briefer.schemas import ChartAsset, Portfolio, PriceSnapshot  # noqa: E402

log = get_logger("media.charts")

FIGSIZE = (16, 9)
DPI = 120  # 16×9 in × 120 dpi = 1920×1080 px

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
UP = "#2a78d6"  # azul
DOWN = "#e34948"  # rojo
NEUTRAL = "#8a8984"
# Orden categórico fijo (validado para daltonismo en pares adyacentes); "Otros" en gris.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHERS_COLOR = "#b5b4ae"

_RC = {
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT_SECONDARY,
    "axes.titlecolor": TEXT_PRIMARY,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 1.0,
    "xtick.color": TEXT_SECONDARY,
    "ytick.color": TEXT_SECONDARY,
    "xtick.labelsize": 18,
    "ytick.labelsize": 18,
    "font.size": 18,
    "font.family": "DejaVu Sans",
}


# ── Utilidades ─────────────────────────────────────────────────────────────────────


def safe_name(ticker: str) -> str:
    """Nombre de fichero seguro para un ticker (``^IBEX`` -> ``IBEX``, ``SAN.MC`` -> ``SAN_MC``)."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", ticker).strip("_")
    return cleaned or "ticker"


def fmt_number(value: float, decimals: int = 2) -> str:
    """Número en formato español: ``12345.6`` -> ``"12.345,60"``."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_pct(value: float, decimals: int = 2) -> str:
    """Variación con signo: ``1.234`` -> ``"+1,23 %"``."""
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return f"{sign}{fmt_number(abs(value), decimals)} %"


def trend_color(value: float) -> str:
    """Azul si sube, rojo si baja, gris si plano."""
    return UP if value > 0 else (DOWN if value < 0 else NEUTRAL)


def trend_arrow(value: float) -> str:
    """▲ / ▼ / ● según el signo (pista redundante con el color)."""
    return "▲" if value > 0 else ("▼" if value < 0 else "●")


def _new_figure() -> tuple[Figure, plt.Axes]:
    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    return fig, ax


def _title(fig: Figure, title: str, subtitle: str | None = None) -> None:
    fig.text(0.04, 0.94, title, fontsize=34, fontweight="bold", color=TEXT_PRIMARY, va="top")
    if subtitle:
        fig.text(0.04, 0.875, subtitle, fontsize=20, color=TEXT_SECONDARY, va="top")


def _footer(fig: Figure, text: str = "Market Briefer · datos informativos, no es asesoramiento") -> None:
    fig.text(0.04, 0.03, text, fontsize=14, color=TEXT_SECONDARY, va="bottom")


def _save(fig: Figure, path: Path) -> Path:
    """Guarda a tamaño fijo (sin ``bbox_inches="tight"`` para mantener 1920×1080) y cierra."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    finally:
        plt.close(fig)
    return path


# ── Gráficos ───────────────────────────────────────────────────────────────────────


def make_price_chart(snapshot: PriceSnapshot, out_dir: Path) -> ChartAsset:
    """Línea de cotización del histórico de un ticker (kind="price_line")."""
    if not snapshot.history:
        raise ValueError(f"{snapshot.ticker}: sin histórico de precios")
    history = sorted(snapshot.history, key=lambda item: item[0])
    dates = [d for d, _ in history]
    closes = [c for _, c in history]
    color = trend_color(snapshot.change_pct)

    fig, ax = _new_figure()
    with plt.rc_context(_RC):
        ax.plot(dates, closes, color=color, linewidth=3, solid_capstyle="round")
        low = min(closes)
        pad = (max(closes) - low) * 0.08 or abs(low) * 0.01 or 1.0
        ax.set_ylim(low - pad, max(closes) + pad)
        ax.fill_between(dates, closes, low - pad, color=color, alpha=0.08, linewidth=0)
        ax.scatter([dates[-1]], [closes[-1]], s=140, color=color, zorder=3, edgecolors=SURFACE, linewidths=2)
        ax.annotate(
            f"{fmt_number(closes[-1])} {snapshot.currency}",
            (dates[-1], closes[-1]),
            xytext=(-14, 18),
            textcoords="offset points",
            ha="right",
            fontsize=20,
            fontweight="bold",
            color=TEXT_PRIMARY,
        )
        ax.grid(axis="x", visible=False)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: fmt_number(v)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
        ax.tick_params(length=0, pad=8)
        ax.margins(x=0.01)
    _title(
        fig,
        f"{snapshot.ticker}   {trend_arrow(snapshot.change_pct)} {fmt_pct(snapshot.change_pct)} hoy",
        f"Último: {fmt_number(snapshot.last)} {snapshot.currency} · {len(history)} sesiones "
        f"({dates[0]:%d/%m} – {dates[-1]:%d/%m/%Y})",
    )
    _footer(fig)
    fig.subplots_adjust(left=0.08, right=0.96, top=0.8, bottom=0.12)
    path = _save(fig, Path(out_dir) / f"{safe_name(snapshot.ticker)}_price.png")
    return ChartAsset(path=path, ticker=snapshot.ticker, kind="price_line")


def make_overview_chart(snapshots: list[PriceSnapshot], out_dir: Path) -> ChartAsset:
    """Barras horizontales con la variación diaria (%) de todos los tickers (kind="overview_bar")."""
    if not snapshots:
        raise ValueError("make_overview_chart: no hay precios")
    ordered = sorted(snapshots, key=lambda s: s.change_pct)  # la mayor subida queda arriba
    labels = [s.ticker for s in ordered]
    values = [s.change_pct for s in ordered]
    colors = [trend_color(v) for v in values]
    span = max(abs(v) for v in values) or 1.0

    fig, ax = _new_figure()
    with plt.rc_context(_RC):
        bar_h = 0.62 if len(values) > 1 else 0.4
        ax.barh(labels, values, color=colors, height=bar_h, edgecolor=SURFACE, linewidth=2)
        ax.set_axisbelow(True)
        ax.axvline(0, color=TEXT_SECONDARY, linewidth=1.5)
        for y, v in enumerate(values):
            offset = span * 0.02
            ax.text(
                v + (offset if v >= 0 else -offset),
                y,
                f"{trend_arrow(v)} {fmt_pct(v)}",
                va="center",
                ha="left" if v >= 0 else "right",
                fontsize=19,
                fontweight="bold",
                color=TEXT_PRIMARY,
            )
        ax.set_xlim(-span * 1.35, span * 1.35)
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: fmt_pct(v, 1)))
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", length=0, labelsize=22, pad=10)
        ax.tick_params(axis="x", length=0)
        ax.spines["left"].set_visible(False)
    ups = sum(v > 0 for v in values)
    downs = sum(v < 0 for v in values)
    _title(fig, "Variación del día", f"{ups} suben · {downs} bajan · {len(values)} valores seguidos")
    _footer(fig)
    fig.subplots_adjust(left=0.14, right=0.96, top=0.8, bottom=0.12)
    path = _save(fig, Path(out_dir) / "overview_change.png")
    return ChartAsset(path=path, ticker=None, kind="overview_bar")


def portfolio_weights(portfolio: Portfolio, prices: list[PriceSnapshot] | None = None) -> dict[str, float]:
    """Pesos normalizados (suman 1) de la cartera.

    Usa ``weight`` si existe; si solo hay ``quantity`` y se conoce el precio, usa el valor
    de mercado (cantidad × último precio; ignora diferencias de divisa: es orientativo).
    """
    last = {p.ticker: p.last for p in prices or []}
    raw: dict[str, float] = {}
    for pos in portfolio.positions:
        if pos.weight is not None and pos.weight > 0:
            raw[pos.ticker] = raw.get(pos.ticker, 0.0) + pos.weight
        elif pos.quantity and pos.ticker in last:
            raw[pos.ticker] = raw.get(pos.ticker, 0.0) + pos.quantity * last[pos.ticker]
    total = sum(raw.values())
    return {t: v / total for t, v in raw.items()} if total > 0 else {}


def make_portfolio_chart(
    portfolio: Portfolio,
    out_dir: Path,
    prices: list[PriceSnapshot] | None = None,
    min_share: float = 0.03,
) -> ChartAsset:
    """Reparto de la cartera por pesos (kind="portfolio_pie"), en forma de donut.

    Las posiciones por debajo de ``min_share`` y las que excedan los 8 colores categóricos se
    agrupan en «Otros».
    """
    weights = portfolio_weights(portfolio, prices)
    if not weights:
        raise ValueError("make_portfolio_chart: la cartera no tiene pesos ni cantidades valorables")
    items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    main = [(t, w) for t, w in items if w >= min_share][: len(CATEGORICAL)]
    others = 1.0 - sum(w for _, w in main)
    labels = [t for t, _ in main]
    values = [w for _, w in main]
    colors = CATEGORICAL[: len(main)]
    if others > 1e-9:
        labels.append("Otros")
        values.append(others)
        colors.append(OTHERS_COLOR)

    fig, ax = _new_figure()
    with plt.rc_context(_RC):
        ax.grid(False)
        ax.axis("off")
        ax.set_position([0.04, 0.1, 0.5, 0.72])
        ax.pie(
            values,
            colors=colors,
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.38, "edgecolor": SURFACE, "linewidth": 3},
        )
        ax.set_aspect("equal")
        ax.text(0, 0.06, str(len(weights)), ha="center", va="center", fontsize=48, fontweight="bold",
                color=TEXT_PRIMARY)
        ax.text(0, -0.16, "posiciones", ha="center", va="center", fontsize=20, color=TEXT_SECONDARY)
        # Leyenda con valores (la identidad no depende solo del color)
        y = 0.76
        for label, value, color in zip(labels, values, colors, strict=True):
            fig.patches.append(
                FancyBboxPatch(
                    (0.6, y - 0.018), 0.022, 0.036, boxstyle="round,pad=0.002", transform=fig.transFigure,
                    facecolor=color, edgecolor="none",
                )
            )
            fig.text(0.635, y, label, fontsize=22, color=TEXT_PRIMARY, va="center")
            fig.text(0.94, y, fmt_pct(value * 100, 1).lstrip("+"), fontsize=22, color=TEXT_PRIMARY,
                     va="center", ha="right", fontweight="bold")
            y -= 0.07
    _title(fig, f"Reparto de la cartera · {portfolio.name}", "Peso de cada posición sobre el total")
    _footer(fig)
    path = _save(fig, Path(out_dir) / "portfolio_weights.png")
    return ChartAsset(path=path, ticker=None, kind="portfolio_pie")


def make_charts(
    prices: list[PriceSnapshot], out_dir: Path, portfolio: Portfolio | None = None
) -> list[ChartAsset]:
    """Genera todos los gráficos del briefing (overview + uno por ticker + cartera).

    Orden: variación del día (si hay ≥ 2 valores), una línea por ticker con histórico (en el
    orden recibido) y el reparto de la cartera si es valorable. Un fallo en un gráfico se
    registra en el log y no tumba el resto.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets: list[ChartAsset] = []
    if len(prices) >= 2:
        try:
            assets.append(make_overview_chart(prices, out_dir))
        except Exception as exc:
            log.warning("Gráfico de variaciones omitido: %s", exc)
    for snap in prices:
        if not snap.history:
            continue
        try:
            assets.append(make_price_chart(snap, out_dir))
        except Exception as exc:
            log.warning("Gráfico de %s omitido: %s", snap.ticker, exc)
    if portfolio is not None and portfolio.positions:
        try:
            assets.append(make_portfolio_chart(portfolio, out_dir, prices=prices))
        except Exception as exc:
            log.warning("Gráfico de cartera omitido: %s", exc)
    return assets


__all__ = [
    "fmt_number",
    "fmt_pct",
    "make_charts",
    "make_overview_chart",
    "make_portfolio_chart",
    "make_price_chart",
    "portfolio_weights",
    "safe_name",
]
