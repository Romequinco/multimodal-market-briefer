"""Salida estructurada común a los LLM reales: JSON -> Pydantic con 1 reintento autocorrectivo.

Carril B. Cada proveedor aporta una función ``call(messages) -> (texto, usage)`` que ya pide
al modelo JSON restringido por el esquema (``output_config.format`` en Anthropic,
``response_json_schema`` en Gemini). Aquí se valida con Pydantic y, si falla, se repite
**una** vez enviando al modelo su propia respuesta y el error de validación.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from typing import get_origin

from pydantic import BaseModel, ValidationError

from briefer.logging_utils import get_logger

log = get_logger("providers.llm")

CallFn = Callable[[list[dict]], tuple[str, dict[str, int]]]

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MAX_ERROR_CHARS = 1_500


class StructuredOutputError(ValueError):
    """El modelo no devolvió un JSON válido para ``response_model`` tras el reintento."""


def dict_fields(response_model: type[BaseModel]) -> list[str]:
    """Campos de primer nivel de tipo ``dict[str, str]`` (p. ej. ``DocumentInsight.key_figures``).

    Los esquemas JSON estrictos (Anthropic ``output_config.format``) exigen
    ``additionalProperties: false`` en todos los objetos: un diccionario libre queda reducido a
    ``{}`` y el modelo solo puede devolverlo **vacío**. Por eso estos campos viajan como lista de
    pares ``{"label", "value"}`` (``encode_dict_fields``) y se reconvierten antes de validar.
    """
    names: list[str] = []
    for name, info in response_model.model_fields.items():
        annotation = info.annotation
        if get_origin(annotation) is dict:
            names.append(name)
    return names


_PAIR_LIST_SCHEMA: dict = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
        "required": ["label", "value"],
        "additionalProperties": False,
    },
}


def encode_dict_fields(schema: dict, fields: list[str]) -> dict:
    """Copia de ``schema`` con cada campo de ``fields`` como lista de pares ``{label, value}``."""
    if not fields:
        return schema
    out = copy.deepcopy(schema)
    props = out.get("properties", {})
    for name in fields:
        if name in props:
            description = props[name].get("description") or props[name].get("title") or name
            props[name] = {**copy.deepcopy(_PAIR_LIST_SCHEMA), "description": f"{description} (lista etiqueta -> valor)"}
    return out


def decode_dict_fields(data: object, fields: list[str]) -> object:
    """Inverso de ``encode_dict_fields``: listas de pares -> ``dict`` (acepta también dicts)."""
    if not fields or not isinstance(data, dict):
        return data
    data = dict(data)
    for name in fields:
        value = data.get(name)
        if isinstance(value, list):
            pairs: dict[str, str] = {}
            for item in value:
                if isinstance(item, dict) and str(item.get("label", "")).strip():
                    pairs[str(item["label"]).strip()] = str(item.get("value", "")).strip()
            data[name] = pairs
    return data


def parse_json_model(
    text: str, response_model: type[BaseModel], pair_fields: list[str] | None = None
) -> BaseModel:
    """Convierte ``text`` (JSON, con o sin vallas ```json) en ``response_model``.

    ``pair_fields``: campos ``dict`` que llegan como lista de pares (``encode_dict_fields``).

    Raises:
        ValueError / ValidationError: JSON mal formado o que no cumple el esquema.
    """
    cleaned = _FENCE.sub("", text.strip()).strip()
    data = json.loads(cleaned)
    return response_model.model_validate(decode_dict_fields(data, pair_fields or []))


def complete_structured(
    call: CallFn,
    messages: list[dict],
    response_model: type[BaseModel],
    usage_out: dict[str, int] | None = None,
    *,
    max_fix_attempts: int = 1,
    pair_fields: list[str] | None = None,
) -> BaseModel:
    """Llama al modelo y valida; con error, reintenta ``max_fix_attempts`` veces.

    ``usage_out`` acumula los tokens de **todas** las llamadas (para que el coste del paso
    incluya el reintento). ``pair_fields``: ver ``parse_json_model``.

    Raises:
        StructuredOutputError: si tras los reintentos la salida sigue sin ser válida.
    """
    if usage_out is None:
        usage_out = {}
    usage_out["input_tokens"] = 0
    usage_out["output_tokens"] = 0
    history = list(messages)
    last_error: Exception | None = None
    for attempt in range(max_fix_attempts + 1):
        text, usage = call(history)
        usage_out["input_tokens"] += int(usage.get("input_tokens", 0))
        usage_out["output_tokens"] += int(usage.get("output_tokens", 0))
        try:
            return parse_json_model(text, response_model, pair_fields)
        except (ValueError, ValidationError) as exc:  # json.JSONDecodeError es ValueError
            last_error = exc
            detail = str(exc)[:_MAX_ERROR_CHARS]
            log.warning(
                "Salida estructurada %s inválida (intento %d): %s",
                response_model.__name__,
                attempt + 1,
                detail.splitlines()[0] if detail else type(exc).__name__,
            )
            history = list(messages) + [
                {"role": "assistant", "content": text[:20_000] or "(vacío)"},
                {
                    "role": "user",
                    "content": (
                        f"Tu respuesta no es un JSON válido para el esquema {response_model.__name__}. "
                        f"Error de validación:\n{detail}\n\n"
                        "Devuelve de nuevo la respuesta COMPLETA, corregida, solo como JSON."
                    ),
                },
            ]
    raise StructuredOutputError(
        f"{response_model.__name__}: salida no válida tras {max_fix_attempts + 1} intentos: {last_error}"
    ) from last_error
