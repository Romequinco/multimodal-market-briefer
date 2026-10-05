# ADR-004 · Salida estructurada con `output_config` JSON Schema y pares para los diccionarios

- **Estado:** Aceptado
- **Fecha:** 05-oct-2026
- **Ámbito:** `src/briefer/providers/llm/anthropic_llm.py`, `providers/llm/_structured.py`,
  `providers/llm/gemini_llm.py`; consumidores de `LLMProvider.complete(..., response_model=…)` (Analista,
  Guionista, Q&A, `pdf_reader`, `chart_reader`). Carril B

## Contexto

- El contrato `LLMProvider.complete(..., response_model=X)` exige devolver una instancia válida de `X` o lanzar
  ([03](../03_contratos_modulos.md#interfaces-de-proveedores)); los agentes dependen de ello (`Analysis`,
  `PodcastScript`, `DocumentInsight`).
- La vía clásica (herramienta forzada con `tool_choice`) no sirve con el modelo principal: Claude Sonnet 5.5
  rechaza `tool_choice` de tipo `any`/`tool` con un 400.
- La API de Anthropic ofrece **salida estructurada** con `output_config.format = {"type": "json_schema",
  "schema": …}`, que restringe la respuesta al esquema. El esquema debe ser estricto: `additionalProperties:
  false` en todos los objetos y sin algunas restricciones de JSON Schema; `anthropic.transform_schema` adapta
  el que genera Pydantic.
- Problema detectado en la integración: con ese esquema estricto, un campo `dict[str, str]` libre
  (`DocumentInsight.key_figures`) queda como objeto sin propiedades admitidas, así que el modelo solo puede
  devolver `{}`: las cifras del PDF y del gráfico llegaban siempre vacías.
- Los contratos están congelados salvo cambios aditivos ([03 · reglas](../03_contratos_modulos.md#reglas-de-cambio)).

## Decisión

Los LLM reales piden JSON restringido por esquema y validan con Pydantic, con **un** reintento autocorrectivo;
los campos `dict` viajan como **lista de pares** y se reconvierten antes de validar, sin cambiar el contrato.

1. `AnthropicLLM` envía `output_config.format` con el esquema de `anthropic.transform_schema(response_model)`
   (cacheado por clase). Gemini usa el equivalente (`response_mime_type="application/json"` +
   `response_json_schema`).
2. `_structured.complete_structured` valida con Pydantic; si falla, repite una vez enviando al modelo su propia
   respuesta y el error de validación. Si vuelve a fallar, lanza `StructuredOutputError` (y el pipeline aplica
   el fallback del paso, ver [ADR-003](ADR-003-tolerancia-fallos-y-contratos-v02.md) y
   [03 · v0.3](../03_contratos_modulos.md#pasos-núcleo-y-pasos-opcionales)). `last_usage` suma los tokens de
   todos los intentos.
3. `dict_fields(response_model)` detecta los campos `dict` de primer nivel; `encode_dict_fields` los sustituye
   en el esquema por un array de `{"label": str, "value": str}`; `decode_dict_fields` (vía `pair_fields` en
   `parse_json_model`) los convierte de nuevo en `dict` antes de `model_validate`.

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |
| Herramienta forzada (`tool_choice`) | Patrón conocido, funciona en Haiku | 400 en Sonnet 5.5; dos caminos distintos según modelo |
| JSON «a mano» en el prompt + parseo | Sin dependencias de API | Sin garantía de esquema; más reintentos y más coste |
| Cambiar `key_figures` a `list[KeyFigure]` en `schemas.py` | Esquema limpio | Cambio **incompatible** de contrato (rompe mocks, UI, tests y briefings guardados) |
| **`output_config` JSON Schema + pares para `dict`** (elegida) | Esquema garantizado por la API, un solo camino para Sonnet y Haiku, contrato intacto | Adaptación interna (`_structured.py`) que hay que mantener; solo cubre `dict` de primer nivel |

## Consecuencias

- Positivas: `DocumentInsight.key_figures` llega relleno con Sonnet y Haiku; `smoke_real.py` comprueba
  `anthropic.structured` y `gemini.structured`; test sin red de la codificación de pares
  (`tests/test_integration_f1.py::test_dict_fields_travel_as_pairs_in_strict_schema`).
- Negativas / deuda: un `dict` anidado en un submodelo no se codifica (hoy no existe ninguno); si se añade, hay
  que ampliar `dict_fields`. El reintento autocorrectivo puede duplicar el coste de un paso cuando ocurre.
- Para revertirla: volver a texto libre + parseo, o cambiar `key_figures` a lista de objetos con cambio de
  versión mayor de contratos.
