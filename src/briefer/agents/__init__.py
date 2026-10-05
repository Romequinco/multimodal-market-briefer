"""Agentes IA (carril B).

- ``analyst``: Agente Analista — ``MarketContext`` -> ``Analysis`` (resume e interpreta).
- ``scriptwriter``: Agente Guionista — ``Analysis`` -> ``PodcastScript`` (diálogo A/B).
- ``qa``: Agente Q&A — pregunta + ``Briefing`` -> respuesta con fuentes.

Los prompts de sistema viven en ``agents/prompts/*.md`` (editables sin tocar código).
Los agentes reciben el ``LLMProvider`` por parámetro (inyección de dependencias) para poder
probarlos con ``MockLLM``.
"""

from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


_HTML_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


def load_prompt(name: str) -> str:
    """Devuelve el contenido de ``prompts/<name>.md`` (UTF-8) sin comentarios HTML.

    Los comentarios ``<!-- ... -->`` son notas para el equipo y no se envían al LLM.
    """
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return _HTML_COMMENT.sub("", text).strip() + "\n"
