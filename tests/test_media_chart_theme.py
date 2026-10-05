"""Temas de los gráficos PNG (``BRIEFER_CHART_THEME``): oscuro por defecto y claro seleccionable."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from matplotlib.text import Text
from PIL import Image

from briefer.config import Settings, reset_settings_cache
from briefer.media import charts
from briefer.schemas import Portfolio, Position, PriceSnapshot

DARK_BG = (0x12, 0x15, 0x1B)


def _snap(ticker: str, change: float, days: int = 22, start: float = 100.0) -> PriceSnapshot:
    history = [(date(2026, 9, 7) + timedelta(days=i), round(start * (1 + 0.004 * i), 2)) for i in range(days)]
    return PriceSnapshot(ticker=ticker, last=history[-1][1], change_pct=change, currency="EUR", history=history)


def _prices() -> list[PriceSnapshot]:
    return [_snap("SAN.MC", 2.4), _snap("AAPL", -1.1), _snap("^IBEX", 0.5, start=19000)]


def _portfolio() -> Portfolio:
    return Portfolio(name="Test", positions=[Position(ticker="SAN.MC", weight=0.7),
                                             Position(ticker="AAPL", weight=0.3)])


def _corner(path: Path) -> tuple[int, int, int]:
    with Image.open(path) as img:
        assert img.size == (1920, 1080)
        return img.convert("RGB").getpixel((2, 2))


def _close(rgb: tuple[int, int, int], target: tuple[int, int, int], tol: int = 3) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(rgb, target, strict=True))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_both_themes_generate_valid_pngs(tmp_path: Path, theme: str) -> None:
    assets = charts.make_charts(_prices(), tmp_path, portfolio=_portfolio(), theme=theme)
    assert [a.kind for a in assets] == ["overview_bar", "price_line", "price_line", "price_line", "portfolio_pie"]
    for asset in assets:
        with Image.open(asset.path) as img:
            img.verify()  # PNG íntegro
        corner = _corner(asset.path)
        if theme == "dark":
            assert _close(corner, DARK_BG), corner
        else:
            assert _close(corner, (0xFC, 0xFC, 0xFB)), corner


def test_default_theme_is_dark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings.model_fields["briefer_chart_theme"].default == "dark"
    # Sin variable de entorno y sin leer el .env local (que podría fijar otro tema).
    monkeypatch.delenv("BRIEFER_CHART_THEME", raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    reset_settings_cache()
    try:
        assert charts.resolve_theme(None) is charts.DARK
        asset = charts.make_price_chart(_snap("SAN.MC", 1.0), tmp_path)  # theme=None -> config
        assert _close(_corner(asset.path), DARK_BG)
    finally:
        reset_settings_cache()


def test_theme_from_env_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIEFER_CHART_THEME", "light")
    reset_settings_cache()
    try:
        assert charts.resolve_theme(None) is charts.LIGHT
        asset = charts.make_overview_chart(_prices(), tmp_path)
        assert _close(_corner(asset.path), (0xFC, 0xFC, 0xFB))
    finally:
        reset_settings_cache()
    assert charts.resolve_theme(" Dark ") is charts.DARK
    with pytest.raises(ValueError):
        charts.make_charts(_prices(), tmp_path, theme="sepia")


def test_dark_keeps_arrows_signs_and_fonts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Accesibilidad: el color nunca es la única pista (▲/▼ y signo); serif en títulos, mono en cifras."""
    captured: list[list[Text]] = []
    real_save = charts._save

    def spy(fig, path):
        captured.append([t for t in fig.findobj(Text) if t.get_text()])
        return real_save(fig, path)

    monkeypatch.setattr(charts, "_save", spy)
    charts.make_price_chart(_snap("AAPL", -1.1), tmp_path, theme="dark")
    charts.make_overview_chart(_prices(), tmp_path, theme="dark")
    price, overview = captured
    words = [t.get_text() for t in price]
    assert "▼ −1,10 %" in words
    assert any(t.get_text().startswith("Apple") and "DejaVu Serif" in t.get_fontfamily() for t in price)
    badge = next(t for t in price if t.get_text() == "▼ −1,10 %")
    assert "DejaVu Sans Mono" in badge.get_fontfamily()
    over = [t.get_text() for t in overview]
    assert "▲ +2,40 %" in over and "▼ −1,10 %" in over and "▲ +0,50 %" in over
