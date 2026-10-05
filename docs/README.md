# Documentación de Market Briefer

Índice operativo del proyecto. El enunciado y la rúbrica están en [00_enunciado.md](00_enunciado.md); los
contratos que permiten trabajar en paralelo, en [03_contratos_modulos.md](03_contratos_modulos.md); el estado
vivo, en [06_estado_actual.md](06_estado_actual.md).

## Estado a 05-oct-2026 (cierre de la Fase 1, camino real)

Núcleo real fin a fin funcionando (UI y CLI): noticias y precios reales con caché, Claude Sonnet 5.5 (Analista y
visión) y Haiku 4.5 (Guionista y Q&A), edge-tts, fallback marcado, *grounding*, briefing real pregenerado en la
portada y modos real / demo sin claves / mock. Medido: ≈ 0,065 € y ≈ 62 s por briefing con PDF + gráfico; Q&A
≈ 0,005 € y 6-13 s. Contratos v0.3. Pendiente: Whisper (STT), Q&A < 10 s en frío, vídeo, portada, envíos.
Entrega: **8-oct-2026, 18:00** (objetivo interno 16:30).

| Bloque | Evidencia actual | Estado |
| --- | --- | --- |
| Idea y diagrama | `assets/arquitectura_mvp_podcast_financiero.png`, [01](01_producto_y_propuesta_valor.md) | Hecho |
| Stack y decisiones | [ADR-001](decisiones/ADR-001-stack-mvp.md) a [ADR-004](decisiones/ADR-004-salida-estructurada-json-schema.md) | Hecho |
| Contratos (`schemas.py`, `providers/base.py`) | [03](03_contratos_modulos.md) v0.3 | Hecho; solo cambios aditivos |
| Carril A · entradas, visión y Telegram | `src/briefer/ingest/`, `providers/vision/` | Noticias, precios, caché, PDF y gráfico reales hechos; STT (Whisper), CLIP, captura de cartera y Telegram pendientes (D2) |
| Carril B · agentes, orquestación y calidad | `src/briefer/agents/`, `pipeline.py`, `providers/llm/` | Agentes reales con Claude, *grounding*, fallback marcado, paralelismo, CI hechos; latencia del Q&A en frío y calidad del Guionista (D2) |
| Carril C · media, UI y demo | `src/briefer/media/`, `delivery/`, `app/` | edge-tts real, normalización para voz, modos, pregenerado, «Cómo se hizo» hechos; vídeo, portada y email pendientes (D2) |
| Plug-and-play (scripts, Docker) | `scripts/`, `Dockerfile`, `.github/workflows/tests.yml` | Instalación limpia y CI; clon limpio y Docker pendientes |
| Viabilidad y compliance | [04](04_viabilidad_costes_latencia_compliance.md) | Costes y latencias **medidos** (3 briefings, 4 preguntas); costes fijos y p50/p95 pendientes |
| Revisión y mejora en paralelo | [05 · caminos](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2) | 6 caminos abiertos para cualquiera (rama propia + PR) |
| README con capturas, demo, pitch | `README.md`, `pitch/` | README al día (estado, modos, mediciones); capturas, demo y pitch pendientes (D3) |

Convenciones:

- Identificadores de código en inglés; docstrings, comentarios y documentación en español.
- Todo número de coste o latencia es **estimación** hasta que se mida con `StepMetric`; se marca así.
- `schemas.py` y `providers/base.py` solo cambian por acuerdo de los tres (ver [03](03_contratos_modulos.md#reglas-de-cambio)).
- El material de clase vive en `raw/` (no versionado); en `clase/` solo hay resúmenes propios.

## Ruta de lectura

### Para una persona del equipo

1. [00 · Enunciado](00_enunciado.md): qué nos piden y la checklist de rúbrica.
2. [01 · Producto](01_producto_y_propuesta_valor.md): qué construimos y para quién.
3. [02 · Arquitectura](02_arquitectura_y_flujo_datos.md): cómo fluye la información.
4. [03 · Contratos](03_contratos_modulos.md): qué consume y produce tu carril.
5. [05 · Roadmap](05_roadmap_TODO.md) y [06 · Estado](06_estado_actual.md): qué toca hacer hoy.
6. [07 · Revisión crítica](07_revision_critica.md): por qué el plan es el que es (hallazgos, MoSCoW, horarios).

### Para un asistente de código

Leer en este orden antes de tocar nada:

1. [03 · Contratos](03_contratos_modulos.md): firmas y schemas son vinculantes; no cambiarlos sin acuerdo.
2. [02 · Arquitectura](02_arquitectura_y_flujo_datos.md): capa en la que vive cada cosa.
3. [06 · Estado](06_estado_actual.md): qué está hecho y qué bloquea.
4. [05 · Roadmap](05_roadmap_TODO.md): la tarea concreta, su fichero y su criterio de hecho.
5. [Decisiones](decisiones/README.md): por qué el stack es el que es (y [ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md): pasos núcleo/opcionales).
6. [07 · Revisión crítica](07_revision_critica.md), solo si la tarea toca prioridades o alcance (MoSCoW y orden de recortes ya están en 05).

Reglas: no ejecutar git, no versionar `.env`, no copiar material de clase literal, todo debe funcionar en modo
`mock` sin claves.

## Mapa de documentos

| Documento | Función |
| --- | --- |
| [00_enunciado.md](00_enunciado.md) | Enunciado estructurado y checklist rúbrica → repo |
| [01_producto_y_propuesta_valor.md](01_producto_y_propuesta_valor.md) | Problema, público, valor, competencia, monetización, métricas |
| [02_arquitectura_y_flujo_datos.md](02_arquitectura_y_flujo_datos.md) | Capas, componentes, secuencias, cadena de modelos, almacenamiento |
| [03_contratos_modulos.md](03_contratos_modulos.md) | Schemas, interfaces de providers, funciones públicas, carriles |
| [04_viabilidad_costes_latencia_compliance.md](04_viabilidad_costes_latencia_compliance.md) | Costes, latencias, regulación, monetización con números |
| [05_roadmap_TODO.md](05_roadmap_TODO.md) | Tareas por fase y carril hasta la entrega |
| [06_estado_actual.md](06_estado_actual.md) | Estado vivo |
| [07_revision_critica.md](07_revision_critica.md) | Revisión crítica del plan (05-oct): hallazgos, MoSCoW, plan por fases, checklist de rúbrica |
| [decisiones/](decisiones/README.md) | ADRs |
| [clase/00_indice.md](clase/00_indice.md) | Resumen del material del taller |
| [assets/](assets/) | Diagramas y capturas |
