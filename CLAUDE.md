# CLAUDE.md — multimodal-market-briefer

> Contexto operativo para agentes IA que trabajen en este repo. Se carga en cada sesión abierta en la raíz.
> Mandan `docs/00_enunciado.md` (qué se evalúa) y `docs/03_contratos_modulos.md` (cómo encajan las piezas).
> Mantener este fichero corto: el detalle vive en `docs/`.

## Qué es

Práctica MIAX **Taller B5-T4**: MVP de una startup FinTech con IA multimodal. Grupo de 3.
**Entrega: jueves 8-oct-2026, 18:00** (repo GitHub con MVP funcional + demo).

**Market Briefer**: cada día recoge noticias de mercado filtradas por los tickers/cartera del usuario, las
interpreta (Agente Analista), escribe un diálogo (Agente Guionista) y genera un **podcast a 2 voces** con
transcripción, gráficos del día y, si da tiempo, **vídeo corto**. Además lee capturas de gráficos y PDFs de
resultados, y responde preguntas por voz (Agente Q&A). Entrega por web, email y Telegram.
Diagrama de la idea: `docs/assets/arquitectura_mvp_podcast_financiero.png`.

## Qué puntúa (no perderlo de vista)

- Más modalidades de entrada/salida **con sentido** y **encadenamiento de varios modelos** > un modelo monolítico.
- MVP que arranca de verdad (`scripts/run.ps1`, `scripts/run.sh`, `docker compose up`), UI clara, robustez.
- Separación limpia **providers (IA) / lógica (ingest, agents, media, delivery, pipeline) / UI (app/)**.
- README exhaustivo (capturas, diagrama de flujo multimodal, arquitectura) + pitch técnico + viabilidad
  (costes, latencia, MiFID II/RGPD, monetización).

## Stack — decisiones cerradas (ver `docs/decisiones/`)

| Capa | Elección | Alternativa por config |
|---|---|---|
| UI | Streamlit multipágina (`app/`) | — |
| LLM (analista, guionista, Q&A) | Anthropic Claude | Gemini, OpenAI, mock |
| Visión (gráficos, páginas PDF) | Claude visión | Qwen2.5-VL local, mock |
| STT | Whisper (API o local) | mock |
| TTS 2 voces | `edge-tts` (gratis, voces es-ES) | ElevenLabs, mock |
| Noticias/precios | `yfinance` + RSS (`feedparser`) | `data/samples/` |
| Gráficos / vídeo | matplotlib-plotly / `moviepy`+ffmpeg | — |
| Config | `.env` → `src/briefer/config.py` | — |

## Mapa del repo

```
app/                      UI Streamlit (solo presentación; llama a briefer.pipeline)
src/briefer/schemas.py    CONTRATOS Pydantic entre módulos  ← no cambiar sin acordarlo entre los 3
src/briefer/pipeline.py   orquestación: run_briefing(), answer_question()
src/briefer/providers/    capa IA: base.py (interfaces), registry.py, mock.py, llm/ vision/ stt/ tts/ image/
src/briefer/ingest/       entradas y procesado (noticias, tickers, precios, PDF, gráfico, cartera, voz)
src/briefer/agents/       analista, guionista, Q&A (+ prompts/*.md)
src/briefer/media/        gráficos, podcast, transcripción, vídeo, portada
src/briefer/delivery/     email, Telegram
tests/                    sin red, con providers mock
data/samples/             ejemplos versionados · data/cache, data/outputs ignorados
docs/                     documentación del proyecto (índice en docs/README.md)
docs/clase/               resúmenes temáticos de la asignatura (contexto de modelos)
docs/raw/                 material de clase original — IGNORADO por git, nunca versionar
```

Carriles de trabajo paralelos (sin asignar personas): **A** entradas/procesado · **B** agentes/orquestación ·
**C** salidas/entrega/UI. Cada carril desarrolla contra `providers/mock.py` y los contratos de `schemas.py`.

## Qué leer según la tarea

| Tarea | Leer |
|---|---|
| Cualquier cosa | `docs/06_estado_actual.md`, `docs/05_roadmap_TODO.md` |
| Cambiar contratos o interfaces | `docs/03_contratos_modulos.md` |
| Arquitectura / flujo | `docs/02_arquitectura_y_flujo_datos.md` |
| Costes, latencias, compliance | `docs/04_viabilidad_costes_latencia_compliance.md` |
| Elegir/usar un modelo concreto | `docs/clase/00_indice.md` → `docs/clase/11_recetario_notebooks.md` |
| Detalle del material original | `docs/raw/text/` (texto extraído; solo existe en local) |

## Reglas

1. **Contratos primero**: un cambio en `schemas.py` o `providers/base.py` se documenta en `docs/03_contratos_modulos.md`.
2. **Todo proveedor tiene mock** y el camino mock debe funcionar siempre sin red ni claves (`BRIEFER_*_PROVIDER=mock`).
3. La UI no llama a proveedores directamente: solo a `briefer.pipeline`.
4. **Compliance**: el producto informa, no asesora. Sin recomendaciones de compra/venta; disclaimer visible en
   app, guion y audio; citar la fuente de cada noticia; avisar de que la voz es sintética.
5. No versionar `docs/raw/`, `.env`, ni salidas generadas (`data/outputs/`, audios, vídeos).
6. Nunca copiar literal el material de clase a ficheros versionados: resumir.
7. Números de coste/latencia: o medidos (y se dice cómo) o marcados como estimación.
8. **Git**: commits en español, sin ninguna mención a IA/Claude (sin `Co-Authored-By` ni pies generados).
   `git pull --rebase` antes de empezar y antes de subir.
9. Al cerrar una sesión: actualizar `docs/06_estado_actual.md` y marcar checkboxes en `docs/05_roadmap_TODO.md`.

## Comandos

```bash
scripts/run.sh                 # Linux/macOS: venv + deps + streamlit
scripts/run.ps1                # Windows
docker compose up --build      # contenedor, http://localhost:8501
python -m pytest -q            # tests (mock, sin red)
python scripts/demo.py --mock  # briefing de punta a punta por CLI
```
