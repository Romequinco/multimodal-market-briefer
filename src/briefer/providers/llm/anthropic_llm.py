"""LLM con Anthropic Claude — proveedor por defecto de los tres agentes.

Carril B. Implementa ``LLMProvider.complete(system, messages, response_model)``:

- Sin ``response_model``: texto libre (bloques ``text`` concatenados).
- Con ``response_model``: **salida estructurada** de la Messages API
  (``output_config.format = json_schema``), con el esquema del modelo Pydantic adaptado por
  ``anthropic.transform_schema`` (``additionalProperties: false``, sin restricciones no
  admitidas). Los campos ``dict[str, str]`` (``DocumentInsight.key_figures``) se piden como lista
  de pares ``{label, value}`` y se reconvierten (``_structured.encode_dict_fields``). Se valida con Pydantic y, si falla, se reintenta **una** vez enviando el error
  (ver ``_structured.complete_structured``). Se usa este mecanismo y no ``tool_choice``
  forzado porque Sonnet 5.5 rechaza ``tool_choice`` de tipo ``any``/``tool`` (400).
- ``last_usage`` = tokens de entrada/salida de la llamada (sumando el reintento si lo hubo).
- Timeouts (120 s, 10 s de conexión) y 3 reintentos automáticos del SDK ante 429/5xx/529.

Modelos (config): ``BRIEFER_LLM_MODEL`` (``claude-sonnet-5-5``, razonamiento adaptativo con
``effort="medium"``) y, con ``cheap=True``, ``BRIEFER_LLM_MODEL_CHEAP``
(``claude-haiku-4-5-20251001``, sin razonamiento extendido) para Guionista, Q&A y resúmenes.
Relación con clase: patrón de agente con LLM + salida estructurada del notebook 9 (Agents).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from briefer.config import Settings
from briefer.providers.base import LLMProvider
from briefer.providers.llm import _anthropic_common as common
from briefer.providers.llm._structured import complete_structured, dict_fields, encode_dict_fields

#: ``max_tokens`` por tipo de salida (incluye el razonamiento adaptativo en Sonnet 5.5).
MAX_TOKENS_TEXT = 8_000
MAX_TOKENS_STRUCTURED = 16_000
DEFAULT_EFFORT = "medium"


class AnthropicLLM(LLMProvider):
    """Cliente de Claude (SDK ``anthropic``)."""

    provider_name = "anthropic"

    def __init__(self, settings: Settings, cheap: bool = False, effort: str | None = DEFAULT_EFFORT) -> None:
        super().__init__()
        self.settings = settings
        self.cheap = cheap
        self.model = settings.briefer_llm_model_cheap if cheap else settings.briefer_llm_model
        self.effort = effort
        self._client: Any = None  # se crea en el primer uso (ver _get_client)
        self._schemas: dict[type[BaseModel], dict] = {}

    def _get_client(self) -> Any:  # -> anthropic.Anthropic
        """Cliente compartido del proceso (``common.get_client``), creado de forma perezosa.

        Si se asigna ``self._client`` (tests), se usa ese.
        """
        if self._client is None:
            self._client = common.get_client(self.settings)
        return self._client

    def warmup(self) -> float:
        """Precalienta el SDK y la conexión con una llamada gratuita (``models.retrieve``).

        Devuelve los segundos empleados. No consume tokens. Ver ``pipeline.warmup``.
        """
        if self._client is not None:  # cliente inyectado (tests): nada que calentar
            return 0.0
        return common.warmup_client(self.settings, self.model)

    def _schema(self, response_model: type[BaseModel]) -> dict:
        """Esquema JSON admitido por la API para ``response_model`` (cacheado por clase)."""
        if response_model not in self._schemas:
            import anthropic

            # Los dict libres (DocumentInsight.key_figures) viajan como lista de pares: el esquema
            # estricto los dejaría en {} (additionalProperties: false) y llegarían siempre vacíos.
            self._schemas[response_model] = encode_dict_fields(
                anthropic.transform_schema(response_model), dict_fields(response_model)
            )
        return self._schemas[response_model]

    def _create(self, system: str, messages: list[dict], max_tokens: int, fmt: dict | None) -> Any:
        output_config: dict[str, Any] = common.request_options(self.model, self.effort)
        if fmt is not None:
            output_config["format"] = fmt
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": common.to_api_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if output_config:
            kwargs["output_config"] = output_config
        return self._get_client().messages.create(**kwargs)

    def complete(
        self,
        system: str,
        messages: list[dict],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        """Llama a la Messages API de Claude (ver ``LLMProvider.complete``).

        Raises:
            anthropic.APIError: errores de la API tras los reintentos del SDK.
            LLMResponseError: rechazo, respuesta cortada o vacía.
            StructuredOutputError: JSON no válido para ``response_model`` tras el reintento.
        """
        # Se reinicia ANTES de llamar: si la llamada falla, last_usage no debe arrastrar los
        # tokens de la llamada anterior (el pipeline los sumaría dos veces).
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}
        if response_model is None:
            resp = self._create(system, messages, MAX_TOKENS_TEXT, None)
            self.last_usage = common.usage_dict(resp)
            return common.response_text(resp)

        fmt = {"type": "json_schema", "schema": self._schema(response_model)}

        # Se acumula en last_usage ANTES de leer el texto: si la respuesta no sirve
        # (rechazo, cortada), los tokens ya se han pagado y deben contar en el coste.
        def call(history: list[dict]) -> tuple[str, dict[str, int]]:
            resp = self._create(system, history, MAX_TOKENS_STRUCTURED, fmt)
            common.add_usage(self.last_usage, common.usage_dict(resp))
            return common.response_text(resp), {}

        return complete_structured(call, messages, response_model, pair_fields=dict_fields(response_model))
