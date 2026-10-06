"""Portada del episodio (opcional): texto a imagen + título superpuesto.

Carril C. Entrada: ``Analysis`` + ``ImageGenProvider`` (Gemini «Nano Banana 2 Lite», SDXL-Turbo
local o mock). Salida: ruta PNG o ``None`` si no hay generador configurado.

- ``build_cover_prompt``: prompt en inglés con un **estilo fijo de marca** (ilustración editorial
  nocturna y minimalista, paleta «Noticiero nocturno» de ``docs/08_identidad_marca.md`` descrita
  con palabras) y un matiz según el **sentimiento mayoritario** de los puntos clave. Nunca lleva
  cifras, nombres de empresas ni el titular: los modelos de imagen escriben mal, una empresa
  invitaría a dibujar su logo y una flecha o un símbolo de compra/venta sonaría a recomendación.
- ``overlay_title``: el texto lo pone Pillow, no el modelo: franja inferior semitransparente con
  el titular (ajustado a varias líneas), «Briefly · fecha» y, en la esquina superior derecha, la
  marca **«Imagen generada por IA»** (obligatoria: transparencia del AI Act, art. 50).
- ``make_cover``: genera la imagen en ``out_dir/cover.png`` y le superpone los textos.
"""

from __future__ import annotations

import os
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from briefer import brand
from briefer.providers.base import ImageGenProvider
from briefer.schemas import Analysis

#: Marca de contenido sintético (AI Act, art. 50). Siempre visible en la portada.
AI_LABEL = "Imagen generada por IA"
#: Fuente de marca para titulares (OFL); si no está, ``ImageFont.load_default``.
FONT_PATH = brand.ASSETS_DIR / "fuentes" / "SourceSerif4-Variable.ttf"
#: Ancho mínimo del lienzo: las imágenes más pequeñas (mock 64x64) se amplían para que el texto se lea.
MIN_WIDTH = 1024
MAX_TITLE_LINES = 3

# Paleta «Noticiero nocturno» (docs/08_identidad_marca.md, tokens de app/components/theme.py).
_BG = (0x12, 0x15, 0x1B)
_ACCENT = (0xC0, 0x50, 0x2A)
_ACCENT_SOFT = (0xF0, 0x99, 0x7B)
_TEXT = (0xD6, 0xDE, 0xE8)
_TEXT_STRONG = (0xFF, 0xFF, 0xFF)
_TEXT_MUTED = (0x9A, 0x99, 0x92)

_MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

_BASE_STYLE = (
    "Minimalist editorial illustration for the cover of an evening financial news podcast. "
    "A quiet financial district at night seen from a distance: simple geometric buildings, a few "
    "warm lit windows, and one abstract flowing ribbon of light drifting across the sky. "
    "Flat shapes with subtle paper grain, calm and elegant, generous empty space in the lower "
    "third of the frame. Colour palette: deep charcoal-navy night, burnt orange as the single "
    "accent colour, soft coral highlights, muted grey-blue tones."
)
_MOODS = {
    "positivo": (
        "Mood: quietly optimistic; the ribbon of light rises gently and a faint warm glow "
        "touches the horizon."
    ),
    "negativo": (
        "Mood: sober and contemplative, not alarming; low heavy clouds, cooler blue shadows "
        "and rain-slick reflections, the ribbon of light dims and sinks slowly."
    ),
    "neutral": (
        "Mood: still and balanced; a calm steady night, the ribbon of light runs level and even."
    ),
}
_NEGATIVE = (
    "Strictly no text of any kind: no letters, no words, no numbers, no signage, no tickers, "
    "no labelled charts, no logos or brand marks, no recognisable people or faces, no arrows, "
    "no currency symbols, no buy or sell signs. Wide horizontal composition."
)


def dominant_sentiment(analysis: Analysis) -> str:
    """Sentimiento mayoritario de ``analysis.key_points``; ``"neutral"`` si no hay o hay empate."""
    counts = Counter(kp.sentiment for kp in analysis.key_points)
    if not counts:
        return "neutral"
    ranked = counts.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "neutral"
    return str(ranked[0][0])


def build_cover_prompt(analysis: Analysis) -> str:
    """Prompt visual en inglés: estilo fijo de marca + matiz del sentimiento del día.

    No incluye cifras, tickers, empresas ni el titular (los títulos se superponen después).
    """
    mood = _MOODS.get(dominant_sentiment(analysis), _MOODS["neutral"])
    return " ".join([_BASE_STYLE, mood, _NEGATIVE])


def format_date_es(value: Any) -> str:
    """``date`` -> «6 de octubre de 2026»; cualquier otra cosa, tal cual como texto."""
    try:
        return f"{value.day} de {_MONTHS_ES[value.month - 1]} de {value.year}"
    except (AttributeError, IndexError, TypeError):
        return str(value)


def cover_texts(title: str, date_text: str) -> dict[str, str]:
    """Textos que ``overlay_title`` dibuja (función pura, para tests y accesibilidad)."""
    clean = " ".join((title or "").split()) or brand.BRAND_NAME
    meta = f"{brand.BRAND_NAME} · {date_text}" if date_text else brand.BRAND_NAME
    return {"title": clean, "meta": meta, "ai_label": AI_LABEL}


def _font(size: int, weight: str = "SemiBold") -> Any:
    from PIL import ImageFont

    if FONT_PATH.exists():
        try:
            font = ImageFont.truetype(str(FONT_PATH), size)
            try:
                font.set_variation_by_name(weight)
            except Exception:  # noqa: BLE001 - sin variaciones: peso por defecto de la fuente
                pass
            return font
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 no admite tamaño
        return ImageFont.load_default()


def wrap_text(text: str, font: Any, max_width: float, draw: Any, max_lines: int = MAX_TITLE_LINES) -> list[str]:
    """Ajusta ``text`` a líneas de ``max_width`` px; si sobran, la última acaba en «…»."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(f"{last}…", font=font) > max_width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = f"{last.rstrip(' ,;:.')}…"
    return lines


def overlay_title(image_path: Path, title: str, date_text: str) -> Path:
    """Superpone titular, «Briefly · fecha» y la marca «Imagen generada por IA» (sobrescribe el PNG)."""
    from PIL import Image, ImageDraw

    image_path = Path(image_path)
    base = Image.open(image_path).convert("RGBA")
    if base.width < MIN_WIDTH:
        scale = MIN_WIDTH / base.width
        base = base.resize((MIN_WIDTH, max(1, round(base.height * scale))), Image.Resampling.LANCZOS)
    w, h = base.size
    texts = cover_texts(title, date_text)

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    margin = round(w * 0.045)
    title_font = _font(max(16, round(w * 0.038)))
    meta_font = _font(max(12, round(w * 0.019)), "Regular")
    label_font = _font(max(11, round(w * 0.016)), "Regular")

    # Franja inferior: titular + metadatos.
    lines = wrap_text(texts["title"], title_font, w - 2 * margin, draw)
    title_lh = round(title_font.size * 1.18) if hasattr(title_font, "size") else 20
    meta_h = round(meta_font.size * 1.3) if hasattr(meta_font, "size") else 16
    gap = round(margin * 0.3)
    pad_y = round(margin * 0.7)
    band_h = min(h, pad_y + meta_h + gap + title_lh * len(lines) + pad_y)
    top = h - band_h
    draw.rectangle([0, top, w, h], fill=(*_BG, 205))
    draw.rectangle([0, top, w, top + max(2, round(w * 0.003))], fill=(*_ACCENT, 255))
    y = top + pad_y
    brand_text = brand.BRAND_NAME
    draw.text((margin, y), brand_text, font=meta_font, fill=(*_ACCENT_SOFT, 255))
    rest = texts["meta"][len(brand_text):]
    if rest:
        x = margin + draw.textlength(brand_text, font=meta_font)
        draw.text((x, y), rest, font=meta_font, fill=(*_TEXT_MUTED, 255))
    y += meta_h + gap
    for line in lines:
        draw.text((margin, y), line, font=title_font, fill=(*_TEXT_STRONG, 255))
        y += title_lh

    # Marca de contenido generado por IA (esquina superior derecha), siempre visible.
    pad = round(w * 0.008) + 4
    lb = draw.textbbox((0, 0), texts["ai_label"], font=label_font)
    lw, lh = lb[2] - lb[0], lb[3] - lb[1]
    x1, y0 = w - round(margin * 0.5), round(margin * 0.5)
    x0, y1 = x1 - lw - 2 * pad, y0 + lh + 2 * pad
    draw.rounded_rectangle([x0, y0, x1, y1], radius=pad, fill=(*_BG, 215), outline=(*_TEXT_MUTED, 200))
    draw.text((x0 + pad - lb[0], y0 + pad - lb[1]), texts["ai_label"], font=label_font, fill=(*_TEXT, 255))

    out = Image.alpha_composite(base, layer).convert("RGB")
    tmp = image_path.with_name(f"{image_path.stem}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        out.save(tmp, format="PNG")
        os.replace(tmp, image_path)
    finally:
        tmp.unlink(missing_ok=True)
    return image_path


def make_cover(analysis: Analysis, image_gen: ImageGenProvider | None, out_dir: Path) -> Path | None:
    """Genera la portada en ``out_dir/cover.png``; devuelve ``None`` si ``image_gen`` es ``None``."""
    if image_gen is None:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = image_gen.generate(build_cover_prompt(analysis), out_dir / "cover.png")
    return overlay_title(path, analysis.headline, format_date_es(analysis.date))


__all__ = [
    "AI_LABEL",
    "build_cover_prompt",
    "cover_texts",
    "dominant_sentiment",
    "format_date_es",
    "make_cover",
    "overlay_title",
    "wrap_text",
]
