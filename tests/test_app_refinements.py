"""Regresiones de los flujos de consulta, repetición y lectura, sin APIs reales."""

from __future__ import annotations

from ui_helpers import ASK, FORM_KEY, MAIN, app, button, form_app, html

from briefer import pipeline, storage
from briefer.agents import qa
from briefer.schemas import BriefingOptions
from components import briefing_view, new_briefing, qa_view


def test_demo_recovers_briefing_points_and_valid_sources(sample_briefing, monkeypatch):
    monkeypatch.setattr(pipeline.registry, "get_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM")))
    # La función guiada no necesita siquiera construir un proveedor.
    result = qa.demo_answer("¿Qué dice este briefing sobre Santander?", sample_briefing)
    assert sample_briefing.analysis.key_points[0].explanation in result.answer_text
    assert result.sources == sample_briefing.analysis.key_points[0].sources
    assert "Demo guiada" in result.answer_text
    other = qa.demo_answer("¿Qué dice este briefing sobre Nintendo?", sample_briefing)
    assert "no encuentro ese tema" in other.answer_text and not other.sources


def test_demo_refuses_advice_and_has_no_context_fallback(sample_briefing):
    assert "asesoramiento" in qa.demo_answer("¿Me recomiendas comprar Santander?", sample_briefing).answer_text
    assert "abre un briefing" in qa.demo_answer("¿Qué pasa?", None).answer_text


def test_demo_ui_disables_microphone_and_resets_after_mode_change(sample_briefing):
    at = app(ASK)
    at.session_state["briefing"] = sample_briefing
    at.run()
    assert not at.chat_input[0].proto.accept_audio
    at.chat_input[0].set_value("¿Qué dice el briefing sobre Santander?").run()
    assert at.session_state["qa_history"]
    at.session_state["run_mode"] = "demo_voices"
    at.run()
    assert not at.exception
    assert not at.session_state["qa_history"] and not at.session_state["qa_answers"]


def test_topic_button_navigates_and_answers_from_that_point(sample_briefing):
    at = app(MAIN)
    at.session_state["briefing"] = sample_briefing
    at.run()
    next(b for b in at.button if b.label == "Preguntar sobre esto").click().run()
    assert not at.exception
    result = at.session_state["qa_answers"][0]
    assert sample_briefing.analysis.key_points[0].title in result.question
    assert sample_briefing.analysis.key_points[0].explanation in result.answer_text


def test_audio_on_demand_does_not_repeat_question_or_history(sample_briefing, monkeypatch, tmp_path):
    from briefer.providers.mock import write_silence_wav

    calls = []

    def speak(answer, briefing, **kwargs):
        calls.append(answer.question)
        return answer.model_copy(update={"audio_path": write_silence_wav(tmp_path / "answer.wav")})

    monkeypatch.setattr(pipeline, "speak_answer", speak)
    at = app(ASK)
    at.session_state["briefing"] = sample_briefing
    at.session_state["run_mode"] = "demo_voices"
    at.session_state["qa_speak"] = False
    at.run()
    at.chat_input[0].set_value("¿Qué pasó en el mercado según este briefing?").run()
    history = list(at.session_state["qa_history"])
    button(at, "Escuchar respuesta").click().run()
    assert not at.exception and len(calls) == 1
    assert at.session_state["qa_history"] == history and len(at.session_state["qa_answers"]) == 1
    assert at.get("audio")


def test_pending_error_is_shown_without_shadowed_function(sample_briefing, monkeypatch):
    def missing(*args, **kwargs):
        raise NotImplementedError("Pendiente")

    monkeypatch.setattr(pipeline, "answer_question", missing)
    at = app(ASK)
    at.session_state["briefing"] = sample_briefing
    at.run()
    at.chat_input[0].set_value("Hola").run()
    assert not at.exception and at.info


def test_duration_reaches_pipeline_and_survives_storage():
    at = form_app().run()
    at.number_input(key=f"{FORM_KEY}_duration").set_value(5.5).run()
    button(at, "Generar briefing").click().run()
    assert not at.exception
    briefing = at.session_state["briefing"]
    assert briefing.generation_options.target_minutes == 5.5
    assert storage.load_briefing(storage.briefing_dir(briefing.id)).generation_options.target_minutes == 5.5


def test_repeat_prefills_options_and_clears_unrelated_portfolio(sample_briefing):
    at = form_app()
    at.session_state["portfolio"] = sample_briefing.context.portfolio
    at.session_state[new_briefing.REPEAT_KEY] = {
        "tickers": ["ITX.MC"], "options": BriefingOptions(target_minutes=3.0, make_video=True),
        "date": "05/10/2026",
    }
    at.run()
    assert not at.exception
    assert at.multiselect[0].value == ["ITX.MC"]
    assert at.number_input(key=f"{FORM_KEY}_duration").value == 3.0
    assert at.toggle(key=f"{FORM_KEY}_video").value
    assert "portfolio" not in at.session_state
    assert at.session_state[f"{FORM_KEY}_docs_epoch"] == 1
    assert f"{FORM_KEY}_request" not in at.session_state


def test_transcript_highlight_escapes_external_text():
    out = briefing_view.transcript_html([("A", "<script>Santander</script>", None)], query="santander")
    assert "<script>" not in out and "<mark>Santander</mark>" in out
    assert "&lt;script&gt;" in out
    assert "<mark>" not in briefing_view.transcript_html([("A", "[a-z]", None)], query=".*")


def test_transcript_search_reports_matches_and_offers_text_download(sample_briefing):
    at = app(MAIN)
    at.session_state["briefing"] = sample_briefing
    at.run()
    at.text_input(key=f"hoy_transcript_search_{sample_briefing.id}").set_value("Hola").run()
    assert not at.exception and "<mark>Hola</mark>" in html(at)
    assert "Transcripción .txt" in [d.label for d in at.get("download_button")]


def test_source_metadata_and_suggestions_use_briefing_date(sample_briefing):
    news = sample_briefing.context.news[0]
    source = qa_view._source_md(news.id, {news.id: news})
    assert news.source in source and news.published_at.strftime("%d/%m/%Y") in source
    assert all("hoy" not in s for s in qa_view.suggestions(sample_briefing))


def test_repeat_button_from_archive_prepares_existing_briefing(monkeypatch):
    from ui_helpers import ARCHIVE

    saved = pipeline.run_briefing(["ITX.MC"], use_mock=True)
    monkeypatch.setattr(new_briefing, "_new_briefing_dialog", lambda: None)
    at = app(ARCHIVE).run()
    at.button(key=f"arch_repeat_{saved.id}").click().run()
    assert not at.exception
    assert at.session_state[new_briefing.REPEAT_KEY]["tickers"] == ["ITX.MC"]
    assert len(storage.list_briefings()) == 1  # abrir el formulario no genera un episodio
