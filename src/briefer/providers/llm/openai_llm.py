"""LLM con OpenAI — **stub documentado** (fuera del alcance del MVP).

Carril B. Recorte acordado en la revisión crítica (docs/07, H10): como máximo **un** LLM
alternativo, y ese es Gemini (``gemini_llm.py``). La clase se mantiene para que la interfaz
``LLMProvider`` siga mostrando que un tercer proveedor es un cambio de ``.env``, pero
``complete`` lanza ``NotImplementedError``; en el pipeline, un paso núcleo cuyo LLM real falla
cae a ``mock`` marcado en su ``StepMetric`` (no rompe el briefing).

Cómo se implementaría (roadmap):
1. ``from openai import OpenAI``; ``client = OpenAI(api_key=..., timeout=120, max_retries=3)``.
2. ``msgs = [{"role": "system", "content": system}, *messages]``.
3. Texto libre: ``client.chat.completions.create(model=..., messages=msgs)``.
4. Estructurado: ``response_format={"type": "json_schema", ...}`` y validar con
   ``_structured.complete_structured`` (como Anthropic y Gemini).
5. ``last_usage`` desde ``resp.usage`` (``prompt_tokens``, ``completion_tokens``).
Con ``base_url="http://localhost:11434/v1"`` serviría también para Ollama local.
"""

from __future__ import annotations

from pydantic import BaseModel

from briefer.config import Settings
from briefer.providers.base import LLMProvider


class OpenAILLM(LLMProvider):
    """Cliente de OpenAI (no implementado en el MVP; ver docstring del módulo)."""

    provider_name = "openai"

    def __init__(self, settings: Settings, cheap: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.briefer_openai_model
        self._client = None

    def complete(
        self,
        system: str,
        messages: list[dict],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        """No implementado en el MVP: usar ``BRIEFER_LLM_PROVIDER=anthropic`` o ``gemini``."""
        raise NotImplementedError(
            "OpenAILLM no está implementado en el MVP (recorte: un único LLM alternativo, Gemini). "
            "Usa BRIEFER_LLM_PROVIDER=anthropic o gemini."
        )
