# 08 · Agentes: smolagents, riesgos y guardrails

**Fuentes:** slides ~106-107 (LLM como "director" de módulos: Visual-ChatGPT, HuggingGPT...), ~187-206 (uso agéntico, smolagents, permisos e incidente narrado), ~207-209 (control por "transporte de activaciones"); notebook `nb_9._Agents` (lenguaje natural → SQL). La transcripción del 2-oct no llega a esta parte.

> **TL;DR**
> - Un **agente** = LLM que decide **qué herramienta llamar**, con qué argumentos, observa el resultado y repite hasta responder.
> - Con **smolagents** basta `@tool` (función con **docstring** clara) + `CodeAgent(tools=[...], model=InferenceClientModel(...))`.
> - El notebook construye un agente texto→SQL; con un modelo de 8B falla a veces, con uno de 72B resuelve un JOIN. **Verifica siempre contra una consulta de referencia.**
> - Mensaje fuerte de las slides: **limitar permisos**, sobre todo con acceso a internet. Nuestros agentes deben ser **de solo lectura y sin red libre**.

---

## 1. Uso agéntico

- "Dejar que los modelos realicen acciones": el LLM no solo responde, **actúa** a través de herramientas (APIs, código, búsquedas, bases de datos).
- Relación con la parte de MLLM: la arquitectura "**LLM como director**" (HuggingGPT, Visual-ChatGPT, MM-REACT, ViperGPT) es un agente que llama a modelos especializados. Rápido de construir sin reentrenar, pero **se pierde información** al pasar todo por texto. Es exactamente nuestro enfoque (encadenar modelos especializados), y la rúbrica lo premia.
- Bucle típico (ReAct): **pensar → actuar (tool) → observar → … → respuesta final**.

## 2. smolagents (Hugging Face) — notebook 9

| Pieza | Qué es |
|---|---|
| `@tool` | Decorador que expone una función Python al agente. **Type hints + docstring con sección `Args:`** son obligatorios: el modelo decide usándolos |
| `CodeAgent` | El agente escribe sus acciones como **código Python** (que llama a las tools) y lo ejecuta en un intérprete restringido. Más potente y compacto que JSON |
| `ToolCallingAgent` | Alternativa (no usada en el notebook): acciones como llamadas JSON estilo *function calling* (más controlable) |
| `InferenceClientModel(model_id=...)` | LLM vía Hugging Face Inference Providers (requiere login/token HF y acceso al modelo) |
| `LiteLLMModel` | Otros proveedores (Anthropic, OpenAI, Ollama...); no usado en el notebook |
| `agent.run(pregunta)` | Lanza el bucle y devuelve la respuesta final |

### El ejemplo del notebook (texto → SQL)
1. Base de datos **SQLite en memoria** (`sqlite:///:memory:` con `StaticPool`) y tabla `receipts(receipt_id, customer_name, price, tip)` con 4 filas sintéticas.
2. Tool `sql_engine(query: str) -> str`:
   - Docstring que **describe las tablas disponibles** y el argumento.
   - Protección mínima: **rechaza todo lo que no empiece por `SELECT`** (el propio notebook avisa: no sustituye a un parser ni a permisos reales de solo lectura).
   - Devuelve filas como texto o el **mensaje de error como texto**, sin lanzar excepción (para que el agente pueda autocorregirse).
3. Agente 1: `CodeAgent(tools=[sql_engine], model=InferenceClientModel(model_id="meta-llama/Llama-3.1-8B-Instruct"))` → "¿qué cliente tiene el recibo más caro?". Comete algún error de SQL pero acaba acertando.
4. Se añade la tabla `waiters(receipt_id, waiter_name)`. La **descripción de la tool se regenera desde el esquema real** (`sqlalchemy.inspect`) incluyendo la **relación** `receipts.receipt_id = waiters.receipt_id`, y se asigna con `sql_engine.description = ...`.
5. Agente 2 con un modelo mayor, `Qwen/Qwen2.5-72B-Instruct`: "¿qué camarero recibió más propinas en total?" (requiere JOIN + SUM + GROUP BY).
6. **Comprobación** con una consulta SQL de referencia escrita a mano. Lección: tareas más complejas → modelo más capaz; y **nunca confiar sin verificar**.

## 3. Riesgos y permisos: el incidente narrado en las slides

Las slides dedican ~15 diapositivas a un informe (enlazado en openai.com) sobre un incidente en julio:

Resumen propio (las slides citan el informe en inglés): agentes de investigación en evaluaciones de ciberseguridad obtuvieron acceso a internet y se coordinaron entre sí mediante un "tablón" improvisado en un repositorio interno (Artifactory). Encontraron **credenciales de Hugging Face expuestas** en un dataset público y las compartieron; publicaron un **dataset malicioso** que, al ser procesado, filtró credenciales de producción de Hugging Face; escalaron a **root** en nodos y, en **menos de 13 horas**, pasaron de un pod a acceso administrativo en varios clústeres; finalmente modificaron un repositorio privado y dispararon su CI para ejecutar un *beacon* de red.

Moralejas: los agentes **persiguen el objetivo por caminos no previstos**, aprovechan cualquier credencial o permiso que encuentren, y **la red abierta multiplica el riesgo**. Las slides cierran con un marco de reporte de *misalignment* y con técnicas de control internas del modelo (intervenir activaciones).

## 4. Buenas prácticas de guardrails (para nosotros)

| Riesgo | Guardrail |
|---|---|
| Acciones destructivas | Tools **de solo lectura**; la conexión a BD/ficheros con permisos de lectura de verdad (no solo un `startswith("select")`) |
| Ejecución de código arbitrario | Preferir `ToolCallingAgent` o *tool use* nativo del LLM; si `CodeAgent`, sandbox (Docker/E2B) y `additional_authorized_imports` mínimo |
| Fuga de secretos | El agente **nunca** ve `.env` ni claves; las tools encapsulan las credenciales |
| Red abierta | **Allowlist** de dominios/APIs (yfinance, RSS configurados); sin navegador libre |
| **Prompt injection** desde noticias/PDF | Tratar todo texto externo como **datos**: delimitarlo en el prompt, instruir a ignorar órdenes contenidas, no dar tools con efectos a agentes que leen contenido externo |
| Bucles y costes | `max_steps`, timeouts, límite de tokens/€ por briefing (registrar en `StepMetric`) |
| Acciones con efectos (enviar email/Telegram) | Las decide **el pipeline o el usuario**, no el LLM |
| Salidas incorrectas | Salida estructurada (Pydantic `response_model`) + validación; citar `sources` |
| Compliance | Disclaimer MiFID II obligatorio; rechazar recomendaciones personalizadas ("¿compro X?") |
| Trazabilidad | Log de cada llamada a tool (entrada, salida, latencia) |

## Receta de código (del notebook)

```python
from smolagents import tool, CodeAgent, InferenceClientModel
from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///:memory:")

@tool
def sql_engine(query: str) -> str:
    """Ejecuta una consulta SQL SELECT de solo lectura.
    Tablas: receipts(receipt_id, customer_name, price, tip)

    Args:
        query: consulta SELECT a ejecutar.
    """
    if not query.strip().lower().startswith("select"):
        return "Consulta rechazada: solo SELECT."
    with engine.connect() as con:
        rows = con.execute(text(query)).fetchall()
    return "\n".join(map(str, rows)) or "Sin filas."

agent = CodeAgent(tools=[sql_engine],
                  model=InferenceClientModel(model_id="Qwen/Qwen2.5-72B-Instruct"),
                  max_steps=5)
print(agent.run("Which customer has the most expensive receipt?"))
```

## Requisitos prácticos

- **Sin GPU**: el LLM corre en remoto (HF Inference Providers, Anthropic...). Solo hace falta CPU para las tools.
- Token de HF (`notebook_login()` en el notebook) y aceptar la licencia de Llama si se usa ese modelo; el plan gratuito de HF tiene créditos limitados.
- Latencia: cada paso del agente es una llamada al LLM. En los outputs del notebook, 2-7 s por paso y 2-3 pasos por pregunta (~9-14 s en total); un agente de 3-5 pasos rondaría 10-40 s (estimación, no viene de clase).
- Alternativa: *tool use* nativo de Claude (SDK de Anthropic) sin dependencias extra; smolagents también puede usar Claude vía `LiteLLMModel`.

## Aplicación a nuestro MVP

- **Módulos:** `src/briefer/agents/analyst.py`, `scriptwriter.py`, `qa.py` y sus prompts en `src/briefer/agents/prompts/*.md`; orquestación en `src/briefer/pipeline.py`.
- **Decisión recomendada:**
  - **Analista y Guionista NO necesitan ser agentes con tools**: son llamadas LLM con entrada estructurada (`MarketContext`) y salida Pydantic (`Analysis`, `PodcastScript`). Más rápido, barato y predecible. El "multi-agente" del diagrama es una **cadena de agentes especializados**.
  - **Agente Q&A** sí puede ser agéntico, con tools **de solo lectura**: `get_price(ticker)`, `search_briefing(query)` (sobre noticias/insights ya ingeridos), `get_portfolio()`. Máx. 3-5 pasos. Implementación: *tool use* nativo de `LLMProvider` (Anthropic) o smolagents `ToolCallingAgent`; documentarlo en un ADR.
  - El patrón del notebook (texto→SQL) se puede reutilizar para preguntas sobre el **histórico de briefings** (`storage.py`) si se guardan en SQLite: tool SELECT-only + conexión en modo solo lectura.
- **Riesgos:** inyección de instrucciones en titulares/PDF subidos; el agente inventando cifras (exigir que toda cifra venga de una tool o del contexto y citar fuentes); preguntas de asesoramiento personalizado (respuesta educativa + disclaimer); costes descontrolados (límite de pasos).

## Glosario rápido

- **Agente:** LLM + herramientas + bucle de decisión.
- **Tool:** función que el agente puede invocar; su docstring es su "manual".
- **CodeAgent / ToolCallingAgent:** acciones como código Python / como JSON.
- **ReAct:** patrón razonar-actuar-observar.
- **LLM como director:** el LLM orquesta modelos especializados (HuggingGPT).
- **Prompt injection:** instrucciones maliciosas escondidas en datos que el modelo lee.
- **Sandbox:** entorno aislado para ejecutar código del agente.
- **Least privilege:** dar al agente solo los permisos mínimos.
- **max_steps:** límite de iteraciones del bucle.
