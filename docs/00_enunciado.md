# 00 · Enunciado

Transcripción estructurada del enunciado del taller (fuente: `docs/raw/text/enunciado.txt`) y checklist de
rúbrica con el lugar del repo donde se cubre cada punto.

## Datos básicos

| Campo | Valor |
| --- | --- |
| Taller | B5-T4 · Diseño y prototipado de una startup FinTech basada en IA multimodal |
| Modalidad | Grupos de 3 estudiantes |
| Entrega | Aula virtual, **8-oct-2026 a las 18:00** |
| Entregable | Repositorio en GitHub con el código fuente del MVP funcional |

## 1. Objetivo

Concebir, diseñar e implementar un **MVP** de una startup FinTech cuyo producto central sea una aplicación
interactiva impulsada por **modelos de IA multimodal**. Se pide una visión que una negocio (propuesta de valor,
viabilidad, necesidad real de mercado) con ingeniería capaz de **orquestar varios modelos** (lenguaje, visión,
audio/voz, generación multimodal) dentro de una aplicación usable, coherente e intuitiva.

## 2. Contexto

El sector financiero maneja información dispersa y heterogénea: informes en PDF, gráficos de velas y series
temporales, conferencias de resultados en audio, vídeos de opinión, prensa y datos tabulares. Los modelos
fundacionales multimodales abren la puerta a reinventar servicios, pero un producto FinTech no es conectar una
API de chat: hay que articular **flujos multimodales** donde varias modalidades de entrada y salida colaboren
para aportar valor diferencial de forma ágil y viable.

## 3. Entorno técnico

Se admite cualquier combinación de modelos abiertos (Hugging Face, vLLM, Ollama), APIs comerciales (OpenAI,
Anthropic, Gemini, Mistral, ElevenLabs, Whisper…) o modelos propios. Modalidades de referencia:

| Modalidad | Ejemplos del enunciado |
| --- | --- |
| Texto → texto | Razonamiento financiero, síntesis de noticias, análisis regulatorio, asesoramiento conversacional |
| Imagen/documento → texto | Extracción de balances, gráficos de cotizaciones, facturas, tickets, documentos oficiales |
| Texto → imagen | Infografías personalizadas, diagramas de cartera, representación visual del riesgo |
| Audio → texto | Transcripción de llamadas, juntas de accionistas, comandos de voz |
| Texto → audio | Agentes de voz, resúmenes diarios por audio, **podcasts financieros automatizados** |
| Cruzadas / búsqueda multimodal | Embeddings tipo CLIP, análisis de vídeo de webinars, reportes multimedia automatizados |

## 4. Tarea

### 4.1 Idea y propuesta de valor

- **Definición esquemática del producto:** esquema visual y descriptivo del problema, público objetivo
  (B2C, B2B o B2B2C) y propuesta de valor diferencial de la multimodalidad.
- **Viabilidad técnica y económica:** costes de inferencia y APIs, latencias para una UX fluida, marco
  regulatorio (compliance, privacidad de datos bancarios) y modelo de monetización.

### 4.2 Riqueza multimodal y orquestación

- **Diversidad de modalidades:** más modalidades de entrada y salida integradas con sentido = más nota.
- **Orquestación multi-modelo:** puntúa más encadenar modelos especializados que llamar a un único modelo.

### 4.3 MVP y usabilidad

- **MVP ejecutable:** aplicación operativa real.
- **Usabilidad:** diseño de UI, fluidez de UX, claridad de navegación y robustez.
- **Plug-and-play:** scripts de arranque directo y dependencias completas (`requirements.txt` o `Dockerfile`).

### 4.4 Repositorio y documentación

- **README y pitch deck técnico:** README exhaustivo con capturas, diagrama de flujo de datos multimodal y
  descripción de la arquitectura.
- **Calidad y modularidad:** separación limpia entre conexión con modelos, lógica de negocio e interfaz.

## 5. Entregables

1. **Repositorio de GitHub** con el código completo del MVP, bien organizado.
2. **Demostración funcional:** app desplegada en la nube o demo grabada/en vivo que muestre la usabilidad y la
   integración real de las modalidades.

---

## Checklist de rúbrica → repo

**Estado final** (mié 7-oct-2026, entrega `v1.0`: fases 0-3 cerradas, UI rediseñada y **app desplegada en la nube** en
<https://multimodal-market-briefer-production.up.railway.app/>, rama `entrega-v1`, que sustituye a la demo grabada). Se actualiza en
[06_estado_actual.md](06_estado_actual.md); el análisis de huecos por criterio está en
[07 §5](07_revision_critica.md#5-checklist-de-rúbrica--evidencia-que-verá-el-evaluador).
Leyenda: **Hecho** · **Parcial** (existe, falta lo que se pide) · **Pendiente**.

| # | Criterio | Dónde se cubre | Estado | Hueco a cerrar (fase) |
| --- | --- | --- | --- | --- |
| R1 | Esquema visual del producto | `docs/assets/arquitectura_mvp_podcast_financiero.png`, mermaid en `README.md` y [01](01_producto_y_propuesta_valor.md) | Hecho | — |
| R2 | Problema, público (B2C/B2B/B2B2C), valor de la multimodalidad | [01](01_producto_y_propuesta_valor.md), `README.md`, diapositivas del pitch | Hecho | — |
| R3 | Costes de inferencia y APIs | [04](04_viabilidad_costes_latencia_compliance.md) con columnas «Medido», `costs.py` (tarifas Anthropic verificadas 05-oct; STT y caché de prompts), `StepMetric.est_cost_eur` por paso, `costs.format_cost_summary` | Hecho (medido) | Fase 2: N = 6 briefings reales, coste p50 0,0337 € / p95 0,0620 € (0,0691 € con PDF + gráfico); ≈ 0,005 € por pregunta (7 medidas); costes fijos ≈ 1.070 €/mes (B2C) / ≈ 3.700 €/mes (B2B2C) y punto de equilibrio en 04. Contraste con la consola revisado a ojo el 06-oct: cuadra aproximadamente |
| R4 | Latencias para UX fluida | [04](04_viabilidad_costes_latencia_compliance.md), `Briefing.metrics` y `QAAnswer.metrics` visibles en la UI y en «Cómo se hizo»; `pipeline.warmup`, texto antes que audio | Hecho (medido) | Fase 2: briefing p50 **52,7 s** / p95 **68,2 s** (N = 6, `notebooks/eval/resumen.md`); Q&A con voz p50 6,4 s en frío y 6,0 s en caliente; STT 1,3 s |
| R5 | Compliance y privacidad | [04](04_viabilidad_costes_latencia_compliance.md) (tabla riesgo → control en código), `DISCLAIMER_ES`, `agents/guardrails.py` (recomendaciones, *grounding* en Analista y Guionista, inyección), red-team (`tests/test_agents_redteam.py`), cierre hablado y metadatos ID3 de voz sintética (AI Act), extractos ≤ 200 caracteres en origen y `robots.txt`, **cartera no persistida** ([ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md)), audio de la pregunta y subidas borrados, secretos redactados, MAR («impacto de la noticia» por noticia, nunca por valor), transferencias RGPD, rótulos de IA en vídeo, portada y Telegram | Hecho | Causas sin fuente en el Q&A: se matizan, no se bloquean |
| R6 | Monetización | [01](01_producto_y_propuesta_valor.md), [04](04_viabilidad_costes_latencia_compliance.md) (recalculada con costes medidos), costes fijos ≈ 1.070 / 3.700 €/mes, planes y punto de equilibrio B2C y B2B2C | Hecho | — |
| R7 | Diversidad de modalidades | Tabla de modalidades en `README.md` con columna «Activo en la demo» | Hecho | Todas verificadas en real: texto→texto (3 agentes), imagen→texto, imagen→datos (cartera desde captura), documento→texto, imagen→etiqueta (router CLIP local), audio→texto (STT), texto→audio (2 voces), texto→etiqueta (FinBERT), datos→imagen, subtítulos, verificación del podcast por STT, texto→imagen (portada SDXS local), imagen+audio→vídeo y entrega por Telegram (verificado el 06-oct). Email retirado (decisión de producto) |
| R8 | Encadenamiento multi-modelo | `pipeline.py` (pasos núcleo/opcionales, paralelismo, fallback marcado), puertas de *grounding* con reintento, pestaña «Cómo se hizo» (`app/components/trace.py`) | Hecho (real) | Cadenas reales: **CLIP local (router) →** Sonnet visión → Haiku (estructura) → Sonnet (Analista) → Haiku (Guionista) → edge-tts → STT (WER del podcast) → SDXS local (portada) → Pillow + ffmpeg (vídeo); cartera: Sonnet visión → Haiku → mapeo determinista; voz → Whisper → Haiku (Q&A) → edge-tts; Haiku → FinBERT. La decisión del router queda en la traza. Cuaderno de recorrido `notebooks/00_recorrido_pipeline.ipynb` (15 pasos, mock); modelo por agente elegido con evidencia ([ADR-007](decisiones/ADR-007-modelos-por-agente.md)) |
| R9 | MVP ejecutable | `app/`, `scripts/demo.py`, `scripts/smoke_real.py`; modos real / demo sin claves / mock; Q&A por voz real | Hecho | — |
| R10 | UI / UX / navegación / robustez | UI rediseñada el 07-oct: **3 vistas sin barra lateral** (Hoy · Preguntar · Archivo), «Hoy» con el briefing del día sin pulsar nada, diálogo «Nuevo briefing» (buscador de **169 activos** validados + búsqueda en Yahoo Finance, cartera, documentos, opciones), chat de voz y texto en una sola barra, chip del modo con insignias de proveedores, avisos de fallback, traza «Cómo se hizo»; doble clic protegido; errores redactados; contraste ≥ 4,5:1 con test; tolerancia a fallos ([ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md)) | Hecho | 8 capturas rehechas tras el rediseño en `README.md#capturas`; prueba con usuarios fuera de alcance |
| R11 | Plug-and-play | `requirements.txt` + `pip install -e .` verificados (Python 3.13, venv limpio, `pip-audit` limpio); **CI en verde en GitHub** (3.11 y 3.13); `scripts/run.ps1` probado desde un clon limpio (app en 220 s); `Dockerfile` no root con *healthcheck* verificado (contenedor *healthy* en 10 s, briefing real dentro: 114 s, 0,061 €); **desplegado en Railway** con la misma imagen (`railway.json`, puerto `$PORT`, modo Real con contraseña; [09](09_despliegue_railway.md)) | Hecho | Solo queda `run.sh` verificado de punta a punta en Linux/macOS (la prueba se cortó por red lenta; el contenedor Linux sí funciona) |
| R12 | README exhaustivo con capturas | `README.md` reescrito para la entrega: URL de la app desplegada arriba, enlace al pitch e insignia de CI, «Arranca en 2 comandos», 8 capturas de la UI nueva (`docs/assets/capturas/`), modalidades, diagramas de flujo y orquestación, arquitectura, mediciones, viabilidad, compliance y configuración en anexos | Hecho | — |
| R13 | Diagrama de flujo multimodal | `README.md` (flujo multimodal y **diagrama de orquestación** con ramas, decisiones y sustitutos), [02](02_arquitectura_y_flujo_datos.md), grafo «Cómo se hizo» generado por briefing, pitch | Hecho | — |
| R14 | Descripción de arquitectura | `README.md`, [02](02_arquitectura_y_flujo_datos.md), [ADRs](decisiones/README.md) (001-007) | Hecho | — |
| R15 | Pitch deck técnico | `pitch/pitch_briefly.pdf` final (7 diapositivas, pensado para acompañar la demo en vivo; fuente `pitch/pitch_briefly.html`, `scripts/build_pitch.py --demo-url`): equipo completo, URL y QR de la app desplegada en la diapositiva de demo y cierre | Hecho | — |
| R16 | Separación modelos / negocio / UI | `providers/` (nuevos `image/clip_classifier.py`, `image/gemini_image.py`; `image/sdxl_turbo.py` ya implementado: portada local) · `ingest/agents/media/delivery` · `app/` (la sección «Tu cartera» del diálogo «Nuevo briefing» lee la captura solo vía `pipeline.portfolio_from_screenshot`); inyección de dependencias; **1225 tests sin red** + 13 `live`, ruff + mypy en la CI; *stubs* retirados (v0.3.9) | Hecho | — |
| R17 | Demo funcional | **App desplegada en la nube**: <https://multimodal-market-briefer-production.up.railway.app/> (Railway, rama `entrega-v1`, versión `v1.0`): abre en modo demo sin claves con el briefing real pregenerado; el modo Real (datos de hoy) pide una contraseña que el equipo da aparte. Guion para presentarla en vivo en `pitch/demo_guion.md` | Hecho | La app desplegada sustituye a la demo grabada (el enunciado admite cualquiera de las dos) |
