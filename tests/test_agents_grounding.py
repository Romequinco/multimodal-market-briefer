"""Tests de las puertas de calidad del carril B: cifras trazables (grounding) y alternancia
de locutores en el guion. Sin red: LLMs falsos."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import BaseModel

from briefer.agents import analyst, guardrails, scriptwriter
from briefer.providers.base import LLMProvider
from briefer.schemas import Analysis, KeyPoint, MarketContext, PodcastScript, ScriptLine


class ScriptedLLM(LLMProvider):
    """Devuelve en orden las respuestas indicadas (la última se repite)."""

    provider_name = "fake"
    model = "fake-llm"

    def __init__(self, *responses: object) -> None:
        super().__init__()
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, system: str, messages: list[dict], response_model: type[BaseModel] | None = None):
        self.calls.append({"messages": messages})
        self.last_usage = {"input_tokens": 10, "output_tokens": 5}
        resp = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(resp, Exception):
            raise resp
        return resp


def _analysis(explanation: str, headline: str = "El Santander sube") -> Analysis:
    return Analysis(
        date=date(2026, 10, 5),
        headline=headline,
        key_points=[
            KeyPoint(
                title="Banca",
                explanation=explanation,
                tickers=["SAN.MC"],
                sentiment="positivo",
                sources=["ejemplo-001"],
            )
        ],
        market_mood="Positivo.",
    )


# ── untraceable_figures ─────────────────────────────────────────────────────────────


def test_untraceable_figures_matches_spanish_and_english_formats() -> None:
    ref = "SAN.MC: 5.10 EUR · +1.20 % · -3.45 % desde 05/09 · Ingresos 3T 2026: 1.245 M€"
    text = (
        "Sube un 1,2 % hasta 5,1 euros. Ingresos de 1.245 millones. Cae un 3,5 % en el mes. "
        "Crece un 12,5 %. El IBEX 35 y el S&P 500 suben. En 2026 hay 3 bancos. Objetivo: 7,80 euros."
    )
    assert guardrails.untraceable_figures(text, ref) == ["12,5", "7,80"]


def test_extract_figures_ignores_years_small_ints_dates_and_codes() -> None:
    figs = guardrails.extract_figures("En 2026, 3 bancos; el 05/10/2026 y en el 3T y Q3 subió un 4 %.")
    assert figs == ["4"]  # el 4 va con %, así que sí cuenta


def test_strip_figures_removes_only_affected_sentences() -> None:
    text, changed = guardrails.strip_figures("Sube un 1,2 %. Crece un 12,5 %. Buen día.", ["12,5"])
    assert changed and text == "Sube un 1,2 %. Buen día."


# ── Analista con grounding ──────────────────────────────────────────────────────────


def test_analyze_retries_once_when_figures_are_untraceable(sample_context: MarketContext) -> None:
    bad = _analysis("El banco sube un 1,2 %. Su beneficio crece un 37,5 %.")
    good = _analysis("El banco sube un 1,2 % según los datos del día.")
    llm = ScriptedLLM(bad, good)
    trace: list[str] = []
    result = analyst.analyze(sample_context, llm, trace=trace)
    assert len(llm.calls) == 2
    fix_msg = llm.calls[1]["messages"][-1]["content"]
    assert "37,5" in fix_msg and llm.calls[1]["messages"][1]["role"] == "assistant"
    assert "37,5" not in result.key_points[0].explanation
    assert any("1 reintento" in t for t in trace) and any("corregido" in t for t in trace)


def test_analyze_strips_figures_still_untraceable_after_retry(sample_context: MarketContext) -> None:
    bad = _analysis("El banco sube un 1,2 %. Su beneficio crece un 37,5 %.", headline="Récord del 99,9 %")
    llm = ScriptedLLM(bad)  # el reintento devuelve lo mismo
    trace: list[str] = []
    result = analyst.analyze(sample_context, llm, trace=trace)
    assert len(llm.calls) == 2
    assert result.key_points[0].explanation == "El banco sube un 1,2 %."
    assert "99,9" not in result.headline and result.headline  # titular por defecto
    assert any("eliminadas" in t for t in trace)


def test_analyze_keeps_first_result_if_retry_fails(sample_context: MarketContext) -> None:
    bad = _analysis("El banco sube un 1,2 %. Su beneficio crece un 37,5 %.")
    llm = ScriptedLLM(bad, RuntimeError("429"))
    result = analyst.analyze(sample_context, llm)
    assert result.key_points[0].explanation == "El banco sube un 1,2 %."


def test_analyze_traceable_figures_need_no_retry(sample_context: MarketContext) -> None:
    llm = ScriptedLLM(_analysis("El banco sube un 1,2 % y factura 100 M€ según resultados.pdf."))
    trace: list[str] = []
    analyst.analyze(sample_context, llm, trace=trace)
    assert len(llm.calls) == 1 and trace == ["grounding: todas las cifras trazables"]


def test_analyze_check_can_be_disabled(sample_context: MarketContext) -> None:
    llm = ScriptedLLM(_analysis("Crece un 37,5 %."))
    result = analyst.analyze(sample_context, llm, check_figures=False)
    assert len(llm.calls) == 1 and "37,5" in result.key_points[0].explanation


# ── Guionista: tramos del mismo locutor ─────────────────────────────────────────────


def _lines(speakers: str) -> list[ScriptLine]:
    return [ScriptLine(speaker=s, text=f"Frase {i}.") for i, s in enumerate(speakers)]  # type: ignore[arg-type]


def test_same_speaker_runs_and_merge() -> None:
    lines = _lines("ABBBAAB")
    assert scriptwriter.same_speaker_runs(lines) == [(1, 3)]
    merged = scriptwriter.merge_long_runs(lines)
    assert [l.speaker for l in merged] == ["A", "B", "A", "A", "B"]
    assert merged[1].text == "Frase 1. Frase 2. Frase 3."
    assert scriptwriter.merge_long_runs(_lines("ABAB")) == _lines("ABAB")


def test_script_problems_flags_runs_of_three() -> None:
    script = PodcastScript(title="t", lines=_lines("ABBBA"))
    problems = scriptwriter.script_problems(script, 4.0, length_tolerance=None)
    assert any("3 o más intervenciones seguidas" in p for p in problems)
    ok = PodcastScript(title="t", lines=_lines("ABBAAB"))
    assert scriptwriter.script_problems(ok, 4.0, length_tolerance=None) == []


def test_write_script_retries_on_long_run_then_merges(sample_context: MarketContext) -> None:
    analysis = _analysis("El banco sube.")
    bad = PodcastScript(title="Ep", lines=_lines("ABBBBA"))
    llm = ScriptedLLM(bad)
    trace: list[str] = []
    script = scriptwriter.write_script(analysis, llm, length_tolerance=None, trace=trace)
    assert len(llm.calls) == 2  # 1 reintento por el tramo largo
    assert not scriptwriter.same_speaker_runs(script.lines)
    assert any("reintento 1" in t for t in trace)


def test_write_script_reports_fallback_note() -> None:
    llm = ScriptedLLM(RuntimeError("caído"))
    trace: list[str] = []
    script = scriptwriter.write_script(_analysis("Explicación."), llm, trace=trace)
    assert scriptwriter.FALLBACK_NOTE in trace and script.lines


@pytest.mark.parametrize("figure", ["1,2", "1.20", "+1,20"])
def test_traceable_variants(figure: str) -> None:
    assert guardrails.untraceable_figures(f"Sube un {figure} %", "variación +1.20 %") == []
