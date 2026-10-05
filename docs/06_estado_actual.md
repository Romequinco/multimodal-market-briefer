# 06 · Estado actual

> Responde a «¿en qué estado está el proyecto hoy?». Se actualiza al final de cada jornada. Solo se marca
> como hecho lo que alguien del equipo ha ejecutado y visto funcionar; lo no comprobado se marca **NO
> VERIFICADO**. Las cifras de coste y latencia que no salgan de un `StepMetric` real se marcan **NO MEDIDO**.

**Fecha:** lun 5-oct-2026, noche · **Fase:** F0 cerrada (camino mock fin a fin) · **Siguiente:** D1, núcleo
real · **Entrega:** jue 8-oct-2026, 18:00 (objetivo interno 16:30) · **Contratos:** v0.2 · **Plan:**
[05](05_roadmap_TODO.md), revisado según [07](07_revision_critica.md)

## Resumen

Todo el producto funciona **en modo mock, sin red ni claves**: la UI y `scripts/demo.py --mock` generan un
briefing completo (noticias de ejemplo → Analista → Guionista → podcast a dos voces → SRT → gráficos →
`briefing.json`) y el Q&A responde. **Nada que necesite red o claves está implementado todavía**: los
proveedores reales y la ingesta real son *stubs*. El riesgo pasa de diseño a ejecución: D1 es el día del
núcleo real.

## Qué funciona

| Elemento | Estado | Evidencia |
| --- | --- | --- |
| Idea, diagrama, propuesta de valor, stack | Hecho | [01](01_producto_y_propuesta_valor.md), [ADR-001](decisiones/ADR-001-stack-mvp.md), [ADR-002](decisiones/ADR-002-proveedores-intercambiables.md) |
| Contratos v0.2 | Hecho | `schemas.py` (`StepMetric.error`, `QAAnswer.metrics`), [03](03_contratos_modulos.md), [ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md) |
| Interfaces, `registry`, proveedores mock | Hecho | `providers/base.py`, `registry.py`, `mock.py` |
| Ingesta en modo mock (carril A) | Hecho | `load_sample_news`, `dedupe_news`, `synthetic_snapshots`, `normalize_ticker` / `extract_tickers` / `filter_by_tickers` con alias, `load_portfolio_csv`; `tests/test_ingest_mock.py` |
| Lectores de PDF, gráfico y voz | Hecho con mocks | `read_pdf`, `read_chart` (+ `validate_image`), `voice_to_insight`; probados con `MockVision` / `MockSTT` / `MockLLM` sobre los ficheros de ejemplo. Con proveedores reales: NO VERIFICADO |
| Datos de ejemplo | Hecho | `data/samples/`: CSV, JSON, `grafico_ejemplo.png`, `resultados_ejemplo.pdf`, `generar_muestras.py` |
| Agentes Analista, Guionista, Q&A (carril B) | Hecho con `MockLLM` | Prompts de producción en `agents/prompts/`; `postprocess_analysis` (fuentes y tickers trazables), Guionista con reintento y guion de respaldo, Q&A con citas; `tests/test_agents_mock.py` |
| Guardarraíles MiFID II | Hecho | `agents/guardrails.py` aplicado en los tres agentes; tests con negaciones |
| Tolerancia a fallos por paso | Hecho (opcionales) | Portada, vídeo, entregas, subidas y guardado no rompen el briefing; un paso núcleo lanza `PipelineStepError` con su nombre. Caída a mock de un paso núcleo: **pendiente** (D1) |
| Métricas por paso | Hecho (mock) | Un `StepMetric` por paso, `storage.save` incluido en `Briefing.metrics` (bug corregido), `error` en el paso fallido. Latencias y costes reales: NO MEDIDO |
| Podcast, transcripción, gráficos (carril C) | Hecho con `MockTTS` | TTS por línea en paralelo con reintentos, concatenación con ffmpeg/stdlib, SRT, gráficos matplotlib 1920×1080; `tests/test_media_mock.py` |
| Persistencia | Hecho | `storage.py` con rutas relativas portables; `tests/test_storage.py` (round-trip y carpeta movida) |
| Textos de email y Telegram | Hecho (funciones puras) | `build_email_html`, `build_caption`; el envío es *stub* |
| UI | Hecho en modo demo | «Generar briefing» pinta titular, audio, transcripción, gráficos y métricas; Mi cartera carga el CSV; Histórico reabre briefings |
| e2e mock | Hecho | `tests/test_pipeline_mock.py` sin `skip` (verificado en integración Fase 0) |
| Instalación | Hecho | `pip install -r requirements.txt` + `pip install -e .` en un venv nuevo con Python 3.13 |
| Docker y scripts de arranque | Creados | NO VERIFICADOS en clon limpio (D2 Sync 4 y D3) |

## Qué no funciona todavía

Todo lo que necesita red o claves. Con `BRIEFER_FALLBACK_TO_MOCK=true` (por defecto) la falta de clave cae a
mock **en silencio** (solo log); las insignias de la UI que lo delatan son tarea de D1.

| Elemento | Fichero / función | Fase |
| --- | --- | --- |
| Noticias reales | `ingest/news.py`: `fetch_news`, `fetch_rss_news`, `fetch_yfinance_news` | D1 |
| Precios reales y caché | `ingest/prices.py`: `get_price_snapshots`, `get_price_snapshot` | D1 |
| LLM real | `providers/llm/anthropic_llm.py`: `AnthropicLLM.complete` | D1 |
| TTS real | `providers/tts/edge_tts_provider.py`: `EdgeTTS.synthesize` | D1 |
| Visión real | `providers/vision/claude_vision.py`: `ClaudeVision.describe`, `detect_media_type` | D1 |
| STT real | `providers/stt/whisper_api.py`: `WhisperAPI.transcribe` | D2 |
| Vídeo | `media/video.make_video` | D2 |
| Portada | `media/cover.py`, proveedor texto→imagen | D2 (Should) |
| Envíos | `send_briefing_telegram` (Should), `send_briefing_email` (Could) | D2 |
| Fallback núcleo → mock marcado, insignias, modos Ejemplo / Sin claves / Real | `pipeline.py`, `app/components/players.py` | D1 |
| Briefing pregenerado | `data/samples/demo_briefing/` | D1 (v1), D3 (final) |
| Orquestación visible: router CLIP, puertas de calidad, WER, traza | ver [05 · D2](05_roadmap_TODO.md#d2--miércoles-7-oct--multimodalidad-orquestación-visible-y-vídeo) | D2 |
| CI, prueba de humo real | `.github/workflows/`, `scripts/smoke_real.py` | D1, primera hora |
| Proveedores alternativos (Gemini, OpenAI, Qwen, SDXL, ElevenLabs, Whisper local, CLIP) | *stubs* | Could / Won't; se retiran del registry en D3 si no se implementan |
| Capturas, demo grabada, pitch, costes y latencias medidos | — | D3 (hoy al 0 %) |

## Riesgos principales

Detalle y costes en [07 §2](07_revision_critica.md#2-hallazgos-críticos-ordenados-por-impacto-en-nota--riesgo-de-entrega).

| Riesgo | Impacto | Mitigación prevista |
| --- | --- | --- |
| Orquestación lineal: el evaluador ve «un LLM con pasos» | Nota de 4.2 | Router CLIP, puertas de calidad con reintento, WER, paralelismo y pestaña «Cómo se hizo» (D2) |
| Demo sin claves pobre (noticias ficticias, podcast de silencio) y sin briefing real de respaldo | Primeros 30 s del evaluador | Pregenerado real en la portada, modo «Sin claves» con edge-tts real, insignias (D1) |
| Claves / IDs de modelo sin verificar (`claude-sonnet-5-5` en `.env.example` y `costs.py`) | 404 en la primera llamada real | Prueba de humo a primera hora de D1, clave con límite de gasto |
| yfinance pobre en `.MC` y con *rate limit* | Briefing vacío o en inglés | Google News RSS en español por empresa + caché diaria; sin precio → se omite (nunca sintético en real) |
| edge-tts no oficial, *throttling*, sin uso comercial | Sin audio | Versión fijada, ≤ 4 hilos, reintentos (ya en `synthesize_podcast`), pregenerado; Azure Speech en producción (docs/04) |
| TTS lee mal tickers y cifras | Se oye en la demo | `normalize_for_speech` + instrucción en el prompt del Guionista (D1) |
| Vídeo lento/frágil con moviepy 1080×1920 | Demo sin vídeo | ffmpeg directo, 720×1280, fps bajo, opcional (D2) |
| Modalidades prometidas > demostradas | Credibilidad | Tabla del README con columna «Activo en la demo» (D3) |
| Capturas, demo y pitch al 0 % | Entregable | Code freeze jue 11:00; D3 dedicado |
| Carril C sobrecargado | Retrasos | Rebalanceo de [05](05_roadmap_TODO.md#carriles-rebalanceados): Telegram a A, calidad y métricas a B |

## Próximos pasos (D1, en orden)

1. **09:00** · Prueba de humo real (Anthropic texto + visión, Whisper, edge-tts), IDs de modelo verificados,
   clave de grupo con límite de gasto; CI con `pytest -q`.
2. **09:00-13:00** · A: noticias RSS en español + precios con caché. B: `AnthropicLLM.complete`, Analista real,
   Guionista en Haiku. C: `EdgeTTS.synthesize` + `normalize_for_speech`.
3. **13:00 Sync 1** · `demo.py --tickers SAN.MC AAPL` real con audio real. Desde aquí, contratos solo aditivos.
4. **13:00-18:00** · A: `ClaudeVision` + `read_chart` real. B: fallback núcleo → mock marcado, insignias,
   paralelismo, métricas verificadas. C: modos Ejemplo / Sin claves / Real, `MockLLM` realista, portada de la app.
5. **18:00 Sync 2** · briefing real e2e desde la UI y **pregenerado v1** en `data/samples/demo_briefing/`.
6. **18:00-22:00** · A: `read_pdf` real. B: prompts con 3 carteras. C: transcripción con locutores, métricas
   visuales.
7. **22:00 go/no-go** · si el e2e real no funciona, el miércoles se cancelan las Should salvo fallbacks y
   pregenerado.

## Registro de jornadas

| Fecha | Resumen |
| --- | --- |
| 05-oct-2026 (tarde) | Idea cerrada, stack decidido, contratos v0.1. Esqueleto de código: schemas, mocks, registry, config, costs, logging, pipeline, UI esbozada, scripts y Docker. `pytest`: 38 passed / 2 skipped. |
| 05-oct-2026 (noche) | Revisión crítica ([07](07_revision_critica.md)) y plan revisado. Fase 0 por tres carriles: ingesta mock, agentes con guardarraíles, tolerancia a fallos, media, storage portable, UI en modo demo, datos de ejemplo extra. Contratos v0.2 ([ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md)). e2e mock sin `skip`. Instalación limpia verificada (Python 3.13). |
