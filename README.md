# Market Briefer

**Tu podcast diario de mercados, hecho a medida de tu cartera.**

Market Briefer es el MVP de una startup FinTech de IA multimodal (práctica MIAX, taller B5-T4). Cada día
recoge las noticias de mercado relevantes para los tickers que sigue el usuario, las interpreta y genera un
**podcast explicativo a dos voces** con su transcripción, los gráficos del día y, opcionalmente, un **vídeo
corto**. El usuario puede además subir una captura de gráfico o un PDF de resultados para que entren en el
análisis, y **preguntar por voz** sobre el briefing a un agente que le responde también por voz.

> **Estado (05-oct-2026):** esqueleto. Estructura, contratos (`schemas.py`), proveedores mock, `registry`,
> configuración, pipeline y UI esbozada funcionan; los módulos de `ingest/`, `agents/`, `media/`, `delivery/` y
> `storage.py` son *stubs* pendientes de implementar. Estado vivo en
> [docs/06_estado_actual.md](docs/06_estado_actual.md).

> **Aviso legal.** Market Briefer genera **información financiera genérica con fines educativos**. No es
> asesoramiento en materia de inversión en el sentido de MiFID II, no tiene en cuenta la situación personal
> del usuario y **no emite recomendaciones de compra o venta**. Las voces del podcast son **sintéticas**,
> generadas por IA. Ver [viabilidad y compliance](docs/04_viabilidad_costes_latencia_compliance.md).

---

## Índice

1. [Problema y propuesta de valor](#problema-y-propuesta-de-valor)
2. [Flujo de datos multimodal](#flujo-de-datos-multimodal)
3. [Modalidades y modelos](#modalidades-y-modelos)
4. [Arquitectura por capas](#arquitectura-por-capas)
5. [Estructura del repositorio](#estructura-del-repositorio)
6. [Arranque rápido](#arranque-rápido)
7. [Configuración](#configuración)
8. [Capturas](#capturas)
9. [Demo](#demo)
10. [Documentación](#documentación)
11. [Equipo](#equipo)

---

## Problema y propuesta de valor

| | |
| --- | --- |
| **Problema** | El inversor minorista recibe la información de mercado dispersa y en formatos heterogéneos: titulares, notas de prensa, PDFs de resultados de 40 páginas, gráficos de velas. Leerlo todo cada día no es realista, y los resúmenes genéricos no hablan de *su* cartera. |
| **Público** | **B2C:** inversor minorista hispanohablante con cartera propia (acciones y ETFs). **B2B2C (canal):** brokers, neobancos y newsletters financieras que quieren ofrecer el briefing con su marca. |
| **Propuesta** | Un briefing diario **personalizado por cartera** que se **escucha** (camino al trabajo, en el gimnasio), se **lee** (transcripción), se **ve** (gráficos y vídeo corto) y se **interroga por voz**. |
| **Por qué multimodal** | Las fuentes ya son multimodales (texto, PDF, imagen de gráfico, voz del usuario) y el consumo también (audio, vídeo, texto, gráficos). Un solo modelo de chat no cubre ese ciclo; una cadena de modelos especializados sí. |

Detalle en [docs/01_producto_y_propuesta_valor.md](docs/01_producto_y_propuesta_valor.md).

---

## Flujo de datos multimodal

![Arquitectura del MVP](docs/assets/arquitectura_mvp_podcast_financiero.png)

El mismo flujo en Mermaid, con el módulo del repo que implementa cada caja:

```mermaid
flowchart LR
    subgraph E["1 · Entradas"]
        N["Noticias de mercado<br/>(yfinance + RSS)"]
        G["Captura de gráfico<br/>(PNG/JPG)"]
        C["Cartera del usuario<br/>(CSV / formulario)"]
        P["PDF de resultados"]
        V["Pregunta por voz<br/>(audio)"]
    end

    subgraph PR["2 · Procesado"]
        FT["Filtro por tickers<br/>ingest/tickers.py"]
        LI["Lectura de imagen<br/>ingest/chart_reader.py"]
        LP["Lectura de PDF<br/>ingest/pdf_reader.py"]
        VT["Voz a texto<br/>ingest/voice.py"]
    end

    subgraph AG["3 · Agentes IA"]
        AN["Agente Analista<br/>resume e interpreta"]
        GU["Agente Guionista<br/>crea el diálogo A/B"]
        QA["Agente Q&A<br/>responde preguntas"]
    end

    subgraph S["4 · Salidas"]
        GD["Gráficos del día<br/>media/charts.py"]
        AU["Audio podcast<br/>2 voces · media/podcast.py"]
        TR["Transcripción + SRT<br/>media/transcript.py"]
        VI["Vídeo corto<br/>media/video.py"]
    end

    subgraph D["5 · Entrega"]
        W["App web<br/>(Streamlit)"]
        EM["Email"]
        TG["Telegram"]
    end

    N --> FT
    G --> LI
    C --> LI
    C -. tickers .-> FT
    P --> LP
    V --> VT

    FT --> AN
    LI --> AN
    LP --> AN
    VT --> QA

    AN --> GU
    AN --> GD
    GU --> AU
    GU --> TR
    QA --> AU

    GD --> VI
    AU --> VI
    AU --> W
    VI --> W
    TR --> EM
    AU --> TG
```

> En el diagrama original la cartera entra por «lectura de imagen» (captura de la cartera del broker). En el
> MVP la cartera también se puede introducir como CSV o formulario; en ambos casos sus tickers alimentan el
> filtro de noticias. El agente Q&A usa como contexto el briefing ya generado.

Arquitectura completa, diagramas de secuencia y mapeo caja → módulo en
[docs/02_arquitectura_y_flujo_datos.md](docs/02_arquitectura_y_flujo_datos.md).

---

## Modalidades y modelos

| # | Modalidad | Dirección | Uso en la app | Modelo / herramienta por defecto | Alternativas (por config) |
| --- | --- | --- | --- | --- | --- |
| 1 | Texto → texto | Entrada → razonamiento | Noticias filtradas → análisis (Agente Analista) | Claude Sonnet (`BRIEFER_LLM_MODEL`) | Gemini, OpenAI, `mock` |
| 2 | Texto → texto | Razonamiento → guion | Análisis → diálogo a dos voces (Agente Guionista) | Claude Sonnet (`BRIEFER_LLM_MODEL`) | Gemini, OpenAI, `mock` |
| 3 | Imagen → texto | Entrada | Captura de gráfico de cotización → descripción y cifras | Claude visión | Qwen2.5-VL-3B local, `mock` |
| 4 | Documento → texto | Entrada | PDF de resultados → cifras clave y resumen | `pypdf` + Claude visión en páginas con poco texto + Claude Haiku (`BRIEFER_LLM_MODEL_CHEAP`) | Qwen2.5-VL local |
| 5 | Imagen → etiqueta | Enrutado | ¿La imagen subida es velas, tabla u otra cosa? (zero-shot) | CLIP *(opcional, desactivado por defecto)* | `none`, `mock` |
| 6 | Audio → texto | Entrada | Pregunta por voz del usuario | Whisper API | `faster-whisper` local, `mock` |
| 7 | Texto → audio | Salida | Podcast a dos voces y respuesta hablada del Q&A | `edge-tts` (gratis, voces es-ES) | ElevenLabs, `mock` |
| 8 | Datos → imagen | Salida | Gráficos del día por ticker | matplotlib | — |
| 9 | Texto → imagen | Salida | Portada del episodio *(opcional, desactivada por defecto)* | SDXL-Turbo | `none`, `mock` |
| 10 | Imagen + audio → vídeo | Salida | Vídeo corto con gráficos, audio y subtítulos *(opcional)* | `moviepy` + ffmpeg | Stable Video Diffusion *(extra, no previsto)* |
| 11 | Audio → texto (subtítulos) | Salida | Transcripción y fichero SRT sincronizado | Derivado del guion + tiempos del TTS | Whisper sobre el audio final |

El Agente Q&A usa el modelo barato (`BRIEFER_LLM_MODEL_CHEAP`, Claude Haiku). Proveedores por defecto según
`.env.example`; en el código, sin `.env`, todo es `mock`.

La gracia no está en cada modelo por separado sino en **encadenarlos**: imagen/PDF/voz → texto estructurado →
análisis → guion → audio → vídeo, con contratos tipados entre cada paso.

---

## Arquitectura por capas

```mermaid
flowchart TB
    UI["<b>UI</b> · app/ (Streamlit multipágina)<br/>Briefing · Preguntar · Mi cartera · Histórico"]
    PL["<b>Orquestación</b> · src/briefer/pipeline.py<br/>run_briefing() · answer_question() · métricas por paso"]
    subgraph BIZ["<b>Lógica de negocio</b> · src/briefer/"]
        ING["ingest/<br/>noticias, precios, PDF,<br/>gráfico, cartera, voz"]
        AGT["agents/<br/>analista, guionista, Q&A<br/>+ prompts/*.md"]
        MED["media/<br/>gráficos, podcast,<br/>transcripción, vídeo, portada"]
        DLV["delivery/<br/>email, Telegram"]
    end
    PRV["<b>Conexión con modelos IA</b> · src/briefer/providers/<br/>LLM · visión · STT · TTS · imagen · mock (registry por config)"]
    X["APIs externas / modelos locales<br/>Anthropic · OpenAI · Gemini · edge-tts · ElevenLabs · Whisper · HF"]

    UI --> PL --> BIZ
    ING --> PRV
    AGT --> PRV
    MED --> PRV
    PRV --> X
```

| Capa | Ubicación | Responsabilidad | No hace |
| --- | --- | --- | --- |
| UI | `app/` | Formularios, reproductores, histórico, subida de ficheros | Llamar a modelos o APIs directamente |
| Orquestación | `src/briefer/pipeline.py` | Resolver proveedores, encadenar pasos, medir latencia y coste (tolerar fallos parciales: previsto) | Lógica de prompts o de formato |
| Negocio | `ingest/`, `agents/`, `media/`, `delivery/` | Transformar datos entre contratos (`schemas.py`); reciben el proveedor por parámetro | Conocer qué proveedor concreto hay detrás |
| Proveedores | `providers/` | Hablar con cada API/modelo detrás de una interfaz común | Lógica de negocio |

Contratos (schemas Pydantic e interfaces) en [docs/03_contratos_modulos.md](docs/03_contratos_modulos.md).

---

## Estructura del repositorio

```text
.
├── app/                         # UI Streamlit (solo presentación; llama a briefer.pipeline / storage)
│   ├── main.py                  # portada y navegación
│   ├── pages/                   # 1_Briefing.py · 2_Preguntar.py · 3_Mi_cartera.py · 4_Historico.py
│   └── components/              # __init__.py (añade src/ al path) · players.py (disclaimer, barra lateral, reproductores)
├── src/briefer/
│   ├── config.py                # Settings desde .env (pydantic-settings)
│   ├── schemas.py               # contratos de datos (Pydantic v2) + DISCLAIMER_ES
│   ├── pipeline.py              # run_briefing() y answer_question()
│   ├── costs.py                 # coste estimado por paso (tarifas aproximadas)
│   ├── logging_utils.py         # logger y track_step() → StepMetric
│   ├── storage.py               # guardar/cargar briefings en data/outputs/
│   ├── providers/               # base.py · registry.py · mock.py · llm/ · vision/ · stt/ · tts/ · image/
│   ├── ingest/                  # news, tickers, prices, pdf_reader, chart_reader, portfolio, voice
│   ├── agents/                  # analyst, scriptwriter, qa + prompts/{analyst,scriptwriter,qa}.md
│   ├── media/                   # charts, podcast, transcript, video, cover
│   └── delivery/                # email_sender, telegram_sender
├── tests/                       # conftest.py · test_schemas.py · test_pipeline_mock.py
├── scripts/                     # run.ps1 · run.sh · demo.py
├── data/samples/                # portfolio_ejemplo.csv · noticias_ejemplo.json · README.md (versionado)
├── data/cache/ data/outputs/    # generados en ejecución (ignorados por git)
├── notebooks/                   # pruebas exploratorias de modelos (README con ideas)
├── pitch/                       # pitch deck técnico (README con el contenido previsto)
├── docs/                        # documentación del proyecto (ver índice)
├── Dockerfile  docker-compose.yml
├── requirements.txt             # dependencias del MVP
├── requirements-local.txt       # opcional: modelos locales (torch, transformers, faster-whisper…)
├── pyproject.toml  .env.example  .gitignore
├── CLAUDE.md                    # contexto para agentes IA
└── README.md
```

---

## Arranque rápido

Requisitos: **Python 3.11+** y **ffmpeg** en el PATH (solo para el vídeo). Con Docker no hace falta nada más.

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run.ps1          # MVP
powershell -ExecutionPolicy Bypass -File scripts\run.ps1 -Local   # + modelos locales (requirements-local.txt)
```

### Linux / macOS

```bash
bash scripts/run.sh            # MVP
bash scripts/run.sh --local    # + modelos locales (requirements-local.txt)
```

Ambos scripts crean `.venv`, instalan `requirements.txt` (y `requirements-local.txt` con `-Local` /
`--local`), copian `.env.example` a `.env` si no existe, fijan `PYTHONPATH=src` y lanzan
`streamlit run app/main.py` en <http://localhost:8501>.

Manualmente: `pip install -r requirements.txt` (o `pip install -e .`, y `pip install -e .[local]` para los
modelos locales) y `streamlit run app/main.py` (`app/components` añade `src/` al path).

### Docker

```bash
docker compose up --build      # http://localhost:8501
```

Requiere **Docker Compose ≥ 2.24** (usa `env_file` con `required: false`: si no hay `.env`, arranca en modo
mock). La imagen incluye ffmpeg pero no los modelos locales; `data/outputs/` y `data/cache/` se montan como
volúmenes.

### Modo mock (sin claves ni red)

Todo el pipeline está pensado para funcionar con proveedores falsos que devuelven datos deterministas. Hay
tres formas de activarlo:

- **UI:** interruptor «Modo demo (mocks, sin red ni claves)» en la barra lateral, **activado por defecto**.
- **CLI:** `python scripts/demo.py --mock`.
- **`.env`:** `BRIEFER_*_PROVIDER=mock` (es también el valor por defecto del código si no hay `.env`).

```bash
python scripts/demo.py --mock                                   # briefing completo con mocks
python scripts/demo.py --mock --question "¿Por qué sube el Santander?"
python scripts/demo.py --tickers SAN.MC AAPL --portfolio data/samples/portfolio_ejemplo.csv
python -m pytest -q                                             # tests sin red
```

Flags de `scripts/demo.py`: `--tickers T [T ...]` (por defecto `BRIEFER_DEFAULT_TICKERS`),
`--portfolio CSV`, `--upload [FICHERO ...]` (PDF, imagen o audio), `--video`, `--cover`,
`--deliver [email|telegram ...]`, `--mock` y `--question TEXTO` (en vez del briefing, pregunta al Agente Q&A).
Mientras `ingest/`, `agents/`, `media/` y `storage` sean *stubs*, `demo.py --mock` termina con
«Pendiente de implementar: …» (código de salida 2).

---

## Configuración

Toda la configuración vive en `.env` (nunca se versiona) y se lee en `src/briefer/config.py`
(pydantic-settings, sin distinguir mayúsculas). Plantilla completa y comentada en `.env.example`.

**Ojo con los valores por defecto:** en el **código** todos los proveedores son `mock` (y `none` para imagen y
clasificador) para que tests y desarrollo funcionen sin red ni claves; **`.env.example` propone el stack real**
del MVP (`anthropic` + `claude` + `whisper_api` + `edge`). La columna «`.env.example`» indica el valor que
queda al copiar la plantilla.

### Proveedores

| Variable | Valores | Código | `.env.example` | Para qué |
| --- | --- | --- | --- | --- |
| `BRIEFER_LLM_PROVIDER` | `anthropic` · `gemini` · `openai` · `mock` | `mock` | `anthropic` | Agentes analista, guionista y Q&A |
| `BRIEFER_VISION_PROVIDER` | `claude` · `qwen_local` · `mock` | `mock` | `claude` | Lectura de gráficos y páginas de PDF |
| `BRIEFER_STT_PROVIDER` | `whisper_api` · `whisper_local` · `mock` | `mock` | `whisper_api` | Pregunta por voz |
| `BRIEFER_TTS_PROVIDER` | `edge` · `elevenlabs` · `mock` | `mock` | `edge` | Podcast y respuesta hablada |
| `BRIEFER_IMAGE_GEN_PROVIDER` | `sdxl_turbo` · `none` · `mock` | `none` | `none` | Portada (opcional) |
| `BRIEFER_IMAGE_CLASSIFIER_PROVIDER` | `clip` · `none` · `mock` | `none` | `none` | Clasificar capturas (opcional) |
| `BRIEFER_FALLBACK_TO_MOCK` | `true` · `false` | `true` | `true` | Si falta clave o librería: mock con aviso (`true`) o `ProviderConfigError` (`false`) |

### Modelos

| Variable | Por defecto (código y `.env.example`) | Para qué |
| --- | --- | --- |
| `BRIEFER_LLM_MODEL` | `claude-sonnet-5-5` | Analista y guionista (Anthropic) |
| `BRIEFER_LLM_MODEL_CHEAP` | `claude-haiku-4-5-20251001` | Q&A y resúmenes de documentos (`get_llm(cheap=True)`) |
| `BRIEFER_GEMINI_MODEL` | `gemini-2.5-flash` | LLM si `BRIEFER_LLM_PROVIDER=gemini` |
| `BRIEFER_OPENAI_MODEL` | `gpt-4o-mini` | LLM si `BRIEFER_LLM_PROVIDER=openai` |
| `BRIEFER_VISION_MODEL` | `claude-sonnet-5-5` | Visión con Claude |
| `BRIEFER_QWEN_VL_MODEL` | `Qwen/Qwen2.5-VL-3B-Instruct` | Visión local |
| `BRIEFER_WHISPER_API_MODEL` | `whisper-1` | STT por API |
| `BRIEFER_WHISPER_LOCAL_MODEL` | `base` (`tiny` · `base` · `small` · `medium`) | STT local (`faster-whisper`) |
| `BRIEFER_SDXL_MODEL` | `stabilityai/sdxl-turbo` | Portada local |
| `BRIEFER_CLIP_MODEL` | `openai/clip-vit-base-patch32` | Clasificador local |
| `BRIEFER_LOCAL_DEVICE` | `auto` (`auto` · `cpu` · `cuda` · `mps`) | Dispositivo de los modelos locales |

Los modelos locales requieren `requirements-local.txt`.

### Idioma, voces y contenido

| Variable | Por defecto (código y `.env.example`) | Para qué |
| --- | --- | --- |
| `BRIEFER_LANGUAGE` | `es` | Idioma de STT y contenido |
| `BRIEFER_VOICE_A` · `BRIEFER_VOICE_B` | `es-ES-AlvaroNeural` · `es-ES-ElviraNeural` | Voces edge-tts (B también responde en el Q&A) |
| `BRIEFER_SPEAKER_A_NAME` · `BRIEFER_SPEAKER_B_NAME` | `Álvaro` · `Elvira` | Nombres de los presentadores en guion y transcripción |
| `ELEVENLABS_VOICE_A` · `ELEVENLABS_VOICE_B` | vacío | Ids de voz si `BRIEFER_TTS_PROVIDER=elevenlabs` |
| `ELEVENLABS_MODEL` | `eleven_multilingual_v2` | Modelo de ElevenLabs |
| `BRIEFER_DEFAULT_TICKERS` | `SAN.MC,ITX.MC,IBE.MC,AAPL,MSFT,NVDA` | Tickers por defecto (formato Yahoo, separados por comas) |
| `BRIEFER_NEWS_RSS_FEEDS` | vacío | Feeds RSS adicionales, separados por comas |
| `BRIEFER_NEWS_MAX_ITEMS` | `20` | Máximo de noticias por briefing |
| `BRIEFER_PODCAST_TARGET_MINUTES` | `4` | Duración objetivo del podcast |

### Claves y entrega

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | vacío | LLM y visión con Claude |
| `OPENAI_API_KEY` | vacío | Whisper API y LLM OpenAI (opcional) |
| `GEMINI_API_KEY` | vacío | LLM Gemini (opcional) |
| `ELEVENLABS_API_KEY` | vacío | Voces ElevenLabs (opcional) |
| `TELEGRAM_BOT_TOKEN` · `TELEGRAM_CHAT_ID` | vacío | Entrega por Telegram (opcional) |
| `SMTP_HOST` · `SMTP_USER` · `SMTP_PASSWORD` · `SMTP_FROM` | vacío | Entrega por email (opcional) |
| `SMTP_PORT` | `587` | Puerto SMTP |
| `SMTP_TO` | vacío | Destinatarios, separados por comas |
| `SMTP_USE_TLS` | `true` | Usar TLS en la conexión SMTP |

### Rutas y logging

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `BRIEFER_DATA_DIR` · `BRIEFER_CACHE_DIR` · `BRIEFER_OUTPUT_DIR` · `BRIEFER_SAMPLES_DIR` | `data` · `data/cache` · `data/outputs` · `data/samples` | Rutas (relativas a la raíz del repo si no son absolutas) |
| `BRIEFER_LOG_LEVEL` | `INFO` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |

Sin `ANTHROPIC_API_KEY` (u otra clave necesaria) la app sigue arrancando: con `BRIEFER_FALLBACK_TO_MOCK=true`
el `registry` cae a `mock` y lo deja en el log; la barra lateral de la UI muestra la configuración activa
(«Proveedores configurados»).

---

## Capturas

> TODO: añadir capturas reales en `docs/assets/capturas/` cuando la UI esté terminada (D3, 08-oct).

| Pantalla | Captura |
| --- | --- |
| Portada / selección de tickers | TODO `docs/assets/capturas/01_portada.png` |
| Briefing del día (podcast + transcripción + gráficos) | TODO `docs/assets/capturas/02_briefing.png` |
| Vídeo corto generado | TODO `docs/assets/capturas/03_video.png` |
| Preguntar por voz (Q&A) | TODO `docs/assets/capturas/04_preguntar.png` |
| Subida de PDF / captura de gráfico | TODO `docs/assets/capturas/05_subidas.png` |
| Mi cartera | TODO `docs/assets/capturas/06_cartera.png` |
| Histórico y métricas (latencia/coste por paso) | TODO `docs/assets/capturas/07_historico.png` |

---

## Demo

> TODO: enlace a la demo grabada (vídeo de 3-5 min) y, si se despliega, URL pública.

Guion previsto de la demo:

1. Elegir tickers / cargar cartera de ejemplo.
2. Subir un PDF de resultados y una captura de gráfico.
3. Generar el briefing: mostrar análisis, podcast a dos voces, transcripción, gráficos y vídeo.
4. Preguntar por voz sobre el briefing y escuchar la respuesta.
5. Enviar por email / Telegram.
6. Enseñar la tabla de métricas (latencia y coste estimado por paso) y el modo mock.

---

## Documentación

| Documento | Contenido |
| --- | --- |
| [docs/README.md](docs/README.md) | Índice operativo y ruta de lectura |
| [00 · Enunciado](docs/00_enunciado.md) | Enunciado estructurado y checklist de rúbrica |
| [01 · Producto](docs/01_producto_y_propuesta_valor.md) | Problema, público, propuesta de valor, monetización |
| [02 · Arquitectura](docs/02_arquitectura_y_flujo_datos.md) | Capas, componentes, secuencias, cadena de modelos |
| [03 · Contratos](docs/03_contratos_modulos.md) | Schemas, interfaces y reparto por carriles |
| [04 · Viabilidad](docs/04_viabilidad_costes_latencia_compliance.md) | Costes, latencias, compliance, monetización |
| [05 · Roadmap](docs/05_roadmap_TODO.md) | TODO hasta la entrega |
| [06 · Estado actual](docs/06_estado_actual.md) | Qué funciona y qué no |
| [Decisiones (ADR)](docs/decisiones/README.md) | Decisiones de arquitectura |
| [Material de clase](docs/clase/00_indice.md) | Resumen del material del taller |
| [Pitch deck](pitch/README.md) | Pitch técnico |

---

## Aviso legal

Market Briefer es un proyecto académico. El contenido generado:

- es **información genérica**, no asesoramiento de inversión personalizado (MiFID II);
- **no** contiene recomendaciones de compra, venta o mantenimiento de ningún instrumento;
- puede contener errores: los modelos de IA pueden equivocarse o interpretar mal una noticia;
- resume y **cita la fuente** de cada noticia; los derechos de las noticias pertenecen a sus editores;
- usa **voces sintéticas** generadas por IA (transparencia, AI Act).

Los datos de cartera se procesan localmente y solo se envían a un proveedor de IA los tickers y pesos
necesarios para el análisis. Ver [docs/04](docs/04_viabilidad_costes_latencia_compliance.md).

---

## Equipo

| Integrante | Rol principal |
| --- | --- |
| TODO nombre 1 | TODO |
| TODO nombre 2 | TODO |
| TODO nombre 3 | TODO |

Máster MIAX · Taller B5-T4 · Entrega 8-oct-2026.
