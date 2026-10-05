"""Agente Q&A: responde preguntas del usuario sobre el briefing del día.

Carril B. Entrada: pregunta en texto (si fue por voz, ya transcrita por ``ingest.voice``) +
``Briefing`` (contexto: análisis, noticias, documentos). Salida: ``QAAnswer`` (texto y fuentes;
el audio lo añade ``pipeline.answer_question`` con TTS). Prompt: ``prompts/qa.md``.
"""

from __future__ import annotations

from briefer.providers.base import LLMProvider
from briefer.schemas import Briefing, QAAnswer


def build_qa_context(briefing: Briefing | None, max_chars: int = 20_000) -> str:
    """Contexto textual para responder: análisis + noticias (con ids) + insights."""
    # TODO: reutilizar el formato de analyst.build_user_message + analysis.model_dump_json;
    # si briefing es None, devolver "" (el agente debe decir que no hay briefing cargado).
    raise NotImplementedError("build_qa_context: pendiente (carril B)")


def answer(
    question: str,
    briefing: Briefing | None,
    llm: LLMProvider,
    history: list[dict] | None = None,
) -> QAAnswer:
    """Responde ``question`` usando solo el contexto del briefing (sin inventar datos)."""
    # TODO:
    # 1. system = load_prompt("qa") + "\n\n# Contexto\n" + build_qa_context(briefing).
    # 2. messages = (history or []) + [{"role": "user", "content": question}].
    # 3. Salida estructurada con un modelo interno (answer_text, sources) o texto libre +
    #    extracción de ids citados entre corchetes [id].
    # 4. Guardarraíles MiFID: si la pregunta pide recomendación personalizada ("¿compro?",
    #    "¿vendo?", "¿cuánto invierto?"), responder con información general + disclaimer.
    # 5. Usar el modelo barato (registry.get_llm(cheap=True)) — lo decide el pipeline.
    raise NotImplementedError("answer: pendiente (carril B)")
