"""Las vistas de la UI con ``streamlit.testing.v1.AppTest`` (modo demo, sin red ni claves).

Rediseño «Tres pestañas, cero sidebar»: ``main.py`` (armazón + Hoy), el cuerpo del diálogo «Nuevo
briefing» (``new_briefing_form``, antes páginas Briefing y Mi cartera), ``views/preguntar.py`` y
``views/archivo.py`` (antes Histórico). ``conftest._mock_env`` deja todos los proveedores en mock y las
salidas en un directorio temporal.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from ui_helpers import (  # noqa: E402
    ARCHIVE,
    ASK,
    FORM_KEY,
    HOY,
    MAIN,
    app,
    button,
    disclaimers,
    form_app,
    html,
    make_demo,
    texts,
    use_samples,
)

from briefer import brand, pipeline, storage  # noqa: E402


@pytest.fixture
def empty_samples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Carpeta de samples sin briefing pregenerado (aísla el test del contenido del repo)."""
    return use_samples(monkeypatch, tmp_path)


def _chip(at) -> str:
    """Texto del chip del modo (primer popover de la barra superior)."""
    return at.get("popover")[0].proto.popover.label


# ── Hoy (portada) ──────────────────────────────────────────────────────────────────


def test_home_without_any_briefing_shows_friendly_message(empty_samples: Path) -> None:
    at = app(MAIN).run()
    assert not at.exception
    assert brand.BRAND_NAME.lower() in html(at)  # marca en la barra superior
    assert "Aún no hay ningún briefing" in texts(at.markdown)
    assert any(b.label == "Nuevo briefing" for b in at.button)
    assert _chip(at) == "Demo offline"  # el modo demo se ve siempre (chip)
    assert disclaimers(at) == 1


def test_home_shows_pregenerated_briefing(empty_samples: Path) -> None:
    make_demo(empty_samples)
    at = app(MAIN).run()
    assert not at.exception
    assert at.session_state["briefing"].id == storage.load_demo_briefing().id
    assert at.get("audio"), "Hoy debe tener el reproductor del podcast sin pulsar nada"
    assert at.get("graphviz_chart"), "la pestaña «Cómo se hizo» debe dibujar la traza"
    assert "Voces sintéticas generadas con IA, no son personas reales" in html(at)
    assert [t.label for t in at.tabs] == ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]
    labels = [b.label for b in at.get("download_button")]
    assert any(label.startswith("Podcast .") for label in labels)
    assert "Subtítulos .srt" in labels and "Todo .zip" in labels
    assert disclaimers(at) == 1


def _as_real(briefing):
    """Copia del briefing con métricas de proveedores reales (simula un briefing 100 % real)."""
    real = {"ingest.news": "yfinance+rss", "ingest.prices": "yfinance", "agents.analyst": "anthropic",
            "agents.scriptwriter": "anthropic", "media.podcast": "edge"}
    metrics = [m.model_copy(update={"provider": real.get(m.step, m.provider), "model": "x"})
               if m.step in real else m for m in briefing.metrics]
    return briefing.model_copy(update={"metrics": metrics})


def test_home_skips_saved_mock_briefing_and_keeps_pregenerated(empty_samples: Path) -> None:
    """M5: un ensayo en «Demo offline» no tapa el pregenerado real de Hoy."""
    make_demo(empty_samples)
    demo_id = storage.load_demo_briefing().id
    saved = pipeline.run_briefing(["ITX.MC"], use_mock=True)  # se guarda en data/outputs (tmp)
    assert storage.is_simulated_briefing(saved)
    at = app(MAIN).run()
    assert not at.exception
    assert at.session_state["briefing"].id == demo_id != saved.id


def test_home_prefers_latest_saved_real_briefing(empty_samples: Path) -> None:
    make_demo(empty_samples)
    saved = _as_real(pipeline.run_briefing(["ITX.MC"], use_mock=True))
    # De otro día: Hoy indica el origen («Último guardado · fecha») y que no está «en antena».
    old = saved.analysis.model_copy(update={"date": date(2026, 10, 1)})
    saved = saved.model_copy(update={"analysis": old})
    storage.save_briefing(saved)
    at = app(MAIN).run()
    assert not at.exception
    assert at.session_state["briefing"].id == saved.id
    assert "Último guardado · 01/10/2026" in html(at)


# ── Nuevo briefing (diálogo; antes página Briefing) ─────────────────────────────────


def test_new_briefing_form_defaults_and_demo_mode() -> None:
    at = form_app().run()
    assert not at.exception
    assert at.multiselect[0].value == ["SAN.MC", "ITX.MC", "IBE.MC", "AAPL", "NVDA"]
    toggles = {t.label: t for t in at.toggle}
    assert "Refrescar datos (ignorar caché)" not in toggles  # solo en modo real
    assert not toggles["Vídeo corto"].value
    assert not button(at, "Generar briefing").disabled


def test_new_briefing_generates_in_demo_mode() -> None:
    at = form_app().run()
    button(at, "Generar briefing").click().run()
    assert not at.exception
    assert not at.error, texts(at.error)
    briefing = at.session_state["briefing"]
    assert at.session_state["_nb_done"] == briefing.id  # «Hoy» lo recoge y lo muestra
    assert f"{FORM_KEY}_request" not in at.session_state
    assert storage.list_briefings(), "el briefing se guarda en data/outputs"


def test_new_briefing_progress_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """El progreso se ve en un ``st.status`` (se anula ``st.rerun`` para inspeccionarlo)."""
    import streamlit as st

    monkeypatch.setattr(st, "rerun", lambda *a, **k: None)
    at = form_app().run()
    button(at, "Generar briefing").click().run()
    assert not at.exception
    status = at.status[0]
    assert status.state == "complete" and status.label == "Briefing listo"
    progress_lines = [m.value for m in status.markdown if m.value.startswith("(")]
    assert progress_lines and progress_lines[-1].endswith("Briefing listo.")


def test_hoy_shows_new_briefing_after_generation() -> None:
    briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], use_mock=True)
    at = app(HOY)
    at.session_state["briefing"] = briefing
    at.session_state["_nb_done"] = briefing.id
    at.run()
    assert not at.exception
    assert at.session_state["_hoy_new_id"] == briefing.id and "_nb_done" not in at.session_state
    assert "Briefing listo" in texts(at.toast)
    assert [t.label for t in at.tabs] == ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]
    assert at.get("graphviz_chart")
    labels = [b.label for b in at.get("download_button")]
    assert "Podcast .wav" in labels and "Subtítulos .srt" in labels
    assert any("demostración" in c.value for c in at.caption)


def test_hoy_back_returns_to_briefing_generated_in_session() -> None:
    """«Volver al último» tras abrir otro del archivo vuelve al recién generado, no al destacado."""
    new = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    other = pipeline.run_briefing(["AAPL"], use_mock=True)
    at = app(HOY)
    at.session_state["briefing"] = new
    at.session_state["_nb_done"] = new.id
    at.run()
    at.session_state["briefing"] = other  # «Abrir» desde Archivo
    at.run()
    assert not at.exception
    button(at, "Volver al último").click().run()
    assert not at.exception
    assert at.session_state["briefing"].id == new.id
    assert "Recién generado" in html(at)


def test_new_briefing_friendly_error_with_step(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise pipeline.PipelineStepError("media.podcast", RuntimeError("sin conexión"))

    monkeypatch.setattr(pipeline, "run_briefing", boom)
    at = form_app().run()
    button(at, "Generar briefing").click().run()
    assert not at.exception
    assert at.status[0].state == "error"
    assert "media.podcast" in at.status[0].label
    assert "sin conexión" in texts(at.error)
    assert not button(at, "Generar briefing").disabled  # el formulario vuelve para reintentar


def test_hoy_shows_fallback_warning() -> None:
    from briefer.schemas import StepMetric

    briefing = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    metrics = [m.model_copy(update={"provider": "anthropic", "model": "claude"}) if m.step == "agents.analyst"
               else m for m in briefing.metrics]
    metrics.append(StepMetric(step="agents.scriptwriter", provider="mock", model="mock-llm", latency_s=0.0,
                              error="APIStatusError: 529"))
    at = app(HOY)
    at.session_state["briefing"] = briefing.model_copy(update={"metrics": metrics})
    at.run()
    assert not at.exception
    assert "cayeron a mock" in texts(at.warning)


# ── Preguntar, cartera (en el diálogo) y Archivo ───────────────────────────────────


def test_ask_page_answers_in_demo_mode() -> None:
    at = app(ASK).run()
    assert not at.exception
    at.chat_input[0].set_value("¿Qué ha pasado hoy con el Santander?").run()
    assert not at.exception
    assert not at.error, texts(at.error)
    answers = at.session_state["qa_answers"]
    assert answers and answers[0].question == "¿Qué ha pasado hoy con el Santander?"
    assert "¿Qué ha pasado hoy con el Santander?" in texts(at.markdown)  # burbuja del usuario
    assert answers[0].answer_text in texts(at.markdown)


def test_portfolio_sample_loads_in_new_briefing() -> None:
    at = form_app().run()
    assert not at.exception
    at.segmented_control[0].set_value("sample").run()  # «Ejemplo»
    assert not at.exception
    portfolio = at.session_state["portfolio"]
    assert portfolio.positions
    body = "\n".join(m.value for m in at.markdown)
    assert "mb-nb-pftable" in body and portfolio.positions[0].ticker in body
    assert "no se guarda en disco" in body  # nota de privacidad de la cartera


def test_new_briefing_with_portfolio_never_writes_it_to_disk() -> None:
    """ADR-005: la cartera del diálogo va al pipeline en memoria; en disco, ni pesos ni gráfico de reparto."""
    import json

    at = form_app().run()
    at.segmented_control[0].set_value("sample").run()
    portfolio = at.session_state["portfolio"]
    button(at, "Generar briefing").click().run()
    assert not at.exception and not at.error, texts(at.error)
    briefing = at.session_state["briefing"]
    assert briefing.context.portfolio is not None  # en la sesión, sí
    raw = (storage.briefing_dir(briefing.id) / storage.BRIEFING_FILE).read_text(encoding="utf-8")
    assert json.loads(raw)["context"]["portfolio"] is None and '"weight"' not in raw
    folder = storage.briefing_dir(briefing.id)
    assert not list(folder.rglob("portfolio_weights.png"))
    assert at.session_state["portfolio"] == portfolio  # sigue en la sesión para el siguiente briefing


def test_archive_opens_saved_briefing_in_hoy() -> None:
    saved = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    at = app(MAIN).run()
    at.switch_page(ARCHIVE).run()
    assert not at.exception
    assert saved.analysis.headline in html(at)
    button(at, "Abrir").click().run()  # «Abrir» = briefing activo + ir a Hoy
    assert not at.exception
    assert at.session_state["briefing"].id == saved.id
    assert "mb-hoy-sub" in html(at), "tras «Abrir» se muestra Hoy"
    assert at.get("graphviz_chart")
    assert disclaimers(at) == 1


def test_archive_page_empty() -> None:
    at = app(ARCHIVE).run()
    assert not at.exception
    assert "Todavía no hay briefings guardados" in texts(at.markdown)
    assert '<h2 class="mb-arch-h">Archivo</h2>' in html(at)
    assert not at.text_input and not at.segmented_control  # sin buscador ni filtros si no hay nada


# ── Modo de ejecución (chip de la barra superior; antes barra lateral) ─────────────


def test_mode_chip_offers_demo_with_real_voices(empty_samples: Path) -> None:
    at = app(MAIN).run()
    assert not at.exception
    radio = at.radio(key="mb_mode_choice")
    assert radio.options == ["Demo sin claves (voces reales)", "Demo offline (mock, sin red)"]
    # Con BRIEFER_TTS_PROVIDER=mock explícito (tests/CI) la demo por defecto es la offline.
    assert radio.value == "mock" and _chip(at) == "Demo offline"
    assert "Modo real no disponible" in texts(at.caption)
    radio.set_value("demo_voices").run()
    assert not at.exception
    assert at.session_state["run_mode"] == "demo_voices" and at.session_state["use_mock"] is True
    assert _chip(at) == "Demo · voces reales"


def test_hoy_marks_sample_fallback_as_substitute() -> None:
    from briefer.logging_utils import fallback_error

    briefing = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    metrics = []
    for m in briefing.metrics:
        if m.step == "agents.analyst":
            m = m.model_copy(update={"provider": "anthropic", "model": "claude", "detail": "grounding OK"})
        if m.step == "ingest.news":
            m = m.model_copy(update={"error": fallback_error("data/samples", ConnectionError("sin red"))})
        metrics.append(m)
    at = app(HOY)
    at.session_state["briefing"] = briefing.model_copy(update={"metrics": metrics})
    at.run()
    assert not at.exception
    warnings = texts(at.warning)
    assert "cayeron a mock o a datos de ejemplo" in warnings and "datos de ejemplo (sustituto)" in warnings
    assert "fallaron" not in warnings  # el sustituto no se cuenta como error
    assert "grounding OK" in texts(at.caption)
