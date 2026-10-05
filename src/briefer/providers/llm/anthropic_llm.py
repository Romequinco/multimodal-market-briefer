"""LLM con Anthropic Claude — proveedor por defecto de los tres agentes.

Carril B. Implementa ``LLMProvider.complete(system, messages, response_model)``:
- Entrada: prompt de sistema + mensajes estilo chat.
- Salida: ``str`` o instancia validada de ``response_model`` (``Analysis``, ``PodcastScript``…).

Modelos (config): ``BRIEFER_LLM_MODEL`` (``claude-sonnet-5-5``) y, con ``cheap=True``,
``BRIEFER_LLM_MODEL_CHEAP`` (``claude-haiku-4-5-20251001``) para tareas baratas (Q&A, resúmenes).
Relación con clase: patrón de agente con LLM + herramientas del notebook 9 (Agents).
"""

from __future__ import annotations

from pydantic import BaseModel

from briefer.config import Settings
from briefer.providers.base import LLMProvider


class AnthropicLLM(LLMProvider):
    """Cliente de Claude (SDK ``anthropic``)."""

    provider_name = "anthropic"

    def __init__(self, settings: Settings, cheap: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.briefer_llm_model_cheap if cheap else settings.briefer_llm_model
        self._client = None  # se crea en el primer uso (ver _get_client)

    def _get_client(self):  # -> anthropic.Anthropic
        """Crea el cliente de forma perezosa."""
        # TODO:
        # - import anthropic (dentro de la función: import perezoso).
        # - anthropic.Anthropic(api_key=self.settings.anthropic_api_key.get_secret_value(),
        #   max_retries=3, timeout=60).
        # - Cachear en self._client.
        raise NotImplementedError("AnthropicLLM._get_client: pendiente (carril B)")

    def complete(
        self,
        system: str,
        messages: list[dict],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        """Llama a la Messages API de Claude.

        Ver ``LLMProvider.complete``. Rellena ``self.last_usage`` con ``response.usage``.
        """
        # TODO:
        # 1. client = self._get_client().
        # 2. Sin response_model: client.messages.create(model=self.model, system=system,
        #    messages=messages, max_tokens=4096) y concatenar los bloques de tipo "text".
        # 3. Con response_model: salida estructurada. Opción A (recomendada): tool use con
        #    input_schema=response_model.model_json_schema() y tool_choice forzado a esa
        #    herramienta; validar con response_model.model_validate(block.input).
        #    Opción B: pedir "solo JSON" y response_model.model_validate_json(texto).
        # 4. Si la validación falla, reintentar 1 vez añadiendo el error de validación al
        #    mensaje (autocorrección); si vuelve a fallar, lanzar ValueError claro.
        # 5. self.last_usage = {"input_tokens": resp.usage.input_tokens,
        #    "output_tokens": resp.usage.output_tokens} para costs.estimate_cost_eur.
        # Casos borde: rate limit (429) -> el SDK reintenta; overloaded (529) -> reintento
        # con backoff; respuesta cortada por max_tokens (stop_reason == "max_tokens").
        raise NotImplementedError("AnthropicLLM.complete: pendiente (carril B)")
