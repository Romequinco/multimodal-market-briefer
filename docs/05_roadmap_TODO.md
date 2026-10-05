# 05 · Roadmap y TODO hasta la entrega

**Entrega: jueves 8-oct-2026, 18:00** (aula virtual). Tareas por fase y por carril, sin asignar personas:
cada uno marca la que coge escribiendo su nombre al lado. Contratos y firmas reales en
[03](03_contratos_modulos.md).

Formato: `- [ ] Tarea — ficheros / funciones — **Hecho cuando:** criterio verificable`. Solo se marca `[x]` lo
que se ha ejecutado y visto funcionar.

## Resumen de fases

| Fase | Fecha | Objetivo | Hito de salida |
| --- | --- | --- | --- |
| D0 | lun 5-oct | Esqueleto | `streamlit run` arranca y `pytest` pasa en modo mock |
| D1 | mar 6-oct | Camino feliz fin a fin | Briefing real (noticias → análisis → guion → podcast 2 voces → transcripción → gráficos) visible en la UI |
| D2 | mié 7-oct | Multimodalidad extra + UI + vídeo | PDF, gráfico, Q&A por voz, vídeo, email/Telegram; UI pulida; Docker probado |
| D3 | jue 8-oct | Entregable | README con capturas, demo grabada, pitch deck; entrega antes de las 18:00 con buffer |

---

## D0 · Lunes 5-oct · Esqueleto

### Transversal

- [x] Estructura de carpetas y `__init__.py` — `src/briefer/**`, `app/**`, `tests/` — **Hecho cuando:** `import briefer` funciona con `pythonpath = ["src"]` (pytest) y desde `app/` (vía `app/components/__init__.py`)
- [x] Contratos v0.1 — `src/briefer/schemas.py` (incl. `Briefing.deliveries`, `DISCLAIMER_ES`, `new_briefing_id`) — **Hecho cuando:** todos los modelos de [03](03_contratos_modulos.md) existen y `tests/test_schemas.py` pasa
- [x] Interfaces y registry — `providers/base.py`, `providers/registry.py` (`get_llm(cheap=, force_mock=)`, `get_vision`, `get_stt`, `get_tts`, `get_image_gen`, `get_image_classifier`, `describe_providers`, `ProviderConfigError`) — **Hecho cuando:** `test_registry_*` pasan (mocks por defecto, fallback sin clave, error con `BRIEFER_FALLBACK_TO_MOCK=false`, carga perezosa)
- [x] Proveedores mock — `providers/mock.py` (`MockLLM`, `MockVision`, `MockSTT`, `MockTTS`, `MockImageGen`, `MockImageClassifier`) — **Hecho cuando:** `test_mock_*` pasan sin red
- [x] Esqueletos de proveedores reales — `providers/llm/*`, `vision/*`, `stt/*`, `tts/*`, `image/*` — **Hecho cuando:** existen con `provider_name`, `model` y constructor `(settings)`; los métodos lanzan `NotImplementedError` con `TODO`
- [x] Config — `src/briefer/config.py`, `.env.example` — **Hecho cuando:** todas las variables de `README.md#configuración` están en `.env.example` y en `Settings`
- [x] Costes y métricas — `costs.py` (`estimate_cost_eur`, `summarize_metrics`…), `logging_utils.py` (`get_logger`, `track_step`) — **Hecho cuando:** `test_costs` y `test_track_step_records_metric_even_on_error` pasan
- [ ] Dependencias — `requirements.txt`, `requirements-local.txt`, `pyproject.toml` — **Hecho cuando:** `pip install -r requirements.txt` (y `pip install -e .`) en un venv nuevo sin errores *(ficheros creados; instalación limpia NO VERIFICADA)*
- [x] Scripts de arranque creados — `scripts/run.ps1` (`-Local`), `scripts/run.sh` (`--local`), `scripts/demo.py` — **Hecho cuando:** existen y `demo.py --help` lista los flags *(arranque en clon limpio: ver D3)*
- [x] Datos de ejemplo — `data/samples/portfolio_ejemplo.csv`, `noticias_ejemplo.json`, `data/samples/README.md` — **Hecho cuando:** `test_sample_news_match_schema` y `test_sample_portfolio_csv_matches_schema` pasan
- [x] Documentación base — `README.md`, `docs/*` — **Hecho cuando:** índice y contratos publicados y alineados con el código
- [ ] Datos de ejemplo extra — `data/samples/` — **Hecho cuando:** hay una captura de gráfico y un PDF corto de ejemplo (ver `data/samples/README.md`)

### Carril A

- [x] Esqueleto de `ingest/*` con las firmas de [03](03_contratos_modulos.md) — `src/briefer/ingest/*.py` — **Hecho cuando:** todas las funciones existen como *stubs* con `TODO`
- [ ] Camino mock de entradas — `news.load_sample_news`, `prices.synthetic_snapshots`, `tickers.normalize_ticker` / `filter_by_tickers`, `portfolio.load_portfolio_csv` / `portfolio_tickers` — **Hecho cuando:** devuelven datos válidos desde `data/samples/` / sintéticos sin red

### Carril B

- [x] Orquestación escrita — `pipeline.py` (`get_providers`, `process_upload`, `run_briefing`, `answer_question`) — **Hecho cuando:** `test_pipeline_module_imports` pasa
- [ ] `pipeline.run_briefing` en modo mock fin a fin — `pipeline.py` + `agents.analyst.analyze` / `build_user_message`, `agents.scriptwriter.write_script` / `estimate_duration_s` — **Hecho cuando:** se quita el `skip` de `tests/test_pipeline_mock.py::test_run_briefing_with_mocks` y pasa (`Briefing` válido con `metrics`)
- [x] Borradores de prompts — `agents/prompts/{analyst,scriptwriter,qa}.md`, `agents.load_prompt` — **Hecho cuando:** existen con rol, formato de salida y reglas de compliance

### Carril C

- [x] UI esbozada — `app/main.py`, `app/pages/1_Briefing.py`, `2_Preguntar.py`, `3_Mi_cartera.py`, `4_Historico.py`, `app/components/players.py` — **Hecho cuando:** `streamlit run app/main.py` arranca, las 4 páginas cargan sin excepción y muestran «Pendiente» donde falta código
- [ ] Camino mock de salidas — `media.podcast.synthesize_podcast` / `concat_audio` / `audio_duration_s`, `media.transcript.build_transcript` / `segments_to_srt` / `format_srt_timestamp`, `media.charts.make_charts` — **Hecho cuando:** con `MockTTS` y precios sintéticos generan audio, SRT y PNG
- [ ] Persistencia — `storage.briefing_dir`, `save_briefing`, `load_briefing`, `list_briefings` — **Hecho cuando:** guarda y recarga un `Briefing` idéntico (round-trip JSON) y la página Histórico lo lista
- [ ] La página Briefing muestra un briefing mock — `app/pages/1_Briefing.py` — **Hecho cuando:** con «Modo demo» activado, «Generar briefing» pinta titular, audio, transcripción, gráficos y métricas

---

## D1 · Martes 6-oct · Camino feliz fin a fin

### Carril A · Entradas y procesado

- [ ] Noticias reales — `ingest/news.py`: `fetch_yfinance_news`, `fetch_rss_news`, `dedupe_news`, `fetch_news` — **Hecho cuando:** para 3 tickers devuelve ≥ 5 `NewsItem` con fuente y URL
- [ ] Filtro por tickers y alias (nombre de empresa) — `ingest/tickers.py`: `TICKER_UNIVERSE`, `extract_tickers`, `filter_by_tickers` — **Hecho cuando:** test con noticias de ejemplo filtra correctamente
- [ ] Precios e histórico 1 mes — `ingest/prices.py`: `get_price_snapshot`, `get_price_snapshots` — **Hecho cuando:** `PriceSnapshot` con `change_pct` y `history` para tickers US y `.MC`
- [ ] Cartera desde CSV — `ingest/portfolio.py`: `load_portfolio_csv` — **Hecho cuando:** carga `portfolio_ejemplo.csv` y valida tickers
- [ ] Caché de red — `data/cache/` (`BRIEFER_CACHE_DIR`) — **Hecho cuando:** segunda ejecución del mismo día no vuelve a llamar a yfinance

### Carril B · Agentes y orquestación

- [ ] Proveedor Anthropic con salida estructurada — `providers/llm/anthropic_llm.py`: `AnthropicLLM.complete` (rellena `last_usage`) — **Hecho cuando:** `complete(..., response_model=Analysis)` devuelve un `Analysis` válido
- [ ] Agente Analista — `agents/analyst.py`: `analyze`, `build_user_message`; `prompts/analyst.md` — **Hecho cuando:** con contexto real produce 4-6 `KeyPoint` con fuentes y disclaimer
- [ ] Agente Guionista — `agents/scriptwriter.py`: `write_script`, `estimate_duration_s`; `prompts/scriptwriter.md` — **Hecho cuando:** guion A/B de 3-5 min, natural, con disclaimer hablado al final
- [ ] Métricas por paso verificadas fin a fin — `pipeline.py`, `costs.py`, `logging_utils.track_step` — **Hecho cuando:** un briefing real tiene un `StepMetric` por paso con latencia real y coste estimado (código escrito; falta verificar)
- [ ] Tolerancia a fallos — `pipeline.py` — **Hecho cuando:** un fallo en un paso opcional (portada, vídeo, entrega) no rompe el briefing; un fallo núcleo cae a mock y se marca (hoy las excepciones se propagan)

### Carril C · Salidas y UI

- [ ] TTS edge-tts 2 voces — `providers/tts/edge_tts_provider.py`: `EdgeTTS.synthesize` — **Hecho cuando:** sintetiza una frase con `BRIEFER_VOICE_A` y `BRIEFER_VOICE_B`
- [ ] Podcast — `media/podcast.py`: `synthesize_podcast`, `concat_audio` — **Hecho cuando:** concatena las líneas en un mp3 con `AudioSegment` y tiempos correctos
- [ ] Transcripción y SRT — `media/transcript.py`: `build_transcript`, `segments_to_srt` — **Hecho cuando:** SRT sincronizado con el audio (±0,5 s)
- [ ] Gráficos del día — `media/charts.py`: `make_price_chart`, `make_overview_chart`, `make_portfolio_chart`, `make_charts` — **Hecho cuando:** un PNG por ticker + uno de variaciones del día (+ cartera si la hay)
- [ ] Página Briefing — `app/pages/1_Briefing.py`, `app/components/players.py` (`render_briefing`) — **Hecho cuando:** botón «Generar briefing» → progreso por pasos → reproductor, transcripción, gráficos, análisis

### Integración D1

- [ ] `scripts/demo.py` real — **Hecho cuando:** `python scripts/demo.py --tickers SAN.MC AAPL` genera un briefing completo con claves reales y lo guarda en `data/outputs/<id>/`

---

## D2 · Miércoles 7-oct · Multimodalidad extra, UI y vídeo

### Carril A

- [ ] Lectura de PDF — `ingest/pdf_reader.py`: `extract_page_texts`, `pages_needing_vision`, `page_images`, `read_pdf` — **Hecho cuando:** un PDF de resultados real produce `DocumentInsight` con ≥ 3 `key_figures`
- [ ] Visión Claude — `providers/vision/claude_vision.py`: `ClaudeVision.describe`, `detect_media_type` — **Hecho cuando:** describe una captura de velas con tendencia y niveles
- [ ] Lectura de gráfico — `ingest/chart_reader.py`: `read_chart` — **Hecho cuando:** la captura entra como insight en el análisis
- [ ] STT — `providers/stt/whisper_api.py` (`WhisperAPI.transcribe`) y/o `whisper_local.py` (`WhisperLocal.transcribe`); `ingest/voice.py`: `transcribe_question`, `voice_to_insight`, `save_audio_upload` — **Hecho cuando:** transcribe una pregunta de 10 s en español correctamente
- [ ] *(Opcional)* Clasificador CLIP — `providers/image/clip_classifier.py` (`CLIPClassifier.classify`), `chart_reader.classify_image` — **Hecho cuando:** distingue las `CHART_LABELS` en 3 imágenes de prueba

### Carril B

- [ ] Agente Q&A — `agents/qa.py`: `answer`, `build_qa_context`; `prompts/qa.md` — **Hecho cuando:** responde con fuentes y reconduce peticiones de recomendación
- [ ] `answer_question` fin a fin — `pipeline.py` — **Hecho cuando:** se quita el `skip` de `test_answer_question_with_mocks` y pasa; en real, audio → texto → respuesta → audio en < 10 s (medido con `StepMetric`)
- [ ] Proveedor alternativo (Gemini u OpenAI) — `providers/llm/gemini_llm.py` / `openai_llm.py` (`complete`, soporte de `cheap`) — **Hecho cuando:** cambiar `BRIEFER_LLM_PROVIDER` genera un briefing sin tocar código
- [ ] Revisión de prompts con 3 carteras distintas — **Hecho cuando:** sin recomendaciones de compra/venta ni datos inventados en las 3

### Carril C

- [ ] Vídeo corto — `media/video.py`: `make_video` — **Hecho cuando:** mp4 vertical (1080×1920 por defecto) con gráficos, audio y subtítulos
- [ ] *(Opcional)* Portada — `media/cover.py` (`make_cover`, `build_cover_prompt`, `overlay_title`), `providers/image/sdxl_turbo.py` (`SDXLTurbo.generate`) — **Hecho cuando:** genera portada o se omite sin error con `BRIEFER_IMAGE_GEN_PROVIDER=none`
- [ ] Email — `delivery/email_sender.py`: `build_email_html`, `send_briefing_email` — **Hecho cuando:** llega un email con transcripción, enlace y disclaimer
- [ ] Telegram — `delivery/telegram_sender.py`: `build_caption`, `send_briefing_telegram` — **Hecho cuando:** el bot envía el audio y el titular
- [ ] Página Preguntar — `app/pages/2_Preguntar.py` (`render_qa_answer`) — **Hecho cuando:** grabar pregunta → texto + audio + fuentes
- [ ] Páginas Mi cartera e Histórico — `app/pages/3_Mi_cartera.py`, `4_Historico.py` — **Hecho cuando:** la cartera cargada se usa en Briefing (`st.session_state`); el histórico reabre briefings anteriores
- [ ] Subidas en Briefing (PDF + imagen + audio) — `app/pages/1_Briefing.py` → `pipeline.process_upload` — **Hecho cuando:** los ficheros subidos aparecen como insights en el resultado
- [ ] Pulido UI — `app/*` — **Hecho cuando:** estados de carga, errores amigables, disclaimer visible, indicador de modo mock, tabla de métricas

### Transversal D2

- [x] Docker creado — `Dockerfile` (python:3.11-slim + ffmpeg), `docker-compose.yml` (Compose ≥ 2.24) — **Hecho cuando:** los ficheros existen
- [ ] Docker probado — **Hecho cuando:** `docker compose up --build` en máquina limpia sirve la app en :8501 con ffmpeg incluido
- [ ] Tests — `tests/*` — **Hecho cuando:** `python -m pytest -q` pasa en modo mock sin red **sin tests saltados**

---

## D3 · Jueves 8-oct · Entregable

- [ ] Congelar funcionalidades a las 12:00 — **Hecho cuando:** a partir de ahí solo correcciones
- [ ] Clon limpio + `run.ps1` / `run.sh` / Docker — **Hecho cuando:** los tres caminos funcionan desde cero
- [ ] Capturas — `docs/assets/capturas/*.png`, `README.md#capturas` — **Hecho cuando:** las 7 capturas de la tabla existen y se ven en GitHub
- [ ] Demo grabada (3-5 min) — enlace en `README.md#demo` — **Hecho cuando:** muestra los 6 pasos del guion de demo con audio
- [ ] Pitch deck técnico — `pitch/` — **Hecho cuando:** problema, público, valor, demo, arquitectura, cadena de modelos, costes, compliance, monetización, equipo
- [ ] Costes y latencias medidos — `docs/04_viabilidad_costes_latencia_compliance.md`; tarifas de `costs.py` verificadas — **Hecho cuando:** columna «Medido» rellena con 3 briefings reales y los `TODO: verificar` de `costs.py` resueltos
- [ ] Revisión de compliance — UI, prompts, email, Telegram, podcast — **Hecho cuando:** `DISCLAIMER_ES` presente en todos los canales y voz sintética avisada
- [ ] README final — `README.md` — **Hecho cuando:** sin TODO, equipo con nombres, enlaces revisados
- [ ] Estado final — `docs/06_estado_actual.md`, checklist de `docs/00_enunciado.md` — **Hecho cuando:** reflejan lo entregado
- [ ] Revisar que no se versiona `.env`, `data/outputs/` ni `docs/raw/` — **Hecho cuando:** comprobado en el último commit
- [ ] Entrega en aula virtual antes de las 17:00 (1 h de buffer) — **Hecho cuando:** enlace al repo subido

---

## Recortes si no da tiempo

Orden en que se cae algo (lo primero de la lista es lo primero que se recorta). Nada de esta lista afecta al
camino feliz de D1.

| Prioridad de recorte | Funcionalidad | Qué queda en su lugar |
| --- | --- | --- |
| 1 | Stable Video Diffusion | Vídeo con imágenes estáticas (moviepy) |
| 2 | Portada generada (SDXL-Turbo) | Sin portada (`BRIEFER_IMAGE_GEN_PROVIDER=none`) o plantilla matplotlib |
| 3 | Clasificador CLIP | Se asume que la imagen subida es un gráfico (`BRIEFER_IMAGE_CLASSIFIER_PROVIDER=none`) |
| 4 | Telegram | Solo email + web |
| 5 | Proveedor LLM alternativo | Solo Anthropic + mock (la arquitectura lo permite igualmente) |
| 6 | Qwen2.5-VL local | Solo Claude visión |
| 7 | Email | Solo web (descarga de audio y transcripción) |
| 8 | Vídeo corto | Podcast + gráficos en la web |
| 9 | Histórico | Solo el último briefing |
| — | **No se recorta nunca** | Noticias → Analista → Guionista → podcast 2 voces → transcripción → gráficos; PDF o gráfico (al menos uno); Q&A por voz; modo mock; scripts de arranque; README con diagrama |
