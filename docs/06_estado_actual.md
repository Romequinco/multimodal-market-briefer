# 06 · Estado actual

> Responde a «¿en qué estado está el proyecto hoy?». Se actualiza al final de cada jornada. Solo se marca
> como hecho lo que alguien del equipo ha ejecutado y visto funcionar; lo no comprobado se marca **NO
> VERIFICADO**. Las cifras de coste y latencia que no salgan de un `StepMetric` real se marcan **NO MEDIDO**.

**Fecha:** lun 5-oct-2026, cierre de la Fase 1 (camino real) · **Fase:** F0 y D1 cerradas (D1 adelantado) ·
**Siguiente:** D2 (mar 6 - mié 7) + [caminos de revisión](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2) ·
**Entrega:** jue 8-oct-2026, 18:00 (objetivo interno 16:30) · **Contratos:** v0.3 ([03](03_contratos_modulos.md)) ·
**Plan:** [05](05_roadmap_TODO.md)

## Resumen

El **núcleo real funciona de punta a punta**: noticias reales en español e inglés → filtro por tickers →
lectura de PDF y gráfico con Claude visión → Agente Analista (Sonnet 5.5) con puerta de *grounding* →
Agente Guionista (Haiku 4.5) → podcast a dos voces con edge-tts → SRT → gráficos → `briefing.json`, y el Q&A
responde por texto con voz. Medido el 05-oct: **≈ 0,065 € y ≈ 61-64 s** por briefing con PDF + gráfico;
Q&A **≈ 0,005 €** y **6-7 s** en caliente (11-13 s en frío). La app abre con un **briefing real pregenerado**,
tiene tres modos (real · demo sin claves con voces reales · mock offline) y la pestaña «Cómo se hizo». Faltan:
**STT (Whisper)**, la latencia del Q&A en frío, vídeo, portada, envíos y las piezas de multimodalidad extra
(CLIP, captura de cartera).

## Qué funciona

| Elemento | Estado | Evidencia |
| --- | --- | --- |
| Contratos v0.3 | Hecho | `schemas.CONTRACTS_VERSION = "0.3"` (`StepMetric.detail`, semántica «Fallback a …»), [03](03_contratos_modulos.md), [ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md) |
| Noticias reales | Hecho, verificado en real | `ingest/news.py`: Google News RSS es-ES por empresa + RSS de titulares de Yahoo + Expansión «Mercados» + Europa Press, en paralelo, dedupe, ventana 48 h → 7 días. Briefing real: 20 obtenidas, 16 relevantes. **yfinance news da 404 hoy** (se desactiva sola; queda el RSS de Yahoo) |
| Precios reales | Hecho, verificado en real | `ingest/prices.py`: una descarga en lote (`yf.download`), divisa de yfinance, ticker sin datos se omite; `PriceFetchError` si no hay ninguno |
| Caché diaria | Hecho, medido | `ingest/cache.py` (`data/cache/`): ingesta de ~6 s → ~0,3 s en la 2.ª ejecución del día; `use_cache=False` / «Refrescar datos» / `demo.py --refresh` |
| Índices de contexto | Hecho | `^IBEX` y `^GSPC` (`BRIEFER_CONTEXT_TICKERS`): precios y noticias de mercado, fuera de los tickers del usuario |
| LLM Anthropic | Hecho, verificado en real | `AnthropicLLM`: salida estructurada con `output_config` JSON Schema + 1 reintento autocorrectivo; `key_figures` como pares `{label, value}` ([ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md)). Sonnet 5.5 (analista, visión) y Haiku 4.5 (guionista, Q&A, estructurado de documentos) |
| Visión | Hecho, verificado en real | `ClaudeVision`: PDF (páginas pobres en texto) y captura de gráfico → `DocumentInsight` con 10 y 14 cifras en el pregenerado |
| LLM alternativo Gemini | Hecho (humo) | `GeminiLLM`: `smoke_real.py` `gemini.structured` OK. Briefing completo con Gemini: NO VERIFICADO |
| Agentes | Hecho, verificado en real | Analista con *grounding* de cifras (`guardrails.untraceable_figures`, resultado en `StepMetric.detail`); Guionista con reparación determinista (homoglifos, tramos del mismo locutor) y respaldo; Q&A con citas y guardarraíles MiFID |
| TTS real | Hecho, verificado en real | `EdgeTTS` (`edge-tts==7.2.8`, reintentos propios), 6 hilos, `normalize_for_speech` (cifras, tickers, periodos, siglas), metadatos ID3 de voz sintética |
| Fallback núcleo → sustituto marcado | Hecho (tests) | noticias → `data/samples`, precios → sintéticos, agentes → mock, guion → respaldo, TTS → mock; `StepMetric.error = "Fallback a …"`, aviso en la UI y nodo naranja en la traza. `tests/test_pipeline_fallback.py`. Fallo real provocado en vivo: NO VERIFICADO |
| Paralelismo | Hecho, medido | Noticias ∥ precios ∥ subidas: pared 61-64 s frente a 82-100 s de suma de pasos |
| Modos de ejecución | Hecho | `run_briefing(mode="real"\|"mock"\|"demo_voices")`; barra lateral con interruptor «Modo real» (bloqueado si faltan claves) y tipo de demo; insignias por proveedor |
| Briefing pregenerado | Hecho | `data/samples/demo_briefing/` (briefing real `20261005-110721-a127a9`, 2,7 MB, rutas relativas, extractos ≤ 200 caracteres), exportado con `storage.export_briefing`; portada de la app con `load_featured_briefing` |
| Pestaña «Cómo se hizo» | Hecho | `app/components/trace.py`: grafo DOT con modelo, latencia, coste, *detail* y estado de cada paso; `tests/test_app_trace.py` |
| CLI | Hecho | `scripts/demo.py` (`--mock`, `--demo-voices`, `--refresh`, `--question`…), `scripts/smoke_real.py` (OK/FAIL/SKIP/PEND por proveedor, ≈ 0,005 €) |
| Tests y CI | Hecho | **419 tests sin red** en verde + 7 `live` (`-m live`); `.github/workflows/tests.yml` en mock. Primera ejecución en GitHub: NO VERIFICADA desde aquí |
| Lo de la Fase 0 | Hecho | Camino mock, persistencia portable, UI multipágina, textos de email/Telegram, instalación limpia (ver registro) |

## Mediciones (05-oct-2026)

Detalle y método en [04](04_viabilidad_costes_latencia_compliance.md#método-de-medición): 3 briefings reales con
5 tickers + PDF + gráfico (1 sin caché, 2 con caché) y 4 preguntas.

| Qué | Medido |
| --- | --- |
| Briefing con PDF + gráfico | **≈ 0,065 €** (0,0640-0,0660) · **61,1-63,6 s** de pared |
| Desglose de coste | Analista 0,0248 € · gráfico 0,0170 € · PDF 0,0152 € · Guionista 0,0081 € · resto 0 € |
| Desglose de latencia | visión PDF/gráfico 20-25 s (en paralelo con la ingesta) → Analista ~11 s → Guionista ~13-15 s → TTS ~12-13 s |
| Podcast | 3:58-4:20 min, 18-20 intervenciones |
| Q&A texto → respuesta hablada | **≈ 0,005 €** · **6,0-7,0 s** en caliente · **11,0-13,2 s** en frío (1.ª pregunta del proceso) |
| Demo sin claves con voces reales | 6,2 s, 0 € |
| Gasto real de la sesión de integración | ≈ 0,35 € (estimado con `costs.py`) |

## Qué no funciona todavía

| Elemento | Fichero / función | Fase |
| --- | --- | --- |
| STT (pregunta por voz, notas de voz reales) | `providers/stt/whisper_api.py`: `WhisperAPI.transcribe` (*stub*; `smoke_real.py` lo marca PEND) | D2 |
| Q&A con audio < 10 s en frío | `pipeline.answer_question` (precalentar clientes, respuesta más corta) | D2 |
| Rótulo de los índices en el gráfico de variación | `media/charts.make_overview_chart` (pinta `^IBEX`/`^GSPC` como si fueran valores) | D2 |
| Calidad estable del Guionista (Haiku) | `prompts/scriptwriter.md`, `scriptwriter.write_script` (fallos ocasionales → reintento o respaldo) | D2 + camino 2 |
| Vídeo | `media/video.make_video` (*stub*) | D2 |
| Portada texto→imagen | `media/cover.py` (*stub*); Gemini image disponible con la clave actual | D2 (Should) |
| Router CLIP, captura de cartera | `providers/image/clip_classifier.py`, `portfolio_from_image` (nueva) | D2 (Should) |
| Envíos | `send_briefing_telegram` (Should), `send_briefing_email` (Could) | D2 |
| RGPD en la UI | consentimiento de cartera, borrado del audio de la pregunta | D2 |
| Proveedores sin implementar | `OpenAILLM` (*stub* documentado, recorte), Qwen-VL, Whisper local, ElevenLabs, SDXL | Won't; limpieza D3 |
| Docker y scripts en clon limpio | `Dockerfile`, `scripts/run.*` | D2 Sync 4 / D3 |
| Capturas, demo grabada, pitch | — | D3 |

## Riesgos principales

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| Q&A por voz sin STT real y > 10 s en frío | Criterio de latencia y modalidad audio → texto en la demo | Whisper API primero en D2; precalentar; si no llega, Q&A por texto con respuesta hablada (ya medido) |
| Fuentes sin SLA: yfinance (news ya da 404), Google News RSS, edge-tts | Briefing con menos noticias o sin audio | Varias fuentes en paralelo, caché diaria, fallback marcado a `data/samples` / `MockTTS`, pregenerado en la portada; Azure Speech y noticias licenciadas en producción (04) |
| Guionista en Haiku irregular | Podcast con formato raro o guion de respaldo en la demo | Reintento + reparación determinista + respaldo; camino 2 decide si pasa a Sonnet (+~0,02 €) |
| Extractos de noticias de hasta 600 caracteres en la ingesta | Derechos de autor | Pregenerado recortado a ≤ 200; acotar lo que se muestra/exporta (D2) |
| Variabilidad de la API de visión (un PDF tardó 63 s en una ejecución) | Demo en vivo lenta | Subidas en paralelo, barra de progreso, pregenerado; en la demo grabada usar caché |
| Modalidades prometidas > demostradas (vídeo, portada, CLIP, envíos) | Nota de 4.2 | Columna «Activo en la demo» honesta en el README; recortes ordenados en [05](05_roadmap_TODO.md#recortes-si-no-da-tiempo) |
| Capturas, demo y pitch al 0 % | Entregable | Code freeze jue 11:00; D3 dedicado |

## Próximos pasos (D2, en orden)

1. **Martes mañana** · Whisper API (`WhisperAPI.transcribe`) y Q&A por voz medido; precalentar clientes para
   bajar el Q&A en frío de 10 s; rótulo de índices en el gráfico; calidad del Guionista.
2. **En paralelo** · repartir los [caminos de revisión](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2)
   (el 1, evaluación de briefings, es el recomendado).
3. **mar 13:00 Sync 1** · go/no-go de las Should.
4. **Hasta mié 18:00** · vídeo con ffmpeg, portada (Gemini image), Telegram, RGPD en la UI, `docs/04` reforzado,
   Docker probado.
5. **mié 22:00** · *feature freeze*.

## Registro de jornadas

| Fecha | Resumen |
| --- | --- |
| 05-oct-2026 (tarde) | Idea cerrada, stack decidido, contratos v0.1. Esqueleto de código: schemas, mocks, registry, config, costs, logging, pipeline, UI esbozada, scripts y Docker. `pytest`: 38 passed / 2 skipped. |
| 05-oct-2026 (noche) | Revisión crítica ([07](07_revision_critica.md)) y plan revisado. Fase 0 por tres carriles: ingesta mock, agentes con guardarraíles, tolerancia a fallos, media, storage portable, UI en modo demo, datos de ejemplo extra. Contratos v0.2 ([ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md)). e2e mock sin `skip`. Instalación limpia verificada (Python 3.13). |
| 05-oct-2026 (cierre F1) | Camino real integrado (D1 adelantado): noticias RSS + Yahoo con caché, precios en lote, Claude texto/visión con salida estructurada ([ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md)), Gemini alternativo, edge-tts real con normalización y metadatos ID3, fallback núcleo marcado, *grounding*, modos real/demo/mock, índices de contexto, subidas en paralelo, pregenerado real en la portada, pestaña «Cómo se hizo», `smoke_real.py`, CI. Contratos v0.3. 419 tests sin red + 7 `live`. Medido: ≈ 0,065 € y ≈ 62 s por briefing con PDF + gráfico; Q&A ≈ 0,005 €, 6-13 s. |
