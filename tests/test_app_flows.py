"""Flujos de la UI con AppTest (D2): Hoy → Preguntar, «Nuevo briefing» sin relanzarse en recargas,
respuesta en dos tiempos, calentamiento, conversación por briefing y Archivo robusto.
Sin red ni claves (``conftest._mock_env``)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402
from ui_helpers import (  # noqa: E402
    ARCHIVE,
    ASK,
    FORM_KEY,
    MAIN,
    app,
    button,
    disclaimers,
    form_app,
    html,
    make_demo,
    use_samples,
)

from briefer import brand, pipeline, storage  # noqa: E402


@pytest.fixture
def demo_samples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Samples con un pregenerado mock y sin briefings guardados."""
    samples = use_samples(monkeypatch, tmp_path)
    make_demo(samples)
    return samples


# ── Hoy ────────────────────────────────────────────────────────────────────────────


def test_home_first_30_seconds(demo_samples: Path) -> None:
    at = app(MAIN).run()
    assert not at.exception
    body = html(at)
    assert brand.BRAND_NAME.lower() in body                    # marca en la barra superior
    assert "Tu briefing" in body and "en antena" in body       # cabecera de Hoy
    assert at.get("popover")[0].proto.popover.label == "Demo offline"  # chip del modo
    assert at.get("audio")                                     # reproductor arriba, sin pulsar nada
    assert any(b.label == "Preguntar sobre este briefing" for b in at.button)
    assert any(b.label == "Nuevo briefing" for b in at.button)
    tabs = [str(p.proto.page) for p in at.get("page_link")]
    assert "preguntar" in tabs and "archivo" in tabs           # pestañas Hoy · Preguntar · Archivo
    assert at.get("graphviz_chart")                            # «Cómo se hizo»
    assert disclaimers(at) == 1                                # aviso legal una sola vez, al pie
    assert any("no constituye" in c.value.lower() for c in at.caption)
    assert not at.warning  # el disclaimer no es un st.warning a toda anchura


def test_home_ask_button_opens_ask_with_context(demo_samples: Path) -> None:
    at = app(MAIN).run()
    demo_id = at.session_state["briefing"].id
    button(at, "Preguntar sobre este briefing").click().run()
    assert not at.exception
    assert at.session_state["briefing"].id == demo_id
    assert "mb-qa-title" in html(at), "«Preguntar sobre este briefing» navega a Preguntar"
    assert storage.load_demo_briefing().analysis.headline in html(at)  # «Sobre: <titular>»
    assert disclaimers(at) == 1


def test_home_is_cached_between_reruns(demo_samples: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st.cache_data.clear()
    calls = {"n": 0}
    real = storage.load_featured_briefing

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(storage, "load_featured_briefing", counting)
    at = app(MAIN).run()
    at.run()
    at.run()
    assert not at.exception
    assert calls["n"] == 1


# ── Nuevo briefing: sin relanzar en recargas ni con doble clic ─────────────────────


def _counting_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    real = pipeline.run_briefing
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_briefing", counting)
    return calls


def test_generate_runs_once_and_not_on_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _counting_run(monkeypatch)
    at = form_app().run()
    button(at, "Generar briefing").click().run()
    assert not at.exception and calls["n"] == 1
    assert f"{FORM_KEY}_request" not in at.session_state  # la petición se consume una vez
    at.run()  # recarga / interacción con otro widget
    at.toggle(key=f"{FORM_KEY}_video").set_value(True).run()
    assert not at.exception
    assert calls["n"] == 1, "una recarga no debe relanzar el briefing"
    assert at.session_state["_nb_done"] == at.session_state["briefing"].id


def test_request_is_consumed_once_and_needs_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """La petición (la deja el callback de «Generar») se consume una sola vez; sin valores ni
    cartera no se lanza nada (el botón ya sale deshabilitado)."""
    calls = _counting_run(monkeypatch)
    request = {"tickers": [], "uploads": [], "make_video": False, "make_cover": False, "deliver": [],
               "refresh": False}
    at = form_app()
    at.session_state[f"{FORM_KEY}_request"] = request
    at.run()
    assert not at.exception and calls["n"] == 0
    assert f"{FORM_KEY}_request" not in at.session_state
    at.session_state[f"{FORM_KEY}_request"] = {**request, "tickers": ["SAN.MC"]}
    at.run()
    at.run()
    assert not at.exception and calls["n"] == 1


def test_briefing_error_allows_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise pipeline.PipelineStepError("ingest.news", RuntimeError("sin red"))

    monkeypatch.setattr(pipeline, "run_briefing", boom)
    at = form_app().run()
    button(at, "Generar briefing").click().run()
    assert not at.exception
    assert "ingest.news" in at.status[0].label
    assert f"{FORM_KEY}_request" not in at.session_state and "_nb_done" not in at.session_state
    assert not button(at, "Generar briefing").disabled  # se puede reintentar
    assert at.multiselect[0].value == ["SAN.MC", "ITX.MC", "IBE.MC", "AAPL", "NVDA"]  # sin perder valores


# ── Preguntar ──────────────────────────────────────────────────────────────────────


def test_ask_uses_featured_context_and_suggestions(demo_samples: Path) -> None:
    at = app(ASK).run()
    assert not at.exception
    assert at.session_state["briefing"] is not None  # llega directo: usa el destacado de Hoy
    assert "Sobre:" in html(at)
    pills = at.pills(key="qa_suggest")
    suggestion = next(o for o in pills.options if o.startswith("¿Qué ha pasado hoy"))
    pills.set_value(suggestion).run()
    assert not at.exception
    answers = at.session_state["qa_answers"]
    assert len(answers) == 1 and answers[0].question.startswith("¿Qué ha pasado hoy")
    assert "mb-qa-lat" in html(at)  # chip de latencia total
    assert at.pills(key="qa_suggest").value is None  # la sugerencia se desmarca
    assert suggestion not in at.pills(key="qa_suggest").options  # no se ofrece otra vez lo ya preguntado


def test_ask_resets_conversation_when_briefing_changes() -> None:
    first = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    second = pipeline.run_briefing(["ITX.MC"], use_mock=True)
    at = app(ASK)
    at.session_state["briefing"] = first
    at.run()
    at.chat_input[0].set_value("¿Qué tal el Santander?").run()
    assert len(at.session_state["qa_answers"]) == 1
    at.session_state["briefing"] = second
    at.run()
    assert not at.exception
    assert at.session_state["qa_answers"] == [] and at.session_state["qa_history"] == []


def test_ask_clear_conversation() -> None:
    at = app(ASK).run()
    assert at.button(key="qa_clear").disabled  # nada que borrar todavía
    at.chat_input[0].set_value("Hola").run()
    assert len(at.session_state["qa_history"]) == 2
    at.button(key="qa_clear").click().run()
    assert not at.exception
    assert at.session_state["qa_answers"] == [] and at.session_state["qa_history"] == []


def test_ask_two_step_when_pipeline_supports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    real_answer = pipeline.answer_question

    def answer_text_only(question, briefing=None, **kwargs):
        seen["speak"] = kwargs.get("speak")
        return real_answer(question, briefing, **kwargs)

    def speak_answer(answer, briefing=None, **kwargs):
        seen["spoken"] = answer.answer_text
        return answer.model_copy(update={"audio_path": None})

    monkeypatch.setattr(pipeline, "answer_question", answer_text_only)
    monkeypatch.setattr(pipeline, "speak_answer", speak_answer, raising=False)
    at = app(ASK).run()
    at.chat_input[0].set_value("¿Qué ha pasado?").run()
    assert not at.exception
    assert seen["speak"] is False and seen["spoken"]  # texto primero, voz después


def test_ask_without_audio_answer_skips_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    real_answer = pipeline.answer_question

    def spy(question, briefing=None, **kwargs):
        seen.append(kwargs.get("speak"))
        return real_answer(question, briefing, **kwargs)

    monkeypatch.setattr(pipeline, "answer_question", spy)
    monkeypatch.setattr(pipeline, "speak_answer", lambda *a, **k: pytest.fail("no debe hablar"), raising=False)
    at = app(ASK).run()
    at.toggle(key="qa_speak").set_value(False).run()
    at.chat_input[0].set_value("¿Qué ha pasado?").run()
    assert not at.exception and seen == [False]


def test_ask_warmup_runs_once_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    st.cache_resource.clear()
    done = threading.Event()
    calls: list[str] = []

    def warmup(mode=None):
        calls.append(mode)
        done.set()

    monkeypatch.setattr(pipeline, "warmup", warmup, raising=False)
    at = app(ASK).run()
    at.run()
    assert not at.exception
    assert done.wait(5)
    assert calls == ["mock"]
    st.cache_resource.clear()


def test_ask_without_optional_pipeline_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(pipeline, "warmup", raising=False)
    monkeypatch.delattr(pipeline, "speak_answer", raising=False)
    st.cache_resource.clear()
    at = app(ASK).run()
    at.chat_input[0].set_value("Hola").run()
    assert not at.exception and at.session_state["qa_answers"]


# ── Archivo y cartera ──────────────────────────────────────────────────────────────


def test_archive_lists_corrupt_briefing_without_breaking() -> None:
    saved = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    bad = storage.briefing_dir("29991231-235959-ffffff")  # el más reciente, y roto
    (bad / storage.BRIEFING_FILE).write_text("{ roto", encoding="utf-8")
    at = app(MAIN).run()
    at.switch_page(ARCHIVE).run()
    assert not at.exception
    body = html(at)
    assert "Briefing no disponible" in body and "no se puede abrir" in body
    assert [b.label for b in at.button].count("Abrir") == 1  # el roto no se puede abrir, sí borrar
    button(at, "Abrir").click().run()
    assert not at.exception
    assert at.session_state["briefing"].id == saved.id
    labels = [b.label for b in at.get("download_button")]
    assert "Todo .zip" in labels


def test_portfolio_sample_lists_its_tickers_in_new_briefing() -> None:
    at = form_app().run()
    at.multiselect[0].set_value([]).run()
    at.segmented_control[0].set_value("sample").run()
    assert not at.exception
    portfolio = at.session_state["portfolio"]
    assert portfolio.positions
    body = "\n".join(m.value for m in at.markdown)
    assert "de tu cartera" in body and portfolio.positions[0].ticker in body
    assert "cartera" in body.split("mb-nb-sum")[1]  # resumen del pie: «… · cartera»
    assert not button(at, "Generar briefing").disabled  # basta la cartera, sin valores sueltos
