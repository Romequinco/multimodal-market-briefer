# ADR-007 · Modelo por agente: Sonnet analiza, Haiku escribe y responde, Gemini como alternativa

- **Estado:** Aceptado
- **Fecha:** 06-oct-2026
- **Ámbito:** `agents/analyst.py`, `agents/scriptwriter.py`, `agents/qa.py`, `pipeline.scriptwriter_llm`,
  `providers/llm/*`, variables `BRIEFER_LLM_PROVIDER`, `BRIEFER_LLM_MODEL`, `BRIEFER_LLM_MODEL_CHEAP`,
  `BRIEFER_SCRIPTWRITER_MODEL`, `BRIEFER_GEMINI_MODEL`, `BRIEFER_VISION_MODEL`. Carril B (camino 2 de
  [05](../05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2))

## Contexto

- Cada agente usa hoy un modelo elegido con poca evidencia: Analista y visión en Claude Sonnet 5.5, Guionista y
  Q&A en Claude Haiku 4.5 ([ADR-001](ADR-001-stack-mvp.md)). El Guionista tenía una primera comparativa de 4
  guiones ([ADR-006](ADR-006-guionista-haiku-puertas-deterministas.md)) y Gemini había generado un briefing
  completo una vez (05-oct, 0,021 €, sin tocar código), pero sin medir calidad.
- La rúbrica premia el encadenamiento de varios modelos «con sentido»: hay que poder justificar qué modelo hace
  cada paso con coste, latencia y calidad medidos, y si hay una alternativa de otro proveedor.
- Restricciones: presupuesto del camino ≤ 1 €, sin tocar código, prompts ni `.env`; el producto informa y no
  asesora (MiFID II), así que la ausencia de consejo y la trazabilidad de cifras pesan más que el estilo.

## Decisión

**Se mantienen los modelos actuales; no hay cambio de configuración.** Analista en **Sonnet 5.5**; Guionista
y Q&A en **Haiku 4.5** (se **confirma ADR-006**, que no se edita); visión sigue en **Sonnet 5.5** (no se comparó en
este camino). **Gemini (`gemini-2.5-flash`) es alternativa viable para el briefing completo como plan B de
proveedor** (`BRIEFER_LLM_PROVIDER=gemini`), no como opción por defecto.

| Agente | Modelo | Por qué |
| --- | --- | --- |
| Analista | Claude Sonnet 5.5 | Único limpio a la primera en los 2 contextos y el mejor del juez en fidelidad (4,5 frente a 3,0 y 2,0) |
| Guionista | Claude Haiku 4.5 | Sin problemas finales en 4/4, el más rápido y 3,2× más barato que Sonnet; las puertas deterministas cubren lo que se le escapa |
| Q&A | Claude Haiku 4.5 | Los tres reconducen la petición de consejo y citan fuentes; Haiku es barato y ya está medido con la cadena de voz (< 10 s) |
| Visión | Claude Sonnet 5.5 | Sin cambios: no se midió aquí (queda como deuda) |
| Alternativa de proveedor | Gemini 2.5 Flash | ≈ 45 % más barato por briefing, pero Analista 2× más lento y con reintentos; útil si Anthropic falla o se agota el crédito |

## Cómo se midió y con qué coste

Cuaderno [`notebooks/02_comparativa_modelos.ipynb`](../../notebooks/02_comparativa_modelos.ipynb), ejecutado en
real el 06-oct-2026; resultados en `notebooks/eval/comparativa/` (`runs.jsonl`, `juez.jsonl`, `resumen.md`,
tablas CSV). **Gasto total: 0,546 €** (agentes 0,399 € + juez 0,147 €), medido como el pipeline: tokens reales de
cada llamada (reintentos incluidos) por las tarifas de `briefer.costs` vía `pipeline._MeteredLLM`. Las tarifas de
Gemini son estimación (ver `costs.py`).

- **Contextos congelados** (`MarketContext` de briefings guardados, copiados a `eval/comparativa/contextos/`):
  `demo` (pregenerado del 05-oct: 5 tickers, 19 noticias, PDF + gráfico) y `oct06` (SAN.MC + AAPL, 19 noticias,
  gráfico). Sin cartera.
- **Analista:** 1 ejecución por modelo y contexto (`analyst.analyze` con sus puertas). **Guionista:** 2 guiones
  por modelo y contexto sobre el **mismo análisis de Sonnet** (aísla el modelo) + la cadena propia de Haiku y
  Gemini. **Q&A:** 2 preguntas (factual y «¿me recomiendas comprar Nvidia?») sobre el pregenerado.
- **Métricas deterministas:** validez estructurada a la primera, reintentos de las puertas, cifras no trazables
  (`guardrails.untraceable_figures`) y recomendaciones (`contains_advice`) en la primera salida y en la final,
  `script_problems` y duración estimada del guion.
- **Juez ciego:** Sonnet 5.5 con salida estructurada y `effort="low"`, salidas anónimas A/B/C en orden aleatorio
  y en el inverso (promedio de las dos pasadas), rúbrica 1-5. Sonnet 5.5 **no admite `temperature`** (400,
  «deprecated for this model»): la variabilidad se acota con `effort` bajo y la doble pasada.

### Resultados (medias por ejecución)

| Agente | Modelo | n | Coste (€) | Latencia (s) | JSON a la 1.ª | Reintentos de puertas | Juez fidelidad / claridad / naturalidad / sin consejo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Analista | Sonnet 5.5 | 2 | 0,0264 | 15,0 | 2/2 | 0 | 4,5 / 4,5 / – / 4,25 |
| Analista | Haiku 4.5 | 2 | 0,0096 | 16,9 | 2/2 | 0 | **2,0** / 4,0 / – / 3,25 |
| Analista | Gemini 2.5 Flash | 2 | 0,0148 | **32,9** | 2/2 | **2** (1 recomendación que persistió y se recortó; 1 cifra no trazable) | 3,0 / 4,0 / – / 4,0 |
| Guionista | Sonnet 5.5 | 4 | 0,0349 | 21,1 | 4/4 | 1 (frase con forma de recomendación) | 4,25 / 4,5 / 3,5 / 5,0 |
| Guionista | Haiku 4.5 | 4 | 0,0109 | 14,9 | 4/4 | 1 (gramática) | 3,5 / 4,0 / 3,5 / 4,25 |
| Guionista | Gemini 2.5 Flash | 4 | 0,0074 | 15,5 | 4/4 | 3 (duración > 5 min) | 4,0 / 4,0 / 3,5 / 4,25 |
| Q&A | Sonnet 5.5 | 2 | 0,0110 | 2,5 | – | – | (0 recomendaciones) |
| Q&A | Haiku 4.5 | 2 | 0,0044 | 3,8 | – | – | (0 recomendaciones) |
| Q&A | Gemini 2.5 Flash | 2 | 0,0018 | 3,1 | – | – | (0 recomendaciones) |

- En **todas** las salidas finales: 0 cifras no trazables, 0 recomendaciones detectadas, 0 guiones de respaldo y
  JSON válido a la primera (ningún reintento de salida estructurada).
- **Duración estimada del guion** (objetivo 4 min, rango 3-5): Haiku 3,4-3,9 min; Sonnet 4,1-4,7; Gemini 5,1-6,0 a
  la primera (4,6-5,1 tras reescribir; 1 de 4 terminó fuera de rango). El audio real dura ≈ 20 % más que la
  estimación (pregenerado: 5:27 frente a 4,5 min), así que lo corto de Haiku es una ventaja.
- **Cadena propia** (Analista + Guionista del mismo modelo): Sonnet 0,071 € · Haiku 0,029 € · Gemini 0,021 €; la
  de por defecto (Sonnet + Haiku) ≈ 0,037 €. Con el análisis de Haiku, su guion dejó un punto clave sin tratar
  en 1 de 2 casos (aviso que persistió tras el reintento).
- Lo que el juez vio y las puertas no: el Analista en Haiku añade hechos y causas sin respaldo («en
  conversaciones», «generan presión») que no son cifras, y Gemini insinúa causalidad. Es el motivo principal
  para no bajar el Analista de modelo.

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |
| **Sonnet analiza, Haiku escribe y responde (elegida)** | Mejor fidelidad donde se razona sobre las fuentes; Guionista y Q&A baratos con puertas deterministas | El Analista domina el coste del texto (≈ 70 %) |
| Todo en Haiku | ≈ 0,029 € por briefing (−22 %) y misma latencia | Fidelidad del Analista 2,0 según el juez: hechos sin respaldo que ninguna puerta detecta |
| Guionista en Sonnet | Mejor nota del juez (fidelidad 4,25 frente a 3,5) | 3,2× el coste del paso y más lento (21 s); mismas métricas deterministas; posible autopreferencia del juez |
| Todo en Gemini 2.5 Flash | Lo más barato (≈ 0,021 €), JSON válido a la primera | Analista 2× más lento y con reintento en 2/2 (consejo, cifra); guiones largos; tarifas sin verificar |
| Q&A en Sonnet | Algo más rápido en esta muestra (2,5 s) | 2,5× el coste por pregunta; con n = 2 la diferencia de latencia no es concluyente |

## Consecuencias

- Positivas: la elección por agente queda justificada con datos y es reproducible (el cuaderno rehace las tablas
  sin red con `RUN_REAL=False`); Gemini queda probado como segundo proveedor con calidad medida, útil para el
  pitch (sin dependencia de un solo proveedor) y como plan B en la demo.
- Negativas / deuda que se asume: muestra pequeña (2 contextos; 1 análisis y 2 guiones por modelo y contexto);
  juez de la misma familia que uno de los candidatos; visión sin comparar (Claude frente a Qwen2.5-VL o Gemini);
  `gemini-2.5-flash` piensa en el Analista (4,8-6,5 k tokens de salida) y eso le cuesta latencia; el Q&A de Haiku
  usó «mantención» (regionalismo que `fix_regionalisms` no recoge todavía).
- Para revertirla: todo es configuración, sin tocar código: `BRIEFER_SCRIPTWRITER_MODEL=claude-sonnet-5-5`
  (Guionista en Sonnet), `BRIEFER_LLM_MODEL=claude-haiku-4-5-20251001` (Analista en Haiku) o
  `BRIEFER_LLM_PROVIDER=gemini` (briefing completo en Gemini). Repetir el cuaderno con más contextos antes de
  cambiar por defecto.
