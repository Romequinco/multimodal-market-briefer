"""Marca en la UI (carril C): favicon, logo de la barra lateral y títulos de página.

Los textos (nombre, eslogan, locutores) salen de ``briefer.brand``; los ficheros de imagen, de
``docs/assets/marca/`` (``scripts/generar_marca.py``). Si falta algún fichero la app **no se rompe**:
el favicon vuelve al icono Material de cada página y el logo de la barra lateral simplemente no se pinta.
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from briefer import brand

ICON_FILE = "briefly_icono_192.png"
LOGO_FILE = "briefly_logo_oscuro.png"
MARK_FILE = "briefly_velas.svg"
FALLBACK_ICON = ":material/podcasts:"


def asset(name: str, assets_dir: Path | None = None) -> Path | None:
    """Ruta de un activo de marca si existe (``None`` si falta)."""
    path = (assets_dir or brand.ASSETS_DIR) / name
    return path if path.is_file() else None


def page_icon(fallback: str = FALLBACK_ICON, assets_dir: Path | None = None) -> str:
    """Favicon para ``st.set_page_config``: el icono de Briefly o, si no está, el icono Material."""
    path = asset(ICON_FILE, assets_dir)
    return str(path) if path else fallback


def page_title(section: str | None = None) -> str:
    """Título de la pestaña del navegador: ``"Briefing · Briefly"`` o solo ``"Briefly"``."""
    return f"{section} · {brand.BRAND_NAME}" if section else brand.BRAND_NAME


def setup_page(section: str | None = None, fallback_icon: str = FALLBACK_ICON) -> None:
    """``st.set_page_config`` común (título, favicon y ``layout="wide"``) + logo de la barra lateral."""
    st.set_page_config(page_title=page_title(section), page_icon=page_icon(fallback_icon), layout="wide")
    sidebar_logo()


def sidebar_logo(assets_dir: Path | None = None) -> bool:
    """Logo horizontal en la barra lateral (``st.logo``) e icono para la barra plegada. ``True`` si se pintó."""
    logo = asset(LOGO_FILE, assets_dir)
    if logo is None or not hasattr(st, "logo"):
        return False
    icon = asset(ICON_FILE, assets_dir)
    try:
        st.logo(str(logo), size="large", icon_image=str(icon) if icon else None)
    except Exception:  # versión de Streamlit sin algún parámetro: el logo es decorativo
        return False
    return True


def mark_path(assets_dir: Path | None = None) -> Path | None:
    """Las cuatro velas sin texto (para la cabecera de la portada), si el fichero existe."""
    return asset(MARK_FILE, assets_dir)


def mark_html(height: int = 40, assets_dir: Path | None = None) -> str:
    """``<img>`` decorativo (``alt=""``) con las velas en *data URI*; cadena vacía si falta el fichero.

    Va junto al título «Briefly» de la cabecera: el nombre ya lo lee el lector de pantalla en el ``h1``.
    """
    path = mark_path(assets_dir)
    if path is None:
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return (f'<img class="mb-mark" src="data:image/svg+xml;base64,{data}" alt="" aria-hidden="true" '
            f'height="{int(height)}" width="{int(height)}">')


__all__ = [
    "FALLBACK_ICON",
    "ICON_FILE",
    "LOGO_FILE",
    "MARK_FILE",
    "asset",
    "mark_html",
    "mark_path",
    "page_icon",
    "page_title",
    "setup_page",
    "sidebar_logo",
]
