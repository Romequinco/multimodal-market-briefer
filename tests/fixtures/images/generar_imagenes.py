"""Genera las imágenes sintéticas de prueba del router CLIP (``tests/test_image_clip.py``).

Todo se dibuja aquí con matplotlib / Pillow (nada descargado de internet). Datos inventados.
Uso: ``.venv/Scripts/python tests/fixtures/images/generar_imagenes.py``.

- ``velas.png``: gráfico de velas japonesas con volumen, estilo plataforma de *trading*.
- ``lineas.png``: gráfico de líneas de cotización con fechas y rejilla.
- ``tabla.png``: tabla de cuenta de resultados (cifras por año).
- ``cartera.png``: captura de móvil de un bróker con las posiciones de la cartera.
- ``paisaje.jpg``: «foto» de paisaje en JPEG (cielo, montañas, lago, árboles), no financiera.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

OUT = Path(__file__).resolve().parent
RNG = np.random.default_rng(7)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def velas() -> None:
    n = 60
    close = 4.2 + np.cumsum(RNG.normal(0, 0.05, n))
    open_ = np.r_[close[0], close[:-1]] + RNG.normal(0, 0.02, n)
    high = np.maximum(open_, close) + RNG.uniform(0.01, 0.06, n)
    low = np.minimum(open_, close) - RNG.uniform(0.01, 0.06, n)
    vol = RNG.uniform(2, 9, n)
    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(8, 5), dpi=80, sharex=True, gridspec_kw={"height_ratios": [4, 1]}
    )
    for a in (ax, axv):
        a.set_facecolor("#131722")
        a.grid(color="#2a2e39", linewidth=0.6)
        a.tick_params(colors="#b2b5be", labelsize=8)
    fig.patch.set_facecolor("#131722")
    for i in range(n):
        up = close[i] >= open_[i]
        color = "#26a69a" if up else "#ef5350"
        ax.vlines(i, low[i], high[i], color=color, linewidth=1)
        ax.add_patch(
            Rectangle(
                (i - 0.35, min(open_[i], close[i])), 0.7, abs(close[i] - open_[i]) or 0.004, color=color
            )
        )
        axv.bar(i, vol[i], color=color, width=0.7)
    ax.set_xlim(-1, n)
    ax.yaxis.tick_right()
    ax.set_title("SAN.MC · Banco Santander · 1D", color="#d1d4dc", loc="left", fontsize=10)
    axv.set_xticks(range(0, n, 10), [f"{d} ago" for d in range(1, 61, 10)])
    fig.tight_layout()
    fig.savefig(OUT / "velas.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def lineas() -> None:
    n = 250
    price = 180 + np.cumsum(RNG.normal(0.08, 1.6, n))
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=80)
    ax.plot(range(n), price, color="#1f77b4", linewidth=1.6)
    ax.fill_between(range(n), price, price.min() - 5, color="#1f77b4", alpha=0.08)
    ax.set_title("AAPL · Cotización último año (USD)", loc="left")
    ax.set_xticks(range(0, n, 50), ["oct", "dic", "feb", "abr", "jun"])
    ax.set_ylabel("Precio (USD)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "lineas.png")
    plt.close(fig)


def tabla() -> None:
    rows = [
        ("Ingresos", "45.210", "48.930", "+8,2 %"),
        ("Margen bruto", "18.044", "19.880", "+10,2 %"),
        ("EBITDA", "12.310", "13.775", "+11,9 %"),
        ("Amortizaciones", "-3.120", "-3.290", "+5,4 %"),
        ("EBIT", "9.190", "10.485", "+14,1 %"),
        ("Resultado financiero", "-1.050", "-980", "-6,7 %"),
        ("Beneficio neto", "6.480", "7.415", "+14,4 %"),
        ("BPA (EUR)", "0,41", "0,47", "+14,6 %"),
        ("Deuda neta", "21.300", "19.850", "-6,8 %"),
    ]
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=80)
    ax.axis("off")
    ax.set_title("Cuenta de resultados consolidada (millones EUR)", loc="left", fontsize=12, weight="bold")
    table = ax.table(
        cellText=[list(r) for r in rows],
        colLabels=["Concepto", "2024", "2025", "Var. %"],
        loc="center",
        cellLoc="right",
        colLoc="right",
        colWidths=[0.42, 0.18, 0.18, 0.16],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.45)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#d0d7de")
        if r == 0:
            cell.set_facecolor("#1f3a5f")
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        elif r % 2 == 0:
            cell.set_facecolor("#f3f6f9")
        if c == 0:
            cell.get_text().set_horizontalalignment("left")
    fig.tight_layout()
    fig.savefig(OUT / "tabla.png")
    plt.close(fig)


def cartera() -> None:
    w, h = 390, 780
    img = Image.new("RGB", (w, h), "#ffffff")
    d = ImageDraw.Draw(img)
    # Barra de estado del móvil y cabecera de la app.
    d.text((20, 12), "9:41", fill="#111111", font=_font(14, True))
    d.text((300, 12), "4G  87%", fill="#111111", font=_font(13))
    d.text((20, 50), "Mi cartera", fill="#111111", font=_font(26, True))
    d.text((20, 92), "Valor total", fill="#6b7280", font=_font(14))
    d.text((20, 112), "24.583,17 €", fill="#111111", font=_font(30, True))
    d.text((20, 152), "+312,40 € (+1,29 %) hoy", fill="#16a34a", font=_font(15))
    # Pestañas.
    for i, tab in enumerate(["Posiciones", "Órdenes", "Movimientos"]):
        x = 20 + i * 120
        d.text((x, 195), tab, fill="#111111" if i == 0 else "#9ca3af", font=_font(15, i == 0))
    d.line((20, 220, 110, 220), fill="#2563eb", width=3)
    d.line((0, 224, w, 224), fill="#e5e7eb", width=1)
    positions = [
        ("SAN", "Banco Santander", "1.200 acc.", "5.214,00 €", "+2,10 %"),
        ("ITX", "Inditex", "85 acc.", "4.301,85 €", "-0,84 %"),
        ("IBE", "Iberdrola", "300 acc.", "3.912,00 €", "+0,45 %"),
        ("AAPL", "Apple Inc.", "15 acc.", "3.088,52 €", "+1,72 %"),
        ("MSFT", "Microsoft", "8 acc.", "3.011,40 €", "-0,31 %"),
        ("BBVA", "BBVA", "350 acc.", "3.367,00 €", "+1,05 %"),
        ("REP", "Repsol", "140 acc.", "1.688,40 €", "-1,22 %"),
    ]
    y = 238
    for tick, name, qty, value, chg in positions:
        d.ellipse((20, y + 4, 60, y + 44), fill="#e0e7ff")
        d.text((40, y + 24), tick[:2], fill="#3730a3", font=_font(13, True), anchor="mm")
        d.text((72, y + 4), tick, fill="#111111", font=_font(16, True))
        d.text((72, y + 26), f"{name} · {qty}", fill="#6b7280", font=_font(12))
        d.text((w - 20, y + 4), value, fill="#111111", font=_font(16, True), anchor="ra")
        color = "#16a34a" if chg.startswith("+") else "#dc2626"
        d.text((w - 20, y + 26), chg, fill=color, font=_font(13), anchor="ra")
        d.line((20, y + 58, w - 20, y + 58), fill="#f0f0f0", width=1)
        y += 66
    # Barra de navegación inferior.
    d.line((0, h - 64, w, h - 64), fill="#e5e7eb", width=1)
    for i, tab in enumerate(["Inicio", "Cartera", "Mercados", "Perfil"]):
        d.text(
            (50 + i * 97, h - 34), tab, fill="#2563eb" if i == 1 else "#9ca3af", font=_font(12), anchor="mm"
        )
    img.save(OUT / "cartera.png", optimize=True)


def paisaje() -> None:
    w, h = 640, 427
    y = np.linspace(0, 1, h)[:, None, None]
    sky = (1 - y) * np.array([70, 130, 200]) + y * np.array([235, 200, 160])
    arr = np.broadcast_to(sky, (h, w, 3)).astype(np.float64).copy()
    img = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(img)
    d.ellipse((470, 60, 540, 130), fill=(255, 236, 180))
    xs = np.arange(0, w + 20, 20)
    for base, amp, color in [(230, 110, (95, 105, 130)), (270, 70, (60, 85, 70))]:
        ridge = base - amp * np.abs(np.sin(xs / 90 + base)) - RNG.uniform(0, 15, len(xs))
        d.polygon([(0, h), *zip(xs.tolist(), ridge.tolist(), strict=True), (w, h)], fill=color)
    d.rectangle((0, 300, w, h), fill=(70, 120, 150))
    for _ in range(40):
        x = int(RNG.uniform(0, w))
        d.line(
            (x, int(RNG.uniform(305, h)), x + int(RNG.uniform(10, 40)), int(RNG.uniform(305, h))),
            fill=(150, 185, 205),
        )
    for x in range(10, w, 38):
        top = int(RNG.uniform(200, 250))
        d.polygon([(x, 305), (x + 15, top), (x + 30, 305)], fill=(30, 60, 40))
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    noise = RNG.normal(0, 6, (h, w, 3))
    out = np.clip(np.asarray(img, dtype=np.float64) + noise, 0, 255).astype(np.uint8)
    Image.fromarray(out).save(OUT / "paisaje.jpg", quality=85)


if __name__ == "__main__":
    for fn in (velas, lineas, tabla, cartera, paisaje):
        fn()
    print("Imágenes generadas en", OUT)
