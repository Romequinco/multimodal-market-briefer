"""Genera los activos de marca de **Briefly** en ``docs/assets/marca/`` (reproducible).

Uso::

    python scripts/generar_marca.py

Logo «LG1-A · velas-ecualizador» (``docs/08_identidad_marca.md``): cuatro velas japonesas (mecha fina +
cuerpo redondeado) a alturas de ecualizador, alternando ``#F0997B`` y ``#C0502A``, a la izquierda de la
palabra «briefly» en minúscula con Source Serif 4 seminegrita (600).

Cómo se construye:

- La tipografía es la **fuente variable Source Serif 4** del repositorio oficial de Google Fonts
  (``docs/assets/marca/fuentes/``, licencia SIL OFL 1.1 en ``OFL.txt``). Se instancia en memoria con
  ``fontTools`` (peso 600 para la marca, 400 para el eslogan); el fichero original no se modifica.
- El texto se **convierte a trazados** (``<path>``): los SVG se ven igual en cualquier sitio (GitHub,
  navegadores sin la fuente, editores) y no dependen de fuentes instaladas. Se aplica el *kerning* de la
  fuente (tabla GPOS).
- Los PNG se rasterizan con Pillow **a partir de la misma geometría** (supermuestreo ×4), así que PNG y
  SVG coinciden.

Nombre, eslogan y carpeta de salida salen de ``briefer.brand`` (fuente única de la marca).
Requiere ``fonttools`` (``requirements-dev.txt``; ya llega como dependencia de matplotlib) y Pillow.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image, ImageDraw

from briefer import brand

OUT_DIR = brand.ASSETS_DIR
FONT_FILE = OUT_DIR / "fuentes" / "SourceSerif4-Variable.ttf"

# ── Paleta (tokens del tema «Noticiero nocturno», app/components/theme.py) ──────────
BG = "#12151B"
SURFACE = "#1C2129"
ACCENT = "#C0502A"
ACCENT_SOFT = "#F0997B"
WHITE = "#FFFFFF"
MUTED = "#9A9992"

WORDMARK = brand.BRAND_NAME.lower()
SS = 4  # supermuestreo de los PNG

# ── Geometría de las velas (unidades del viewBox de referencia 0 0 240 90) ──────────
#: (x de la mecha, y1, y2, cuerpo x, y, ancho, alto, color)
CANDLES: tuple[tuple[float, float, float, float, float, float, float, str], ...] = (
    (18, 28, 70, 12, 38, 12, 24, ACCENT_SOFT),
    (36, 16, 76, 30, 24, 12, 42, ACCENT),
    (54, 34, 66, 48, 42, 12, 16, ACCENT_SOFT),
    (72, 10, 74, 66, 18, 12, 48, ACCENT),
)
CANDLES_BOX = (12.0, 10.0, 78.0, 76.0)  # x0, y0, x1, y1
WICK_WIDTH = 2.4
BODY_RADIUS = 2.0


# ── Escena mínima (formas comunes a SVG y PNG) ────────────────────────────────────


@dataclass
class Line:
    x: float
    y1: float
    y2: float
    width: float
    color: str


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    rx: float
    color: str


@dataclass
class Glyphs:
    """Texto ya convertido a contornos: ``contours`` en coordenadas de usuario (para PNG) y ``d`` (SVG)."""

    d: str
    contours: list[list[tuple[float, float]]]
    color: str


Shape = Line | Rect | Glyphs


@dataclass
class Scene:
    width: float
    height: float
    shapes: list[Shape]
    background: str | None = None
    title: str = ""


# ── Tipografía ────────────────────────────────────────────────────────────────────


class _FlattenPen(BasePen):
    """Convierte contornos (cuadráticas y cúbicas) en polígonos para rasterizar con Pillow."""

    def __init__(self, glyph_set: Any, steps: int = 12) -> None:
        super().__init__(glyph_set)
        self.contours: list[list[tuple[float, float]]] = []
        self._cur: list[tuple[float, float]] = []
        self.steps = steps

    def _moveTo(self, pt: tuple[float, float]) -> None:  # noqa: N802 (API de fontTools)
        self._cur = [pt]

    def _lineTo(self, pt: tuple[float, float]) -> None:  # noqa: N802
        self._cur.append(pt)

    def _curveToOne(self, p1, p2, p3) -> None:  # noqa: N802
        (x0, y0) = self._cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self._cur.append((
                u**3 * x0 + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * y0 + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            ))

    def _qCurveToOne(self, p1, p2) -> None:  # noqa: N802
        (x0, y0) = self._cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self._cur.append((u * u * x0 + 2 * u * t * p1[0] + t * t * p2[0],
                              u * u * y0 + 2 * u * t * p1[1] + t * t * p2[1]))

    def _closePath(self) -> None:  # noqa: N802
        if len(self._cur) > 2:
            self.contours.append(self._cur)
        self._cur = []

    _endPath = _closePath


class Face:
    """Instancia estática (en memoria) de la fuente variable, con avances y *kerning* GPOS."""

    def __init__(self, wght: float, opsz: float) -> None:
        font = TTFont(str(FONT_FILE))
        self.font = instancer.instantiateVariableFont(font, {"wght": wght, "opsz": opsz})
        self.upem = self.font["head"].unitsPerEm
        self.cmap = self.font.getBestCmap()
        self.glyph_set = self.font.getGlyphSet()
        self.hmtx = self.font["hmtx"]
        self._kern = self._kern_lookups()
        os2 = self.font["OS/2"]
        self.cap_height = getattr(os2, "sCapHeight", 0) or 0.66 * self.upem
        self.x_height = getattr(os2, "sxHeight", 0) or 0.47 * self.upem

    def _kern_lookups(self) -> list[Any]:
        if "GPOS" not in self.font:
            return []
        gpos = self.font["GPOS"].table
        indices: list[int] = []
        for rec in gpos.FeatureList.FeatureRecord:
            if rec.FeatureTag == "kern":
                indices.extend(rec.Feature.LookupListIndex)
        lookups = gpos.LookupList.Lookup
        return [lookups[i] for i in sorted(set(indices))]

    def kerning(self, left: str, right: str) -> int:
        total = 0
        for lookup in self._kern:
            for sub in lookup.SubTable:
                st = sub.ExtSubTable if lookup.LookupType == 9 else sub
                if getattr(st, "LookupType", 2) != 2 or left not in st.Coverage.glyphs:
                    continue
                value = None
                if st.Format == 1:
                    pairs = st.PairSet[st.Coverage.glyphs.index(left)].PairValueRecord
                    for pv in pairs:
                        if pv.SecondGlyph == right:
                            value = pv.Value1
                            break
                elif st.Format == 2:
                    c1 = st.ClassDef1.classDefs.get(left, 0)
                    c2 = st.ClassDef2.classDefs.get(right, 0)
                    value = st.Class1Record[c1].Class2Record[c2].Value1
                if value is not None and getattr(value, "XAdvance", 0):
                    total += value.XAdvance
                    break
        return total

    def layout(self, text: str, tracking: float = 0.0) -> list[tuple[str, float]]:
        """``[(glifo, x en unidades de fuente)]`` y el avance total al final (glifo vacío)."""
        names = [self.cmap[ord(ch)] for ch in text]
        out: list[tuple[str, float]] = []
        x = 0.0
        for i, name in enumerate(names):
            out.append((name, x))
            x += self.hmtx[name][0] + tracking * self.upem
            if i + 1 < len(names):
                x += self.kerning(name, names[i + 1])
        out.append(("", x - tracking * self.upem))
        return out

    def advance(self, text: str, size: float, tracking: float = 0.0) -> float:
        return self.layout(text, tracking)[-1][1] * size / self.upem

    def ink_bounds(self, text: str, size: float, tracking: float = 0.0) -> tuple[float, float]:
        """Primer y último x con tinta (descuenta el margen lateral de los glifos extremos)."""
        g = self.text(text, 0, 0, size, WHITE, tracking)
        xs = [p[0] for c in g.contours for p in c]
        return min(xs), max(xs)

    def text(self, text: str, x: float, baseline: float, size: float, color: str,
             tracking: float = 0.0) -> Glyphs:
        scale = size / self.upem
        parts: list[str] = []
        contours: list[list[tuple[float, float]]] = []
        for name, gx in self.layout(text, tracking)[:-1]:
            matrix = (scale, 0, 0, -scale, x + gx * scale, baseline)
            svg = SVGPathPen(self.glyph_set, ntos=_num)
            self.glyph_set[name].draw(TransformPen(svg, matrix))
            if svg.getCommands():
                parts.append(svg.getCommands())
            flat = _FlattenPen(self.glyph_set)
            self.glyph_set[name].draw(TransformPen(flat, matrix))
            contours.extend(flat.contours)
        return Glyphs(" ".join(parts), contours, color)


def _num(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


# ── Piezas del logo ───────────────────────────────────────────────────────────────


def candles(dx: float = 0, dy: float = 0, scale: float = 1.0, color: str | None = None,
            wick: float = WICK_WIDTH) -> list[Shape]:
    """Las cuatro velas (mecha + cuerpo), desplazadas y escaladas; ``color`` fuerza una sola tinta."""
    shapes: list[Shape] = []
    for wx, y1, y2, bx, by, bw, bh, c in CANDLES:
        ink = color or c
        shapes.append(Line(dx + wx * scale, dy + y1 * scale, dy + y2 * scale, wick * scale, ink))
        shapes.append(Rect(dx + bx * scale, dy + by * scale, bw * scale, bh * scale, BODY_RADIUS * scale, ink))
    return shapes


#: Wordmark: tamaño y separación respecto a las velas (unidades del viewBox de referencia).
WORD_SIZE = 40.0
WORD_GAP = 14.0
WORD_TRACKING = -0.012


def horizontal(face: Face, word_color: str, candle_color: str | None = None,
               background: str | None = None, pad: float = 8.0) -> Scene:
    """Logo horizontal: velas a la izquierda y «briefly» centrado ópticamente en la altura de las velas."""
    x0, y0, x1, y1 = CANDLES_BOX
    shapes = candles(dx=pad - x0, dy=pad - y0, color=candle_color)
    ink_l, ink_r = face.ink_bounds(WORDMARK, WORD_SIZE, WORD_TRACKING)
    # Centro óptico: mitad de la altura de ascendentes (b, f, l) sobre la línea base.
    asc = face.cap_height * WORD_SIZE / face.upem * 1.06
    mid = pad + (y1 - y0) / 2
    baseline = mid + asc / 2
    word_x = pad + (x1 - x0) + WORD_GAP - ink_l
    shapes.append(face.text(WORDMARK, word_x, baseline, WORD_SIZE, word_color, WORD_TRACKING))
    width = word_x + ink_r + pad
    height = (y1 - y0) + 2 * pad
    return Scene(width, height, shapes, background, f"{brand.BRAND_NAME}")


def mark(pad: float = 2.0) -> Scene:
    """Solo las cuatro velas, en color y sin texto (cabecera de la app, junto al nombre en HTML)."""
    x0, y0, x1, y1 = CANDLES_BOX
    return Scene((x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad, candles(dx=pad - x0, dy=pad - y0), None,
                 f"{brand.BRAND_NAME} · velas")


def icon(size: float = 512, small: bool = False) -> Scene:
    """Icono cuadrado (rx ≈ 22 %) en ``#C0502A`` con las cuatro velas en blanco, centradas.

    ``small`` (favicon de 32 px): velas algo más grandes y mechas más gruesas para que no se pierdan.
    """
    x0, y0, x1, y1 = CANDLES_BOX
    target = size * (0.66 if small else 0.56)
    scale = target / max(x1 - x0, y1 - y0)
    dx = (size - (x1 - x0) * scale) / 2 - x0 * scale
    dy = (size - (y1 - y0) * scale) / 2 - y0 * scale
    shapes: list[Shape] = [Rect(0, 0, size, size, size * 0.22, ACCENT)]
    shapes += candles(dx, dy, scale, color=WHITE, wick=WICK_WIDTH * (1.6 if small else 1.0))
    return Scene(size, size, shapes, None, f"{brand.BRAND_NAME} · icono")


def vertical(face: Face, tag_face: Face) -> Scene:
    """Versión vertical: velas arriba, «briefly» y el eslogan debajo (portadas, pitch, cierre de vídeo)."""
    x0, y0, x1, y1 = CANDLES_BOX
    word_size = 64.0
    tag_size = 19.0
    word_l, word_r = face.ink_bounds(WORDMARK, word_size, WORD_TRACKING)
    tag_l, tag_r = tag_face.ink_bounds(brand.TAGLINE, tag_size)
    width = max(word_r - word_l, tag_r - tag_l) + 48
    scale = 1.7
    cw, ch = (x1 - x0) * scale, (y1 - y0) * scale
    top = 24.0
    shapes = candles(dx=(width - cw) / 2 - x0 * scale, dy=top - y0 * scale, scale=scale)
    word_base = top + ch + 22 + face.cap_height * word_size / face.upem * 1.06
    shapes.append(face.text(WORDMARK, (width - (word_r - word_l)) / 2 - word_l, word_base, word_size,
                            WHITE, WORD_TRACKING))
    tag_base = word_base + 26 + tag_face.cap_height * tag_size / tag_face.upem
    shapes.append(tag_face.text(brand.TAGLINE, (width - (tag_r - tag_l)) / 2 - tag_l, tag_base, tag_size, MUTED))
    height = tag_base + 26
    return Scene(width, height, shapes, None, f"{brand.BRAND_NAME} · {brand.TAGLINE}")


def banner(face: Face, tag_face: Face, width: int = 1280, height: int = 320) -> Scene:
    """Banner del README (1280×320 sobre ``#12151B``): logo horizontal grande y eslogan debajo."""
    logo = horizontal(face, WHITE, pad=0)
    scale = 2.1
    tag_size = 30.0
    tag_l, tag_r = tag_face.ink_bounds(brand.TAGLINE, tag_size)
    logo_w, logo_h = logo.width * scale, logo.height * scale
    gap = 34.0
    tag_cap = tag_face.cap_height * tag_size / tag_face.upem
    block_h = logo_h + gap + tag_cap
    top = (height - block_h) / 2
    left = (width - logo_w) / 2
    shapes: list[Shape] = [_scaled(s, scale, left, top) for s in logo.shapes]
    tag_base = top + logo_h + gap + tag_cap
    shapes.append(tag_face.text(brand.TAGLINE, (width - (tag_r - tag_l)) / 2 - tag_l, tag_base, tag_size, MUTED))
    # Filete «en antena» bajo el eslogan.
    shapes.append(Rect((width - 56) / 2, tag_base + 26, 56, 3, 1.5, ACCENT))
    return Scene(width, height, shapes, BG, f"{brand.BRAND_NAME} · {brand.TAGLINE}")


def _scaled(shape: Shape, k: float, dx: float, dy: float) -> Shape:
    if isinstance(shape, Line):
        return Line(dx + shape.x * k, dy + shape.y1 * k, dy + shape.y2 * k, shape.width * k, shape.color)
    if isinstance(shape, Rect):
        return Rect(dx + shape.x * k, dy + shape.y * k, shape.w * k, shape.h * k, shape.rx * k, shape.color)
    contours = [[(dx + x * k, dy + y * k) for x, y in c] for c in shape.contours]
    return Glyphs("", contours, shape.color)  # solo para PNG


# ── Salida SVG ────────────────────────────────────────────────────────────────────


def to_svg(scene: Scene) -> str:
    w, h = _num(scene.width), _num(scene.height)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" aria-label="{scene.title}">',
        f"<title>{scene.title}</title>",
    ]
    if scene.background:
        out.append(f'<rect width="100%" height="100%" fill="{scene.background}"/>')
    for s in scene.shapes:
        if isinstance(s, Line):
            out.append(f'<line x1="{_num(s.x)}" y1="{_num(s.y1)}" x2="{_num(s.x)}" y2="{_num(s.y2)}" '
                       f'stroke="{s.color}" stroke-width="{_num(s.width)}" stroke-linecap="round"/>')
        elif isinstance(s, Rect):
            out.append(f'<rect x="{_num(s.x)}" y="{_num(s.y)}" width="{_num(s.w)}" height="{_num(s.h)}" '
                       f'rx="{_num(s.rx)}" fill="{s.color}"/>')
        else:
            out.append(f'<path fill="{s.color}" d="{s.d}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ── Salida PNG (misma geometría, supermuestreo) ───────────────────────────────────


def _rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _orientation(contour: list[tuple[float, float]]) -> int:
    """+1 o -1 según el sentido de giro del contorno (área con signo, fórmula del lazo)."""
    pairs = zip(contour, contour[1:] + contour[:1], strict=True)
    area = sum(xa * yb - xb * ya for (xa, ya), (xb, yb) in pairs)
    return 1 if area >= 0 else -1


def render(scene: Scene, width_px: int, height_px: int | None = None) -> Image.Image:
    """Rasteriza la escena a ``width_px`` de ancho (supermuestreo ×``SS`` y reducción LANCZOS)."""
    k = width_px / scene.width
    W = width_px * SS  # noqa: N806
    H = round(height_px or scene.height * k) * SS  # noqa: N806
    s = k * SS
    canvas = Image.new("RGBA", (W, H), (*_rgb(scene.background), 255) if scene.background else (0, 0, 0, 0))
    for shape in scene.shapes:
        mask = Image.new("L", (W, H), 0)
        draw = ImageDraw.Draw(mask)
        if isinstance(shape, Line):
            r = shape.width * s / 2
            draw.rounded_rectangle((shape.x * s - r, shape.y1 * s - r, shape.x * s + r, shape.y2 * s + r),
                                   radius=r, fill=255)
        elif isinstance(shape, Rect):
            draw.rounded_rectangle((shape.x * s, shape.y * s, (shape.x + shape.w) * s, (shape.y + shape.h) * s),
                                   radius=shape.rx * s, fill=255)
        else:
            # Regla «nonzero» (la de TrueType y SVG): la fuente variable conserva contornos solapados, así
            # que se suma el sentido de giro de cada contorno relleno y hay tinta donde la suma no es 0.
            winding = np.zeros((H, W), dtype=np.int16)
            for contour in shape.contours:
                pts = [(x * s, y * s) for x, y in contour]
                x0 = max(int(min(p[0] for p in pts)) - 1, 0)
                y0 = max(int(min(p[1] for p in pts)) - 1, 0)
                x1 = min(int(max(p[0] for p in pts)) + 2, W)
                y1 = min(int(max(p[1] for p in pts)) + 2, H)
                if x1 <= x0 or y1 <= y0:
                    continue
                layer = Image.new("L", (x1 - x0, y1 - y0), 0)
                ImageDraw.Draw(layer).polygon([(x - x0, y - y0) for x, y in pts], fill=255)
                inside = np.asarray(layer) > 127
                winding[y0:y1, x0:x1] += inside.astype(np.int16) * _orientation(contour)
            mask = Image.fromarray(np.where(winding != 0, 255, 0).astype(np.uint8), "L")
        color = Image.new("RGBA", (W, H), (*_rgb(shape.color), 255))
        canvas.paste(color, (0, 0), mask)
    small = canvas.convert("RGBa").resize((W // SS, H // SS), Image.Resampling.LANCZOS).convert("RGBA")
    return small


def save_png(img: Image.Image, name: str) -> Path:
    path = OUT_DIR / name
    img.save(path, optimize=True)
    return path


def save_svg(scene: Scene, name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(to_svg(scene), encoding="utf-8", newline="\n")
    return path


def main() -> int:
    if not FONT_FILE.exists():
        print(f"Falta la fuente {FONT_FILE.relative_to(ROOT)} (ver docs/assets/marca/fuentes/).", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    word = Face(wght=600, opsz=60)
    tag = Face(wght=400, opsz=20)

    dark = horizontal(word, WHITE)
    written = [
        save_svg(dark, "briefly_logo_oscuro.svg"),
        save_svg(horizontal(word, SURFACE), "briefly_logo_claro.svg"),
        save_svg(horizontal(word, SURFACE, candle_color=SURFACE), "briefly_logo_mono.svg"),
        save_svg(icon(), "briefly_icono.svg"),
        save_svg(mark(), "briefly_velas.svg"),
        save_svg(vertical(word, tag), "briefly_vertical.svg"),
    ]
    ico = icon()
    for px in (32, 192, 512):
        scene = icon(small=True) if px <= 32 else ico
        written.append(save_png(render(scene, px, px), f"briefly_icono_{px}.png"))
    written.append(save_png(render(dark, 1200), "briefly_logo_oscuro.png"))
    written.append(save_png(render(banner(word, tag), 1280, 320), "briefly_banner.png"))
    for path in written:
        print(f"{path.relative_to(ROOT)}  ({path.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
