# 06 · Estado actual

> Responde a «¿en qué estado está el proyecto hoy?». Se actualiza al final de cada jornada. Solo se marca
> como hecho lo que alguien del equipo ha ejecutado y visto funcionar; lo no comprobado se marca **NO
> VERIFICADO**. Las cifras de coste y latencia que no salgan de un `StepMetric` real se marcan **NO MEDIDO**.

**Fecha:** 05-oct-2026 (D0) · **Fase:** esqueleto · **Entrega:** 8-oct-2026, 18:00 · **Contratos:** v0.1

## Qué funciona

| Elemento | Estado | Evidencia |
| --- | --- | --- |
| Idea, diagrama y propuesta de valor | Hecho | `docs/assets/arquitectura_mvp_podcast_financiero.png`, [01](01_producto_y_propuesta_valor.md) |
| Stack y decisiones | Hecho | [ADR-001](decisiones/ADR-001-stack-mvp.md), [ADR-002](decisiones/ADR-002-proveedores-intercambiables.md) |
| Contratos (`schemas.py`) y su documentación | Hecho | `src/briefer/schemas.py`, [03](03_contratos_modulos.md) alineado con el código |
| Interfaces, `registry` y proveedores mock | Hecho | `providers/base.py`, `registry.py`, `mock.py`; tests `test_registry_*` y `test_mock_*` |
| Configuración (`config.py` + `.env.example`) | Hecho | Defaults del código = `mock`; `.env.example` propone el stack real |
| Costes estimados y medición de pasos | Hecho (unitario) | `costs.py`, `logging_utils.track_step`; tests `test_costs`, `test_track_step_*`. Tarifas sin verificar (NO MEDIDO) |
| Orquestación (`pipeline.py`) | Escrito | `run_briefing`, `answer_question`, `process_upload`; se importa (`test_pipeline_module_imports`), pero no se ha ejecutado fin a fin |
| Tests | `python -m pytest -q` → **38 passed, 2 skipped** | Saltados: `test_run_briefing_with_mocks` y `test_answer_question_with_mocks` (se activarán cuando `ingest/`, `agents/`, `media/` y `storage` estén implementados) |
| UI Streamlit esbozada | Arranca | `streamlit run app/main.py`: las 4 páginas cargan sin excepción; «Generar briefing», «Preguntar» e «Histórico» muestran «Pendiente: …» |
| CLI | Arranca | `python scripts/demo.py --mock` imprime el disclaimer y sale con «Pendiente de implementar: load_sample_news: pendiente (carril A)» (código 2) |
| Docker y scripts de arranque | Creados | `Dockerfile`, `docker-compose.yml`, `scripts/run.ps1`, `scripts/run.sh`: NO VERIFICADOS en clon limpio |
| Documentación base | Hecho | `README.md`, `docs/` |

## Qué no funciona todavía

| Elemento | Fase prevista |
| --- | --- |
| *Stubs* (`NotImplementedError`) de `ingest/*`, `agents/{analyst,scriptwriter,qa}.py`, `media/*`, `delivery/*`, `storage.py` | D0-D2 |
| Proveedores reales (`AnthropicLLM`, `ClaudeVision`, `WhisperAPI`, `EdgeTTS`… todos *stubs*) | D1-D2 |
| Pipeline en modo mock fin a fin (los 2 tests saltados) | D0-D1 |
| Tolerancia a fallos por paso (hoy las excepciones se propagan) | D1 |
| Noticias y precios reales | D1 |
| Agentes Analista y Guionista con LLM real | D1 |
| Podcast a dos voces, transcripción y gráficos | D1 |
| PDF, captura de gráfico, Q&A por voz | D2 |
| Vídeo, email, Telegram | D2 |
| Instalación limpia de `requirements.txt` y Docker probado en máquina limpia | D2 |
| Capturas, demo grabada, pitch deck | D3 |
| Costes y latencias medidos | D3 (hoy NO MEDIDO) |

## Bloqueos y riesgos

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| Claves de API no disponibles para todos | Un carril no puede probar en real | Modo `mock` por defecto (código, «Modo demo» de la UI, `demo.py --mock`); una clave compartida solo para integración |
| `yfinance` sin noticias o con cambios de API | Briefing vacío | RSS como segunda fuente; `noticias_ejemplo.json` como respaldo |
| `edge-tts` depende de un servicio no oficial | Sin audio | Alternativa ElevenLabs o mock por config; mp3 de demo pregenerado |
| ffmpeg no instalado en la máquina del evaluador | Sin vídeo | Docker incluye ffmpeg; el vídeo es opcional (falta implementar que su fallo no rompa el briefing) |
| Modelos locales pesados (Whisper, Qwen-VL, SDXL) en CPU | Latencia alta | APIs por defecto en `.env.example`; locales solo como alternativa (`requirements-local.txt`) |
| `docker-compose.yml` usa `env_file.required: false` | Falla con Docker Compose antiguo | Requiere Docker Compose ≥ 2.24 (documentado en el README) |
| Tiempo: 3 días | Funcionalidades a medias | Recortes priorizados en [05](05_roadmap_TODO.md#recortes-si-no-da-tiempo) |

## Próximos pasos

1. Cerrar D0: implementar el camino mock (`load_sample_news`, `synthetic_snapshots`, `filter_by_tickers`,
   `analyze`, `write_script`, `synthesize_podcast`, `build_transcript`, `make_charts`, `storage`) y quitar los
   `skip` de `tests/test_pipeline_mock.py`.
2. Repartir los carriles A/B/C y anotar nombres en [05](05_roadmap_TODO.md).
3. D1: primer briefing real fin a fin y medir el primer `StepMetric`.

## Registro de jornadas

| Fecha | Resumen |
| --- | --- |
| 05-oct-2026 | Idea cerrada, stack decidido, contratos v0.1. Esqueleto de código: schemas, mocks, registry, config, costs, logging, pipeline, UI esbozada, scripts y Docker. `pytest`: 38 passed / 2 skipped. Documentación alineada con el código. |
