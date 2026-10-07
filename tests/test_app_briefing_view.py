"""Vista unificada de un briefing (``components/briefing_view.py``): helpers puros (HTML escapado) y
``render_briefing_view`` con AppTest (portada con IA, vídeo, audio que falta). Sin red."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from ui_helpers import APP_DIR, TIMEOUT  # noqa: E402

from briefer import brand  # noqa: E402
from briefer.schemas import AudioAsset, Briefing, ScriptLine, StepMetric, VideoAsset  # noqa: E402
from components import briefing_view as bv  # noqa: E402,I001

EVIL = '<script>alert("x")</script>'


def _with_metrics(b: Briefing, provider: str) -> Briefing:
    return b.model_copy(update={"metrics": [
        StepMetric(step="agents.analyst", provider=provider, model="m", latency_s=0.1)]})


# ── Helpers puros ──────────────────────────────────────────────────────────────────


def test_origin_label(sample_briefing: Briefing) -> None:
    assert bv.origin_label(sample_briefing, "archivo") == "Del archivo · 05/10/2026"
    assert bv.origin_label(sample_briefing, "nuevo") == "Recién generado · 05/10/2026"
    assert bv.origin_label(sample_briefing, None) == "" and bv.origin_label(sample_briefing, "otro") == ""
    assert set(bv.ORIGIN_LABELS) == {"guardado", "pregenerado", "archivo", "nuevo"}


def test_origin_pill_text_marks_demo(sample_briefing: Briefing) -> None:
    demo, real = _with_metrics(sample_briefing, "mock"), _with_metrics(sample_briefing, "anthropic")
    assert bv.origin_pill_text(demo, "pregenerado") == "Ejemplo pregenerado · simulado"
    assert bv.origin_pill_text(real, "pregenerado") == "Ejemplo pregenerado · datos y modelos reales"
    saved_demo, saved_real = bv.origin_pill_text(demo, "guardado"), bv.origin_pill_text(real, "guardado")
    assert saved_demo.startswith("Último guardado") and saved_demo.endswith(" · demo")
    assert saved_real.startswith("Último guardado") and "demo" not in saved_real
    assert bv.origin_pill_text(real, "archivo") == "Del archivo · 05/10/2026"
    assert bv.origin_pill_text(real, None) == ""


def test_hero_meta(sample_briefing: Briefing) -> None:
    assert bv.hero_meta(sample_briefing) == ["05/10/2026", "0:02 min", "2 voces sintéticas", "SAN.MC"]
    silent = sample_briefing.model_copy(update={"audio": None})
    assert bv.hero_meta(silent) == ["05/10/2026", "2 voces sintéticas", "SAN.MC"]


def test_hero_head_html_escapes(sample_briefing: Briefing) -> None:
    analysis = sample_briefing.analysis.model_copy(update={"headline": EVIL, "market_mood": EVIL})
    b = sample_briefing.model_copy(update={"analysis": analysis})
    out = bv.hero_head_html(b, "archivo")
    assert "<script>" not in out and out.count("&lt;script&gt;") == 2
    assert "Del archivo · 05/10/2026" in out and 'class="mb-hero__title"' in out
    assert "mb-hero__tickers" in out and "SAN.MC" in out
    assert "mb-hero__origin" not in bv.hero_head_html(b)  # sin origen, sin etiqueta


def test_voices_html_names_and_synthetic_note() -> None:
    out = bv.voices_html()
    assert brand.SPEAKER_A_NAME in out and brand.SPEAKER_B_NAME in out
    assert bv.VOICE_NOTE in out and "no son personas reales" in bv.VOICE_NOTE
    assert "&lt;b&gt;" in bv.voices_html({"A": "<b>", "B": "Osa"})


def test_transcript_lines_use_script_text_and_segment_times(sample_briefing: Briefing) -> None:
    assert bv.transcript_lines(sample_briefing) == [("A", "Hola", 0.0), ("B", "Buenas", 1.0)]
    # Guion y segmentos que no casan uno a uno: el texto del guion, sin tiempos.
    script = sample_briefing.script.model_copy(update={"lines": [*sample_briefing.script.lines,
                                                                  ScriptLine(speaker="A", text="Adiós")]})
    mismatch = sample_briefing.model_copy(update={"script": script})
    assert [t for *_, t in bv.transcript_lines(mismatch)] == [None, None, None]
    # Sin guion: los segmentos del audio.
    no_script = sample_briefing.model_copy(update={"script": script.model_copy(update={"lines": []})})
    assert bv.transcript_lines(no_script) == [("A", "Hola", 0.0), ("B", "Buenas", 1.0)]
    assert bv.transcript_lines(no_script.model_copy(update={"audio": None})) == []


def test_transcript_html_escapes_and_names() -> None:
    out = bv.transcript_html([("A", EVIL, 65.0), ("B", "vale", None)], {"A": "Toro", "B": "Osa"})
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "Toro <span>1:05</span>" in out and "mb-badge--b" in out and ">O<" in out


def test_is_today(sample_briefing: Briefing) -> None:
    assert bv.is_today(sample_briefing, today=date(2026, 10, 5))
    assert not bv.is_today(sample_briefing, today=date(2026, 10, 6))


# ── render_briefing_view con AppTest ───────────────────────────────────────────────


def _render(app_dir: str, briefing_json: str, origin: str | None) -> None:
    import sys

    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from briefer.schemas import Briefing as B
    from components.briefing_view import render_briefing_view

    render_briefing_view(B.model_validate_json(briefing_json), key="t", origin=origin)


def _run(b: Briefing, origin: str | None = None):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_render, args=(str(APP_DIR), b.model_dump_json(), origin), default_timeout=TIMEOUT)
    return at.run()


def _image_captions(at) -> list[str]:
    return [img.caption for el in at.get("image") for img in el.proto.imgs]


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (8, 8), "#C0502A").save(path)
    return path


def test_render_full_briefing(sample_briefing: Briefing, tmp_path: Path) -> None:
    import wave

    audio = tmp_path / "pod.wav"
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    b = sample_briefing.model_copy(update={
        "audio": AudioAsset(path=audio, duration_s=2.0, segments=sample_briefing.audio.segments),
        "cover_path": _png(tmp_path / "cover.png"),
        "video": VideoAsset(path=video, duration_s=2.0),
        "charts": [sample_briefing.charts[0].model_copy(update={"path": _png(tmp_path / "c.png")})],
    })
    at = _run(b, "archivo")
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs] == ["Puntos clave", "Transcripción", "Gráficos", "Vídeo", "Cómo se hizo"]
    captions = _image_captions(at)
    assert bv.AI_IMAGE_NOTE in captions, "la portada lleva «Imagen generada por IA»"
    assert "Variación del día · SAN.MC" in captions or any("SAN.MC" in c for c in captions)  # gráfico
    body = "\n".join(h.proto.body for h in at.get("html"))
    assert "Del archivo · 05/10/2026" in body and bv.VOICE_NOTE in body
    assert at.get("audio") and at.get("video")
    labels = [d.label for d in at.get("download_button")]
    assert labels == ["Podcast .wav", "Todo .zip"]  # el .srt del ejemplo no existe en disco
    assert any(btn.label == "Preguntar sobre este briefing" for btn in at.button)
    assert not any("mb-disclaimer" in c.value for c in at.caption), "el aviso legal lo pone el pie del armazón"


def test_render_without_files_on_disk(sample_briefing: Briefing) -> None:
    """Audio, gráficos y vídeo que ya no están en disco: avisos amables, sin pestaña de vídeo."""
    at = _run(sample_briefing)
    assert not at.exception, at.exception
    assert "ya no está en disco" in "\n".join(i.value for i in at.info)
    assert [t.label for t in at.tabs] == ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]
    assert not at.get("audio")
    assert bv.AI_IMAGE_NOTE not in _image_captions(at) and not any("SAN.MC" in c for c in _image_captions(at))
    assert any("ya no están en disco" in m.value for m in at.markdown)
