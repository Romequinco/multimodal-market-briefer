"""Agente Guionista: convierte el análisis en un diálogo de podcast a 2 voces.

Carril B. Entrada: ``Analysis``. Salida: ``PodcastScript`` (líneas con ``speaker`` "A"/"B",
~3-5 min, cierre con el disclaimer). Prompt: ``prompts/scriptwriter.md``.
A = presentador/a que guía; B = analista que explica (nombres configurables en ``.env``).
"""

from __future__ import annotations

from briefer.providers.base import LLMProvider
from briefer.schemas import Analysis, PodcastScript, ScriptLine

WORDS_PER_MINUTE = 150  # ritmo de locución aproximado en español


def estimate_duration_s(lines: list[ScriptLine], wpm: int = WORDS_PER_MINUTE) -> float:
    """Duración estimada del guion en segundos a partir del nº de palabras."""
    # TODO: palabras = sum(len(l.text.split()) for l in lines); return palabras / wpm * 60.
    raise NotImplementedError("estimate_duration_s: pendiente (carril B)")


def write_script(
    analysis: Analysis,
    llm: LLMProvider,
    target_minutes: float = 4.0,
    speaker_names: tuple[str, str] = ("Álvaro", "Elvira"),
) -> PodcastScript:
    """Genera el guion del episodio."""
    # TODO:
    # 1. system = load_prompt("scriptwriter") con {target_minutes}, {speaker_a}, {speaker_b}
    #    sustituidos (str.format o replace).
    # 2. user = analysis.model_dump_json(indent=2).
    # 3. script = llm.complete(system, [...], response_model=PodcastScript).
    # 4. Post-proceso: alternar hablantes si hay 3+ líneas seguidas del mismo; garantizar
    #    que la última línea incluye el disclaimer (añadirla si falta); recalcular
    #    est_duration_s con estimate_duration_s.
    # 5. Si la duración se aleja >40 % del objetivo, pedir 1 reescritura (más corto/largo).
    # Casos borde: cifras y tickers deben escribirse "para ser leídos" (p. ej. "SAN.MC" ->
    # "Banco Santander", "3,2 %" -> "tres coma dos por ciento" o dejar que el TTS lo lea).
    raise NotImplementedError("write_script: pendiente (carril B)")
