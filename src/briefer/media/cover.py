"""Portada del episodio (opcional): texto a imagen + título superpuesto.

Carril C. Entrada: ``Analysis`` + ``ImageGenProvider`` (SDXL-Turbo local, notebook 4, o
mock). Salida: ruta PNG o ``None`` si no hay generador configurado.
"""

from __future__ import annotations

from pathlib import Path

from briefer.providers.base import ImageGenProvider
from briefer.schemas import Analysis


def build_cover_prompt(analysis: Analysis) -> str:
    """Prompt visual (en inglés suele funcionar mejor) a partir del tono del día."""
    # TODO: estilo fijo de marca ("minimalist editorial illustration, financial district,
    # morning light, ...") + matiz según sentimiento mayoritario de los key_points.
    # Sin texto ni cifras en el prompt (los modelos de difusión no escriben bien).
    raise NotImplementedError("build_cover_prompt: pendiente (carril C, opcional)")


def overlay_title(image_path: Path, title: str, date_text: str) -> Path:
    """Superpone título y fecha sobre la imagen con Pillow."""
    # TODO: PIL.ImageDraw con franja semitransparente inferior; fuente por defecto si no
    # hay TTF disponible (ImageFont.load_default()).
    raise NotImplementedError("overlay_title: pendiente (carril C, opcional)")


def make_cover(analysis: Analysis, image_gen: ImageGenProvider | None, out_dir: Path) -> Path | None:
    """Genera la portada; devuelve ``None`` si ``image_gen`` es ``None``."""
    # TODO: if image_gen is None: return None; p = image_gen.generate(build_cover_prompt(...),
    # out_dir / "cover.png"); overlay_title(p, analysis.headline, str(analysis.date)).
    raise NotImplementedError("make_cover: pendiente (carril C, opcional)")
