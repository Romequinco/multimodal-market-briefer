"""Agente Q&A: responde preguntas del usuario sobre el briefing del día.

Carril B. Entrada: pregunta en texto (si fue por voz, ya transcrita por ``ingest.voice``) +
``Briefing`` (contexto: análisis, noticias, documentos). Salida: ``QAAnswer`` (texto y fuentes;
el audio lo añade ``pipeline.answer_question`` con TTS). Prompt: ``prompts/qa.md``.

El LLM responde en texto libre citando fuentes entre corchetes (``[ejemplo-001]``); aquí se
extraen las citas válidas a ``QAAnswer.sources`` y se quitan del texto (que se va a leer en
voz alta). Funciona igual con ``MockLLM`` y con un LLM real.
"""

from __future__ import annotations

import re

from briefer.agents import load_prompt
from briefer.agents.analyst import allowed_sources, build_user_message
from briefer.agents.guardrails import (
    ADVICE_REMINDER_ES,
    asks_for_advice,
    fix_spoken_text,
    looks_like_injection,
    strip_advice,
    unhedged_causal_claims,
)
from briefer.logging_utils import get_logger
from briefer.providers.base import LLMProvider
from briefer.schemas import Briefing, QAAnswer

log = get_logger("agents.qa")

MAX_HISTORY_TURNS = 8
_CITATION = re.compile(r"\s*\[([^\[\]]{1,200})\]")

NO_BRIEFING_NOTE = (
    "(No hay ningún briefing cargado. Responde que no tienes el briefing del día y sugiere "
    "generarlo primero; no inventes datos de mercado.)"
)


def build_qa_context(briefing: Briefing | None, max_chars: int = 20_000) -> str:
    """Contexto textual para responder: análisis + noticias (con ids) + documentos.

    Si ``briefing`` es ``None`` devuelve ``""`` (el agente dirá que no hay briefing cargado).
    """
    if briefing is None:
        return ""
    a = briefing.analysis
    lines = [
        f"# Análisis del briefing {briefing.id} ({a.date:%d/%m/%Y})",
        f"Titular: {a.headline}",
        f"Tono del mercado: {a.market_mood}",
    ]
    for kp in a.key_points:
        refs = ", ".join(kp.sources) or "sin fuente"
        tickers = ", ".join(kp.tickers) or "-"
        lines.append(f"- {kp.title} [{kp.sentiment}; {tickers}; fuentes: {refs}]: {kp.explanation}")
    analysis_txt = "\n".join(lines)
    remaining = max(0, max_chars - len(analysis_txt) - 2)
    context_txt = build_user_message(briefing.context, max_chars=remaining) if remaining > 200 else ""
    return (analysis_txt + "\n\n" + context_txt).strip()[:max_chars]


def _extract_citations(text: str, briefing: Briefing | None) -> tuple[str, list[str]]:
    """Quita las citas ``[id]`` del texto y devuelve las que existen en el briefing."""
    valid = allowed_sources(briefing.context) if briefing else {}
    sources: list[str] = []
    for raw in _CITATION.findall(text):
        for part in re.split(r"[,;]", raw):
            canon = valid.get(part.strip().strip("`'\"").lower())
            if canon and canon not in sources:
                sources.append(canon)
    cleaned = _CITATION.sub("", text)
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    return " ".join(cleaned.split()), sources


def answer(
    question: str,
    briefing: Briefing | None,
    llm: LLMProvider,
    history: list[dict] | None = None,
    *,
    trace: list[str] | None = None,
) -> QAAnswer:
    """Responde ``question`` usando solo el contexto del briefing (sin inventar datos).

    - Historial recortado a los últimos ``MAX_HISTORY_TURNS`` turnos válidos.
    - Citas ``[id]`` -> ``sources`` (solo las que existen en el briefing).
    - Guardarraíles MiFID: se eliminan frases de recomendación y, si la pregunta pedía
      consejo personalizado, se añade el recordatorio de que no es asesoramiento.
    - Texto hablado limpio: gramática y caracteres raros (``guardrails.fix_spoken_text``).
    - ``trace`` (opcional) recibe notas de calidad: consejo pedido, frase recortada, intento de
      inyección en la pregunta, nº de fuentes citadas (el pipeline las guarda en ``detail``).
    """
    notes = trace if trace is not None else []
    question = (question or "").strip()
    if not question:
        raise ValueError("La pregunta está vacía.")
    if looks_like_injection(question):
        notes.append("pregunta con forma de instrucción al sistema (se mantiene el rol)")
        log.warning("Q&A: la pregunta intenta cambiar las instrucciones del agente")
    context = build_qa_context(briefing)
    system = load_prompt("qa") + "\n\n# Contexto del briefing\n" + (context or NO_BRIEFING_NOTE)
    past = [
        {"role": m["role"], "content": str(m["content"])}
        for m in (history or [])
        if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()
    ][-MAX_HISTORY_TURNS:]
    while past and past[0]["role"] != "user":  # los proveedores exigen empezar por "user"
        past.pop(0)
    messages = past + [{"role": "user", "content": question}]

    raw = llm.complete(system, messages)
    text = raw if isinstance(raw, str) else str(getattr(raw, "answer_text", raw))
    text, sources = _extract_citations(text, briefing)
    text, changed = strip_advice(fix_spoken_text(text))
    if changed:
        log.warning("Q&A: eliminada una frase con recomendación de inversión")
        notes.append("compliance: frase con recomendación recortada")
    if not text:
        text = "No puedo responder a eso con la información del briefing de hoy."
    advice_asked = asks_for_advice(question)
    if advice_asked:
        notes.append("compliance: pide consejo personalizado -> respuesta neutral + recordatorio")
    if (changed or advice_asked) and "asesoramiento" not in text.lower():
        text = f"{text} {ADVICE_REMINDER_ES}"
    if unhedged_causal_claims(text):
        notes.append("causa afirmada sin atribuir a la fuente")
    notes.append(f"fuentes citadas: {len(sources)}")
    return QAAnswer(question=question, answer_text=text, sources=sources)


__all__ = ["MAX_HISTORY_TURNS", "answer", "build_qa_context"]
