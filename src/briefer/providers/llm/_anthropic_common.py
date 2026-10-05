"""Utilidades compartidas por ``AnthropicLLM`` y ``ClaudeVision`` (SDK ``anthropic``).

Carril B. Centraliza: creación perezosa del cliente (timeouts y reintentos del SDK ante
429/5xx/529 y errores de conexión), lectura de ``usage``, extracción del texto de la
respuesta (ignorando bloques ``thinking``) y los parámetros de razonamiento por modelo.

Nunca se registra ni se imprime la clave: solo se lee de ``Settings`` (``SecretStr``).
"""

from __future__ import annotations

from typing import Any

from briefer.config import Settings

#: Timeout por petición (s). Las llamadas del analista con razonamiento tardan ~10-40 s.
REQUEST_TIMEOUT_S = 120.0
CONNECT_TIMEOUT_S = 10.0
#: Reintentos automáticos del SDK (backoff exponencial) ante 408/409/429/5xx y caídas de red.
MAX_RETRIES = 3


class LLMResponseError(RuntimeError):
    """La respuesta del modelo no es utilizable (rechazo, cortada por ``max_tokens``, vacía…)."""


def make_client(settings: Settings) -> Any:
    """Crea un ``anthropic.Anthropic`` con timeouts y reintentos (import perezoso).

    Raises:
        RuntimeError: si falta ``ANTHROPIC_API_KEY`` (el registry ya lo comprueba antes).
    """
    import anthropic

    if not settings.has_secret("anthropic_api_key"):
        raise RuntimeError("Falta ANTHROPIC_API_KEY en .env")
    key = settings.anthropic_api_key.get_secret_value()  # type: ignore[union-attr]
    return anthropic.Anthropic(
        api_key=key,
        max_retries=MAX_RETRIES,
        timeout=anthropic.Timeout(REQUEST_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
    )


def supports_effort(model: str) -> bool:
    """``True`` si el modelo acepta ``output_config.effort`` (Haiku 4.5 y anteriores no)."""
    m = model.lower()
    return not ("haiku" in m or "claude-3" in m or "sonnet-4-5" in m)


def request_options(model: str, effort: str | None) -> dict[str, Any]:
    """Parámetros extra por modelo: ``effort`` solo donde se admite.

    En Sonnet 5.5 el razonamiento adaptativo va siempre activo (no se puede desactivar con
    ``disabled``); el coste se controla bajando ``effort``. En Haiku 4.5 no se envía nada
    (sin razonamiento extendido): es el modelo barato y rápido.
    """
    if effort and supports_effort(model):
        return {"effort": effort}
    return {}


def usage_dict(response: Any) -> dict[str, int]:
    """``{"input_tokens", "output_tokens"}`` de ``response.usage`` (0 si no hay datos).

    Los tokens leídos/escritos en caché de prompt se suman a la entrada para no infraestimar
    el coste (sin caché explícita suelen ser 0).
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0}
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    inp += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    inp += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return {"input_tokens": inp, "output_tokens": int(getattr(usage, "output_tokens", 0) or 0)}


def response_text(response: Any) -> str:
    """Concatena los bloques ``text`` de la respuesta y valida el ``stop_reason``.

    Raises:
        LLMResponseError: rechazo de seguridad (``refusal``), salida cortada por
            ``max_tokens`` o respuesta sin texto.
    """
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise LLMResponseError(f"El modelo rechazó la petición (refusal, categoría={category})")
    text = "".join(
        getattr(block, "text", "") for block in (response.content or []) if getattr(block, "type", "") == "text"
    ).strip()
    if stop == "max_tokens":
        raise LLMResponseError("Respuesta cortada por max_tokens")
    if not text:
        raise LLMResponseError(f"Respuesta sin texto (stop_reason={stop})")
    return text


def to_api_messages(messages: list[dict]) -> list[dict]:
    """Adapta el historial del contrato (``[{"role", "content": str}]``) a la Messages API.

    Se conservan solo los roles ``user``/``assistant`` (el ``system`` va aparte) y los
    contenidos vacíos se descartan (la API los rechaza). El contenido puede ser ``str`` o una
    lista de bloques ya formateados.
    """
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or content in (None, "", []):
            continue
        out.append({"role": role, "content": content})
    if not out or out[0]["role"] != "user":
        raise ValueError("El historial debe empezar por un mensaje de usuario")
    return out
