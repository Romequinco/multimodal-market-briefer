"""LLM con OpenAI (o servidor compatible, p. ej. Ollama local) — alternativa intercambiable.

Carril B. Implementa ``LLMProvider.complete`` con el SDK ``openai``.
Modelo: ``BRIEFER_OPENAI_MODEL`` (p. ej. ``gpt-4o-mini``). Para Ollama: mismo cliente con
``base_url="http://localhost:11434/v1"`` (TODO: variable de config si se usa).
"""

from __future__ import annotations

from pydantic import BaseModel

from briefer.config import Settings
from briefer.providers.base import LLMProvider


class OpenAILLM(LLMProvider):
    """Cliente de OpenAI Chat Completions / Responses."""

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
        """Genera con OpenAI. Ver ``LLMProvider.complete``."""
        # TODO:
        # 1. from openai import OpenAI; client = OpenAI(api_key=...).
        # 2. msgs = [{"role": "system", "content": system}, *messages].
        # 3. Sin response_model: client.chat.completions.create(model=..., messages=msgs).
        # 4. Con response_model: client.beta.chat.completions.parse(..., response_format=
        #    response_model) -> .choices[0].message.parsed (o JSON mode + model_validate_json).
        # 5. last_usage desde resp.usage (prompt_tokens, completion_tokens).
        raise NotImplementedError("OpenAILLM.complete: pendiente (carril B, opcional)")
