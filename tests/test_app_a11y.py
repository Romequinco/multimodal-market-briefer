"""Accesibilidad del tema «Noticiero nocturno»: contraste WCAG de los tokens, foco visible y que la
información no dependa solo del color (funciones puras, sin Streamlit en ejecución)."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from briefer.schemas import KeyPoint

pytest.importorskip("streamlit")

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components import theme  # noqa: E402


def test_contrast_ratio_reference_values() -> None:
    assert theme.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert theme.contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    assert theme.contrast_ratio("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)  # caso límite conocido
    assert theme.contrast_ratio("#fff", "#000") == pytest.approx(21.0)
    assert theme.contrast_ratio("text", "bg") == theme.contrast_ratio(theme.TOKENS["text"], theme.TOKENS["bg"])
    with pytest.raises(ValueError):
        theme.relative_luminance("#12")


@pytest.mark.parametrize("fg,bg,minimum,usage", theme.CONTRAST_PAIRS,
                         ids=[f"{f}-on-{b}" for f, b, _, _ in theme.CONTRAST_PAIRS])
def test_token_pairs_meet_wcag_aa(fg: str, bg: str, minimum: float, usage: str) -> None:
    ratio = theme.contrast_ratio(fg, bg)
    assert ratio >= minimum, f"{usage}: {fg} sobre {bg} = {ratio:.2f}:1 (< {minimum}:1)"


def test_previous_failing_values_are_gone() -> None:
    """Los valores que no cumplían (muted sobre tarjetas; texto blanco sobre el naranja) ya no se usan."""
    assert theme.contrast_ratio("#888780", theme.TOKENS["surface"]) < 4.5
    assert theme.contrast_ratio("#FFFFFF", "#D85A30") < 4.5
    css = theme.theme_css()
    assert "#888780" not in css and "#D85A30" not in css.upper() and "#c24f29" not in css


def test_streamlit_config_matches_tokens() -> None:
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
    t = theme.TOKENS
    assert config["primaryColor"].upper() == t["accent"].upper()
    assert config["backgroundColor"].upper() == t["bg"].upper()
    assert config["secondaryBackgroundColor"].upper() == t["surface"].upper()
    assert config["textColor"].upper() == t["text"].upper()
    assert config["linkColor"].upper() == t["accent-soft"].upper()
    assert config["grayColor"].upper() == t["text-muted"].upper()
    for key in ("greenColor", "redColor", "orangeColor"):  # colores semánticos de Streamlit como texto
        assert theme.contrast_ratio(config[key], t["surface"]) >= 4.5, key
    assert theme.contrast_ratio("#FFFFFF", config["primaryColor"]) >= 4.5


def test_focus_ring_and_control_borders_in_css() -> None:
    css = theme.theme_css()
    assert ":focus-visible" in css and "outline: 2px solid var(--mb-accent-soft)" in css
    assert "--mb-border-strong" in css and "[data-baseweb=\"input\"]" in css
    assert "prefers-reduced-motion" in css


@pytest.mark.parametrize("sentiment,label", [("positivo", "▲ positivo"), ("negativo", "▼ negativo"),
                                             ("neutral", "● neutral")])
def test_sentiment_not_conveyed_by_color_only(sentiment: str, label: str) -> None:
    out = theme.keypoint_card_html(KeyPoint(title="T", explanation="E", sentiment=sentiment))
    assert label in out  # icono + palabra, además del color del borde


def test_ticker_tape_has_arrow_and_sign() -> None:
    out = theme.ticker_tape_html([{"ticker": "A", "last": 1, "change_pct": 1.5},
                                  {"ticker": "B", "last": 1, "change_pct": -2.0}])
    assert "▲ +1,50 %" in out and "▼ -2,00 %" in out
    assert 'aria-label="Cotizaciones de la sesión"' in out
