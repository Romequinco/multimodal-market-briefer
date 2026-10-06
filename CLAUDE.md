# CLAUDE.md — multimodal-market-briefer

> Contexto operativo para agentes IA que trabajen en este repo. Se carga en cada sesión abierta en la raíz.
> Mandan `docs/00_enunciado.md` (qué se evalúa) y `docs/03_contratos_modulos.md` (cómo encajan las piezas).
> Mantener este fichero corto: el detalle vive en `docs/`.

## Qué es

Práctica MIAX **Taller B5-T4**: MVP de una startup FinTech con IA multimodal. Grupo de 3.
**Entrega: jueves 8-oct-2026, 18:00** (repo GitHub con MVP funcional + demo).

**Briefly** (antes «Market Briefer»; eslogan «El cierre del día, mientras vuelves a casa»): cada día, al cierre,
recoge noticias de mercado filtradas por los tickers/cartera del usuario, las interpreta (Agente Analista),
escribe un diálogo (Agente Guionista) y genera un **podcast a 2 voces** (locutores **Toro** y **Osa**, voces
sintéticas) con transcripción, gráficos del día y, si da tiempo, **vídeo corto**. Además lee capturas de gráficos
y PDFs de resultados, y responde preguntas por voz (Agente Q&A). Entrega por web y Telegram.
Diagrama de la idea: `docs/assets/arquitectura_mvp_podcast_financiero.png`. Marca: `docs/08_identidad_marca.md`;
los textos visibles salen de `src/briefer/brand.py`. **Los nombres internos no cambian**: paquete `briefer`,
repo `multimodal-market-briefer`, variables `BRIEFER_*`, servicio de Docker.

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
| LLM (analista, guionista, Q&A) | Anthropic Claude (Sonnet 5.5 analista; Haiku 4.5 guionista y Q&A; ADR-006) | Gemini, mock; `BRIEFER_SCRIPTWRITER_MODEL` |
| Visión (gráficos, páginas PDF, captura de cartera) | Claude visión (cartera: visión transcribe → Haiku estructura) | mock |
| Router de imágenes subidas | CLIP local `clip-vit-base-patch32` (`BRIEFER_IMAGE_CLASSIFIER_PROVIDER=clip`): no financiera → rechazada sin visión | none, mock |
| STT | OpenAI API (`gpt-4o-mini-transcribe`; `whisper-1` por config) | mock |
| TTS 2 voces | `edge-tts` (gratis, por defecto: Álvaro/Ximena +10 %) · Gemini 3.8 TTS multi-locutor (premium, demo; Q&A siempre edge) | mock |
| Tono de noticias (opcional) | Haiku traduce → FinBERT local (`BRIEFER_FINBERT`, PR #1 de Daniel) | desactivado |
| Noticias/precios | `yfinance` + RSS (`feedparser`) | `data/samples/` |
| Gráficos / vídeo | matplotlib / vídeo 9:16 con Pillow (diapositivas) + ffmpeg de `imageio-ffmpeg` (concat + subtítulos ASS), sin moviepy | — |
| Portada (opcional) | Local y gratis: SDXS `IDKiro/sdxs-512-dreamshaper` en CPU (`BRIEFER_IMAGE_GEN_PROVIDER=local`, alias `sdxl_turbo`; diffusers, 1 paso, OpenRAIL++) | Gemini imagen (`gemini`, de pago, exige facturación), none, mock |
| Entrega | web · Telegram Bot API (verificado en real) | — |
| Config | `.env` → `src/briefer/config.py` | — |

## Mapa del repo

```
app/                      UI Streamlit (solo presentación; llama a briefer.pipeline)
src/briefer/schemas.py    CONTRATOS Pydantic entre módulos  ← no cambiar sin acordarlo entre los 3
src/briefer/pipeline.py   orquestación: run_briefing(), answer_question()
src/briefer/brand.py      marca visible (Briefly, eslogan, locutores): fuente única, no repetir textos
src/briefer/providers/    capa IA: base.py (interfaces), registry.py, mock.py, llm/ vision/ stt/ tts/ image/
src/briefer/ingest/       entradas y procesado (noticias, tickers, precios, PDF, gráfico, cartera, voz, FinBERT)
src/briefer/agents/       analista, guionista, Q&A (+ prompts/*.md)
src/briefer/media/        gráficos, podcast, transcripción, vídeo, portada
src/briefer/delivery/     Telegram
tests/                    sin red, con providers mock y fixtures (+ tests "live" marcados, excluidos por defecto)
scripts/                  run.ps1 · run.sh · demo.py · smoke_real.py
data/samples/             ejemplos versionados + demo_briefing/ (pregenerado) · data/cache, data/outputs ignorados
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
   app, guion y audio; citar la fuente de cada noticia (extracto ≤ 200 caracteres, nunca el cuerpo); avisar de
   que la voz es sintética.
   - **Privacidad de la cartera** (ADR-005): nunca se escribe en disco (`briefing.json` con `portfolio: null`,
     sin gráfico de cartera en `data/`); al LLM solo van tickers y pesos, en memoria.
   - **Secretos**: ningún error, `StepMetric`, log ni texto de la UI lleva claves o tokens; usar
     `logging_utils.error_text` / `redact_secrets` en vez de `str(exc)`.
5. No versionar `docs/raw/`, `.env`, ni salidas generadas (`data/outputs/`, audios, vídeos).
6. Nunca copiar literal el material de clase a ficheros versionados: resumir.
7. Números de coste/latencia: o medidos (y se dice cómo) o marcados como estimación.
8. **Git**: commits en español, sin ninguna mención a IA/Claude (sin `Co-Authored-By` ni pies generados).
   `git pull --rebase` antes de empezar y antes de subir.
9. Al cerrar una sesión: actualizar `docs/06_estado_actual.md` y marcar checkboxes en `docs/05_roadmap_TODO.md`.

## Comandos

```bash
scripts/run.sh [--expose]             # Linux/macOS: venv + deps + streamlit en localhost:8501
scripts/run.ps1 [-Expose]             # Windows (-Expose / --expose: visible en la red local)
docker compose up --build             # contenedor con modelos locales (LOCAL_MODELS=true), http://localhost:8501 (build sin verificar)
python -m pytest -q                   # tests sin red (mock/fixtures); los "live" (red + claves + coste) con -m live
python scripts/demo.py --mock         # briefing de punta a punta por CLI, todo mock (sin red)
python scripts/demo.py --demo-voices  # sin claves: datos de ejemplo + LLM mock + edge-tts real (necesita red)
python scripts/demo.py [--refresh]    # modo real con claves de .env (--refresh ignora la caché diaria)
python scripts/demo.py --question "…" --briefing pregenerado --warmup   # Q&A por CLI (salida 0/1/2/3/130)
python scripts/smoke_real.py          # humo real y barato de cada proveedor con clave (< 0,01 €)
python scripts/evaluar_briefings.py   # evaluación de briefings (notebooks/eval/); --real genera y juzga (gasta)
python scripts/telegram_setup.py [--write] [--test]   # bot de Telegram: lista chats, escribe TELEGRAM_CHAT_ID, prueba
```

Modos del pipeline: `run_briefing(..., mode="real"|"mock"|"demo_voices", use_cache=True)` (ver
`docs/03_contratos_modulos.md`). Las llamadas reales cuestan dinero (≈ 0,065 € por briefing con PDF + gráfico):
para iterar, caché diaria o modo mock. `data/samples/demo_briefing/` es el briefing real pregenerado de la
portada: no se edita a mano (se regenera con `storage.export_briefing`).
