"""LLM con Google Gemini — alternativa intercambiable (``BRIEFER_LLM_PROVIDER=gemini``).

Carril B. Implementa ``LLMProvider.complete`` con el SDK ``google-genai``.
Modelo: ``BRIEFER_GEMINI_MODEL`` (p. ej. ``gemini-2.5-flash``).
"""

from __future__ import annotations

from pydantic import BaseModel

from briefer.config import Settings
from briefer.providers.base import LLMProvider


class GeminiLLM(LLMProvider):
    """Cliente de Gemini (``from google import genai``)."""

    provider_name = "gemini"

    def __init__(self, settings: Settings, cheap: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.briefer_gemini_model  # TODO: modelo "lite" si cheap=True
        self._client = None

    def complete(
        self,
        system: str,
        messages: list[dict],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        """Genera con Gemini. Ver ``LLMProvider.complete``."""
        # TODO:
        # 1. from google import genai; from google.genai import types (import perezoso).
        # 2. client = genai.Client(api_key=self.settings.gemini_api_key.get_secret_value()).
        # 3. Convertir messages a contents (role "assistant" -> "model").
        # 4. config = types.GenerateContentConfig(system_instruction=system, ...);
        #    con response_model: response_mime_type="application/json",
        #    response_schema=response_model y validar con model_validate_json(resp.text).
        # 5. last_usage desde resp.usage_metadata (prompt_token_count, candidates_token_count).
        # Casos borde: respuesta bloqueada por filtros de seguridad (resp.text vacío).
        raise NotImplementedError("GeminiLLM.complete: pendiente (carril B, opcional)")
