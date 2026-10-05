"""Flujos de la UI con AppTest (D2): portada → Preguntar, doble clic / recargas sin relanzar el
briefing, respuesta en dos tiempos, calentamiento, conversación por briefing e histórico robusto.
Sin red ni claves (``conftest._mock_env``)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from briefer import brand, pipeline, storage
from briefer.config import reset_settings_cache

pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

TIMEOUT = 60


def _app(name: str) -> AppTest:
    return AppTest.from_file(str(APP_DIR / name), default_timeout=TIMEOUT)


def _texts(elements) -> str:
    return "\n".join(str(e.value) for e in elements)


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


@pytest.fixture
def demo_samples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Samples con un pregenerado mock y sin briefings guardados."""
    import shutil

    real = Path(__file__).resolve().parents[1] / "data" / "samples"
    samples = tmp_path / "samples"
    samples.mkdir()
    for f in real.iterdir():
        if f.is_file():
            shutil.copy2(f, samples / f.name)
    monkeypatch.setenv("BRIEFER_SAMPLES_DIR", str(samples))
    reset_settings_cache()
    briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], use_mock=True)
    storage.export_briefing(briefing, storage.demo_briefing_dir(samples))
    for path in storage.list_briefings():
        path.unlink()
    return samples


# ── Portada ────────────────────────────────────────────────────────────────────────


def test_home_first_30_seconds(demo_samples: Path) -> None:
    at = _app("main.py").run()
    assert not at.exception
    assert at.title[0].value == brand.BRAND_NAME
    head = _texts(at.markdown)
    assert brand.TAGLINE in head and brand.VALUE_PROPOSITION in head  # eslogan + propuesta de valor
    assert "Demo offline" in head                              # insignia de modo
    assert at.get("audio")                                     # reproductor arriba, sin pulsar nada
    assert any(b.label == "Preguntar sobre este briefing" for b in at.button)
    assert "Generar el tuyo" in _texts(at.get("page_link")) or any(
        "Generar el tuyo" in str(getattr(p, "proto", "")) for p in at.get("page_link"))
    assert any("Cómo se hizo:" in c.value for c in at.caption)
    assert any("No constituye asesoramiento" in c.value or "no constituye" in c.value.lower() for c in at.caption)
    assert not at.warning  # el disclaimer ya no es un st.warning a toda anchura


def test_home_ask_button_sets_context(demo_samples: Path) -> None:
    at = _app("main.py").run()
    demo_id = at.session_state["briefing"].id
    at.session_state["briefing"] = None  # simula otro briefing activo
    _button(at, "Preguntar sobre este briefing").click().run()
    assert not at.exception
    assert at.session_state["briefing"].id == demo_id


def test_home_is_cached_between_reruns(demo_samples: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st.cache_data.clear()
    calls = {"n": 0}
    real = storage.load_featured_briefing

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(storage, "load_featured_briefing", counting)
    at = _app("main.py").run()
    at.run()
    at.run()
    assert not at.exception
    assert calls["n"] == 1


# ── Briefing: sin relanzar en recargas ni con doble clic ───────────────────────────


def test_generate_runs_once_and_not_on_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    real = pipeline.run_briefing
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_briefing", counting)
    at = _app("pages/1_Briefing.py").run()
    _button(at, "Generar briefing").click().run()
    assert not at.exception and calls["n"] == 1
    assert at.session_state["_briefing_busy"] is False
    at.run()  # recarga / interacción con otro widget
    at.sidebar.radio[0].set_value("mock").run()
    assert calls["n"] == 1, "una recarga no debe relanzar el briefing"
    assert any(b.label == "Preguntar sobre este briefing" for b in at.button)


def test_request_ignored_while_busy() -> None:
    at = _app("pages/1_Briefing.py").run()
    at.session_state["_briefing_busy"] = True
    _button(at, "Generar briefing").click()
    # El callback no deja petición si ya hay una en marcha (segundo clic durante la generación).
    from components.players import StatusProgress  # noqa: F401  (la app importa bien)

    at.run()
    assert not at.exception
    assert "_briefing_request" not in at.session_state


def test_briefing_error_resets_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise pipeline.PipelineStepError("ingest.news", RuntimeError("sin red"))

    monkeypatch.setattr(pipeline, "run_briefing", boom)
    at = _app("pages/1_Briefing.py").run()
    _button(at, "Generar briefing").click().run()
    assert not at.exception
    assert at.session_state["_briefing_busy"] is False
    assert not _button(at, "Generar briefing").disabled  # se puede reintentar


# ── Preguntar ──────────────────────────────────────────────────────────────────────


def test_ask_uses_featured_context_and_suggestions(demo_samples: Path) -> None:
    at = _app("pages/2_Preguntar.py").run()
    assert not at.exception
    assert at.session_state["briefing"] is not None  # llega directo: usa el de la portada
    assert any("Contexto:" in c.value for c in at.caption)
    suggestion = next(b for b in at.button if b.label.startswith("¿Qué ha pasado hoy"))
    suggestion.click().run()
    assert not at.exception
    answers = at.session_state["qa_answers"]
    assert len(answers) == 1 and answers[0].question.startswith("¿Qué ha pasado hoy")
    assert any("Latencia total" in c.value for c in at.caption)


def test_ask_resets_conversation_when_briefing_changes() -> None:
    first = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    second = pipeline.run_briefing(["ITX.MC"], use_mock=True)
    at = _app("pages/2_Preguntar.py")
    at.session_state["briefing"] = first
    at.run()
    at.text_input[0].input("¿Qué tal el Santander?").run()
    _button(at, "Preguntar").click().run()
    assert len(at.session_state["qa_answers"]) == 1
    at.session_state["briefing"] = second
    at.run()
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
    at = _app("pages/2_Preguntar.py").run()
    at.text_input[0].input("¿Qué ha pasado?").run()
    _button(at, "Preguntar").click().run()
    assert not at.exception
    assert seen["speak"] is False and seen["spoken"]  # texto primero, voz después


def test_ask_warmup_runs_once_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    st.cache_resource.clear()
    done = threading.Event()
    calls: list[str] = []

    def warmup(mode=None):
        calls.append(mode)
        done.set()

    monkeypatch.setattr(pipeline, "warmup", warmup, raising=False)
    at = _app("pages/2_Preguntar.py").run()
    at.run()
    assert not at.exception
    assert done.wait(5)
    assert calls == ["mock"]
    st.cache_resource.clear()


def test_ask_without_optional_pipeline_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(pipeline, "warmup", raising=False)
    monkeypatch.delattr(pipeline, "speak_answer", raising=False)
    st.cache_resource.clear()
    at = _app("pages/2_Preguntar.py").run()
    at.text_input[0].input("Hola").run()
    _button(at, "Preguntar").click().run()
    assert not at.exception and at.session_state["qa_answers"]


# ── Histórico y cartera ────────────────────────────────────────────────────────────


def test_history_lists_corrupt_briefing_without_breaking() -> None:
    saved = pipeline.run_briefing(["SAN.MC"], use_mock=True)
    bad = storage.briefing_dir("29991231-235959-ffffff")  # el más reciente, y roto
    (bad / storage.BRIEFING_FILE).write_text("{ roto", encoding="utf-8")
    at = _app("pages/4_Historico.py").run()
    assert not at.exception
    assert "no se puede abrir" in _texts(at.warning)
    at.selectbox[0].set_value(saved.id).run()
    assert not at.exception
    assert at.session_state["briefing"].id == saved.id
    labels = [b.label for b in at.get("download_button")]
    assert "Descargar todo (.zip)" in labels


def test_portfolio_page_links_to_briefing() -> None:
    at = _app("pages/3_Mi_cartera.py").run()
    _button(at, "Usar cartera de ejemplo").click().run()
    assert not at.exception
    assert at.session_state["portfolio"].positions
