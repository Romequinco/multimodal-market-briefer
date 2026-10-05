# Documentación de Briefly

Índice operativo del proyecto. **Briefly** es la marca visible (eslogan: «El cierre del día, mientras vuelves a
casa»); el código y el repositorio conservan los nombres técnicos `briefer` / `multimodal-market-briefer`. La guía
de marca está en [08_identidad_marca.md](08_identidad_marca.md). El enunciado y la rúbrica están en [00_enunciado.md](00_enunciado.md); los
contratos que permiten trabajar en paralelo, en [03_contratos_modulos.md](03_contratos_modulos.md); el estado
vivo, en [06_estado_actual.md](06_estado_actual.md).

## Estado a 05-oct-2026 (cierre de la revisión de las Fases 0 y 1)

Núcleo real fin a fin funcionando (UI y CLI) y reforzado por una revisión completa con auditoría: noticias
(Google News, Bing News, Yahoo, prensa) con URL del medio y extracto ≤ 200 caracteres, precios reales con caché,
Claude Sonnet 5.5 (Analista y visión) y Haiku 4.5 (Guionista con puertas deterministas y Q&A), **Q&A por voz real**
(Whisper API), edge-tts con `loudnorm`, fallback marcado, *grounding*, cartera no persistida, secretos
redactados, briefing real pregenerado en la portada y modos real / demo sin claves / mock. Medido: 0,066 € y
82,9 s por briefing con PDF + gráfico (sin caché); Q&A ≈ 0,005 € y 5,2 s con voz en frío. Contratos v0.3.1.
Pendiente: vídeo, portada, CLIP, envíos, captura de cartera, Docker probado.
Entrega: **8-oct-2026, 18:00** (objetivo interno 16:30).

| Bloque | Evidencia actual | Estado |
| --- | --- | --- |
| Idea y diagrama | `assets/arquitectura_mvp_podcast_financiero.png`, [01](01_producto_y_propuesta_valor.md) | Hecho |
| Stack y decisiones | [ADR-001](decisiones/ADR-001-stack-mvp.md) a [ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md) | Hecho |
| Contratos (`schemas.py`, `providers/base.py`) | [03](03_contratos_modulos.md) v0.3.1 | Hecho; solo cambios aditivos |
| Carril A · entradas, visión y Telegram | `src/briefer/ingest/`, `providers/vision/`, `providers/stt/` | Noticias (con Bing News, URL del medio y extractos), precios, caché, PDF, gráfico y **STT (Whisper API)** reales hechos; CLIP, captura de cartera y Telegram pendientes (D2) |
| Carril B · agentes, orquestación y calidad | `src/briefer/agents/`, `pipeline.py`, `providers/llm/` | Agentes reales con Claude, *grounding* en Analista y Guionista, red-team, `warmup` del Q&A (5,2 s con voz en frío), fallback marcado, paralelismo y CI hechos; p50/p95 pendiente (camino 1) |
| Carril C · media, UI y demo | `src/briefer/media/`, `delivery/`, `app/` | edge-tts con `loudnorm`, normalización para voz, gráficos con «Índices de referencia», modos, pregenerado nuevo, «Cómo se hizo» y controles pendientes desactivados hechos; vídeo, portada y envíos pendientes (D2) |
| Plug-and-play (scripts, Docker) | `scripts/`, `Dockerfile`, `.streamlit/config.toml`, `.github/workflows/tests.yml` | `run.ps1` probado y endurecido, CI en verde (3.11 y 3.13), `pip-audit` limpio; Docker endurecido pero **sin probar**; `run.sh` sin probar |
| Viabilidad y compliance | [04](04_viabilidad_costes_latencia_compliance.md) | Costes y latencias **medidos** (4 briefings, 7 preguntas, STT); cartera no persistida ([ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md)); costes fijos y p50/p95 pendientes |
| Revisión y mejora en paralelo | [05 · caminos](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2) | Caminos 3, 4 y 5 cubiertos en gran parte; se recomiendan **1, 2 y 6** |
| Identidad de marca | [08](08_identidad_marca.md), `src/briefer/brand.py`, `assets/marca/` | Decisiones cerradas (Briefly, Toro y Osa, edición de noche, logo de velas-ecualizador); guía de marca completa |
| README con capturas, demo, pitch | `README.md`, `pitch/` | README al día (estado, modos, mediciones, privacidad); capturas, demo y pitch pendientes (D3) |

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
7. [08 · Identidad de marca](08_identidad_marca.md): nombre, tono, locutores, logo, colores y tipografía (antes de
   tocar textos visibles, el pitch o las capturas).

### Para un asistente de código

Leer en este orden antes de tocar nada:

1. [03 · Contratos](03_contratos_modulos.md): firmas y schemas son vinculantes; no cambiarlos sin acuerdo.
2. [02 · Arquitectura](02_arquitectura_y_flujo_datos.md): capa en la que vive cada cosa.
3. [06 · Estado](06_estado_actual.md): qué está hecho y qué bloquea.
4. [05 · Roadmap](05_roadmap_TODO.md): la tarea concreta, su fichero y su criterio de hecho.
5. [Decisiones](decisiones/README.md): por qué el stack es el que es ([ADR-003](decisiones/ADR-003-tolerancia-fallos-y-contratos-v02.md): pasos núcleo/opcionales; [ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md): la cartera no se persiste).
6. [07 · Revisión crítica](07_revision_critica.md), solo si la tarea toca prioridades o alcance (MoSCoW y orden de recortes ya están en 05).
7. [08 · Identidad de marca](08_identidad_marca.md), si la tarea toca textos visibles: nombre, eslogan y locutores
   se leen de `src/briefer/brand.py`, nunca se repiten a mano.

Reglas: no ejecutar git, no versionar `.env`, no copiar material de clase literal, todo debe funcionar en modo
`mock` sin claves, la cartera no se escribe en disco y ningún error, métrica o log lleva claves sin redactar.

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
| [08_identidad_marca.md](08_identidad_marca.md) | Guía de marca: decisiones, logo y variantes, colores con contrastes, tipografía, tono, locutores, formatos |
| [decisiones/](decisiones/README.md) | ADRs |
| [clase/00_indice.md](clase/00_indice.md) | Resumen del material del taller |
| [assets/](assets/) | Diagramas y capturas; [assets/marca/](assets/marca/) con logo, icono, banner y fuentes |
