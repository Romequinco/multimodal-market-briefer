"""Genera los ficheros de ejemplo binarios de ``data/samples/`` (todo FICTICIO).

- ``grafico_ejemplo.png``: captura simulada de un gráfico de velas de un valor inventado
  («EJEMPLO IND.», ticker ficticio ``EJMP``), para probar la lectura de gráficos (visión).
- ``resultados_ejemplo.pdf``: 3 páginas de resultados trimestrales inventados (texto, tabla de
  cifras y una página con gráfico embebido como imagen), para probar ``ingest.pdf_reader``.
- ``cartera_ejemplo.png``: captura ficticia de la pantalla de posiciones de una app de broker
  genérica (sin marcas reales), para probar ``ingest.portfolio.portfolio_from_image``.

Solo usa dependencias del proyecto (matplotlib, numpy, Pillow). Es determinista (semilla fija, sin fechas
de creación en los metadatos), así que regenerar no cambia los ficheros salvo que cambie el código.

Uso:  python data/samples/generar_muestras.py
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parent
SEED = 20261005
COMPANY = "Ejemplo Industrial S.A."
TICKER = "EJMP"
BANNER = "EJEMPLO FICTICIO · datos inventados, no reales"

# Texto en el PDF como TrueType (pypdf extrae mejor el texto que con fuentes Type 3).
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["font.family"] = "DejaVu Sans"


def _ohlc(n: int = 60, start: float = 24.0) -> tuple[list[date], np.ndarray]:
    """Serie OHLC inventada (paseo aleatorio con semilla fija, n sesiones hábiles)."""
    rng = np.random.default_rng(SEED)
    days: list[date] = []
    d = date(2026, 7, 1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    closes = start * np.exp(np.cumsum(rng.normal(0.002, 0.016, n)))
    opens = np.concatenate([[start], closes[:-1]]) * (1 + rng.normal(0, 0.004, n))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.008, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.008, n)))
    volume = rng.integers(800_000, 2_500_000, n)
    return days, np.column_stack([opens, highs, lows, closes, volume])


def _draw_candles(ax_price, ax_vol, days: list[date], data: np.ndarray, dark: bool = True) -> None:
    up, down = ("#26a69a", "#ef5350")
    x = np.arange(len(days))
    for i, (o, h, lo, c, v) in enumerate(data):
        color = up if c >= o else down
        ax_price.vlines(i, lo, h, color=color, linewidth=1)
        ax_price.add_patch(Rectangle((i - 0.3, min(o, c)), 0.6, max(abs(c - o), 0.01), color=color))
        ax_vol.bar(i, v / 1e6, color=color, width=0.6, alpha=0.7)
    sma = np.convolve(data[:, 3], np.ones(20) / 20, mode="valid")
    ax_price.plot(x[19:], sma, color="#ffb74d" if dark else "#f57c00", linewidth=1.3, label="Media 20 sesiones")
    ticks = list(range(0, len(days), 10))
    ax_vol.set_xticks(ticks, [days[i].strftime("%d-%b") for i in ticks])
    ax_price.set_xlim(-1, len(days))
    ax_price.legend(loc="upper left", fontsize=8, frameon=False, labelcolor="#cfd8dc" if dark else "#333333")


def make_chart_png(out: Path) -> Path:
    """Gráfico de velas con volumen, con estética de captura de plataforma de trading."""
    days, data = _ohlc()
    bg, fg, grid = "#131722", "#cfd8dc", "#2a2e39"
    fig = plt.figure(figsize=(10, 6), dpi=110, facecolor=bg)
    ax_price = fig.add_axes((0.06, 0.30, 0.86, 0.58), facecolor=bg)
    ax_vol = fig.add_axes((0.06, 0.08, 0.86, 0.18), facecolor=bg, sharex=ax_price)
    _draw_candles(ax_price, ax_vol, days, data)
    for ax in (ax_price, ax_vol):
        ax.tick_params(colors=fg, labelsize=8)
        ax.yaxis.tick_right()
        ax.grid(color=grid, linewidth=0.6)
        for spine in ax.spines.values():
            spine.set_color(grid)
    plt.setp(ax_price.get_xticklabels(), visible=False)
    ax_vol.set_ylabel("Vol. (M)", color=fg, fontsize=8)
    last, prev = data[-1, 3], data[-2, 3]
    change = (last / prev - 1) * 100
    fig.text(0.06, 0.94, f"{TICKER} · {COMPANY} · 1D · EUR", color=fg, fontsize=12, weight="bold")
    fig.text(
        0.06, 0.905,
        f"O {data[-1, 0]:.2f}  H {data[-1, 1]:.2f}  L {data[-1, 2]:.2f}  C {last:.2f}  ({change:+.2f} %)",
        color="#26a69a" if change >= 0 else "#ef5350", fontsize=9,
    )
    fig.text(0.92, 0.94, BANNER, color="#ffb74d", fontsize=8, ha="right")
    fig.savefig(out, facecolor=bg, metadata={"Software": None})
    plt.close(fig)
    return out


def _text_page(pdf: PdfPages, title: str, paragraphs: list[str]) -> None:
    fig = plt.figure(figsize=(8.27, 11.69))  # A4
    fig.text(0.08, 0.95, BANNER, color="#c62828", fontsize=9, weight="bold")
    fig.text(0.08, 0.91, title, fontsize=16, weight="bold")
    fig.text(0.08, 0.885, f"{COMPANY} (ticker ficticio {TICKER})", fontsize=10, color="#555555")
    y = 0.84
    for para in paragraphs:
        fig.text(0.08, y, para, fontsize=10.5, va="top", wrap=True)
        y -= 0.035 * (para.count("\n") + 1) + 0.025
    fig.text(0.08, 0.04, "Documento de ejemplo generado para la demo de Market Briefer. "
             "No contiene información real ni constituye asesoramiento financiero.", fontsize=7, color="#777777")
    pdf.savefig(fig)
    plt.close(fig)


def make_results_pdf(out: Path) -> Path:
    """PDF de 3 páginas: resumen, tabla de cifras y página con gráfico (imagen embebida)."""
    with PdfPages(out, metadata={"CreationDate": None, "ModDate": None, "Producer": None,
                                 "Creator": "generar_muestras.py", "Title": "Resultados 3T 2026 (ejemplo)"}) as pdf:
        _text_page(pdf, "Resultados del tercer trimestre de 2026", [
            "Resumen ejecutivo (datos inventados):",
            "- Ingresos de 1.245 millones de euros, un 8,4 % más que en el 3T 2025.\n"
            "- EBITDA de 312 millones de euros (+11,2 %), con un margen del 25,1 %.\n"
            "- Beneficio neto atribuido de 158 millones de euros (+6,9 %).\n"
            "- Deuda financiera neta de 890 millones de euros, 1,6 veces EBITDA.",
            "La compañía ficticia atribuye el crecimiento a la división de servicios digitales,\n"
            "que aporta ya el 34 % de los ingresos, y a la mejora de precios en Europa.\n"
            "Los costes energéticos se moderan respecto al mismo periodo del año anterior.",
            "Perspectivas: la dirección mantiene el objetivo de crecimiento de ingresos de un\n"
            "dígito alto para el conjunto de 2026 y un dividendo complementario de 0,42 euros\n"
            "por acción, sujeto a la aprobación de la junta.",
            "Todos los nombres, cifras y previsiones de este documento son ficticios y se han\n"
            "creado únicamente para probar la lectura automática de PDFs.",
        ])

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.08, 0.95, BANNER, color="#c62828", fontsize=9, weight="bold")
        fig.text(0.08, 0.91, "Principales magnitudes (millones de euros)", fontsize=14, weight="bold")
        rows = [
            ["Ingresos", "1.149", "1.245", "+8,4 %"],
            ["EBITDA", "281", "312", "+11,2 %"],
            ["Margen EBITDA", "24,5 %", "25,1 %", "+0,6 p.p."],
            ["Beneficio neto", "148", "158", "+6,9 %"],
            ["Deuda financiera neta", "940", "890", "-5,3 %"],
            ["BPA (euros)", "0,59", "0,63", "+6,8 %"],
        ]
        ax = fig.add_axes((0.08, 0.55, 0.84, 0.3))
        ax.axis("off")
        table = ax.table(cellText=rows, colLabels=["Magnitud", "3T 2025", "3T 2026", "Variación"],
                         loc="upper center", cellLoc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.6)
        fig.text(0.08, 0.5, "Desglose de ingresos por división (ficticio): Industrial 52 %, Servicios\n"
                 "digitales 34 %, Otros 14 %. Plantilla media: 6.480 empleados.", fontsize=10.5, va="top")
        pdf.savefig(fig)
        plt.close(fig)

        # Página 3: el gráfico se embebe como imagen raster para que pypdf pueda extraerlo y
        # enviarlo al modelo de visión (un gráfico vectorial no se podría extraer).
        days, data = _ohlc()
        chart_fig, (ax_p, ax_v) = plt.subplots(2, 1, figsize=(8, 5), dpi=100, height_ratios=(3, 1), sharex=True)
        _draw_candles(ax_p, ax_v, days, data, dark=False)
        ax_p.set_title(f"{TICKER} · cotización diaria jul-sep 2026 (ficticia)", fontsize=11)
        ax_p.set_ylabel("EUR")
        ax_v.set_ylabel("Vol. (M)")
        buf = io.BytesIO()
        chart_fig.savefig(buf, format="png", metadata={"Software": None})
        plt.close(chart_fig)
        buf.seek(0)
        image = plt.imread(buf)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.08, 0.95, BANNER, color="#c62828", fontsize=9, weight="bold")
        fig.text(0.08, 0.91, "Evolución bursátil", fontsize=14, weight="bold")
        ax = fig.add_axes((0.06, 0.45, 0.88, 0.42))
        ax.imshow(image)
        ax.axis("off")
        pdf.savefig(fig)
        plt.close(fig)
    return out


#: Posiciones de la captura de cartera de ejemplo (FICTICIAS): nombre, ticker, títulos, precio.
#: El valor y el peso se calculan; deben coincidir con ``portfolio.MOCK_SCREENSHOT_TRANSCRIPTION``.
PORTFOLIO_ROWS: list[tuple[str, str, int, float]] = [
    ("Banco Santander", "SAN", 1500, 4.52),
    ("Inditex", "ITX", 120, 48.10),
    ("Iberdrola", "IBE", 400, 13.25),
    ("Apple Inc.", "AAPL", 25, 205.40),
    ("NVIDIA Corp.", "NVDA", 60, 117.20),
]


def _es_num(value: float, decimals: int = 2) -> str:
    """``1234.5`` -> ``"1.234,50"`` (formato español)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def make_portfolio_png(out: Path) -> Path:
    """Captura ficticia de la pantalla «Mis posiciones» de una app de broker genérica (Pillow)."""
    from matplotlib import font_manager
    from PIL import Image, ImageDraw, ImageFont

    regular = font_manager.findfont("DejaVu Sans")
    bold = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight="bold"))

    def font(size: int, strong: bool = False) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(bold if strong else regular, size)

    width, height = 1000, 620
    bg, card, ink, muted, line = "#F4F6FA", "#FFFFFF", "#1B2333", "#6B7385", "#E3E7EF"
    accent, up, down = "#2F5BEA", "#14804A", "#C0392B"
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # Barra superior de una app genérica (sin marcas reales).
    draw.rectangle((0, 0, width, 64), fill=accent)
    draw.text((28, 18), "Tu broker (app ficticia)", font=font(22, True), fill="white")
    draw.text((width - 300, 22), "Cuenta de valores ·· 0000", font=font(16), fill="#DCE4FF")
    draw.text((28, 82), "Mis posiciones", font=font(26, True), fill=ink)
    draw.text((28, 118), "Ejemplo ficticio · datos inventados, no reales", font=font(15, True), fill=down)

    total = sum(q * p for _, _, q, p in PORTFOLIO_ROWS)
    draw.rounded_rectangle((28, 152, width - 28, 228), radius=12, fill=card, outline=line)
    draw.text((48, 164), "Valor total de la cartera", font=font(15), fill=muted)
    draw.text((48, 186), f"{_es_num(total)} €", font=font(26, True), fill=ink)
    draw.text((width - 290, 174), "Hoy  +0,84 %", font=font(20, True), fill=up)

    columns = [("Valor", 48), ("Títulos", 370), ("Precio", 490), ("Importe", 640), ("Peso", 820)]
    top = 248
    draw.rounded_rectangle((28, top, width - 28, height - 28), radius=12, fill=card, outline=line)
    for label, x in columns:
        draw.text((x, top + 16), label, font=font(15, True), fill=muted)
    draw.line((44, top + 46, width - 44, top + 46), fill=line, width=2)
    changes = ["+1,2 %", "-0,4 %", "+0,3 %", "+0,9 %", "+2,1 %"]
    for i, (name, ticker, qty, price) in enumerate(PORTFOLIO_ROWS):
        y = top + 60 + i * 56
        value = qty * price
        draw.text((48, y), name, font=font(18, True), fill=ink)
        draw.text((48, y + 24), f"{ticker} · {changes[i]}", font=font(14), fill=down if changes[i][0] == "-" else up)
        draw.text((370, y + 8), _es_num(qty, 0), font=font(18), fill=ink)
        draw.text((490, y + 8), f"{_es_num(price)} €", font=font(18), fill=ink)
        draw.text((640, y + 8), f"{_es_num(value)} €", font=font(18), fill=ink)
        pct = 100 * value / total
        draw.text((820, y + 8), f"{_es_num(pct, 1)} %", font=font(18), fill=ink)
        draw.rectangle((820, y + 34, 820 + int(120 * pct / 100 * 3), y + 38), fill=accent)
        if i < len(PORTFOLIO_ROWS) - 1:
            draw.line((44, y + 48, width - 44, y + 48), fill=line, width=1)

    img.save(out, format="PNG", optimize=True)
    return out


def main() -> None:
    png = make_chart_png(SAMPLES_DIR / "grafico_ejemplo.png")
    pdf = make_results_pdf(SAMPLES_DIR / "resultados_ejemplo.pdf")
    cartera = make_portfolio_png(SAMPLES_DIR / "cartera_ejemplo.png")
    for path in (png, pdf, cartera):
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
