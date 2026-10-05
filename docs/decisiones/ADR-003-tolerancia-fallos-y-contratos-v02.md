# ADR-003 · Tolerancia a fallos por paso y contratos v0.2

- **Estado:** Aceptado
- **Fecha:** 05-oct-2026
- **Ámbito:** `src/briefer/pipeline.py`, `schemas.py` (`StepMetric`, `QAAnswer`), `logging_utils.py`,
  `storage.py`, `app/` (cómo se muestran los errores); todos los carriles

## Contexto

- En el esqueleto (v0.1) cualquier excepción se propagaba desde `run_briefing`: un fallo en la portada, el vídeo
  o un envío por Telegram tumbaba el briefing entero, aunque el podcast ya estuviera generado.
- La rúbrica valora la **robustez** (4.3) y la demo no puede depender de que funcionen a la vez yfinance,
  Anthropic, edge-tts, ffmpeg, SMTP y Telegram ([07 · H2, H4](../07_revision_critica.md)).
- El fallo de un paso se marcaba metiendo `"[ERROR …]"` dentro de `StepMetric.model`: frágil de leer, mezcla
  dos datos en un campo y ensucia la tabla de métricas.
- La métrica de `storage.save` se medía mientras se guardaba y no llegaba a `Briefing.metrics` (bug).
- `QAAnswer` no tenía métricas, así que el objetivo de latencia del Q&A (< 10 s) no se podía demostrar en la UI.
- `briefing.json` guardaba rutas absolutas: el histórico y el futuro briefing pregenerado no funcionarían en otra
  máquina ni en Docker.
- Desde el martes 13:00 los contratos solo admiten cambios aditivos ([05 · reglas](../05_roadmap_TODO.md#reglas-de-trabajo)).

## Decisión

Cada paso de `run_briefing` y `answer_question` se clasifica como **núcleo** u **opcional**, y los contratos
suben a **v0.2** con cambios exclusivamente aditivos.

1. **Núcleo** (`ingest.news`, `ingest.tickers`, `ingest.prices`, `agents.analyst`, `agents.scriptwriter`,
   `media.podcast`, `media.transcript`, `media.charts`; en el Q&A `qa.stt` y `agents.qa`): si falla, se lanza
   `PipelineStepError(step, causa)` (o `StepNotImplementedError` si es un *stub*, que la UI pinta como
   «Pendiente»). Sin estos pasos no hay producto.
2. **Opcional** (cada subida, `media.cover`, `media.video`, cada `delivery.<canal>`, `storage.save`; en el Q&A
   `qa.tts`): si falla, se registra en el log, su `StepMetric` lleva `error` y el briefing sigue sin esa pieza
   (un canal caído queda en `Briefing.deliveries` con `ok=False`).
3. Las entradas inválidas se rechazan **antes** de gastar nada: `ValueError` sin tickers ni cartera o con un
   canal de entrega desconocido.
4. `StepMetric.error: str | None = None` sustituye la marca en `model`; `QAAnswer.metrics: list[StepMetric] = []`.
5. `storage.save` entra en `Briefing.metrics`; `briefing.json` guarda rutas relativas a su carpeta.
6. El progreso se notifica como `"(n/N) mensaje"`, y los tickers de entrada se normalizan con
   `ingest.tickers.normalize_ticker`.
7. Dentro de los pasos núcleo hay redes de seguridad locales que no cambian la clasificación: reintentos por línea
   en el TTS, reescritura única y guion de respaldo en el Guionista, gráficos aislados entre sí.

Queda **pendiente** (D1) y no forma parte de esta decisión cerrada: que un paso núcleo con proveedor real que
falla se **repita con el mock** y quede marcado (`provider="mock"` + `error`), en lugar de abortar.

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |
| Propagar todas las excepciones (v0.1) | Simple; ningún error queda oculto | Un fallo accesorio (Telegram, vídeo) tira un briefing de 1-3 min ya pagado; mala demo |
| Capturar todo y seguir siempre | Nunca se rompe | Un briefing sin análisis o sin audio no tiene sentido; esconde errores graves |
| Caer a mock en **todos** los pasos ya en la Fase 0 | Máxima robustez | Puede grabarse una demo «real» que es mock; necesita insignias en la UI primero (D1) |
| Mantener la marca `"[ERROR …]"` en `model` | Sin tocar `schemas.py` | Parseo frágil, campo con dos significados; la UI tendría que conocer el formato |
| Campo `status: Literal["ok","error","fallback"]` en `StepMetric` | Más expresivo | Dos campos para lo mismo hasta que exista el fallback; `error: str \| None` basta hoy y `fallback` puede añadirse después de forma aditiva |

## Consecuencias

- **Positivas:**
  - Un fallo accesorio ya no cuesta el briefing; la UI enseña qué paso falló y por qué.
  - Métricas completas y legibles (latencia, coste y error por paso, también del guardado y del Q&A): base para
    la pestaña «Cómo se hizo» y para medir p50/p95.
  - Carpetas de briefing portables: habilitan el histórico entre máquinas y el briefing pregenerado.
  - Cambio aditivo: los JSON y el código de v0.1 siguen siendo válidos.
- **Negativas / deuda que se asume:**
  - Hay que mantener la lista núcleo/opcional al añadir pasos (documentada en [03](../03_contratos_modulos.md)).
  - Un paso opcional fallido puede pasar desapercibido si la UI no lo resalta: la UI debe mostrar `error`.
  - La caída a mock del núcleo sigue pendiente y requiere insignias para no engañar en la demo.
- **Para revertir:** volver a propagar en `_optional_step`; `StepMetric.error` puede quedarse (es opcional).

Ver también: [03 · registro de cambios](../03_contratos_modulos.md#registro-de-cambios-de-contrato) ·
[07 · revisión crítica](../07_revision_critica.md).
