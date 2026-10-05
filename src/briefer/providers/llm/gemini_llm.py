"""LLM con Google Gemini — alternativa intercambiable (``BRIEFER_LLM_PROVIDER=gemini``).

Carril B. Implementa ``LLMProvider.complete`` con el SDK ``google-genai``:

- Mensajes del contrato -> ``contents`` (rol ``assistant`` -> ``model``); ``system`` va en
  ``system_instruction``.
- Con ``response_model``: ``response_mime_type="application/json"`` +
  ``response_json_schema`` (esquema JSON del modelo Pydantic) y validación Pydantic con
  **1** reintento autocorrectivo (``_structured.complete_structured``).
- ``last_usage``: ``prompt_token_count`` como entrada y ``candidates_token_count +
  thoughts_token_count`` como salida (el razonamiento se factura como salida).
- Timeout de 120 s y reintentos del SDK ante 429/5xx (``HttpRetryOptions``).

Modelo: ``BRIEFER_GEMINI_MODEL`` (p. ej. ``gemini-2.5-flash``). ``cheap=True`` usa el mismo
modelo (ya es de gama barata) pero con el razonamiento desactivado/reducido.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from briefer.config import Settings
from briefer.providers.base import LLMProvider
from briefer.providers.llm._anthropic_common import LLMResponseError
from briefer.providers.llm._structured import complete_structured

TIMEOUT_MS = 120_000
RETRY_ATTEMPTS = 4  # 1 intento + 3 reintentos
RETRY_STATUS = [408, 429, 500, 502, 503, 504]


def to_gemini_contents(messages: list[dict]) -> list[dict]:
    """Convierte ``[{"role", "content": str}]`` al formato ``contents`` de Gemini."""
    contents: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        text = msg.get("content")
        if role not in ("user", "assistant") or not text:
            continue
        if not isinstance(text, str):
            raise ValueError("GeminiLLM solo admite contenido de texto en los mensajes")
        contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})
    if not contents or contents[0]["role"] != "user":
        raise ValueError("El historial debe empezar por un mensaje de usuario")
    return contents


def _usage(resp: Any) -> dict[str, int]:
    meta = getattr(resp, "usage_metadata", None)
    if meta is None:
        return {"input_tokens": 0, "output_tokens": 0}
    out = int(getattr(meta, "candidates_token_count", 0) or 0)
    out += int(getattr(meta, "thoughts_token_count", 0) or 0)
    return {"input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0), "output_tokens": out}


class GeminiLLM(LLMProvider):
    """Cliente de Gemini (``from google import genai``)."""

    provider_name = "gemini"

    def __init__(self, settings: Settings, cheap: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.cheap = cheap
        self.model = settings.briefer_gemini_model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            from google.genai import types

            if not self.settings.has_secret("gemini_api_key"):
                raise RuntimeError("Falta GEMINI_API_KEY en .env")
            self._client = genai.Client(
                api_key=self.settings.gemini_api_key.get_secret_value(),  # type: ignore[union-attr]
                http_options=types.HttpOptions(
                    timeout=TIMEOUT_MS,
                    retry_options=types.HttpRetryOptions(
                        attempts=RETRY_ATTEMPTS, http_status_codes=RETRY_STATUS
                    ),
                ),
            )
        return self._client

    def _config(self, system: str, response_model: type[BaseModel] | None) -> Any:
        from google.genai import types

        # Sin herramientas: se desactiva el "automatic function calling" (y su aviso en log).
        kwargs: dict[str, Any] = {
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)
        }
        if system:
            kwargs["system_instruction"] = system
        if response_model is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_json_schema"] = response_model.model_json_schema()
        if self.cheap:
            if self.model.startswith("gemini-2.5"):
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            else:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        return types.GenerateContentConfig(**kwargs)

    def _generate(self, system: str, messages: list[dict], response_model: type[BaseModel] | None):
        resp = self._get_client().models.generate_content(
            model=self.model,
            contents=to_gemini_contents(messages),
            config=self._config(system, response_model),
        )
        usage = _usage(resp)
        for key, value in usage.items():
            self.last_usage[key] += value
        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            feedback = getattr(resp, "prompt_feedback", None)
            raise LLMResponseError(f"Gemini devolvió una respuesta vacía (feedback={feedback})")
        return text

    def complete(
        self,
        system: str,
        messages: list[dict],
        response_model: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        """Genera con Gemini. Ver ``LLMProvider.complete``.

        Raises:
            google.genai.errors.APIError: fallo de la API tras los reintentos.
            LLMResponseError: respuesta vacía (p. ej. bloqueada por filtros de seguridad).
            StructuredOutputError: JSON no válido para ``response_model`` tras el reintento.
        """
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}
        if response_model is None:
            return self._generate(system, messages, None)

        def call(history: list[dict]) -> tuple[str, dict[str, int]]:
            return self._generate(system, history, response_model), {}

        return complete_structured(call, messages, response_model)
