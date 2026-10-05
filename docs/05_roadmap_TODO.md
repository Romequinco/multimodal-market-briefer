# 05 · Roadmap y TODO hasta la entrega

**Entrega: jueves 8-oct-2026, 18:00** (aula virtual; objetivo interno 16:30). Plan revisado tras la
[revisión crítica](07_revision_critica.md) del 05-oct. Tareas por fase y por carril, **sin asignar personas**:
cada uno marca la que coge escribiendo su nombre al lado. Contratos y firmas reales en
[03](03_contratos_modulos.md) (v0.2).

Formato: `- [ ] Tarea — ficheros / funciones — **Hecho cuando:** criterio verificable`. Solo se marca `[x]` lo
que se ha ejecutado y visto funcionar. Etiqueta de prioridad entre corchetes: **[M]** Must · **[S]** Should ·
**[C]** Could (ver [MoSCoW](#moscow)). Una tarea marcada «(nueva)» crea una función o fichero que aún no existe:
su nombre es una propuesta y se documenta en [03](03_contratos_modulos.md) al crearla.

## Resumen de fases

| Fase | Fecha | Objetivo | Hito de salida | Go/no-go |
| --- | --- | --- | --- | --- |
| F0 | lun 5-oct | Esqueleto + camino mock fin a fin | `pytest` sin `skip` en verde; la UI genera un briefing mock completo | **Superado** (ver abajo) |
| D1 | mar 6-oct | Núcleo real + demo que no puede fallar | Briefing real (noticias → análisis → guion → podcast 2 voces → SRT → gráficos) en la UI y por CLI con `StepMetric` reales; pregenerado v1 versionado; modo «Sin claves» suena | 22:00: si el e2e real no funciona, el miércoles se cancelan todas las Should salvo fallbacks y pregenerado |
| D2 | mié 7-oct | Multimodalidad, orquestación visible, vídeo | Todas las Must funcionando; Should según go/no-go; Docker y `run.ps1` probados una vez | 13:00: si Q&A por voz o visión no están, se recorta según [el orden de recortes](#recortes-si-no-da-tiempo) |
| D3 | jue 8-oct | Entregable | README con capturas, demo grabada, pitch PDF, clon limpio probado; entrega 16:30 | 15:45: si Docker falla en clon limpio, `run.ps1`/`run.sh` pasan a camino principal |

## Reglas de trabajo

- **Puntos de sincronización** (15 min los tres, con `main` integrado y `pytest` verde): **Sync 1** mar 13:00 ·
  **Sync 2** mar 18:00 · **Sync 3** mié 13:00 · **Sync 4** mié 18:00 · repaso final jue 11:00.
- **Ramas cortas** por carril (`a/...`, `b/...`, `c/...`) con PR a `main` en cada sync; nada de ramas que
  vivan más de medio día. `main` siempre con `pytest -q` verde (CI cuando exista).
- **Contratos:** desde la Sync 1 (mar 13:00) solo cambios **aditivos** en `schemas.py` y `providers/base.py`;
  un único dueño del merge (carril B). Cada cambio, en el registro de [03](03_contratos_modulos.md).
- **Congelaciones:** *feature freeze* **mié 7-oct 22:00** (después, solo arreglos, documentación y demo) ·
  *code freeze* **jue 8-oct 11:00**.
- `docs/06` se actualiza al cierre de cada jornada; `docs/03` está congelado salvo registro de cambios.

## Carriles (rebalanceados)

| Carril | Ámbito |
| --- | --- |
| **A** · Entradas, visión y Telegram | `ingest/*`, `providers/vision/*`, `providers/stt/*`, router CLIP (`providers/image/clip_classifier.py`, `chart_reader.classify_image`), captura de cartera, `delivery/telegram_sender.py`; D3: limpieza de *stubs* y clon limpio |
| **B** · Agentes, orquestación, calidad y viabilidad | `agents/*`, `pipeline.py`, `costs.py`, `providers/llm/*`, fallbacks, puertas de calidad, métricas, CI, `docs/04` medido, dueño de `schemas.py`; D3: mediciones y pitch |
| **C** · Media, UI y demo | `media/*`, `providers/tts/*`, texto→imagen, `delivery/email_sender.py`, `app/*`, modos e insignias, briefing pregenerado; D3: capturas y demo grabada |

---

## F0 · Lunes 5-oct · Esqueleto y camino mock (cerrada)

### Transversal

- [x] Estructura de carpetas y `__init__.py` — `src/briefer/**`, `app/**`, `tests/` — **Hecho cuando:** `import briefer` funciona con `pythonpath = ["src"]` (pytest) y desde `app/`
- [x] Contratos v0.1 → v0.2 — `src/briefer/schemas.py`, [03](03_contratos_modulos.md) — **Hecho cuando:** todos los modelos de 03 existen, `StepMetric.error` y `QAAnswer.metrics` añadidos y `tests/test_schemas.py` pasa *(v0.2 aplicada en la integración de la Fase 0)*
- [x] Interfaces y registry — `providers/base.py`, `providers/registry.py` — **Hecho cuando:** `test_registry_*` pasan (mocks por defecto, fallback sin clave, error con `BRIEFER_FALLBACK_TO_MOCK=false`, carga perezosa)
- [x] Proveedores mock — `providers/mock.py` — **Hecho cuando:** `test_mock_*` pasan sin red
- [x] Esqueletos de proveedores reales — `providers/{llm,vision,stt,tts,image}/*` — **Hecho cuando:** existen con `provider_name`, `model` y constructor `(settings)`
- [x] Config — `config.py`, `.env.example` — **Hecho cuando:** todas las variables del README están en `.env.example` y en `Settings`
- [x] Costes y métricas — `costs.py`, `logging_utils.track_step` — **Hecho cuando:** `test_costs` y `test_track_step_*` pasan
- [x] Dependencias — `requirements.txt`, `pyproject.toml` — **Hecho cuando:** `pip install -r requirements.txt` y `pip install -e .` en un venv nuevo sin errores *(verificado con Python 3.13 en un venv limpio)*
- [x] Scripts de arranque creados — `scripts/run.ps1`, `scripts/run.sh`, `scripts/demo.py` — **Hecho cuando:** existen y `demo.py --help` lista los flags *(clon limpio: D3)*
- [x] Datos de ejemplo — `data/samples/portfolio_ejemplo.csv`, `noticias_ejemplo.json` — **Hecho cuando:** los tests de schema de muestras pasan
- [x] Datos de ejemplo extra — `data/samples/grafico_ejemplo.png`, `resultados_ejemplo.pdf`, `generar_muestras.py` — **Hecho cuando:** existen una captura de gráfico y un PDF corto (con una página pobre en texto que va a visión), regenerables con el script
- [x] Documentación base y revisión crítica — `README.md`, `docs/*`, [07](07_revision_critica.md), [ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md) — **Hecho cuando:** índice, contratos v0.2 y plan revisado publicados

### Carril A

- [x] Camino mock de entradas — `news.load_sample_news`, `news.dedupe_news`, `prices.synthetic_snapshots` (`end`), `prices.currency_for`, `tickers.normalize_ticker` / `extract_tickers` / `filter_by_tickers` (`min_items`), `portfolio.load_portfolio_csv` / `portfolio_tickers` — **Hecho cuando:** devuelven datos válidos desde `data/samples/` / sintéticos sin red (`tests/test_ingest_mock.py`)
- [x] Lectores con proveedores inyectados — `pdf_reader.read_pdf` (+ `extract_page_texts`, `pages_needing_vision`, `page_images`), `chart_reader.read_chart` / `validate_image`, `voice.voice_to_insight` / `transcribe_question` / `save_audio_upload` — **Hecho cuando:** con `MockVision`/`MockSTT`/`MockLLM` procesan el PNG y el PDF de ejemplo y un audio

### Carril B

- [x] Agentes con mock + prompts de producción — `agents/analyst.py` (`analyze`, `postprocess_analysis`), `agents/scriptwriter.py` (`write_script` con reintento y `fallback_script`), `agents/qa.py` (`answer`, citas), `agents/prompts/{analyst,scriptwriter,qa}.md` — **Hecho cuando:** `tests/test_agents_mock.py` pasa
- [x] Guardarraíles de compliance — `agents/guardrails.py` (`contains_advice`, `strip_advice`, `asks_for_advice`) — **Hecho cuando:** los tres agentes los aplican y hay tests de frases con y sin recomendación (incluidas negaciones)
- [x] Tolerancia a fallos por paso — `pipeline.py` (`_core_step`, `_optional_step`, `PipelineStepError`, `StepNotImplementedError`) — **Hecho cuando:** un fallo en portada, vídeo, entrega, subida o guardado no rompe el briefing; un fallo núcleo lanza `PipelineStepError` con el nombre del paso
- [x] Bug de la métrica de guardado — `pipeline.run_briefing` — **Hecho cuando:** `storage.save` aparece en `Briefing.metrics` del JSON guardado
- [x] e2e mock fin a fin — `tests/test_pipeline_mock.py` — **Hecho cuando:** sin `skip`, `test_run_briefing_with_mocks` y `test_answer_question_with_mocks` pasan *(verificado en integración Fase 0)*

### Carril C

- [x] Podcast, transcripción y gráficos — `media/podcast.py` (`synthesize_podcast` en paralelo con reintentos, `concat_audio`, `audio_duration_s`), `media/transcript.py` (`build_transcript`, `segments_to_srt`, `format_srt_timestamp`), `media/charts.py` (`make_charts`, `make_portfolio_chart`) — **Hecho cuando:** con `MockTTS` y precios sintéticos generan audio, SRT y PNG (`tests/test_media_mock.py`)
- [x] Persistencia — `storage.py` — **Hecho cuando:** round-trip JSON idéntico y la carpeta movida se sigue cargando (rutas relativas; `tests/test_storage.py`)
- [x] Textos de entrega — `delivery/email_sender.build_email_html`, `delivery/telegram_sender.build_caption` — **Hecho cuando:** funciones puras con titular, puntos, disclaimer y aviso de voz sintética
- [x] UI en modo demo — `app/pages/1_Briefing.py`, `3_Mi_cartera.py`, `4_Historico.py`, `app/components/players.py` — **Hecho cuando:** con «Modo demo», «Generar briefing» pinta titular, audio, transcripción, gráficos y métricas; Mi cartera carga el CSV; Histórico reabre briefings

### Pendiente de F0 que pasa a primera hora de D1

- [ ] **[M]** Prueba de humo real — `scripts/smoke_real.py` (nueva) — **Hecho cuando:** una llamada real responde para Anthropic texto, Anthropic visión, Whisper API y edge-tts (2 voces), e IDs de modelo de `.env.example` y `costs.py` confirmados en la consola del proveedor
- [ ] **[M]** Clave de grupo con límite de gasto (20-30 $) — **Hecho cuando:** los tres pueden ejecutar la prueba de humo
- [ ] **[M]** CI — `.github/workflows/tests.yml` (nuevo) — **Hecho cuando:** `python -m pytest -q` en modo mock corre en cada PR y la insignia verde sale en el README

---

## D1 · Martes 6-oct · Núcleo real

| Hora | A | B | C |
| --- | --- | --- | --- |
| 09:00-13:00 | Noticias reales (RSS + yfinance) y precios con caché | Humo real; `AnthropicLLM.complete`; Analista real; Guionista en Haiku; CI | `EdgeTTS` + normalización para TTS; podcast real |
| **13:00 Sync 1** | `demo.py --tickers SAN.MC AAPL` con noticias y LLM reales y audio real · desde aquí contratos solo aditivos | | |
| 13:00-18:00 | `ClaudeVision.describe` + `read_chart` real | Fallback núcleo → mock marcado; insignias; paralelismo; métricas verificadas | Modos Ejemplo / Sin claves / Real; LLM mock realista; portada de la app |
| **18:00 Sync 2** | Briefing real e2e desde la UI; **pregenerado v1** en `data/samples/demo_briefing/` | | |
| 18:00-22:00 | `read_pdf` real | Prompts con 3 carteras | Transcripción con locutores, métricas visuales |
| **22:00 go/no-go** | ¿e2e real? Si no: el miércoles solo Must + fallbacks + pregenerado | | |

### Carril A · Entradas

- [ ] **[M]** Noticias en español — `ingest/news.py`: `fetch_rss_news` (Google News RSS por nombre de empresa de `TICKER_UNIVERSE`, `hl=es`, + 1-2 feeds de prensa económica en `BRIEFER_RSS_FEEDS`), `fetch_yfinance_news`, `fetch_news` (ventana `since`, `dedupe_news`) — **Hecho cuando:** para `SAN.MC ITX.MC AAPL` devuelve ≥ 5 `NewsItem` con fuente y URL, y un feed caído no rompe la llamada
- [ ] **[M]** Precios reales con caché diaria — `ingest/prices.py`: `get_price_snapshot`, `get_price_snapshots`; caché en `data/cache/` (`BRIEFER_CACHE_DIR`) — **Hecho cuando:** `PriceSnapshot` con `change_pct` e `history` para US y `.MC`; la segunda ejecución del día no llama a yfinance; un ticker sin datos se omite con aviso (nunca precio sintético en modo real)
- [ ] **[M]** Visión Claude — `providers/vision/claude_vision.py`: `ClaudeVision.describe`, `detect_media_type` (rellena `last_usage`) — **Hecho cuando:** describe `data/samples/grafico_ejemplo.png` con tendencia y niveles
- [ ] **[M]** Gráfico real en el briefing — `ingest/chart_reader.read_chart` con `ClaudeVision` — **Hecho cuando:** la captura subida aparece como insight citado en el `Analysis`
- [ ] **[M]** PDF real — `ingest/pdf_reader.read_pdf` (pypdf + visión en páginas pobres) — **Hecho cuando:** `resultados_ejemplo.pdf` produce un `DocumentInsight` con ≥ 3 `key_figures` y la página 3 pasa por visión

### Carril B · Agentes y orquestación

- [ ] **[M]** Proveedor Anthropic con salida estructurada — `providers/llm/anthropic_llm.py`: `AnthropicLLM._get_client`, `AnthropicLLM.complete` (rellena `last_usage`) — **Hecho cuando:** `complete(..., response_model=Analysis)` devuelve un `Analysis` válido con un contexto real
- [ ] **[M]** Analista real — `agents/analyst.analyze` + `prompts/analyst.md` — **Hecho cuando:** 4-6 `KeyPoint` con fuentes reales, sin tickers ni fuentes fuera del contexto (lo garantiza `postprocess_analysis`) y disclaimer
- [ ] **[M]** Guionista en el modelo barato — `pipeline.run_briefing` (paso `agents.scriptwriter` con `providers.llm_cheap`), `prompts/scriptwriter.md` — **Hecho cuando:** guion A/B de 3-5 min, natural, con cierre hablado (disclaimer + voz sintética) y coste del paso ~60 % menor que con Sonnet
- [ ] **[M]** Fallback núcleo → mock marcado — `pipeline._core_step` / `run_briefing` — **Hecho cuando:** si un proveedor real de un paso núcleo falla (red, 429, 404), el paso se repite con el mock, el briefing termina y el `StepMetric` lo indica (`provider="mock"` + `error` con la causa); la UI lo muestra
- [ ] **[M]** Métricas por paso verificadas — `pipeline.py`, `costs.py` — **Hecho cuando:** un briefing real tiene un `StepMetric` por paso con latencia real y coste estimado coherente con la factura del proveedor
- [ ] **[S]** Paralelismo de ingesta — `pipeline.run_briefing` (noticias ∥ precios con `ThreadPoolExecutor`) — **Hecho cuando:** la latencia de ingesta es ≈ máx. de las dos y se ve en la traza
- [ ] **[M]** Revisión de prompts con 3 carteras distintas — `agents/prompts/*.md` — **Hecho cuando:** sin recomendaciones de compra/venta ni cifras inventadas en las 3 (y `contains_advice` no salta)

### Carril C · Media, UI y demo

- [ ] **[M]** TTS edge-tts 2 voces — `providers/tts/edge_tts_provider.py`: `EdgeTTS.synthesize`; versión fijada en `requirements.txt` — **Hecho cuando:** sintetiza con `BRIEFER_VOICE_A` y `BRIEFER_VOICE_B`; `synthesize_podcast(max_workers≤4, retries=2)` genera un MP3 de 3-5 min sin errores de *throttling*
- [ ] **[M]** Normalización para TTS — `media/podcast.normalize_for_speech` (nueva), aplicada en `synthesize_podcast` — **Hecho cuando:** «SAN.MC» se oye «Santander», «1,5 %» se oye «uno coma cinco por ciento» y «Q3» «tercer trimestre» (test unitario)
- [ ] **[M]** Modos explícitos — `app/components/players.sidebar_controls`, `pipeline.run_briefing` — **Hecho cuando:** la barra lateral ofrece **Ejemplo guardado** (offline, instantáneo) · **Sin claves** (noticias de ejemplo + LLM mock + edge-tts real) · **Real** (`.env`), y el modo activo se ve siempre
- [ ] **[M]** Insignias de proveedor — `app/components/players.py`, `registry.describe_providers` — **Hecho cuando:** cada familia aparece como «real» o «MOCK (falta X)»; un fallback silencioso del registry se ve en la UI
- [ ] **[M]** LLM mock realista — `providers/mock.py` (`MockLLM`) — **Hecho cuando:** en modo «Sin claves» el análisis y el guion son textos en español creíbles (marcados como ejemplo) y el podcast suena con edge-tts
- [ ] **[M]** Briefing pregenerado v1 — `data/samples/demo_briefing/` (briefing.json con rutas relativas, podcast.mp3, SRT, PNG); regla de tamaño de `data/samples/README.md` a < 5 MB en total — **Hecho cuando:** `storage.load_briefing` lo carga en otra máquina y la portada de la app lo muestra al abrir, sin pulsar nada
- [ ] **[S]** Portada de la app (primeros 30 s) — `app/main.py` — **Hecho cuando:** cabecera + insignia de modo + tarjeta del briefing de hoy (pregenerado o último) con reproductor y 3 puntos clave + botones «Generar el mío» / «Preguntar por voz» / «Subir»; disclaimer en banda compacta
- [ ] **[S]** Transcripción y métricas visuales — `app/components/players.render_briefing` — **Hecho cuando:** transcripción con nombres de locutor; `st.metric` de latencia total, coste y nº de modelos + barras por paso

### Integración D1

- [ ] **[M]** `scripts/demo.py` real — **Hecho cuando:** `python scripts/demo.py --tickers SAN.MC AAPL` genera un briefing completo con claves reales y lo guarda en `data/outputs/<id>/`

---

## D2 · Miércoles 7-oct · Multimodalidad, orquestación visible y vídeo

| Hora | A | B | C |
| --- | --- | --- | --- |
| 09:00-13:00 | Whisper API + `transcribe_question` (audio en el uploader ya hecho en F0) | Agente Q&A real + `answer_question` con `QAAnswer.metrics` | Vídeo con ffmpeg (720×1280, subtítulos quemados) |
| **13:00 Sync 3** | PDF + gráfico + Q&A por voz reales · **go/no-go de las Should** | | |
| 13:00-18:00 | Router CLIP/SigLIP + captura de cartera → `Portfolio` | Puertas de calidad (grounding + anti-recomendación); WER del podcast | Portada por texto→imagen API; pestaña «Cómo se hizo»; Preguntar pulida |
| **18:00 Sync 4** | Todo integrado en `main`; Docker probado en una máquina | | |
| 18:00-22:00 | Telegram | `docs/04` (costes fijos, licencias, MAR, AI Act, RGPD); medición p50/p95 | Histórico y Mi cartera; esqueleto del pitch |
| **22:00** | **Feature freeze** | | |

### Carril A

- [ ] **[M]** STT — `providers/stt/whisper_api.py` (`WhisperAPI.transcribe`); `ingest/voice.transcribe_question` — **Hecho cuando:** transcribe una pregunta de 10 s en español correctamente
- [x] **[M]** Audio en el uploader del briefing — `app/pages/1_Briefing.py` (`wav`, `mp3`, `m4a`, `ogg`, `webm`) → `pipeline.process_upload` — **Hecho cuando:** una nota de voz subida aparece como insight `voice` *(hecho en integración F0; verificado en mock por `tests/test_pipeline_mock.py`; falta probar con Whisper real)*
- [ ] **[S]** Router de imágenes por contenido — `providers/image/clip_classifier.py` (`CLIPClassifier.classify`, torch CPU vía `requirements-local.txt` con `--index-url …/whl/cpu`), `chart_reader.classify_image`, enrutado en `pipeline.process_upload` — **Hecho cuando:** distingue velas / línea / tabla / cartera / no financiera en 5 imágenes de prueba; «no financiera» se rechaza sin llamar a visión; la decisión queda en la traza
- [ ] **[S]** Captura de cartera del broker → `Portfolio` — `ingest/portfolio.portfolio_from_image` (nueva; visión + `response_model=Portfolio`) — **Hecho cuando:** una captura de ejemplo produce un `Portfolio` válido que se usa en el briefing
- [ ] **[S]** Telegram — `delivery/telegram_sender.send_briefing_telegram` — **Hecho cuando:** el bot envía titular, audio y disclaimer; sin token devuelve `ok=False, "Telegram no configurado"` sin excepción
- [ ] **[M]** Datos del usuario (RGPD) — `ingest/voice.py`, `pipeline.answer_question` — **Hecho cuando:** el audio de la pregunta se borra tras transcribirlo y hay casilla de consentimiento antes de guardar la cartera

### Carril B

- [ ] **[M]** Agente Q&A real — `agents/qa.answer` con `AnthropicLLM` (barato), `prompts/qa.md` — **Hecho cuando:** responde con fuentes del briefing y reconduce las peticiones de recomendación
- [ ] **[M]** `answer_question` fin a fin con métricas — `pipeline.answer_question` → `QAAnswer.metrics` — **Hecho cuando:** audio → texto → respuesta → audio en < 10 s medido con los `StepMetric` y mostrado en la página Preguntar
- [ ] **[S]** Puerta de *grounding* — `agents/guardrails.untraceable_figures` (nueva), reintento en `analyst.analyze` / `scriptwriter.write_script` — **Hecho cuando:** una cifra o ticker del `Analysis`/guion que no esté en el `MarketContext` provoca **un** reintento con la lista de cifras no trazables; el resultado queda en la traza
- [ ] **[S]** Anti-recomendación con reintento — `agents/guardrails.contains_advice` en el bucle del Analista/Guionista — **Hecho cuando:** una salida con recomendación provoca un reintento antes de recortar la frase
- [ ] **[S]** Whisper sobre el podcast generado — `media/transcript.verify_podcast` (nueva; STT + WER contra el guion) — **Hecho cuando:** el briefing muestra el WER y las líneas con WER alto se re-sintetizan una vez; SRT con tiempos reales
- [ ] **[M]** Contenido de documentos como datos — `pdf_reader.read_pdf`, `chart_reader.read_chart` (delimitadores en el prompt) — **Hecho cuando:** un PDF con «ignora las instrucciones» no altera el análisis
- [ ] **[M]** `docs/04` reforzado — costes fijos (datos, noticias licenciadas, TTS oficial Azure, hosting), punto de equilibrio B2C vs B2B2C, MAR (sentimiento = «impacto de la noticia»), AI Act art. 50, transferencias RGPD, tabla riesgo → control en código — **Hecho cuando:** cada control apunta a un fichero del repo
- [ ] **[M]** Medición p50/p95 — `StepMetric` de 3-5 briefings y 5 Q&A — **Hecho cuando:** columna «Medido» de `docs/04` rellena (cierre en D3)
- [ ] **[C]** Un LLM alternativo — `providers/llm/gemini_llm.py` (`GeminiLLM.complete`) — **Hecho cuando:** `BRIEFER_LLM_PROVIDER=gemini` genera un briefing sin tocar código

### Carril C

- [ ] **[M]** Vídeo corto con ffmpeg — `media/video.make_video` (ffmpeg de `imageio-ffmpeg`, `size=(720, 1280)` desde el pipeline, fps bajo, subtítulos del SRT quemados, TTF libre en el repo) — **Hecho cuando:** MP4 vertical de un briefing de 4 min en < 60 s de CPU; si falla, el briefing sigue (paso opcional)
- [ ] **[S]** Portada / infografía por texto→imagen API — `providers/image/` (proveedor por API, nuevo), `media/cover.py` (`build_cover_prompt`, `overlay_title`, `make_cover`) — **Hecho cuando:** genera una portada marcada «imagen generada por IA», reutilizada como primer fotograma del vídeo y miniatura de Telegram; con `BRIEFER_IMAGE_GEN_PROVIDER=none` se omite sin error
- [ ] **[S]** Pestaña «Cómo se hizo» — `app/components/players.render_trace` (nueva) — **Hecho cuando:** grafo del briefing con cada modelo, latencia, coste, decisión del router, resultado de las puertas y pasos caídos a mock
- [ ] **[M]** Página Preguntar pulida — `app/pages/2_Preguntar.py` — **Hecho cuando:** grabar pregunta → texto en cuanto llega + audio + fuentes + latencia medida
- [ ] **[M]** Pulido UI — `app/*` — **Hecho cuando:** estados de carga con aviso «no cambies de página», errores amables con el paso que falló, disclaimer visible, tabla de métricas, `st.cache_resource` para modelos locales
- [ ] **[C]** Email — `delivery/email_sender.send_briefing_email` — **Hecho cuando:** llega un email con transcripción, gráficos inline (CID) y disclaimer
- [ ] **[S]** Esqueleto del pitch — `pitch/` — **Hecho cuando:** 10-12 diapositivas con títulos y huecos para capturas y cifras medidas

### Transversal D2

- [x] Docker creado — `Dockerfile` (python:3.11-slim + ffmpeg), `docker-compose.yml` (Compose ≥ 2.24) — **Hecho cuando:** los ficheros existen
- [ ] **[M]** Docker probado — **Hecho cuando:** `docker compose up --build` en una máquina sirve la app en :8501 con ffmpeg (Sync 4)
- [ ] **[M]** Tests de funciones puras nuevas — `tests/*` (normalización TTS, grounding, router con umbral, fallback a mock) + test real `@pytest.mark.real` que se salta sin claves — **Hecho cuando:** `python -m pytest -q` pasa sin red y sin tests saltados (salvo `real`)

---

## D3 · Jueves 8-oct · Entregable (hasta 16:30)

| Hora | Tarea | Carril |
| --- | --- | --- |
| 09:00-11:00 | Solo bugs; limpieza de *stubs*; **pregenerado final**; medir 3-5 briefings y 5 Q&A | A limpieza y clon limpio · B mediciones y `docs/04` · C pregenerado y capturas |
| **11:00** | **Code freeze** | — |
| 11:00-13:00 | Demo grabada (3-4 min, 2 tomas) · capturas · README final | C demo · A README · B pitch |
| 13:00-15:00 | Pitch PDF; `docs/06` y checklist de `docs/00` | B pitch · A/C revisión cruzada |
| 15:00-15:45 | **Clon limpio** en otra máquina: `run.ps1` sin `.env` (modo Ejemplo) y con `.env`; `docker compose up --build` | A + C |
| 16:00 | Etiqueta `v1.0`; comprobación de que no se versiona `.env`, `data/outputs/`, `docs/raw/` | B |
| **16:30** | **Entrega en el aula virtual** (17:00 límite interno; 18:00 oficial) | — |

- [ ] **[M]** Limpieza de *stubs* — `providers/registry.py`, `providers/{vision/qwen_vl_local,image/sdxl_turbo,tts/elevenlabs_tts,stt/whisper_local,llm/openai_llm}.py` — **Hecho cuando:** ningún proveedor accesible desde `.env` lanza `NotImplementedError`; los no implementados salen del registry y se citan como roadmap
- [ ] **[M]** Pregenerado final — `data/samples/demo_briefing/` — **Hecho cuando:** regenerado con el código final y cargado en la portada desde un clon limpio
- [ ] **[M]** Costes y latencias medidos — `docs/04`, tarifas de `costs.py` verificadas — **Hecho cuando:** p50/p95 de briefing y Q&A medidos y los `TODO: verificar` de `costs.py` resueltos con fecha
- [ ] **[M]** Clon limpio + `run.ps1` / `run.sh` / Docker — **Hecho cuando:** los tres caminos funcionan desde cero (o se aplica el go/no-go de las 15:45)
- [ ] **[M]** Capturas — `docs/assets/capturas/*.png`, `README.md#capturas` — **Hecho cuando:** las 7 capturas existen y se ven en GitHub
- [ ] **[M]** Demo grabada (3-4 min) — enlace en `README.md#demo` — **Hecho cuando:** muestra portada, generar, subir gráfico/PDF, Q&A por voz, traza y métricas, con audio
- [ ] **[M]** Pitch deck técnico — `pitch/*.pdf` — **Hecho cuando:** problema, usuario, demo, cadena de modelos, resultados medidos, unit economics, compliance como controles, monetización, roadmap, equipo
- [ ] **[M]** README final — `README.md` — **Hecho cuando:** captura/GIF y enlace a la demo arriba, «arranca en 2 comandos», tabla de modalidades con columna «Activo en la demo», diagrama de orquestación, configuración en anexo, sin TODO, equipo con nombres
- [ ] **[M]** Revisión de compliance — UI, prompts, email, Telegram, podcast — **Hecho cuando:** `DISCLAIMER_ES` en todos los canales, voz sintética avisada (hablado + metadatos MP3/MP4) e imagen IA marcada
- [ ] **[M]** Estado final — `docs/06_estado_actual.md`, checklist de `docs/00_enunciado.md` — **Hecho cuando:** reflejan lo entregado
- [ ] **[M]** Higiene del repo — **Hecho cuando:** comprobado en el último commit que no se versiona `.env`, `data/outputs/` ni `docs/raw/`; etiqueta `v1.0`

---

## MoSCoW

Presupuesto: ~90 horas-persona hasta el jueves 17:00; núcleo + entrega ≈ 60 h. **Las Should no pasan de ~25 h.**
Horas estimadas en [07](07_revision_critica.md#3-mejoras-priorizadas-moscow).

| Prioridad | Qué | Fase |
| --- | --- | --- |
| **Must** | Camino mock e2e verde *(hecho)* + CI | F0 / D1 |
| **Must** | Humo real de cada proveedor, IDs verificados, límite de gasto | D1 |
| **Must** | Núcleo real: noticias (RSS en español + yfinance precios) → Analista → Guionista (Haiku) → TTS 2 voces normalizado → SRT → gráficos | D1 |
| **Must** | Fallback por paso (opcional → omitido *(hecho)*; núcleo → mock marcado) + insignias de modo/proveedor | F0 / D1 |
| **Must** | Briefing pregenerado real con rutas relativas, mostrado en la portada | D1 / D3 |
| **Must** | Modo «Sin claves» con edge-tts real y LLM mock realista | D1 |
| **Must** | Gráfico + PDF por visión; Q&A por voz con métricas | D1 / D2 |
| **Must** | Vídeo simple con ffmpeg (opcional en ejecución) | D2 |
| **Must** | README con capturas + demo grabada + pitch PDF + clon limpio | D3 |
| **Must** | `docs/04` con costes y latencias medidos y costes fijos/licencias | D2 / D3 |
| **Should** | Router CLIP/SigLIP · puertas de calidad (grounding + anti-recomendación) · WER del podcast · pestaña «Cómo se hizo» · portada texto→imagen API · captura de cartera → `Portfolio` · Telegram · paralelismo · portada de la app y métricas visuales | D1 / D2 |
| **Could** | Embeddings (histórico y dedupe semántico) · FinBERT como segunda opinión · Q&A con herramientas · email · Gemini como LLM alternativo · despliegue en la nube | D2 si sobra tiempo |
| **Won't** | Stable Video Diffusion, SDXL local, Qwen-VL local, ElevenLabs, Bark, Whisper local, *fine-tuning*, autenticación, base de datos, segundo LLM alternativo | — |

---

## Recortes si no da tiempo

Orden en que se cae algo (lo primero de la lista es lo primero que se recorta). Se aplica en los go/no-go
(mar 22:00, mié 13:00). Nada de esta lista afecta al núcleo.

| Orden | Funcionalidad | Qué queda en su lugar |
| --- | --- | --- |
| 1 | Could: FinBERT, embeddings, Q&A con herramientas, despliegue en la nube | — |
| 2 | Email | Telegram + web |
| 3 | LLM alternativo (Gemini) | Solo Anthropic + mock (la arquitectura lo permite igualmente, ADR-002) |
| 4 | Captura de cartera → `Portfolio` | Cartera por CSV o formulario |
| 5 | Portada texto→imagen API | Sin portada (`BRIEFER_IMAGE_GEN_PROVIDER=none`); el vídeo arranca con el gráfico general |
| 6 | WER del podcast con Whisper | SRT con los tiempos del TTS |
| 7 | Router CLIP/SigLIP | Se asume que la imagen subida es un gráfico (`BRIEFER_IMAGE_CLASSIFIER_PROVIDER=none`) |
| 8 | Telegram | Solo web (descarga de audio y transcripción) |
| 9 | Paralelismo | Pasos secuenciales (el TTS por línea ya es paralelo) |
| 10 | Vídeo corto | Podcast + gráficos en la web |
| Último | Pestaña «Cómo se hizo» y puerta de *grounding* | Son baratas y son la evidencia de orquestación: se recortan solo si no queda otra |
| — | **No se recorta nunca** | Noticias → Analista → Guionista → podcast 2 voces → transcripción → gráficos; PDF y gráfico por visión; Q&A por voz; modos Ejemplo/Sin claves; pregenerado; fallbacks; scripts de arranque; README con capturas y diagrama; demo grabada; pitch |
