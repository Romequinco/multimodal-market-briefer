"""Regresión de los fallos de calidad de la evaluación de 6 briefings reales (06-oct-2026).

Cada bloque usa frases reales de ``notebooks/eval`` (guiones de Haiku y análisis de Sonnet):
marco temporal (saludo y «cierre» a mediodía), causas endurecidas, tono valorativo, foco en los
valores del usuario, concordancia, regionalismos y nivel del logger. Sin red ni reloj real.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel

from briefer import logging_utils
from briefer.agents import analyst, guardrails, qa, scriptwriter, timeframe
from briefer.providers.base import LLMProvider
from briefer.schemas import (
    Analysis,
    Briefing,
    KeyPoint,
    MarketContext,
    NewsItem,
    PodcastScript,
    PriceSnapshot,
    ScriptLine,
)

NOON = datetime(2026, 10, 6, 12, 40)  # martes, sesión abierta
AFTERNOON = datetime(2026, 10, 6, 15, 0)
NIGHT = datetime(2026, 10, 6, 19, 0)
EARLY = datetime(2026, 10, 6, 8, 0)
SATURDAY = datetime(2026, 10, 10, 12, 0)


class ScriptedLLM(LLMProvider):
    """Devuelve en orden las respuestas indicadas (la última se repite)."""

    provider_name = "fake"
    model = "fake-llm"

    def __init__(self, *responses: object) -> None:
        super().__init__()
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, system: str, messages: list[dict], response_model: type[BaseModel] | None = None):
        self.calls.append({"system": system, "messages": messages})
        self.last_usage = {"input_tokens": 10, "output_tokens": 5}
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


_CLOSING = (
    "Recordad: generado con inteligencia artificial y voces sintéticas; no es asesoramiento "
    "financiero ni una recomendación de inversión."
)


def _script(*texts: str) -> PodcastScript:
    return PodcastScript(
        title="Episodio",
        lines=[ScriptLine(speaker="A" if i % 2 == 0 else "B", text=t) for i, t in enumerate(texts)],
    )


def _analysis(*tickers: str, explanation: str = "Telefónica sube según la noticia.") -> Analysis:
    return Analysis(
        date=date(2026, 10, 6),
        headline="Telefónica sube",
        key_points=[
            KeyPoint(title="Telefónica", explanation=explanation, tickers=list(tickers or ["TEF.MC"]),
                     sentiment="positivo", sources=["n1"]),
        ],
        market_mood="Positivo.",
    )


# ── 1. Marco temporal ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("now", "tickers", "greeting", "session", "can_close"),
    [
        (EARLY, ["TEF.MC"], "Buenos días", "pre", False),
        (NOON, ["TEF.MC"], "Buenos días", "open", False),
        (AFTERNOON, ["TEF.MC"], "Buenas tardes", "open", False),
        (datetime(2026, 10, 6, 17, 34), ["TEF.MC"], "Buenas tardes", "open", False),
        (datetime(2026, 10, 6, 17, 35), ["TEF.MC"], "Buenas noches", "closed", True),
        (NIGHT, ["TEF.MC"], "Buenas noches", "closed", True),
        (NIGHT, ["AAPL"], "Buenas noches", "open", False),  # Wall Street sigue abierta
        (NIGHT, ["TEF.MC", "AAPL"], "Buenas noches", "open", True),  # mezcla: Europa ya cerró
        (SATURDAY, ["TEF.MC"], "Buenos días", "closed", True),
        (datetime(2026, 10, 6, 10, 40, tzinfo=UTC), ["TEF.MC"], "Buenos días", "open", False),  # 12:40 Madrid
    ],
)
def test_time_frame_by_hour_and_market(now, tickers, greeting, session, can_close) -> None:
    frame = timeframe.time_frame(now, tickers)
    assert (frame.greeting, frame.session, frame.can_say_close) == (greeting, session, can_close)
    assert f"«{greeting}»" in frame.note


def test_prompt_carries_time_frame_as_data() -> None:
    noon = scriptwriter._render_system(4.0, scriptwriter.DEFAULT_SPEAKERS, timeframe.time_frame(NOON))
    assert "{" not in noon and "«Buenos días»" in noon and "sigue **abierta**" in noon
    assert "edición de noche" in noon  # la marca se mantiene como nombre del producto
    night = scriptwriter._render_system(4.0, scriptwriter.DEFAULT_SPEAKERS, timeframe.time_frame(NIGHT))
    assert "«Buenas noches»" in night and "ya ha cerrado" in night


# Apertura real generada a mediodía (eval 06-oct, cartera_mixta_defensiva).
_NIGHT_OPENING = (
    "Buenas noches, soy Toro. Esto es Briefly, la edición de noche con el cierre del día.",
    "Buenas noches, soy Osa. Os contamos qué ha pasado en los mercados ahora que cierra la sesión.",
    "Ferrovial cierra en 45,19 euros, un 1,91 % por debajo del cierre anterior.",
)


def test_premature_close_claims_at_noon_and_not_at_night() -> None:
    text = " ".join(_NIGHT_OPENING)
    found = scriptwriter.premature_close_claims(text, timeframe.time_frame(NOON, ["FER.MC"]))
    assert {"Buenas noches", "cierre del día", "ahora que cierra la sesión", "cierra en"} <= set(found)
    assert not any("anterior" in f for f in found)  # «el cierre anterior» sí vale
    assert scriptwriter.premature_close_claims(text, timeframe.time_frame(NIGHT, ["FER.MC"])) == []
    fixed = scriptwriter.fix_time_frame(text, timeframe.time_frame(NOON, ["FER.MC"]))
    assert fixed.startswith("Buenos días, soy Toro.") and "con lo que va de sesión" in fixed
    assert "a esta hora de la sesión" in fixed and "cotiza en 45,19" in fixed and "cierre anterior" in fixed


def test_write_script_at_noon_retries_and_repairs_time_frame() -> None:
    analysis = _analysis("FER.MC")
    llm = ScriptedLLM(_script(*_NIGHT_OPENING, _CLOSING))
    trace: list[str] = []
    final = scriptwriter.write_script(analysis, llm, length_tolerance=None, trace=trace,
                                      check_figures=False, now=NOON)
    assert len(llm.calls) == 2 and "Marco temporal" in llm.calls[1]["messages"][-1]["content"]
    assert "«Buenos días»" in llm.calls[0]["system"]
    text = scriptwriter.script_text(final)
    assert final.lines[0].text.startswith("Buenos días, soy Toro")
    assert "noches" not in text.lower() and "cierre del día" not in text
    assert any("marco open" in n for n in trace)


def test_write_script_at_night_keeps_night_greeting() -> None:
    llm = ScriptedLLM(_script(*_NIGHT_OPENING, _CLOSING))
    final = scriptwriter.write_script(_analysis("FER.MC"), llm, length_tolerance=None,
                                      check_figures=False, now=NIGHT)
    assert len(llm.calls) == 1 and final.lines[0].text.startswith("Buenas noches")


def test_fallback_and_closing_follow_time_frame() -> None:
    analysis = _analysis()
    noon = scriptwriter.fallback_script(analysis, frame=timeframe.time_frame(NOON, ["TEF.MC"]))
    assert noon.lines[0].text == "Buenos días, soy Toro y esto es Briefly, lo que va de sesión."
    night = scriptwriter.fallback_script(analysis, frame=timeframe.time_frame(NIGHT, ["TEF.MC"]))
    assert night.lines[0].text.endswith("el cierre del día.")
    assert "noches" not in scriptwriter.closing_line(timeframe.time_frame(NOON)).lower()
    assert scriptwriter.closing_line(timeframe.time_frame(NIGHT)) == scriptwriter.CLOSING_LINE_ES


def test_analyst_message_carries_time_frame(sample_context: MarketContext) -> None:
    llm = ScriptedLLM(_analysis("SAN.MC").model_copy(update={"headline": "Santander sube"}))
    analyst.analyze(sample_context, llm, check_figures=False, now=NOON)
    user = llm.calls[0]["messages"][0]["content"]
    assert "## Momento de generación" in user and "sigue **abierta**" in user


# ── 2. Causas endurecidas ───────────────────────────────────────────────────────

_CAUSAL_BAD = [
    "Pues es un movimiento que el mercado ha celebrado, aunque conviene recordar que acumula una caída.",
    "El banco tiene dudas sobre el proyecto I-24, y eso es lo que está presionando la cotización.",
    "Los inversores castigan a Repsol tras el dato.",
    "La rebaja lastra la acción de Ferrovial.",
]
_CAUSAL_OK = [
    "Según Expansión, el mercado ha celebrado la venta de la participación.",
    "Según los titulares, eso es lo que está presionando la cotización.",
    "La prensa lo relaciona con la rebaja de JPMorgan, que podría estar lastrando la acción.",
    "CaixaBank sube un 1,15 % hasta 12,36 euros.",
    "El mercado vigila la rentabilidad de la deuda.",
]


@pytest.mark.parametrize("sentence", _CAUSAL_BAD)
def test_firm_causal_claims_detected(sentence: str) -> None:
    assert guardrails.unhedged_causal_claims(sentence) == [sentence]


@pytest.mark.parametrize("sentence", _CAUSAL_OK)
def test_hedged_claims_not_flagged(sentence: str) -> None:
    assert guardrails.unhedged_causal_claims(sentence) == []


def test_generic_analysts_needs_plural_source() -> None:
    line = "Barclays elevó su precio objetivo, así que los analistas ven potencial."
    one_source = "Barclays eleva su precio objetivo de 32 a 38 euros."
    assert guardrails.unhedged_causal_claims(line, reference=one_source) == [line]
    assert guardrails.unhedged_causal_claims(line, reference="Varios analistas elevan objetivos.") == []
    assert guardrails.unhedged_causal_claims(line) == []  # sin referencia (Q&A) no se juzga
    named = "Según Barclays, la acción tiene potencial."
    assert guardrails.unhedged_causal_claims(named, reference=one_source) == []


def test_scriptwriter_retries_on_hardened_causality() -> None:
    bad = _script("Hola.", _CAUSAL_BAD[0], _CLOSING)
    good = _script("Hola.", "Según la noticia, la venta se ha cerrado.", _CLOSING)
    llm = ScriptedLLM(bad, good)
    final = scriptwriter.write_script(_analysis(), llm, length_tolerance=None, check_figures=False, now=NIGHT)
    assert len(llm.calls) == 2
    assert "convierten en hecho" in llm.calls[1]["messages"][-1]["content"]
    assert "celebrado" not in scriptwriter.script_text(final)


def test_qa_hedges_new_causal_patterns() -> None:
    text, n = qa.hedge_causal_claims(_CAUSAL_BAD[1])
    assert n == 1 and text.startswith(qa.HEDGE_PREFIX) and guardrails.unhedged_causal_claims(text) == []


# ── 3. Tono valorativo ──────────────────────────────────────────────────────────

_EVALUATIVE_BAD = [
    "Pero aquí hay algo que os debería preocupar: NVIDIA pesa más que 256 empresas del S&P 500 juntas.",
    "Eso suena a un buen negocio para Indra.",
    "Meta Platforms ha sido la estrella de la jornada, ¿verdad?",
    "Impresionante.",
]
_EVALUATIVE_OK = [
    "Según Barclays, es una buena noticia para Repsol.",
    "Meta sube un 2 % y se acerca a máximos.",
    "El mercado vigila la prima de riesgo de Francia.",
    "Las noticias no explican claramente el movimiento de hoy.",
]


@pytest.mark.parametrize("sentence", _EVALUATIVE_BAD)
def test_evaluative_tone_detected(sentence: str) -> None:
    assert guardrails.evaluative_tone(sentence) == [sentence]
    assert not guardrails.contains_advice(sentence)  # no es consejo: por eso hace falta esta puerta


@pytest.mark.parametrize("sentence", _EVALUATIVE_OK)
def test_neutral_tone_not_flagged(sentence: str) -> None:
    assert guardrails.evaluative_tone(sentence) == []


def test_scriptwriter_retries_on_evaluative_tone() -> None:
    llm = ScriptedLLM(_script("Hola.", _EVALUATIVE_BAD[1], _CLOSING), _script("Hola.", "Indra gana el contrato.", _CLOSING))
    trace: list[str] = []
    scriptwriter.write_script(_analysis(), llm, length_tolerance=None, check_figures=False, now=NIGHT, trace=trace)
    assert len(llm.calls) == 2 and "Tono valorativo" in llm.calls[1]["messages"][-1]["content"]
    assert "buen negocio" in llm.calls[1]["messages"][-1]["content"]
    assert not any("tono valorativo" in n for n in trace)  # corregido en el reintento


def test_scriptwriter_prompt_has_neutral_tone_rule() -> None:
    system = scriptwriter._render_system(4.0, scriptwriter.DEFAULT_SPEAKERS, timeframe.time_frame(NIGHT))
    assert "Tono neutro" in system and "los analistas" in system


# ── 4. Foco en los valores del usuario ─────────────────────────────────────────


def _news(nid: str, *tickers: str) -> NewsItem:
    return NewsItem(id=nid, title="t", summary="s", source="Expansión", url=f"https://example.com/{nid}",
                    published_at=datetime(2026, 10, 6, 8, 0), tickers=list(tickers))


def _ibex_context() -> MarketContext:
    return MarketContext(
        date=date(2026, 10, 6),
        tickers=["TEF.MC", "REP.MC", "AENA.MC"],
        news=[_news("n1", "TEF.MC", "AENA.MC"), _news("n2", "REP.MC")],
        prices=[PriceSnapshot(ticker="^IBEX", last=19508.5, change_pct=1.08, currency="EUR")],
    )


def _ibex_analysis(headline: str, first_tickers: list[str]) -> Analysis:
    return Analysis(
        date=date(2026, 10, 6),
        headline=headline,
        key_points=[
            KeyPoint(title="Contexto de mercado", explanation="El índice sube.", tickers=first_tickers,
                     sentiment="positivo", sources=[]),
            KeyPoint(title="Telefónica pierde contratos de Aena", explanation="Según la noticia, Indra gana.",
                     tickers=["TEF.MC", "AENA.MC"], sentiment="negativo", sources=["n1"]),
        ],
        market_mood="Positivo.",
    )


_INDRA = "Indra se lleva contratos de Aena frente a Telefónica mientras el Ibex sube"


def test_focus_problems_flags_headline_about_other_company() -> None:
    problems = analyst.focus_problems(_ibex_analysis(_INDRA, ["TEF.MC"]), _ibex_context())
    assert len(problems) == 1 and "titular" in problems[0] and "TEF.MC" in problems[0]
    ok = _ibex_analysis("Telefónica pierde contratos de Aena frente a Indra", ["TEF.MC"])
    assert analyst.focus_problems(ok, _ibex_context()) == []
    first_index = _ibex_analysis("Telefónica pierde contratos de Aena", ["^IBEX"])
    assert any("primer punto" in p for p in analyst.focus_problems(first_index, _ibex_context()))


def test_focus_not_required_without_user_news() -> None:
    ctx = _ibex_context().model_copy(update={"news": [_news("n9", "SAN.MC")]})
    assert analyst.focus_problems(_ibex_analysis(_INDRA, ["^IBEX"]), ctx) == []


def test_postprocess_moves_user_point_first() -> None:
    out = analyst.postprocess_analysis(_ibex_analysis("Telefónica cae", ["^IBEX"]), _ibex_context())
    assert out.key_points[0].tickers == ["TEF.MC", "AENA.MC"]


def test_analyze_retries_off_focus_headline_then_falls_back() -> None:
    bad = _ibex_analysis(_INDRA, ["TEF.MC"])
    good = _ibex_analysis("Telefónica pierde contratos de Aena frente a Indra", ["TEF.MC"])
    llm = ScriptedLLM(bad, good)
    trace: list[str] = []
    out = analyst.analyze(_ibex_context(), llm, trace=trace, now=NIGHT)
    assert len(llm.calls) == 2 and "no trata de un valor del usuario" in llm.calls[1]["messages"][-1]["content"]
    assert out.headline.startswith("Telefónica") and "foco: corregido en el reintento" in trace

    stubborn = ScriptedLLM(bad)
    trace = []
    out = analyst.analyze(_ibex_context(), stubborn, trace=trace, now=NIGHT)
    assert out.headline == "Telefónica pierde contratos de Aena"
    assert "foco: titular sustituido por el del primer punto del usuario" in trace


# ── 5. Concordancia artículo-sustantivo ────────────────────────────────────────


@pytest.mark.parametrize(
    ("wrong", "right"),
    [
        ("BBVA ha anunciado la lanzamiento de una plataforma.", "BBVA ha anunciado el lanzamiento de una plataforma."),
        ("Los cifras del trimestre.", "Las cifras del trimestre."),
        ("Hablamos de la lanzamiento y del subida.", "Hablamos del lanzamiento y de la subida."),
        ("Un caída y una dato.", "Una caída y un dato."),
        ("Esta resultado y al sesión.", "Este resultado y a la sesión."),
    ],
)
def test_agreement_detected_and_fixed(wrong: str, right: str) -> None:
    assert guardrails.agreement_issues(wrong)
    assert guardrails.grammar_issues(wrong)  # dispara el reintento del Guionista
    assert guardrails.fix_spoken_text(wrong) == right


@pytest.mark.parametrize(
    "text",
    [
        "Las cifras, los resultados, el cierre, la sesión, del día, al cierre y la cotización.",
        "Para que la avance el consejo.",  # «la» pronombre + verbo
        "El alza de los precios y el índice.",
        "Unos beneficios, unas ventas, estos datos y estas acciones.",
    ],
)
def test_agreement_no_false_positives(text: str) -> None:
    assert guardrails.agreement_issues(text) == []
    assert guardrails.fix_spoken_text(text) == text


# ── 6. Regionalismos ───────────────────────────────────────────────────────────


def test_mantencion_is_regionalism() -> None:
    assert scriptwriter.regionalisms("La mantención de la red") == ["mantención"]
    assert scriptwriter.fix_regionalisms("La mantención de la red y las mantenciones") == (
        "El mantenimiento de la red y los mantenimientos"
    )
    assert scriptwriter.fix_regionalisms("Habla de la mantención y de una mantención.") == (
        "Habla del mantenimiento y de un mantenimiento."
    )
    assert scriptwriter.fix_regionalisms("El mantenimiento sigue igual.") == "El mantenimiento sigue igual."


def test_qa_answer_fixes_regionalisms(sample_briefing: Briefing) -> None:
    llm = ScriptedLLM("El coste de mantención de la red sube [ejemplo-001].")
    ans = qa.answer("¿Qué pasa con la red?", sample_briefing, llm)
    assert "mantenimiento" in ans.answer_text and "mantención" not in ans.answer_text


# ── 7. Nivel del logger ────────────────────────────────────────────────────────


def test_get_logger_respects_level_set_by_user(monkeypatch: pytest.MonkeyPatch) -> None:
    root = logging.getLogger("briefer")
    previous = root.level
    monkeypatch.setattr(logging_utils, "_configured", False)
    try:
        root.setLevel(logging.WARNING)  # el usuario lo fija antes de la primera llamada
        logging_utils.get_logger("x")
        assert root.level == logging.WARNING
        monkeypatch.setattr(logging_utils, "_configured", False)
        root.setLevel(logging.NOTSET)  # sin nivel previo: BRIEFER_LOG_LEVEL (INFO por defecto)
        logging_utils.get_logger("x")
        assert root.level == logging.INFO
    finally:
        root.setLevel(previous)
