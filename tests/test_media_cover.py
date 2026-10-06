"""Portada del episodio (sin red): prompt de marca, superposición de textos y marca «generada por IA»."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from briefer import brand
from briefer.media import cover
from briefer.providers.mock import MockImageGen
from briefer.schemas import Analysis, KeyPoint


def _analysis(*sentiments: str, headline: str = "El IBEX sube un 1,2 % y Santander lidera") -> Analysis:
    kps = [
        KeyPoint(
            title=f"Punto {i}",
            explanation="Sube 3,5 % SAN.MC",
            tickers=["SAN.MC"],
            sentiment=s,  # type: ignore[arg-type]
        )
        for i, s in enumerate(sentiments)
    ]
    return Analysis(date=date(2026, 10, 6), headline=headline, key_points=kps, market_mood="mixto")


def _png(path: Path, size: tuple[int, int] = (1344, 768)) -> Path:
    Image.new("RGB", size, (40, 60, 90)).save(path)
    return path


# ── Prompt ──────────────────────────────────────────────────────────────────────


def test_prompt_has_no_figures_tickers_or_headline() -> None:
    prompt = cover.build_cover_prompt(_analysis("positivo", "positivo", "negativo"))
    assert not re.search(r"\d", prompt)  # sin cifras (ni %, ni colores en hexadecimal)
    assert "SAN" not in prompt and "Santander" not in prompt and "IBEX" not in prompt
    low = prompt.lower()
    for must in ("no text", "no numbers", "no logos", "no recognisable people", "no buy or sell"):
        assert must in low
    assert "editorial illustration" in low and "night" in low and "burnt orange" in low


def test_prompt_changes_with_dominant_sentiment() -> None:
    pos = cover.build_cover_prompt(_analysis("positivo", "positivo", "neutral"))
    neg = cover.build_cover_prompt(_analysis("negativo", "negativo", "positivo"))
    neu = cover.build_cover_prompt(_analysis("neutral"))
    assert len({pos, neg, neu}) == 3
    assert "optimistic" in pos and "sober" in neg and "balanced" in neu


@pytest.mark.parametrize(
    ("sentiments", "expected"),
    [((), "neutral"), (("positivo", "negativo"), "neutral"), (("negativo", "negativo", "positivo"), "negativo")],
)
def test_dominant_sentiment_ties_and_empty(sentiments: tuple[str, ...], expected: str) -> None:
    assert cover.dominant_sentiment(_analysis(*sentiments)) == expected


def test_format_date_es() -> None:
    assert cover.format_date_es(date(2026, 10, 6)) == "6 de octubre de 2026"
    assert cover.format_date_es("ayer") == "ayer"


# ── Superposición ───────────────────────────────────────────────────────────────


def test_cover_texts_always_include_ai_label_and_brand() -> None:
    texts = cover.cover_texts("  Titular   del día ", "6 de octubre de 2026")
    assert texts["ai_label"] == cover.AI_LABEL == "Imagen generada por IA"
    assert texts["title"] == "Titular del día"
    assert texts["meta"] == f"{brand.BRAND_NAME} · 6 de octubre de 2026"
    assert cover.cover_texts("", "")["title"] == brand.BRAND_NAME


def test_overlay_keeps_size_and_draws_band_and_ai_label(tmp_path: Path) -> None:
    path = _png(tmp_path / "c.png")
    before = Image.open(path).convert("RGB").copy()
    out = cover.overlay_title(path, "Santander lidera las subidas del IBEX tras las elecciones", "6 de octubre de 2026")
    after = Image.open(out).convert("RGB")
    assert out == path and after.size == before.size
    w, h = after.size
    assert after.getpixel((w // 2, h - 5)) != before.getpixel((w // 2, h - 5))  # franja inferior
    # Esquina superior derecha (marca IA): algún píxel cambia; la superior izquierda, no.
    corner = [(x, y) for x in range(w - 300, w - 20, 7) for y in range(20, 80, 5)]
    assert any(after.getpixel(p) != before.getpixel(p) for p in corner)
    assert after.getpixel((10, 10)) == before.getpixel((10, 10))


def test_overlay_upscales_small_images(tmp_path: Path) -> None:
    out = cover.overlay_title(_png(tmp_path / "s.png", (64, 64)), "Titular", "hoy")
    assert Image.open(out).size == (cover.MIN_WIDTH, cover.MIN_WIDTH)


def test_overlay_without_brand_font_uses_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cover, "FONT_PATH", tmp_path / "no-existe.ttf")
    out = cover.overlay_title(_png(tmp_path / "d.png"), "Titular sin fuente de marca", "hoy")
    assert Image.open(out).size == (1344, 768)


def test_wrap_text_limits_lines_with_ellipsis() -> None:
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = cover._font(40)
    lines = cover.wrap_text(" ".join(["palabra"] * 60), font, 400, draw, max_lines=3)
    assert len(lines) == 3 and lines[-1].endswith("…")
    assert all(draw.textlength(line, font=font) <= 400 for line in lines)


# ── make_cover ──────────────────────────────────────────────────────────────────


def test_make_cover_with_mock_image_gen(tmp_path: Path) -> None:
    out = cover.make_cover(_analysis("positivo"), MockImageGen(), tmp_path / "out")
    assert out is not None and out == tmp_path / "out" / "cover.png" and out.exists()
    assert Image.open(out).size == (cover.MIN_WIDTH, cover.MIN_WIDTH)


def test_make_cover_without_provider_returns_none(tmp_path: Path) -> None:
    assert cover.make_cover(_analysis("neutral"), None, tmp_path) is None
    assert not any(tmp_path.iterdir())


def test_local_diffusion_gets_short_prompt(tmp_path) -> None:
    """Los modelos locales (CLIP corta en 77 tokens) reciben el prompt corto con el matiz del día."""
    from briefer import storage
    from briefer.media import cover

    analysis = storage.load_demo_briefing().analysis
    prompts: list[str] = []

    class FakeLocal:
        provider_name = "sdxl_turbo"
        model = "fake"

        def generate(self, prompt, out_path):
            from PIL import Image

            prompts.append(prompt)
            Image.new("RGB", (768, 432), "navy").save(out_path)
            return out_path

    cover.make_cover(analysis, FakeLocal(), tmp_path)
    assert prompts == [cover.build_cover_prompt_local(analysis)]
    assert len(prompts[0].split()) < 70 and not any(ch.isdigit() for ch in prompts[0])
