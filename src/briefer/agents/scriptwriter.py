"""Agente Guionista: convierte el análisis en un diálogo de podcast a 2 voces.

Carril B. Entrada: ``Analysis``. Salida: ``PodcastScript`` (líneas con ``speaker`` "A"/"B",
~3-5 min, cierre con el disclaimer hablado y el aviso de voz sintética). Prompt:
``prompts/scriptwriter.md``. A = presentador/a que guía; B = analista que explica (nombres
configurables en ``.env``).

Robustez: el guion del LLM se valida (líneas vacías, un solo locutor, falta de cierre,
duración muy lejos del objetivo). Si hay problemas se pide **una** reescritura con las
correcciones; después, lo que quede se repara de forma determinista (nunca se devuelve un
guion inválido). Si el LLM no da nada aprovechable, se genera un guion mínimo a partir del
propio análisis.
"""

from __future__ import annotations

import re

from briefer.agents import load_prompt
from briefer.agents.guardrails import strip_advice
from briefer.logging_utils import get_logger
from briefer.providers.base import LLMProvider
from briefer.schemas import Analysis, PodcastScript, ScriptLine

log = get_logger("agents.scriptwriter")

WORDS_PER_MINUTE = 150  # ritmo de locución aproximado en español
LENGTH_TOLERANCE = 0.4  # desviación relativa de duración que dispara una reescritura

CLOSING_LINE_ES = (
    "Y antes de despedirnos, un recordatorio importante: este episodio lo ha generado "
    "automáticamente un sistema de inteligencia artificial y nuestras voces son sintéticas. "
    "Es información con fines divulgativos, no asesoramiento financiero ni una recomendación "
    "de inversión. Contrastad siempre con fuentes oficiales. ¡Hasta mañana!"
)

_DISCLAIMER_HINTS = ("asesoramiento", "recomendación de inversión", "no es una recomendación")
_SYNTHETIC_HINTS = ("sintétic", "inteligencia artificial", " ia ", "generad")


def estimate_duration_s(lines: list[ScriptLine], wpm: int = WORDS_PER_MINUTE) -> float:
    """Duración estimada del guion en segundos a partir del nº de palabras (≈150 ppm)."""
    words = sum(len(line.text.split()) for line in lines)
    return round(words / max(1, wpm) * 60, 1)


def _render_system(target_minutes: float, speaker_names: tuple[str, str]) -> str:
    target_words = int(target_minutes * WORDS_PER_MINUTE)
    return (
        load_prompt("scriptwriter")
        .replace("{target_minutes}", f"{target_minutes:g}")
        .replace("{target_words}", str(target_words))
        .replace("{speaker_a}", speaker_names[0])
        .replace("{speaker_b}", speaker_names[1])
    )


def _ticker_names(analysis: Analysis) -> dict[str, str]:
    try:
        from briefer.ingest.tickers import TICKER_UNIVERSE
    except Exception:
        return {}
    tickers = {t for kp in analysis.key_points for t in kp.tickers}
    return {t: str(TICKER_UNIVERSE[t].get("name", t)) for t in tickers if t in TICKER_UNIVERSE}


def build_user_message(analysis: Analysis) -> str:
    """Mensaje de usuario: el análisis en JSON + nombres de empresa para leer en voz alta."""
    names = _ticker_names(analysis)
    parts = ["# Análisis del día (única fuente de información)", analysis.model_dump_json(indent=2)]
    if names:
        parts.append("# Nombres para leer en voz alta (no digas el ticker)")
        parts.extend(f"- {t} -> {n}" for t, n in sorted(names.items()))
    return "\n".join(parts)


def _has_closing(lines: list[ScriptLine]) -> bool:
    tail = " ".join(line.text for line in lines[-2:]).lower()
    return any(h in tail for h in _DISCLAIMER_HINTS) and any(h in f" {tail} " for h in _SYNTHETIC_HINTS)


def script_problems(
    script: PodcastScript, target_minutes: float, length_tolerance: float | None = LENGTH_TOLERANCE
) -> list[str]:
    """Lista de problemas del guion (vacía si es válido). Textos pensados para el LLM."""
    problems: list[str] = []
    lines = script.lines
    if len(lines) < 2:
        problems.append("El guion tiene menos de dos intervenciones.")
    if any(not line.text.strip() for line in lines):
        problems.append("Hay intervenciones vacías; todas deben tener texto.")
    speakers = {line.speaker for line in lines if line.text.strip()}
    if lines and speakers != {"A", "B"}:
        problems.append('Solo habla un locutor; deben alternarse "A" y "B".')
    if length_tolerance is not None and lines:
        target_s = target_minutes * 60
        duration = estimate_duration_s(lines)
        if abs(duration - target_s) > length_tolerance * target_s:
            words = int(target_minutes * WORDS_PER_MINUTE)
            problems.append(
                f"La duración estimada es {duration / 60:.1f} min y el objetivo {target_minutes:g} min "
                f"(unas {words} palabras en total)."
            )
    return problems


def _repair(lines: list[ScriptLine]) -> list[ScriptLine]:
    """Reparación determinista: quita vacíos, frases de recomendación y fuerza 2 locutores."""
    cleaned: list[ScriptLine] = []
    for line in lines:
        text, changed = strip_advice(" ".join(line.text.split()))
        if changed:
            log.warning("Guionista: eliminada una frase con recomendación de inversión")
        if text:
            cleaned.append(ScriptLine(speaker=line.speaker, text=text))
    if len({line.speaker for line in cleaned}) < 2 and len(cleaned) >= 2:
        log.warning("Guionista: un solo locutor; se reasignan las voces alternando A/B")
        cleaned = [
            ScriptLine(speaker="A" if i % 2 == 0 else "B", text=line.text)
            for i, line in enumerate(cleaned)
        ]
    return cleaned


def fallback_script(analysis: Analysis, speaker_names: tuple[str, str] = ("Álvaro", "Elvira")) -> PodcastScript:
    """Guion mínimo y determinista construido solo con el análisis (si el LLM falla)."""
    a, b = speaker_names
    lines = [
        ScriptLine(speaker="A", text=f"Buenos días, soy {a} y esto es Market Briefer."),
        ScriptLine(speaker="B", text=f"Y yo soy {b}. El titular de hoy: {analysis.headline}."),
    ]
    for kp in analysis.key_points:
        lines.append(ScriptLine(speaker="A", text=f"Vamos con otro tema: {kp.title}. ¿Qué ha pasado?"))
        lines.append(ScriptLine(speaker="B", text=kp.explanation))
    lines.append(ScriptLine(speaker="A", text=f"¿Y el tono general del mercado? {analysis.market_mood}"))
    return PodcastScript(title=f"Market Briefer · {analysis.date:%d/%m/%Y}", lines=lines)


def _finalize(script: PodcastScript, analysis: Analysis) -> PodcastScript:
    """Repara, añade el cierre obligatorio si falta y recalcula la duración."""
    lines = _repair(script.lines)
    if not lines:
        log.warning("Guionista: guion vacío tras reparar; se usa el guion de respaldo")
        lines = _repair(fallback_script(analysis).lines)
    if not _has_closing(lines):
        closer = "B" if lines[-1].speaker == "A" else "A"
        lines.append(ScriptLine(speaker=closer, text=CLOSING_LINE_ES))
    title = re.sub(r"\s+", " ", script.title or "").strip() or f"Market Briefer · {analysis.date:%d/%m/%Y}"
    return PodcastScript(title=title, lines=lines, est_duration_s=estimate_duration_s(lines))


def _call(llm: LLMProvider, system: str, messages: list[dict]) -> PodcastScript | None:
    try:
        result = llm.complete(system, messages, response_model=PodcastScript)
    except Exception as exc:  # salida no válida del LLM: se reintenta / se usa respaldo
        log.warning("Guionista: el LLM no devolvió un guion válido (%s)", exc)
        return None
    if isinstance(result, PodcastScript):
        return result
    try:
        return (
            PodcastScript.model_validate_json(result)
            if isinstance(result, str)
            else PodcastScript.model_validate(result)
        )
    except Exception as exc:
        log.warning("Guionista: respuesta no convertible a PodcastScript (%s)", exc)
        return None


def write_script(
    analysis: Analysis,
    llm: LLMProvider,
    target_minutes: float = 4.0,
    speaker_names: tuple[str, str] = ("Álvaro", "Elvira"),
    *,
    max_retries: int = 1,
    length_tolerance: float | None = LENGTH_TOLERANCE,
) -> PodcastScript:
    """Genera el guion del episodio (A/B alternando, apertura y cierre con disclaimer).

    Args:
        analysis: salida del Agente Analista.
        llm: proveedor LLM inyectado.
        target_minutes: duración objetivo (≈150 palabras por minuto).
        speaker_names: nombres de los locutores A y B (solo para el texto del guion).
        max_retries: reescrituras como máximo si el guion tiene problemas (por defecto 1).
        length_tolerance: desviación relativa de duración tolerada; ``None`` desactiva esa
            comprobación (útil con ``MockLLM``, que devuelve un guion fijo corto).
    """
    system = _render_system(target_minutes, speaker_names)
    messages: list[dict] = [{"role": "user", "content": build_user_message(analysis)}]
    best: PodcastScript | None = None
    best_score: tuple[int, float] | None = None
    for attempt in range(max_retries + 1):
        script = _call(llm, system, messages)
        if script is None:
            problems = ["La respuesta no tenía el formato estructurado pedido."]
        else:
            problems = script_problems(script, target_minutes, length_tolerance)
            score = (len(problems), abs(estimate_duration_s(script.lines) - target_minutes * 60))
            if best_score is None or score < best_score:
                best, best_score = script, score
        if not problems:
            break
        if attempt < max_retries:
            log.warning("Guionista: reintento %d por: %s", attempt + 1, " ".join(problems))
            messages = messages[:1] + [
                {
                    "role": "assistant",
                    "content": script.model_dump_json() if script is not None else "(respuesta inválida)",
                },
                {
                    "role": "user",
                    "content": "Reescribe el guion completo corrigiendo esto: " + " ".join(problems),
                },
            ]
    if best is None:
        log.warning("Guionista: sin guion del LLM; se usa el guion de respaldo")
        best = fallback_script(analysis, speaker_names)
    return _finalize(best, analysis)


__all__ = [
    "CLOSING_LINE_ES",
    "LENGTH_TOLERANCE",
    "WORDS_PER_MINUTE",
    "build_user_message",
    "estimate_duration_s",
    "fallback_script",
    "script_problems",
    "write_script",
]
