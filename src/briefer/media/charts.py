"""Gráficos del día en PNG (matplotlib) a partir de los precios.

Carril C. Entrada: ``list[PriceSnapshot]`` (+ ``Portfolio`` opcional). Salida:
``list[ChartAsset]`` guardados en ``out_dir``. Se usan en la UI, Telegram y el vídeo.

Estilo común: lienzo 16:9 de 1920×1080 px (apto para vídeo sin reescalar), tipografía grande,
rejilla discreta y color de tendencia siempre acompañado de signo y flecha (▲/▼) para que el
color no sea la única pista. Números y fechas en formato español (``+1,23 %``, ``05/10/2026``).
Cada gráfico lleva en el título la fecha de la última sesión y en el pie la fuente de los datos
(por defecto «Yahoo Finance»).

Temas (``BRIEFER_CHART_THEME`` o parámetro ``theme=``):

- ``dark`` (por defecto, «Noticiero nocturno», a juego con la UI): fondo #12151B, títulos en serif,
  cifras y etiquetas en mono, línea de precio coral con relleno muy sutil, subidas en verde y
  bajadas en rosa, índices y fuente en gris.
- ``light``: el estilo claro original (azul = sube, rojo = baja), útil para impresión.

Las fuentes son las DejaVu que trae matplotlib (Sans, Serif, Sans Mono): no dependen del sistema,
así que se ven igual en Docker.

Índices de referencia (``^IBEX``, ``^GSPC``…, todo ticker que empieza por ``^``): en el gráfico de
variación del día van **aparte**, debajo de los valores del usuario, en gris y rotulados con su
nombre («IBEX 35», «S&P 500») y la marca «índice», para que no se confundan con un valor.

Concurrencia: se usa la API orientada a objetos de matplotlib (``Figure``) sin ``pyplot`` ni
``rcParams`` globales, y el tema viaja como objeto inmutable (``ChartTheme``), así que es seguro
dibujar desde varios hilos o sesiones de Streamlit a la vez. Cada PNG se escribe de forma atómica
(temporal + ``replace``).
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # sin pantalla: necesario en Docker y en los hilos de Streamlit

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import matplotlib.transforms as mtransforms  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from briefer.brand import BRAND_NAME  # noqa: E402
from briefer.logging_utils import get_logger  # noqa: E402
from briefer.schemas import ChartAsset, Portfolio, PriceSnapshot  # noqa: E402

log = get_logger("media.charts")

FIGSIZE = (16, 9)
DPI = 120  # 16×9 in × 120 dpi = 1920×1080 px
DEFAULT_SOURCE = "Yahoo Finance"
FOOTER_NOTE = f"{BRAND_NAME} · información, no asesoramiento financiero"

# Constantes del tema claro (se mantienen por compatibilidad; el estilo vive en ``ChartTheme``).
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
UP = "#2a78d6"  # azul
DOWN = "#e34948"  # rojo
NEUTRAL = "#8a8984"
INDEX_COLOR = "#8f8e88"  # índices de referencia: gris, distinto de los valores del usuario
# Orden categórico fijo (validado para daltonismo en pares adyacentes); "Otros" en gris.
CATEGORICAL = ["#2a78d6", "#eb6834", "#139068", "#b07800", "#c2577f", "#008300", "#4a3aa7", "#e34948"]
OTHERS_COLOR = "#8a8a85"
FONT = "DejaVu Sans"


@dataclass(frozen=True)
class ChartTheme:
    """Paleta y tipografías de un tema de gráficos (inmutable: se comparte entre hilos sin riesgo)."""

    name: str
    surface: str  # fondo de la figura y del eje
    text_primary: str  # títulos, nombres, cifras principales
    text_secondary: str  # etiquetas de los ejes
    muted: str  # subtítulo, fuente, fecha, índices
    grid: str  # rejilla y ejes
    axis: str  # línea del cero y separadores
    up: str
    down: str
    neutral: str
    index: str  # barras de los índices de referencia
    price_line: str | None  # color fijo de la línea de precio (None = color de tendencia)
    fill_alpha: float  # relleno bajo la línea de precio
    categorical: tuple[str, ...]  # cartera
    others: str
    title_font: str
    body_font: str
    mono_font: str


LIGHT = ChartTheme(
    name="light",
    surface=SURFACE,
    text_primary=TEXT_PRIMARY,
    text_secondary=TEXT_SECONDARY,
    muted=TEXT_SECONDARY,
    grid=GRID,
    axis=TEXT_SECONDARY,
    up=UP,
    down=DOWN,
    neutral=NEUTRAL,
    index=INDEX_COLOR,
    price_line=None,
    fill_alpha=0.08,
    categorical=tuple(CATEGORICAL),
    others=OTHERS_COLOR,
    title_font=FONT,
    body_font=FONT,
    mono_font=FONT,
)

DARK = ChartTheme(
    name="dark",
    surface="#12151B",
    text_primary="#D6DEE8",
    text_secondary="#A9B3BF",
    muted="#888780",
    grid="#2A313B",
    axis="#6B7480",
    up="#5DCAA5",
    down="#F09595",
    neutral="#888780",
    index="#888780",
    price_line="#F0997B",
    fill_alpha=0.06,
    categorical=("#F0997B", "#5DCAA5", "#85B7EB", "#EF9F27", "#ED93B1", "#AFA9EC", "#97C459", "#F09595"),
    others="#7A7975",
    title_font="DejaVu Serif",
    body_font="DejaVu Sans",
    mono_font="DejaVu Sans Mono",
)

THEMES: dict[str, ChartTheme] = {"dark": DARK, "light": LIGHT}


def resolve_theme(theme: str | ChartTheme | None = None) -> ChartTheme:
    """Tema pedido (``"dark"`` / ``"light"``) o, con ``None``, el de ``BRIEFER_CHART_THEME`` (``dark``).

    Raises:
        ValueError: si el nombre no es un tema conocido.
    """
    if isinstance(theme, ChartTheme):
        return theme
    if theme is None:
        try:
            from briefer.config import get_settings

            theme = get_settings().briefer_chart_theme
        except Exception:  # pragma: no cover - config inválida: no tumbar los gráficos
            theme = "dark"
    key = str(theme).strip().lower()
    if key not in THEMES:
        raise ValueError(f"Tema de gráfico desconocido: {theme!r} (usa 'dark' o 'light')")
    return THEMES[key]


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
    if round(value, decimals) == 0:
        value = 0.0  # sin «−0,00 %»
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return f"{sign}{fmt_number(abs(value), decimals)} %"


def fmt_date(day: date, with_year: bool = True) -> str:
    """Fecha en formato español: ``05/10/2026`` (o ``05/10``)."""
    return f"{day:%d/%m/%Y}" if with_year else f"{day:%d/%m}"


def trend_color(value: float, theme: ChartTheme = LIGHT) -> str:
    """Color de subida / bajada / plano del tema (claro: azul, rojo, gris; oscuro: verde, rosa, gris)."""
    return theme.up if value > 0 else (theme.down if value < 0 else theme.neutral)


def trend_arrow(value: float) -> str:
    """▲ / ▼ / ● según el signo (pista redundante con el color)."""
    return "▲" if value > 0 else ("▼" if value < 0 else "●")


def is_index(ticker: str) -> bool:
    """``True`` para índices de referencia (convención de Yahoo: empiezan por ``^``)."""
    return ticker.strip().startswith("^")


def display_name(ticker: str) -> str:
    """Nombre legible del ticker (``SAN.MC`` -> «Banco Santander»; ``^IBEX`` -> «IBEX 35»).

    Usa ``ingest.tickers.TICKER_UNIVERSE`` (solo lectura); si no lo conoce, el ticker sin ``^``.
    """
    try:
        from briefer.ingest.tickers import ticker_info

        info = ticker_info(ticker.strip().upper()) or ticker_info(ticker.strip())
        if info and info.get("name"):
            return str(info["name"])
    except Exception:  # pragma: no cover - el universo es opcional para dibujar
        pass
    return ticker.strip().lstrip("^")


def last_session(snapshots: list[PriceSnapshot]) -> date | None:
    """Fecha de la última sesión con datos entre todos los históricos (``None`` si no hay)."""
    days = [d for s in snapshots for d, _ in s.history[-1:]]
    return max(days) if days else None


def _date_ticks(dates: list[date], max_ticks: int = 7) -> list[date]:
    """Hasta ``max_ticks`` fechas repartidas de forma uniforme (siempre la primera y la última).

    Evita que el localizador automático junte dos marcas en el cambio de mes («29/09 01/10»).
    """
    if len(dates) <= max_ticks:
        return list(dates)
    step = (len(dates) - 1) / (max_ticks - 1)
    return [dates[round(i * step)] for i in range(max_ticks)]


def _new_figure(theme: ChartTheme = LIGHT) -> tuple[Figure, Axes]:
    """Figura 1920×1080 sin ``pyplot`` (sin estado global: segura entre hilos)."""
    fig = Figure(figsize=FIGSIZE, dpi=DPI, facecolor=theme.surface)
    ax = fig.add_subplot()
    _style_axes(ax, theme)
    return fig, ax


def _style_axes(ax: Axes, theme: ChartTheme = LIGHT) -> None:
    """Estilo común aplicado al eje (equivale a un ``rc_context`` pero sin tocar ``rcParams``)."""
    ax.set_facecolor(theme.surface)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.grid)
    ax.grid(True, color=theme.grid, linewidth=1.0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=theme.text_secondary, labelsize=18, length=0, pad=8,
                   labelfontfamily=theme.mono_font)


def _small(theme: ChartTheme, size: int) -> int:
    """La mono es más ancha que la sans: algo más pequeña para que quepa el subtítulo en una línea."""
    return size if theme.mono_font == theme.body_font else size - 3


def _title(fig: Figure, title: str, subtitle: str | None = None, theme: ChartTheme = LIGHT) -> None:
    fig.text(0.04, 0.94, title, fontsize=34, fontweight="bold", color=theme.text_primary, va="top",
             family=theme.title_font)
    if subtitle:
        fig.text(0.04, 0.875, subtitle, fontsize=_small(theme, 20), color=theme.muted, va="top",
                 family=theme.mono_font)


def _trend_badge(fig: Figure, change_pct: float, theme: ChartTheme) -> None:
    """Variación del día arriba a la derecha, en color de tendencia (con ▲/▼ y signo)."""
    fig.text(0.96, 0.94, f"{trend_arrow(change_pct)} {fmt_pct(change_pct)}", fontsize=32, fontweight="bold",
             color=trend_color(change_pct, theme), va="top", ha="right", family=theme.mono_font)


def _footer(fig: Figure, source: str | None = DEFAULT_SOURCE, extra: str | None = None,
            theme: ChartTheme = LIGHT) -> None:
    """Pie con la fuente de los datos (a la izquierda) y el aviso (a la derecha)."""
    left = " · ".join(p for p in (f"Fuente: {source}" if source else "", extra or "") if p)
    # Mono (tema oscuro): 13 pt para que fuente + aviso quepan en una línea sin solaparse.
    size = 15 if theme.mono_font == theme.body_font else 13
    if left:
        fig.text(0.04, 0.03, left, fontsize=size, color=theme.muted, va="bottom", family=theme.mono_font)
    fig.text(0.96, 0.03, FOOTER_NOTE, fontsize=size, color=theme.muted, va="bottom", ha="right",
             family=theme.mono_font)


def _save(fig: Figure, path: Path) -> Path:
    """Guarda a tamaño fijo (sin ``bbox_inches="tight"`` para mantener 1920×1080), de forma atómica.

    Se escribe en un temporal único por hilo y se renombra: la UI nunca lee un PNG a medias y
    dos ejecuciones simultáneas no se pisan el temporal. El fondo es el de la figura (su tema).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        fig.savefig(tmp, dpi=DPI, facecolor=fig.get_facecolor(), format="png")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
        fig.clear()
    return path


# ── Gráficos ───────────────────────────────────────────────────────────────────────


def make_price_chart(
    snapshot: PriceSnapshot,
    out_dir: Path,
    *,
    source: str | None = DEFAULT_SOURCE,
    theme: str | None = None,
) -> ChartAsset:
    """Línea de cotización del histórico de un ticker (kind="price_line").

    ``source``: fuente de los datos que se rotula en el pie (``None`` = sin fuente).
    ``theme``: ``"dark"`` / ``"light"`` (``None`` = ``BRIEFER_CHART_THEME``).
    """
    th = resolve_theme(theme)
    if not snapshot.history:
        raise ValueError(f"{snapshot.ticker}: sin histórico de precios")
    history = sorted(snapshot.history, key=lambda item: item[0])
    # Fechas tal cual: matplotlib las convierte con su conversor de unidades (sus stubs no lo modelan).
    dates: Any = [d for d, _ in history]
    closes = [c for _, c in history]
    index = is_index(snapshot.ticker)
    # Tema claro: la línea toma el color de tendencia. Oscuro: línea coral fija y la tendencia va
    # en la cifra grande de arriba a la derecha.
    color = th.price_line or trend_color(snapshot.change_pct, th)
    unit = "puntos" if index else snapshot.currency

    fig, ax = _new_figure(th)
    ax.plot(dates, closes, color=color, linewidth=3, solid_capstyle="round")
    low = min(closes)
    pad = (max(closes) - low) * 0.08 or abs(low) * 0.01 or 1.0
    ax.set_ylim(low - pad, max(closes) + pad)
    ax.fill_between(dates, closes, low - pad, color=color, alpha=th.fill_alpha, linewidth=0)
    ax.scatter([dates[-1]], [closes[-1]], s=140, color=color, zorder=3, edgecolors=th.surface, linewidths=2)
    ax.annotate(
        f"{fmt_number(closes[-1])} {unit}",
        (dates[-1], closes[-1]),
        xytext=(-14, 18),
        textcoords="offset points",
        ha="right",
        fontsize=20,
        fontweight="bold",
        color=th.text_primary,
        family=th.mono_font,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": th.surface, "edgecolor": "none", "alpha": 0.9},
    )
    ax.grid(axis="x", visible=False)
    decimals = 0 if max(closes) >= 1000 else 2  # «19.200» y no «19.200,00» (cabe y se lee mejor)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: fmt_number(v, decimals)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.xaxis.set_major_locator(mticker.FixedLocator(mdates.date2num(_date_ticks(dates))))
    ax.margins(x=0.01)
    name = display_name(snapshot.ticker)
    label = f"{name} · índice" if index else (
        f"{name} · {snapshot.ticker}" if name.upper() != snapshot.ticker.upper() else name)
    subtitle = (
        f"Cierre del {fmt_date(dates[-1])}: {fmt_number(snapshot.last)} {unit} · variación de la sesión · "
        f"{len(history)} sesiones ({fmt_date(dates[0], False)} – {fmt_date(dates[-1])})"
    )
    if th.price_line:
        _title(fig, label, subtitle, th)
        _trend_badge(fig, snapshot.change_pct, th)
    else:
        _title(fig, f"{label}   {trend_arrow(snapshot.change_pct)} {fmt_pct(snapshot.change_pct)}", subtitle, th)
    _footer(fig, source, "precios de cierre", th)
    fig.subplots_adjust(left=0.1, right=0.96, top=0.8, bottom=0.12)
    path = _save(fig, Path(out_dir) / f"{safe_name(snapshot.ticker)}_price.png")
    return ChartAsset(path=path, ticker=snapshot.ticker, kind="price_line")


def make_overview_chart(
    snapshots: list[PriceSnapshot],
    out_dir: Path,
    *,
    source: str | None = DEFAULT_SOURCE,
    theme: str | None = None,
) -> ChartAsset:
    """Barras horizontales con la variación del día (%) (kind="overview_bar").

    Arriba, los valores del usuario ordenados (la mayor subida arriba), en color de tendencia y
    con su nombre; debajo, separados por una línea y rotulados «Índices de referencia», los índices
    (``^IBEX``…) en gris con la marca «índice». El título lleva la fecha de la última sesión.
    ``theme``: ``"dark"`` / ``"light"`` (``None`` = ``BRIEFER_CHART_THEME``).
    """
    th = resolve_theme(theme)
    if not snapshots:
        raise ValueError("make_overview_chart: no hay precios")
    stocks = sorted((s for s in snapshots if not is_index(s.ticker)), key=lambda s: s.change_pct, reverse=True)
    indices = sorted((s for s in snapshots if is_index(s.ticker)), key=lambda s: s.change_pct, reverse=True)
    rows: list[tuple[PriceSnapshot, bool]] = [(s, False) for s in stocks] + [(s, True) for s in indices]
    values = [s.change_pct for s, _ in rows]
    span = max(abs(v) for v in values) or 1.0
    n = len(rows)
    # Posición vertical: de arriba abajo; un hueco extra entre valores e índices.
    gap = 0.6 if stocks and indices else 0.0
    ys = [-(i + (gap if is_idx else 0.0)) for i, (_, is_idx) in enumerate(rows)]
    dark = th.price_line is not None

    fig, ax = _new_figure(th)
    bar_h = 0.62 if n > 1 else 0.4
    colors = [th.index if is_idx else trend_color(s.change_pct, th) for s, is_idx in rows]
    ax.barh(ys, values, color=colors, height=bar_h, edgecolor=th.surface, linewidth=2,
            hatch=None)
    ax.axvline(0, color=th.axis, linewidth=1.5)
    offset = span * 0.02
    for y, (_snap, is_idx), v in zip(ys, rows, values, strict=True):
        if is_idx:
            value_color = th.muted
        else:
            value_color = trend_color(v, th) if dark else th.text_primary
        ax.text(
            v + (offset if v >= 0 else -offset), y, f"{trend_arrow(v)} {fmt_pct(v)}",
            va="center", ha="left" if v >= 0 else "right", fontsize=19, fontweight="bold",
            color=value_color, family=th.mono_font,
        )
    # Etiquetas propias (nombre + ticker o «índice») en lugar de los ticks del eje Y.
    ax.set_yticks([])
    label_tf = mtransforms.blended_transform_factory(ax.transAxes, ax.transData)
    big = n <= 8
    for y, (snap, is_idx) in zip(ys, rows, strict=True):
        name = display_name(snap.ticker)
        sub = "índice" if is_idx else (snap.ticker if name.upper() != snap.ticker.upper() else "")
        ax.text(-0.015, y + (0.13 if sub else 0), name, transform=label_tf, ha="right", va="center",
                fontsize=21 if big else 16, fontweight="bold",
                color=th.muted if is_idx else th.text_primary, family=th.body_font)
        if sub:
            ax.text(-0.015, y - 0.2, sub, transform=label_tf, ha="right", va="center",
                    fontsize=14 if big else 12, color=th.muted,
                    family=th.body_font if is_idx else th.mono_font,
                    style="italic" if is_idx else "normal")
    if stocks and indices:
        sep = (ys[len(stocks) - 1] + ys[len(stocks)]) / 2
        ax.axhline(sep, color=th.axis if dark else th.grid, linewidth=1.5, linestyle=(0, (4, 4)))
        ax.text(1.0, sep - 0.08, "Índices de referencia", transform=label_tf, ha="right", va="top",
                fontsize=15, color=th.muted, style="italic", family=th.body_font)
    ax.set_ylim(min(ys) - 0.7, 0.7)
    lo, hi = min(0.0, *values), max(0.0, *values)
    ax.set_xlim(lo - span * (0.38 if lo < 0 else 0.04), hi + span * (0.38 if hi > 0 else 0.04))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: fmt_pct(v, 1)))
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)

    ups = sum(s.change_pct > 0 for s in stocks)
    downs = sum(s.change_pct < 0 for s in stocks)
    session = last_session(snapshots)
    title = "Variación del día" + (f" · {fmt_date(session)}" if session else "")
    parts = []
    if stocks:
        parts.append(f"{len(stocks)} {'valor' if len(stocks) == 1 else 'valores'}: {ups} suben · {downs} bajan")
    if indices:
        parts.append("referencia: " + ", ".join(display_name(s.ticker) for s in indices))
    _title(fig, title, " · ".join(parts), th)
    _footer(fig, source, "variación del último cierre frente al anterior", th)
    fig.subplots_adjust(left=0.22, right=0.96, top=0.8, bottom=0.12)
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
    *,
    theme: str | None = None,
) -> ChartAsset:
    """Reparto de la cartera por pesos (kind="portfolio_pie"), en forma de donut.

    Las posiciones por debajo de ``min_share`` y las que excedan los 8 colores categóricos se
    agrupan en «Otros». ``theme``: ``"dark"`` / ``"light"`` (``None`` = ``BRIEFER_CHART_THEME``).
    """
    th = resolve_theme(theme)
    weights = portfolio_weights(portfolio, prices)
    if not weights:
        raise ValueError("make_portfolio_chart: la cartera no tiene pesos ni cantidades valorables")
    items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    main = [(t, w) for t, w in items if w >= min_share][: len(th.categorical)]
    others = 1.0 - sum(w for _, w in main)
    labels = [t for t, _ in main]
    values = [w for _, w in main]
    colors = list(th.categorical[: len(main)])
    if others > 1e-9:
        labels.append("Otros")
        values.append(others)
        colors.append(th.others)

    fig, ax = _new_figure(th)
    ax.grid(False)
    ax.axis("off")
    ax.set_position((0.04, 0.1, 0.5, 0.72))
    ax.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": th.surface, "linewidth": 3},
    )
    ax.set_aspect("equal")
    ax.text(0, 0.06, str(len(weights)), ha="center", va="center", fontsize=48, fontweight="bold",
            color=th.text_primary, family=th.title_font)
    ax.text(0, -0.16, "posiciones", ha="center", va="center", fontsize=20, color=th.muted, family=th.body_font)
    # Leyenda con valores (la identidad no depende solo del color)
    y = 0.76
    for label, value, color in zip(labels, values, colors, strict=True):
        fig.patches.append(
            FancyBboxPatch(
                (0.6, y - 0.018), 0.022, 0.036, boxstyle="round,pad=0.002", transform=fig.transFigure,
                facecolor=color, edgecolor="none",
            )
        )
        name = display_name(label) if label != "Otros" else label
        fig.text(0.635, y, name, fontsize=22, color=th.text_primary, va="center", family=th.body_font)
        fig.text(0.94, y, fmt_pct(value * 100, 1).lstrip("+"), fontsize=22, color=th.text_primary,
                 va="center", ha="right", fontweight="bold", family=th.mono_font)
        y -= 0.07
    _title(fig, f"Reparto de la cartera · {portfolio.name}", "Peso de cada posición sobre el total", th)
    _footer(fig, None, "pesos de la cartera cargada (orientativo)", th)
    path = _save(fig, Path(out_dir) / "portfolio_weights.png")
    return ChartAsset(path=path, ticker=None, kind="portfolio_pie")


def make_charts(
    prices: list[PriceSnapshot],
    out_dir: Path,
    portfolio: Portfolio | None = None,
    *,
    line_tickers: Collection[str] | None = None,
    source: str | None = DEFAULT_SOURCE,
    theme: str | None = None,
) -> list[ChartAsset]:
    """Genera todos los gráficos del briefing (overview + uno por ticker + cartera).

    Orden: variación del día (si hay ≥ 2 valores; los índices van aparte, rotulados como
    referencia), una línea por ticker con histórico (en el orden recibido) y el reparto de la
    cartera si es valorable. Un fallo en un gráfico se registra en el log y no tumba el resto.

    ``line_tickers``: si se indica, solo esos tickers tienen gráfico de cotización propio (los
    índices de contexto, p. ej. ``^IBEX``, salen solo en el gráfico de variación del día).
    ``source``: fuente de los precios rotulada en el pie (por defecto «Yahoo Finance»; en modo
    demo el pipeline debería pasar p. ej. ``"precios sintéticos (demo)"``).
    ``theme``: ``"dark"`` / ``"light"`` para todos los gráficos (``None`` = ``BRIEFER_CHART_THEME``).
    Un tema desconocido lanza ``ValueError`` (se resuelve una vez, antes de dibujar).
    """
    theme = resolve_theme(theme).name
    wanted_lines = {t.upper() for t in line_tickers} if line_tickers is not None else None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets: list[ChartAsset] = []
    if len(prices) >= 2:
        try:
            assets.append(make_overview_chart(prices, out_dir, source=source, theme=theme))
        except Exception as exc:
            log.warning("Gráfico de variaciones omitido: %s", exc)
    for snap in prices:
        if not snap.history or (wanted_lines is not None and snap.ticker.upper() not in wanted_lines):
            continue
        try:
            assets.append(make_price_chart(snap, out_dir, source=source, theme=theme))
        except Exception as exc:
            log.warning("Gráfico de %s omitido: %s", snap.ticker, exc)
    if portfolio is not None and portfolio.positions:
        try:
            assets.append(make_portfolio_chart(portfolio, out_dir, prices=prices, theme=theme))
        except Exception as exc:
            log.warning("Gráfico de cartera omitido: %s", exc)
    return assets


__all__ = [
    "DARK",
    "DEFAULT_SOURCE",
    "LIGHT",
    "THEMES",
    "ChartTheme",
    "display_name",
    "fmt_date",
    "fmt_number",
    "fmt_pct",
    "is_index",
    "last_session",
    "make_charts",
    "make_overview_chart",
    "make_portfolio_chart",
    "make_price_chart",
    "portfolio_weights",
    "resolve_theme",
    "safe_name",
]
