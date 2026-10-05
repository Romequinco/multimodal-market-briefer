"""Marca Briefly en la UI y activos de ``docs/assets/marca/`` (sin red; no regenera nada).

Los activos los produce ``scripts/generar_marca.py`` y se versionan: aquí solo se comprueba que están,
que tienen el tamaño esperado y que los SVG llevan el texto convertido a trazados.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from briefer import brand

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components import brand as ui_brand  # noqa: E402

MARCA = brand.ASSETS_DIR
SVGS = ("briefly_logo_oscuro.svg", "briefly_logo_claro.svg", "briefly_logo_mono.svg", "briefly_icono.svg",
        "briefly_vertical.svg", "briefly_velas.svg")
PNGS = {
    "briefly_icono_32.png": (32, 32),
    "briefly_icono_192.png": (192, 192),
    "briefly_icono_512.png": (512, 512),
    "briefly_banner.png": (1280, 320),
}


# ── Activos versionados ──────────────────────────────────────────────────────────────


def test_generator_script_exists() -> None:
    assert (ROOT / "scripts" / "generar_marca.py").is_file()


@pytest.mark.parametrize("name", SVGS)
def test_svg_assets_exist_and_have_outlined_text(name: str) -> None:
    path = MARCA / name
    assert path.is_file(), f"falta {name}: python scripts/generar_marca.py"
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    assert root.tag.endswith("svg") and root.get("viewBox")
    tags = {el.tag.split("}")[-1] for el in root.iter()}
    assert "text" not in tags, "el texto debe ir convertido a trazados (<path>)"
    assert {"rect", "line"} <= tags  # las velas: cuerpo + mecha
    if name not in ("briefly_icono.svg", "briefly_velas.svg"):
        assert "path" in tags  # el logotipo «briefly»


@pytest.mark.parametrize("name,size", PNGS.items())
def test_png_assets_have_expected_size(name: str, size: tuple[int, int]) -> None:
    with Image.open(MARCA / name) as img:
        assert img.size == size


def test_logo_png_is_wide_and_transparent() -> None:
    with Image.open(MARCA / "briefly_logo_oscuro.png") as img:
        assert img.width == 1200 and img.height < img.width
        assert img.mode == "RGBA" and img.getpixel((0, 0))[3] == 0


def test_svg_colors_follow_the_brand() -> None:
    dark = (MARCA / "briefly_logo_oscuro.svg").read_text(encoding="utf-8")
    assert "#F0997B" in dark and "#C0502A" in dark and "#FFFFFF" in dark
    light = (MARCA / "briefly_logo_claro.svg").read_text(encoding="utf-8")
    assert "#1C2129" in light and "#FFFFFF" not in light
    mono = (MARCA / "briefly_logo_mono.svg").read_text(encoding="utf-8")
    assert "#C0502A" not in mono and "#F0997B" not in mono


def test_font_is_bundled_with_its_license() -> None:
    fonts = MARCA / "fuentes"
    assert (fonts / "SourceSerif4-Variable.ttf").is_file()
    assert "SIL Open Font License" in (fonts / "OFL.txt").read_text(encoding="utf-8")


# ── Helpers de marca de la UI ────────────────────────────────────────────────────────


def test_page_icon_uses_brand_icon_when_present() -> None:
    icon = ui_brand.page_icon(":material/forum:")
    assert icon.endswith(ui_brand.ICON_FILE) and Path(icon).is_file()


def test_page_icon_falls_back_when_asset_is_missing(tmp_path: Path) -> None:
    assert ui_brand.page_icon(":material/forum:", assets_dir=tmp_path) == ":material/forum:"
    assert ui_brand.page_icon(assets_dir=tmp_path) == ui_brand.FALLBACK_ICON
    assert ui_brand.sidebar_logo(assets_dir=tmp_path) is False
    assert ui_brand.mark_html(assets_dir=tmp_path) == ""


def test_page_title_and_mark() -> None:
    assert ui_brand.page_title() == brand.BRAND_NAME
    assert ui_brand.page_title("Histórico") == f"Histórico · {brand.BRAND_NAME}"
    html = ui_brand.mark_html()
    assert html.startswith('<img class="mb-mark" src="data:image/svg+xml;base64,') and 'alt=""' in html


def test_no_old_brand_name_left_in_app() -> None:
    for path in APP_DIR.rglob("*.py"):
        assert "Market Briefer" not in path.read_text(encoding="utf-8"), path


# ── Página «Quiénes somos» ──────────────────────────────────────────────────────────


def test_about_page_renders_hosts_and_synthetic_voice_note() -> None:
    at = AppTest.from_file(str(APP_DIR / "pages" / "5_Quienes_somos.py"), default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "Quiénes somos"
    html = "\n".join(str(getattr(e, "proto", e)) for e in at.get("html"))
    markdown = "\n".join(str(m.value) for m in at.markdown)
    for name in (brand.SPEAKER_A_NAME, brand.SPEAKER_B_NAME):
        assert name in html
    assert "sintética (IA)" in html
    assert "M-30" in markdown and brand.COMPLIANCE_MOTTO in markdown
    assert "un toro y una osa" in markdown
    assert any("voces sintéticas generadas por IA" in i.value for i in at.info)
    assert any("Aviso:" in c.value for c in at.caption), "el aviso legal va en todas las páginas"
