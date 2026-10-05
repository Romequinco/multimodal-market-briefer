"""Agentes IA (carril B).

- ``analyst``: Agente Analista — ``MarketContext`` -> ``Analysis`` (resume e interpreta).
- ``scriptwriter``: Agente Guionista — ``Analysis`` -> ``PodcastScript`` (diálogo A/B).
- ``qa``: Agente Q&A — pregunta + ``Briefing`` -> respuesta con fuentes.

Los prompts de sistema viven en ``agents/prompts/*.md`` (editables sin tocar código).
Los agentes reciben el ``LLMProvider`` por parámetro (inyección de dependencias) para poder
probarlos con ``MockLLM``.
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Devuelve el contenido de ``prompts/<name>.md`` (UTF-8)."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
