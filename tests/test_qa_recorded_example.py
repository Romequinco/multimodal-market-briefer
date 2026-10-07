"""El ejemplo permite probar respuesta, fuentes y voz sin llamar a IA ni alterar el chat."""

import json

import pytest

from briefer import pipeline
from briefer.config import ROOT_DIR
from briefer.media.podcast import audio_duration_s
from briefer.qa_examples import load_qa_example


def test_bundled_example_has_meaningful_answers_sources_and_speech():
    example = load_qa_example(ROOT_DIR / "data" / "samples")
    assert example is not None and len(example.answers) == 3
    known = {n.id for n in example.briefing.context.news}
    for answer in example.answers:
        assert len(answer.answer_text.split()) > 70
        assert "Pregunta recibida" not in answer.answer_text
        assert answer.sources and set(answer.sources) <= known
        assert answer.audio_path is not None and answer.audio_path.is_absolute()
        assert audio_duration_s(answer.audio_path) > 20
        assert not answer.metrics  # No inventamos latencias ni una ejecución del LLM.
    assert "5,89 %" in example.answers[0].answer_text
    assert "4,52 %" in example.answers[0].answer_text
    assert "Apple" in example.answers[2].question


def test_missing_recording_keeps_text_available(tmp_path):
    folder = tmp_path / "qa_example"
    folder.mkdir()
    data = (ROOT_DIR / "data/samples/qa_example/conversation.json").read_text(encoding="utf-8")
    (folder / "conversation.json").write_text(data, encoding="utf-8")
    example = load_qa_example(tmp_path)
    assert all(a.audio_path is None and a.answer_text for a in example.answers)


def test_example_cannot_load_audio_outside_its_folder(tmp_path):
    folder = tmp_path / "qa_example"
    folder.mkdir()
    data = json.loads((ROOT_DIR / "data/samples/qa_example/conversation.json").read_text(encoding="utf-8"))
    data["answers"][0]["audio_path"] = "../otro.mp3"
    (folder / "conversation.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="dentro de su carpeta"):
        load_qa_example(tmp_path)


def test_example_dialog_is_offline_and_preserves_active_context(sample_briefing, monkeypatch):
    from ui_helpers import ASK, app

    def forbidden(*args, **kwargs):
        raise AssertionError("El ejemplo debe funcionar sin generar respuestas ni audio.")

    monkeypatch.setattr(pipeline, "answer_question", forbidden)
    monkeypatch.setattr(pipeline, "speak_answer", forbidden)
    at = app(ASK)
    at.session_state["briefing"] = sample_briefing
    at.session_state["run_mode"] = "mock"
    at.run()
    at.button(key="qa_recorded_example").click().run()
    assert not at.exception
    assert len(at.get("audio")) == 3
    assert any("audios ya vienen incluidos" in element.value for element in at.info)
    assert at.session_state["briefing"].id == sample_briefing.id
    assert at.session_state["qa_answers"] == [] and at.session_state["qa_history"] == []


def test_example_button_is_available_without_any_briefing(tmp_path, monkeypatch):
    from ui_helpers import ASK, app

    monkeypatch.setenv("BRIEFER_SAMPLES_DIR", str(tmp_path))
    from briefer.config import reset_settings_cache

    reset_settings_cache()
    at = app(ASK).run()
    assert not at.exception and not at.button(key="qa_recorded_example").disabled
    at.button(key="qa_recorded_example").click().run()
    assert not at.exception
    assert any("no está incluido" in element.value for element in at.info)
