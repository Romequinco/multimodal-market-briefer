"""Tema «Noticiero nocturno» (``app/components/theme.py``): escape de HTML en los helpers,
``apply_theme`` idempotente y las 5 páginas con el tema aplicado sin excepciones (AppTest, sin red)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from briefer import pipeline, storage
from briefer.config import reset_settings_cache
from briefer.schemas import KeyPoint, PriceSnapshot

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components import theme  # noqa: E402

EVIL = '<script>alert("x")</script>'
PAGES = ["main.py", "pages/1_Briefing.py", "pages/2_Preguntar.py", "pages/3_Mi_cartera.py",
         "pages/4_Historico.py"]


def _styles(at: AppTest) -> list[str]:
    return [h.proto.body for h in at.get("html") if "<style>" in h.proto.body]


# ── Escape de HTML ─────────────────────────────────────────────────────────────────


def test_headline_escapes_html() -> None:
    out = theme.headline_html(EVIL, [EVIL, "5:27"])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out and "5:27" in out


def test_keypoint_card_escapes_and_only_links_http() -> None:
    kp = KeyPoint(title=EVIL, explanation=f"texto {EVIL}", tickers=["<b>X</b>"], sentiment="negativo",
                  sources=["n1"])
    out = theme.keypoint_card_html(kp, [(EVIL, "javascript:alert(1)"), ('a" onmouseover="x', "https://ok.example/?a=1&b=<2>")])
    assert "<script>" not in out and "<b>X</b>" not in out
    assert "javascript:" not in out                      # URL no http(s): sin enlace
    assert 'href="https://ok.example/?a=1&amp;b=&lt;2&gt;"' in out
    assert 'a&quot; onmouseover=&quot;x' in out          # no se puede romper el atributo
    assert "mb-kp--down" in out and "▼ negativo" in out  # borde y texto por sentimiento


def test_keypoint_card_compact_hides_explanation() -> None:
    kp = KeyPoint(title="T", explanation="larga explicación", sentiment="positivo")
    out = theme.keypoint_card_html(kp, [("fuente", "https://a.b")], compact=True)
    assert "larga explicación" not in out and "Fuentes" not in out and "mb-kp--up" in out


def test_ticker_tape_escapes_and_marks_direction() -> None:
    prices = [
        PriceSnapshot(ticker="SAN.MC", last=8.5, change_pct=2.37, currency="EUR"),
        PriceSnapshot(ticker="ITX.MC", last=50, change_pct=-1.2, currency="EUR"),
        PriceSnapshot(ticker="^IBEX", last=15234.5, change_pct=0.0, currency="EUR"),
        {"ticker": EVIL, "last": 1, "change_pct": 0.5},
    ]
    out = theme.ticker_tape_html(prices, names={"^IBEX": "IBEX 35"}, indices=["^IBEX"])
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "▲ +2,37 %" in out and "▼ -1,20 %" in out and "● 0,00 %" in out
    assert "15.234,50" in out and "IBEX 35" in out and "mb-idx" in out
    assert theme.ticker_tape_html([]) == ""


def test_other_helpers_escape() -> None:
    for out in (
        theme.tech_label(EVIL), theme.pill_html(EVIL), theme.player_header_html(EVIL, [EVIL], EVIL),
        theme.legend_html([("x", '"><script>', EVIL)]), theme.masthead_meta_html(EVIL),
    ):
        assert "<script>" not in out, out


def test_fmt_date_and_css() -> None:
    assert theme.fmt_date(date(2026, 10, 5)) == "LUN · 05/10/2026"
    css = theme.theme_css()
    assert "#D85A30" in css and "prefers-reduced-motion" in css and "%(" not in css


# ── apply_theme y páginas ──────────────────────────────────────────────────────────


def _twice(app_dir: str) -> None:
    import sys

    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from components.theme import apply_theme

    apply_theme()
    apply_theme()


def test_apply_theme_is_idempotent_per_run() -> None:
    at = AppTest.from_function(_twice, args=(str(APP_DIR),), default_timeout=30).run()
    assert not at.exception
    assert len(_styles(at)) == 1
    at.run()  # en cada recarga se vuelve a inyectar (una vez)
    assert len(_styles(at)) == 1


@pytest.fixture
def demo_samples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import shutil

    real = Path(__file__).resolve().parents[1] / "data" / "samples"
    samples = tmp_path / "samples"
    samples.mkdir()
    for f in real.iterdir():
        if f.is_file():
            shutil.copy2(f, samples / f.name)
    monkeypatch.setenv("BRIEFER_SAMPLES_DIR", str(samples))
    reset_settings_cache()
    storage.export_briefing(pipeline.run_briefing(["SAN.MC", "AAPL"], use_mock=True),
                            storage.demo_briefing_dir(samples))
    for path in storage.list_briefings():
        path.unlink()
    return samples


@pytest.mark.parametrize("page", PAGES)
def test_every_page_applies_theme_without_errors(page: str, demo_samples: Path) -> None:
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=60).run()
    assert not at.exception, at.exception
    assert len(_styles(at)) == 1, "el CSS del tema se inyecta una vez por página"


def test_home_themed_elements(demo_samples: Path) -> None:
    at = AppTest.from_file(str(APP_DIR / "main.py"), default_timeout=60).run()
    assert not at.exception
    bodies = "\n".join(h.proto.body for h in at.get("html"))
    assert "mb-tape" in bodies and "en antena" in bodies and "mb-headline" in bodies
    assert "mb-player" in bodies and "mb-kp" in bodies
    ask = next(b for b in at.button if b.label == "Preguntar sobre este briefing")
    assert ask.proto.type == "primary"
