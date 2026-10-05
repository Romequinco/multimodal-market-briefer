# 06 · Estado actual

> Responde a «¿en qué estado está el proyecto hoy?». Se actualiza al final de cada jornada. Solo se marca
> como hecho lo que alguien del equipo ha ejecutado y visto funcionar; lo no comprobado se marca **NO
> VERIFICADO**. Las cifras de coste y latencia que no salgan de un `StepMetric` real se marcan **NO MEDIDO**.

**Fecha:** lun 5-oct-2026, cierre de la **revisión de las Fases 0 y 1** · **Fase:** F0 y D1 cerradas; parte de D2
adelantada · **Siguiente:** resto de D2 (mar 6 - mié 7) + [caminos 1, 2 y 6](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2) ·
**Entrega:** jue 8-oct-2026, 18:00 (objetivo interno 16:30) · **Contratos:** v0.3.1 ([03](03_contratos_modulos.md)) ·
**Plan:** [05](05_roadmap_TODO.md)

## Resumen

El **núcleo real funciona de punta a punta** y la revisión (4 agentes + auditoría independiente + tanda de
arreglos) lo ha reforzado: noticias reales (Google News, **Bing News**, Yahoo, Expansión, Europa Press) con URL del
medio y extracto breve → filtro por tickers con relevancia → PDF y gráfico con Claude visión → Analista (Sonnet
5.5) con *grounding* → Guionista (Haiku 4.5) con **puertas deterministas** → podcast a dos voces con edge-tts y
`loudnorm` → SRT → gráficos → `briefing.json` **sin cartera**. El **Q&A por voz ya es real** (Whisper API) y cumple
< 10 s también en frío. Medido: **0,066 €** y **82,9 s** por briefing con PDF + gráfico (sin caché); Q&A ≈ 0,005 €,
**5,2 s** con voz en la 1.ª pregunta (con `warmup`) y 4,4 s en caliente; STT 1,3 s con WER 0. Faltan: vídeo,
portada texto→imagen, CLIP, envíos, captura de cartera y **probar Docker**.

## Qué funciona

| Elemento | Estado | Evidencia |
| --- | --- | --- |
| Contratos v0.3.1 | Hecho | `schemas.CONTRACTS_VERSION = "0.3"` (schemas sin cambios); funciones y semántica nuevas en [03](03_contratos_modulos.md#registro-de-cambios-de-contrato); [ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md), [ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md) |
| Noticias reales | Hecho, verificado en real | `ingest/news.py`: Google News y **Bing News** RSS es-ES por empresa + RSS de Yahoo + Expansión + Europa Press, en paralelo; dedupe con casi duplicados (≥ 0,75), fichas de cotización descartadas, `relevance_score`. Pregenerado: 30 fuentes (0 fallidas), 20 seleccionadas, 16 relevantes. **yfinance news** se desactiva sola si no devuelve nada |
| Extractos y URL del medio | Hecho, medido | `ingest/article_meta.py`: enlaces de Google News resueltos al medio, `og:description` solo del `<head>`, `robots.txt`, caché de 7 días, presupuesto de 3 s en hilos daemon. Extracto en ~45-50 % de las noticias en frío y ~80 % desde la 2.ª ejecución del día; ≤ 200 caracteres en origen |
| Precios reales | Hecho, verificado en real | `ingest/prices.py`: descarga en lote, divisa con *timeout*, aviso de cierres antiguos; `PriceFetchError` si no hay ninguno |
| Caché | Hecho, medido | `ingest/cache.py` (`data/cache/`): diaria para noticias y precios; 7 días para URL, extractos y `robots.txt`; purga automática a 7 días |
| LLM Anthropic | Hecho, verificado en real | `AnthropicLLM` con salida estructurada ([ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md)), **cliente compartido** por proceso y `warmup()`; costes con caché de prompts (0,1× / 1,25×) |
| Visión | Hecho, verificado en real | `ClaudeVision`: PDF (páginas pobres en texto; render opcional con `pypdfium2`, que **no** está en requirements) y gráfico (también MPO de móvil). PDF máximo 50 MB. Contenido delimitado como dato |
| STT | Hecho, verificado en real | `WhisperAPI` con `gpt-4o-mini-transcribe` por defecto: WER 0 en 3 preguntas, 1,3 s, la mitad de coste que `whisper-1`; silencio cortado en local; `MockSTT` con prefijo `[MOCK]` |
| LLM alternativo Gemini | Hecho (humo) | `GeminiLLM`: `smoke_real.py` OK. Briefing completo con Gemini: NO VERIFICADO |
| Agentes | Hecho, verificado en real | Analista con *grounding* y aviso de fuentes con forma de instrucción; Guionista con *grounding* contra el análisis, cobertura de puntos clave (6 de 6 en el pregenerado), duración 3-5 min, gramática y palabras raras; Q&A con citas, guardarraíles MiFID y notas en la traza. Haiku frente a Sonnet decidido en [ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md) |
| Red-team | Hecho | `tests/test_agents_redteam.py` (31 tests sin red) + pruebas reales: inyección en noticias y PDF, consejo personalizado, fuera de ámbito, ticker inexistente, contexto vacío |
| Q&A rápido | Hecho, medido | `pipeline.warmup` (en un hilo al abrir «Preguntar») + `answer_question(speak=False)` + `speak_answer`: 1.ª pregunta 3,0 s texto / 5,2 s con voz (antes 16-17 s en la UI); caliente 1,8 / 4,4 s |
| TTS real | Hecho, verificado en real | `EdgeTTS` sin reintentos anidados, fallo rápido del episodio, `normalize_for_speech` ampliado, `loudnorm` −16 LUFS (medido −16,8 LUFS, pico −1,6 dBTP), ID3 «voces sintéticas IA» |
| Gráficos | Hecho | *Thread-safe* (`Figure` sin pyplot); índices en el bloque «Índices de referencia»; fecha y fuente en el título; «precios sintéticos (demo)» en mock o sustituto |
| Fallback núcleo → sustituto marcado | Hecho (tests) | `tests/test_pipeline_fallback.py`; pool de subidas cancelado si cae el núcleo; `PipelineStepError.metrics` con lo ya gastado. Fallo real provocado en vivo: NO VERIFICADO |
| Persistencia y privacidad | Hecho, con tests | La cartera **no se persiste** (`portfolio: null`, sin gráfico de cartera en disco; [ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md)); subidas en carpeta temporal única borrada; audio de la pregunta borrado; `briefing.json` con BOM o campos desconocidos se carga; ZIP portable (`export_briefing_zip`) |
| Secretos | Hecho, con tests | `logging_utils.redact_secrets` / `error_text` en métricas, errores, log y UI; *traceback* solo con `BRIEFER_LOG_LEVEL=DEBUG` |
| Portada y UI | Hecho | Propuesta de valor, reproductor arriba, «Preguntar sobre este briefing», «Generar el tuyo», franja «Cómo se hizo»; doble clic protegido; vídeo, portada IA y envíos **desactivados** («en desarrollo»); la portada nunca destaca un briefing simulado por encima del pregenerado real; `.streamlit/config.toml` (tema, 50 MB, sin telemetría) |
| Briefing pregenerado | Hecho | `data/samples/demo_briefing/` (`20261005-130504-0f8ae2`): 6 puntos clave cubiertos, 0,066 €, 82,9 s, 5:27 de audio, 3,3 MB, `portfolio: null`, extractos ≤ 198 caracteres |
| CLI | Hecho | `scripts/demo.py` (`--mock`, `--demo-voices`, `--refresh`, `--question`, `--briefing`, `--warmup`, `--strict`; salida 0/1/2/3/130), `scripts/smoke_real.py` (con `warmup` y STT con WER) |
| Arranque | Hecho en Windows | `scripts/run.ps1` / `run.sh`: Python ≥ 3.11 (también `py`), abortan si `pip` falla, reinstalan solo si cambian los requirements, `localhost` por defecto (`-Expose` / `--expose`). `run.ps1` probado; `run.sh` NO VERIFICADO |
| Dependencias | Hecho | Sin `moviepy` ni `plotly`; `Pillow>=12.3`, `anthropic>=1.11`; `pip-audit` sin vulnerabilidades |
| Tests y CI | Hecho | **617 tests sin red** + 9 `live` (`-m live`); CI en verde (matriz Python 3.11 y 3.13) |

## Mediciones (05-oct-2026)

Detalle y método en [04](04_viabilidad_costes_latencia_compliance.md#método-de-medición).

| Qué | Medido |
| --- | --- |
| Briefing con PDF + gráfico (pregenerado final, sin caché) | **0,0662 €** · **82,9 s** de pared (134,4 s de suma de pasos) |
| Briefing con PDF + gráfico (Fase 1, 3 ejecuciones) | ≈ 0,065 € · 61,1-63,6 s de pared |
| Desglose de coste (final) | Analista 0,0261 € · gráfico 0,0157 € · PDF 0,0145 € · Guionista 0,0100 € · resto 0 € |
| Desglose de latencia (final) | visión PDF/gráfico ~32 s (en paralelo con la ingesta) → Analista 11,0 s → Guionista 17,9 s → TTS 20,4 s |
| Podcast | Final: 5:27, 28 intervenciones (−16,8 LUFS). Fase 1: 3:58-4:20 min |
| Q&A (texto · texto + voz) | 1.ª con `warmup` **3,0 · 5,2 s** · caliente **1,8 · 4,4 s** · sin `warmup` 9,4 · 12,9 s · ≈ 0,005 € |
| STT | `gpt-4o-mini-transcribe` 1,28 s, WER 0 · `whisper-1` 2,55 s, WER 0 |
| Demo sin claves con voces reales | 6,2 s, 0 € |
| Gasto real de la sesión de revisión | ≈ 0,31 € (estimado con `costs.py`) |

## Qué no funciona todavía

| Elemento | Fichero / función | Fase |
| --- | --- | --- |
| Vídeo | `media/video.make_video` (*stub*; control desactivado en la UI) | D2 |
| Portada texto→imagen | `media/cover.py` (*stub*; Gemini image disponible con la clave actual) | D2 (Should) |
| Router CLIP, captura de cartera | `providers/image/clip_classifier.py`, `portfolio_from_image` (nueva) | D2 (Should) |
| Envíos | `send_briefing_telegram` (Should), `send_briefing_email` (Could); controles desactivados | D2 |
| Docker | `Dockerfile`, `docker-compose.yml` endurecidos pero **NO VERIFICADOS** (sin daemon) | D2 Sync 4 / D3 |
| `run.sh` y clon limpio en Linux/macOS | `scripts/run.sh` | D3 |
| p50/p95 y contraste con la factura | `docs/04`, camino 1 | D2-D3 |
| Proveedores sin implementar | `OpenAILLM` (*stub* documentado), Qwen-VL, Whisper local, ElevenLabs, SDXL | Won't; limpieza D3 |
| Capturas, demo grabada, pitch | — | D3 |

## Riesgos abiertos

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| **Docker sin probar** | `docker compose up` puede fallar el día de la entrega | Probarlo en una máquina con daemon antes del mié 18:00; si falla a las 15:45 del jueves, `run.ps1` / `run.sh` son el camino principal |
| **Duración del pregenerado** (5:27 frente a 4 min de objetivo; la estimación por palabras daba ~4,5 min) | Demo larga; la puerta de duración no lo frena | Ajustar `WORDS_PER_MINUTE` o el prompt y regenerar el pregenerado final en D3 |
| **Regionalismos** en el guion («precificado», «allá») | Calidad percibida del podcast | Ninguna puerta los detecta; lista en `GRAMMAR_FIXES` o prompt; escucha antes de fijar el pregenerado |
| **Causalidad sin fuente en el Q&A** («sube por…») | Afirmaciones no respaldadas (MiFID, *hallucination*) | `unhedged_causal_claims` solo anota en la traza; falta reescribir o pedir reintento |
| Contexto del Q&A en el *system prompt* | Más autoridad para texto de terceros (*prompt injection*) | Aviso de fuentes sospechosas; moverlo a un mensaje `user` delimitado (auditoría S9) |
| **Mecanismos no oficiales**: resolución de enlaces de Google News (`batchexecute`), RSS de Bing News, edge-tts, yfinance | Sin SLA: pueden dejar de funcionar sin aviso | Nunca lanzan; si fallan, enlace original, menos noticias o sustituto marcado; caché; noticias licenciadas y TTS oficial en producción |
| **Globales de estadísticas** (`news.last_fetch_stats`, `last_quality_stats`) | Con dos briefings simultáneos se pisan | El pipeline usa `stats_out` por llamada; los globales solo para depurar |
| Variabilidad de la API de visión (31 s en el pregenerado, 63 s en una ejecución de la F1) | Demo en vivo lenta | Subidas en paralelo, barra de progreso, pregenerado; en la demo grabada usar caché |
| Modalidades prometidas > demostradas (vídeo, portada, CLIP, envíos) | Nota de 4.2 | Controles desactivados y columna «Activo en la demo» honesta en el README; recortes en [05](05_roadmap_TODO.md#recortes-si-no-da-tiempo) |
| Capturas, demo y pitch al 0 % | Entregable | Code freeze jue 11:00; D3 dedicado |

## Próximos pasos (D2, en orden)

1. **Martes mañana** · probar Docker en una máquina con daemon; repartir los caminos **1** (evaluación con
   p50/p95), **2** (comparativa de modelos) y **6** (cuaderno de recorrido).
2. **mar 13:00 Sync 1** · go/no-go de las Should (vídeo, portada, CLIP, Telegram, captura de cartera).
3. **Hasta mié 18:00** · vídeo con ffmpeg, portada (Gemini image), Telegram; `docs/04` con costes fijos;
   duración del guion.
4. **mié 22:00** · *feature freeze*.

## Registro de jornadas

| Fecha | Resumen |
| --- | --- |
| 05-oct-2026 (tarde) | Idea cerrada, stack decidido, contratos v0.1. Esqueleto de código: schemas, mocks, registry, config, costs, logging, pipeline, UI esbozada, scripts y Docker. `pytest`: 38 passed / 2 skipped. |
| 05-oct-2026 (noche) | Revisión crítica ([07](07_revision_critica.md)) y plan revisado. Fase 0 por tres carriles: ingesta mock, agentes con guardarraíles, tolerancia a fallos, media, storage portable, UI en modo demo, datos de ejemplo extra. Contratos v0.2 ([ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md)). e2e mock sin `skip`. Instalación limpia verificada (Python 3.13). |
| 05-oct-2026 (cierre F1) | Camino real integrado (D1 adelantado): noticias RSS + Yahoo con caché, precios en lote, Claude texto/visión con salida estructurada ([ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md)), Gemini alternativo, edge-tts real con normalización y metadatos ID3, fallback núcleo marcado, *grounding*, modos real/demo/mock, índices de contexto, subidas en paralelo, pregenerado real en la portada, pestaña «Cómo se hizo», `smoke_real.py`, CI. Contratos v0.3. 419 tests sin red + 7 `live`. Medido: ≈ 0,065 € y ≈ 62 s por briefing con PDF + gráfico; Q&A ≈ 0,005 €, 6-13 s. |
| 05-oct-2026 (revisión F0-F1) | Revisión completa con auditoría independiente y arreglos: Bing News y `article_meta` (URL final, `og:description`, `robots.txt`), extractos ≤ 200, 13 bugs de ingesta; Whisper API; `warmup` y Q&A en dos tiempos (5,2 s con voz en frío); Guionista con puertas deterministas ([ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md)); red-team; `loudnorm`; gráficos *thread-safe* con «Índices de referencia»; cartera no persistida ([ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md)); redacción de secretos; UI con controles pendientes desactivados; scripts de arranque, Docker y CI endurecidos; `moviepy`/`plotly` fuera. Pregenerado nuevo `20261005-130504-0f8ae2`. Contratos v0.3.1. 617 tests sin red + 9 `live`. Medido: 0,066 € y 82,9 s por briefing; Q&A 5,2 s con voz. |
