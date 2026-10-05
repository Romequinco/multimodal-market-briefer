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

Estado al cierre de la Fase 0 (05-oct-2026, noche). Se actualiza en [06_estado_actual.md](06_estado_actual.md);
el análisis de huecos por criterio está en [07 §5](07_revision_critica.md#5-checklist-de-rúbrica--evidencia-que-verá-el-evaluador).
Leyenda: **Hecho** · **Parcial** (existe, falta lo que se pide) · **Pendiente**.

| # | Criterio | Dónde se cubre | Estado | Hueco a cerrar (fase) |
| --- | --- | --- | --- | --- |
| R1 | Esquema visual del producto | `docs/assets/arquitectura_mvp_podcast_financiero.png`, mermaid en `README.md` y [01](01_producto_y_propuesta_valor.md) | Hecho | — |
| R2 | Problema, público (B2C/B2B/B2B2C), valor de la multimodalidad | [01](01_producto_y_propuesta_valor.md), `README.md` | Hecho (borrador) | Una diapositiva del pitch; B2B2C como motor principal (D3) |
| R3 | Costes de inferencia y APIs | [04](04_viabilidad_costes_latencia_compliance.md), `costs.py`, `StepMetric.est_cost_eur` por paso | Parcial | Tarifas verificadas con fecha, coste **medido** por briefing, costes fijos de datos/licencias (D2-D3) |
| R4 | Latencias para UX fluida | [04](04_viabilidad_costes_latencia_compliance.md), `StepMetric` en `Briefing.metrics` y `QAAnswer.metrics` | Pendiente (NO MEDIDO) | p50/p95 medidos de briefing y Q&A, visibles en la UI (D2-D3) |
| R5 | Compliance y privacidad | [04](04_viabilidad_costes_latencia_compliance.md), `DISCLAIMER_ES`, `agents/guardrails.py`, cierre hablado del Guionista | Parcial | MAR, AI Act art. 50, transferencias RGPD; borrado del audio de la pregunta y consentimiento en la UI (D2) |
| R6 | Monetización | [01](01_producto_y_propuesta_valor.md), [04](04_viabilidad_costes_latencia_compliance.md) | Parcial | Costes fijos y punto de equilibrio (D2) |
| R7 | Diversidad de modalidades | Tabla de modalidades en `README.md` | Parcial (prometido > demostrado) | Texto→imagen por API, captura de cartera, columna «Activo en la demo» (D2-D3) |
| R8 | Encadenamiento multi-modelo | `pipeline.py` (pasos núcleo/opcionales, métricas por paso) | Parcial (lineal; solo mock) | Proveedores reales (D1); router CLIP, puertas de calidad, WER, traza «Cómo se hizo» (D2) |
| R9 | MVP ejecutable | `app/`, `scripts/demo.py` | Parcial: completo en modo mock | Núcleo real fin a fin (D1) |
| R10 | UI / UX / navegación / robustez | `app/` multipágina en modo demo; tolerancia a fallos por paso ([ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md)) | Parcial | Portada de 30 s, modos e insignias, fallback núcleo → mock, pregenerado (D1-D2) |
| R11 | Plug-and-play | `requirements.txt` + `pip install -e .` verificados (Python 3.13, venv limpio); `Dockerfile`, `docker-compose.yml`, `scripts/run.ps1`, `scripts/run.sh` | Parcial | Docker y scripts en clon limpio (D2 Sync 4, D3) |
| R12 | README exhaustivo con capturas | `README.md` | Parcial | Capturas, enlace a la demo arriba, resultados medidos, configuración a un anexo (D3) |
| R13 | Diagrama de flujo multimodal | `README.md`, [02](02_arquitectura_y_flujo_datos.md) | Hecho | Diagrama de **orquestación** con ramas y decisiones (D3) |
| R14 | Descripción de arquitectura | `README.md`, [02](02_arquitectura_y_flujo_datos.md), [ADRs](decisiones/README.md) | Hecho | — |
| R15 | Pitch deck técnico | `pitch/` | Pendiente | PDF de 10-12 diapositivas (D2 esqueleto, D3) |
| R16 | Separación modelos / negocio / UI | `providers/` · `ingest/agents/media/delivery` · `app/`; inyección de dependencias; tests sin red | Hecho | Retirar *stubs* no implementados del registry (D3) |
| R17 | Demo funcional | Vídeo enlazado en `README.md#demo` | Pendiente | Demo grabada de 3-4 min + pregenerado (D3) |
