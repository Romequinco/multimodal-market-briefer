"""«Impacto de la noticia» (FinBERT) fuera del pipeline: lectura tolerante de ``news_impact.json``
(``storage``), copia al exportar y etiqueta junto a cada fuente en «Puntos clave» (sin red ni torch)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from briefer import storage
from briefer.schemas import Briefing

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components import players, theme  # noqa: E402

ROW = {"news_id": "ejemplo-001", "impact": "negativo", "score": 0.91, "probs": {"negativo": 0.91},
       "text_en": "Shares fall", "translated": True, "model": "ProsusAI/finbert"}


def _write_impact(folder: Path, rows: object) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / storage.NEWS_IMPACT_FILE
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


# ── storage ───────────────────────────────────────────────────────────────────────


def test_load_news_impact_from_dir_file_and_briefing(sample_briefing: Briefing, tmp_path: Path) -> None:
    path = _write_impact(tmp_path, [ROW, {"news_id": "x", "impact": "raro"}, "basura", {"impact": "positivo"}])
    expected = {"ejemplo-001": ROW}
    assert storage.load_news_impact(tmp_path) == expected
    assert storage.load_news_impact(path) == expected
    # el briefing de ejemplo tiene el audio en tmp_path: su carpeta se deduce de sus ficheros
    assert storage.load_news_impact(sample_briefing) == expected


def test_load_news_impact_tolerant(sample_briefing: Briefing, tmp_path: Path) -> None:
    assert storage.load_news_impact(tmp_path / "no-existe") == {}
    assert storage.load_news_impact(sample_briefing, base_dir=tmp_path / "outputs") == {}
    (tmp_path / storage.NEWS_IMPACT_FILE).write_text("{roto", encoding="utf-8")
    assert storage.load_news_impact(tmp_path) == {}
    _write_impact(tmp_path, {"no": "es una lista"})
    assert storage.load_news_impact(tmp_path) == {}


def test_load_news_impact_from_outputs_folder(sample_briefing: Briefing, tmp_path: Path) -> None:
    """Sin ficheros en el briefing, se busca en ``<outputs>/<id>/``."""
    bare = sample_briefing.model_copy(update={"audio": None, "transcript": None, "charts": [], "cover_path": None})
    base = tmp_path / "outputs"
    _write_impact(base / bare.id, [ROW])
    assert storage.load_news_impact(bare, base_dir=base) == {"ejemplo-001": ROW}


def test_export_briefing_copies_news_impact(sample_briefing: Briefing, tmp_path: Path) -> None:
    (tmp_path / "podcast.mp3").write_bytes(b"ID3")
    _write_impact(tmp_path, [ROW])
    dest = tmp_path / "export"
    storage.export_briefing(sample_briefing, dest)
    assert json.loads((dest / storage.NEWS_IMPACT_FILE).read_text("utf-8")) == [ROW]
    assert storage.load_news_impact(storage.load_briefing(dest)) == {"ejemplo-001": ROW}

    (tmp_path / storage.NEWS_IMPACT_FILE).unlink()
    other = tmp_path / "export2"
    storage.export_briefing(sample_briefing, other)
    assert not (other / storage.NEWS_IMPACT_FILE).exists()


# ── UI ────────────────────────────────────────────────────────────────────────────


def test_impact_chip_html_symbol_word_and_tooltip() -> None:
    chip = theme.impact_chip_html("positivo")
    assert "impacto de la noticia: ▲ positiva · FinBERT" in chip and "mb-up" in chip
    assert "no es una recomendación" in chip  # tooltip (title)
    assert "▼ negativa" in theme.impact_chip_html("negativo") and "mb-down" in theme.impact_chip_html("negativo")
    assert "● neutral" in theme.impact_chip_html("neutral")
    assert theme.impact_chip_html(None) == "" and theme.impact_chip_html("<b>") == ""


def test_keypoint_card_shows_impact_per_source() -> None:
    kp = {"title": "T", "explanation": "E", "sentiment": "neutral"}
    sources = [("Noticia 1", "https://a.example"), ("Noticia 2", "https://b.example")]
    html = theme.keypoint_card_html(kp, sources, impacts=["negativo", None])
    assert html.count('class="mb-impact ') == 1 and "▼ negativa" in html
    assert "no es una recomendación de compra o venta" in html
    plain = theme.keypoint_card_html(kp, sources)
    assert "mb-impact" not in plain and "FinBERT" not in plain
    assert "mb-impact" not in theme.keypoint_card_html(kp, sources, compact=True, impacts=["positivo"])


def test_source_impact_maps_by_id_or_url(sample_briefing: Briefing) -> None:
    news = players._news_index(sample_briefing)
    item = sample_briefing.context.news[0]
    impacts = {item.id: {"impact": "positivo"}}
    assert players.source_impact(item.id, news, impacts) == "positivo"
    assert players.source_impact(item.url, news, impacts) == "positivo"
    assert players.source_impact("otra", news, impacts) is None


def _render(briefing_json: str) -> None:
    from briefer.schemas import Briefing as B
    from components import players as p

    p.render_key_points(B.model_validate_json(briefing_json))


def _html(at: AppTest) -> str:
    return "".join(h.proto.body for h in at.get("html"))


def test_render_key_points_with_and_without_impact(sample_briefing: Briefing, tmp_path: Path) -> None:
    data = sample_briefing.model_dump_json()
    at = AppTest.from_function(_render, args=(data,), default_timeout=30).run()
    assert not at.exception and "impacto de la noticia" not in _html(at)

    _write_impact(tmp_path, [ROW])  # carpeta del briefing de ejemplo (su audio está en tmp_path)
    at = AppTest.from_function(_render, args=(data,), default_timeout=30).run()
    assert not at.exception
    body = _html(at)
    assert "impacto de la noticia: ▼ negativa · FinBERT" in body
    assert "no es una recomendación" in body


def _tabs(briefing_json: str) -> None:
    import streamlit as st

    from briefer.schemas import Briefing as B
    from components import players as p

    tabs = p.briefing_tabs(B.model_validate_json(briefing_json))
    st.write(len(tabs))


def test_briefing_tabs_show_video_tab_only_with_video(sample_briefing: Briefing, tmp_path: Path) -> None:
    """El vídeo 9:16 tiene su propia pestaña (antes quedaba escondido al final de «Gráficos»)."""
    from briefer.schemas import VideoAsset

    at = AppTest.from_function(_tabs, args=(sample_briefing.model_dump_json(),), default_timeout=30).run()
    assert not at.exception and [t.label for t in at.tabs] == ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]

    mp4 = tmp_path / "briefing.mp4"
    mp4.write_bytes(b"\x00")
    with_video = sample_briefing.model_copy(update={"video": VideoAsset(path=mp4, duration_s=1.0)})
    at = AppTest.from_function(_tabs, args=(with_video.model_dump_json(),), default_timeout=30).run()
    assert not at.exception and [t.label for t in at.tabs][:2] == ["Puntos clave", "Vídeo"]
