# ADR-002 · Proveedores de IA intercambiables y modo mock

- **Estado:** Aceptado
- **Fecha:** 05-oct-2026
- **Ámbito:** `src/briefer/providers/`, y todo módulo que use un modelo (`ingest/`, `agents/`, `media/`)

## Contexto

- La rúbrica exige una **separación limpia** entre la conexión con los modelos, la lógica de negocio y la UI.
- Tres personas trabajan en paralelo durante tres días: no pueden esperar a que exista el código de las otras
  ni depender de que todas tengan todas las claves.
- Las APIs fallan, tienen límites de uso y cambian de precio; una demo en vivo no puede depender de una sola.
- La viabilidad económica ([04](../04_viabilidad_costes_latencia_compliance.md)) depende de poder cambiar a
  modelos más baratos o locales sin reescribir nada.
- El material de clase aporta alternativas locales (Qwen2.5-VL, Whisper, SDXL-Turbo, CLIP, Bark) que queremos
  poder enseñar.

## Decisión

Toda llamada a un modelo pasa por una **interfaz abstracta por familia** (`LLMProvider`, `VisionProvider`,
`STTProvider`, `TTSProvider`, `ImageGenProvider`, `ImageClassifier`) definida en `providers/base.py`. Un
`registry.py` elige la implementación según variables `BRIEFER_<FAMILIA>_PROVIDER` del `.env`.

Existe siempre una implementación **`mock`** por familia que no usa red ni claves y devuelve objetos válidos
según los schemas. Si falta la clave o la librería de un proveedor real y `BRIEFER_FALLBACK_TO_MOCK=true` (por
defecto), el registry cae a `mock` y lo deja en el log; con `false` lanza `ProviderConfigError`. En el código
el proveedor por defecto de cada familia es `mock` (`none` para imagen y clasificador); `.env.example` propone
el stack real.

Reglas:

1. Solo `providers/` importa SDKs de IA (`anthropic`, `openai`, `google-genai`, `edge_tts`, `elevenlabs`,
   `transformers`…).
2. Solo `pipeline.get_providers` llama a `registry.get_*()`; `ingest/`, `agents/` y `media/` **reciben el
   proveedor por parámetro** (inyección de dependencias) y nunca instancian uno concreto.
3. Cada proveedor expone `provider_name` y `model` (y `last_usage` si factura por tokens) para que `StepMetric`
   y `costs.py` registren qué se usó y cuánto cuesta.
4. Los reintentos y los *fallbacks* los decide `pipeline.py`, no el proveedor.

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |
| Llamar a los SDKs directamente desde agentes y media | Menos código inicial | Acopla negocio y proveedor; imposible trabajar sin claves; incumple la separación pedida |
| LangChain / LiteLLM como capa de abstracción | Muchos proveedores ya integrados | Solo cubre bien LLM; añade dependencia pesada y curva; TTS/STT/visión local quedan fuera igualmente |
| Abstracción solo para el LLM | Más simple | Visión, STT y TTS son justo las modalidades que más fallan y más cuestan |
| Mocks solo en los tests (con `unittest.mock`) | Estándar | No sirve para desarrollar la UI ni para una demo de respaldo |

## Consecuencias

- **Positivas:**
  - Los tres carriles avanzan en paralelo desde D0 con datos mock coherentes.
  - `pytest` corre sin red ni claves.
  - Cambiar de modelo (más barato, local, otro proveedor) es una línea en `.env`; se puede enseñar en la demo.
  - Separación de capas demostrable en el código para la rúbrica.
  - Demo de respaldo si una API falla en directo.
- **Negativas / deuda:**
  - Más ficheros y una capa de indirección.
  - Las interfaces son el mínimo común: capacidades específicas (streaming, caché de prompts, voces con
    emoción) requieren ampliar la interfaz o parámetros opcionales.
  - El mock puede ocultar problemas reales de formato: hace falta al menos una prueba de integración real por
    proveedor antes de la entrega.
- **Para revertir:** no se prevé; añadir un proveedor es añadir un fichero y una entrada en el registry.
