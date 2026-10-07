"""La demo responde consultas habituales y nunca lee avisos como respuestas de audio."""

from briefer import pipeline, storage
from briefer.agents import qa
from briefer.schemas import KeyPoint


def test_short_summary_question_uses_saved_points(sample_briefing):
    answer = qa.demo_answer("¿Qué ha pasado?", sample_briefing)
    assert sample_briefing.analysis.key_points[0].explanation in answer.answer_text
    assert answer.response_kind == "demo_excerpt"


def test_brand_alias_recovers_company_point(sample_briefing):
    point = KeyPoint(title="Inditex presenta resultados", explanation="Ingresos del documento de ejemplo.",
                     tickers=["ITX.MC"], sources=[sample_briefing.context.news[0].id])
    briefing = sample_briefing.model_copy(deep=True)
    briefing.analysis.key_points.append(point)
    answer = qa.demo_answer("¿Y Zara?", briefing)
    assert point.explanation in answer.answer_text
    assert sample_briefing.analysis.key_points[0].explanation not in answer.answer_text


def test_price_query_returns_snapshot_value(sample_briefing):
    answer = qa.demo_answer("¿Qué precio tiene Santander?", sample_briefing)
    price = sample_briefing.context.prices[0]
    assert f"{price.last:.2f}".replace(".", ",") in answer.answer_text
    assert price.currency in answer.answer_text
    assert "05/10/2026" in answer.answer_text  # dato del briefing, nunca presentado como precio en vivo


def test_ranking_excludes_context_indexes():
    briefing = storage.load_demo_briefing()
    answer = qa.demo_answer("¿Cuál subió más?", briefing)
    expected = max((p for p in briefing.context.prices if p.ticker in briefing.context.tickers),
                   key=lambda p: p.change_pct)
    assert "Banco Santander" in answer.answer_text and expected.ticker == "SAN.MC"
    assert "IBEX" not in answer.answer_text


def test_unknown_company_does_not_return_market_summary(sample_briefing):
    answer = qa.demo_answer("¿Qué noticias hay de Tesla?", sample_briefing)
    assert answer.response_kind == "demo_notice" and not answer.sources


def test_ranking_down_returns_lowest_change():
    from briefer.ingest.tickers import CATALOG

    briefing = storage.load_demo_briefing()
    expected = min((p for p in briefing.context.prices if p.ticker in briefing.context.tickers),
                   key=lambda p: p.change_pct)
    answer = qa.demo_answer("¿Cuál ha bajado más?", briefing)
    assert CATALOG[expected.ticker]["name"] in answer.answer_text


def test_followup_uses_previous_company(sample_briefing):
    answer = qa.demo_answer("¿Y su precio?", sample_briefing,
                           history=[{"role": "user", "content": "¿Qué pasó con Santander?"}])
    assert answer.response_kind == "demo_excerpt" and "EUR" in answer.answer_text


def test_unmatched_query_never_calls_tts(settings, sample_briefing, monkeypatch):
    monkeypatch.setattr(pipeline, "_speak", lambda *a, **k: (_ for _ in ()).throw(AssertionError("TTS")))
    # La ruta de voz tardía se corta antes de resolver proveedores de audio.
    answer = pipeline.answer_question("¿Qué piensa Elon Musk?", sample_briefing,
                                      settings=settings, mode="mock", speak=False)
    assert answer.response_kind == "demo_notice"
    assert pipeline.speak_answer(answer, sample_briefing, mode="demo_voices", settings=settings) is answer


def test_unmatched_ui_shows_no_audio_action(sample_briefing, monkeypatch):
    from ui_helpers import ASK, app

    monkeypatch.setattr(pipeline, "speak_answer", lambda *a, **k: (_ for _ in ()).throw(AssertionError("TTS")))
    at = app(ASK)
    at.session_state["briefing"] = sample_briefing
    at.session_state["run_mode"] = "demo_voices"
    at.run()
    at.chat_input[0].set_value("¿Qué piensa Elon Musk?").run()
    assert not at.exception and not at.get("audio")
    assert all(b.label != "Escuchar respuesta" for b in at.button)
