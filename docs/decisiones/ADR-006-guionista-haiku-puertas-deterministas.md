# ADR-006 · Guionista en Haiku con puertas deterministas

- **Estado:** Aceptado
- **Fecha:** 05-oct-2026
- **Ámbito:** `src/briefer/agents/scriptwriter.py`, `agents/guardrails.py`, `agents/prompts/scriptwriter.md`,
  `pipeline.scriptwriter_llm`, `BRIEFER_SCRIPTWRITER_MODEL`. Carril B

## Contexto

- En la Fase 1 el Guionista (Claude Haiku 4.5) salía irregular: fallos de formato y alternancia que acababan
  en reintento o en el guion de respaldo, alguna cifra que no estaba en el análisis, homoglifos cirílicos que
  el TTS lee mal y puntos clave que se quedaban fuera del podcast. La pregunta abierta en
  [05](../05_roadmap_TODO.md) era si pasarlo a Sonnet 5.5.
- El Guionista no razona sobre las fuentes: reescribe en diálogo un `Analysis` ya verificado (puerta de
  *grounding* del Analista). Lo que falla son cosas **comprobables** sin un modelo.

## Decisión

**El Guionista sigue en Haiku 4.5 por defecto, con puertas deterministas** que piden una reescritura
(`max_retries=1`) o reparan el guion. Cambiar de modelo es configuración: `BRIEFER_SCRIPTWRITER_MODEL`
(p. ej. `claude-sonnet-5-5`), que lee `pipeline.scriptwriter_llm`; vacío = el modelo barato.

Puertas (`scriptwriter.script_problems`, `write_script`):

- *Grounding* del guion: cifras que no estén en el análisis (`guardrails.untraceable_figures`); si persisten
  tras el reintento, se quitan esas frases.
- Cobertura: cada punto clave con cifras debe aparecer (`missing_key_points`).
- Duración 3-5 min con objetivo de 4 (`duration_bounds_s`).
- Alternancia A/B (`same_speaker_runs`, `merge_long_runs`), recomendaciones (`contains_advice`).
- Texto hablable: `odd_words` (otros alfabetos, invisibles), `grammar_issues` / `fix_spoken_text`
  («para que veis» → «para que veáis»), `fix_homoglyphs`. `unhedged_causal_claims` detecta causas afirmadas sin
  atribuir a la fuente (hoy solo se anota en la traza).

## Datos de la comparativa

2 guiones con Haiku 4.5 frente a 2 con Sonnet 5.5 sobre el **mismo** `Analysis` real (el del pregenerado),
con las mismas puertas:

| Modelo | Coste por guion | Latencia | Resultado con las puertas |
| --- | --- | --- | --- |
| Claude Haiku 4.5 | ≈ 0,009 € | 15-20 s | Cumple (puntos clave cubiertos, cifras trazables) |
| Claude Sonnet 5.5 | ≈ 0,024-0,026 € (**2,6-2,9× más caro**) | 15-20 s | Cumple; algo más natural, sin diferencia que justifique el coste |

En el pregenerado final (`20261005-130504-0f8ae2`): Haiku, 0,0100 €, 17,9 s, 28 intervenciones, «cifras
trazables al análisis» y los 6 puntos clave cubiertos. Muestra pequeña (4 guiones): la comparativa amplia queda
para el camino 2 de [05](../05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2).

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |
| Sonnet 5.5 para el Guionista | Prosa algo más natural | 2,6-2,9× el coste del paso sin mejora medible en las puertas; misma latencia |
| Haiku sin puertas (Fase 1) | Lo más barato | Calidad irregular, cifras sin respaldo, respaldo determinista en la demo |
| **Haiku + puertas deterministas, modelo configurable (elegida)** | Barato, verificable en tests sin red, reversible por `.env` | Las puertas no ven todo (ver negativas) |

## Consecuencias

- Positivas: el coste del briefing sigue dominado por Sonnet en Analista y visión; las puertas son funciones
  puras con tests; la traza («Cómo se hizo») enseña el resultado (`StepMetric.detail` de
  `agents.scriptwriter`).
- Negativas / deuda: la duración del pregenerado (5:27 de audio frente a la estimación de 4,5 min por palabras)
  supera el objetivo de 4 min; las puertas no detectan regionalismos («precificado», «allá»); la cobertura de
  puntos sin cifras no se comprueba; un reintento duplica el coste del paso cuando ocurre.
- Para revertirla: `BRIEFER_SCRIPTWRITER_MODEL=claude-sonnet-5-5` en `.env` (sin tocar código).
