# ADR-001 · Stack del MVP

- **Estado:** Aceptado
- **Fecha:** 05-oct-2026
- **Ámbito:** todo el repositorio; condiciona los tres carriles

## Contexto

- **Plazo:** tres días de trabajo (5 a 8 de octubre) para un equipo de tres.
- **Rúbrica:** puntúa diversidad de modalidades, encadenamiento de modelos especializados, MVP ejecutable con
  UI cuidada, arranque plug-and-play y separación limpia de capas.
- **Coste:** el desarrollo y la demo deben poder hacerse con presupuesto de API mínimo y, si hace falta, sin
  claves.
- **Material de clase:** los notebooks del taller cubren CLIP, Qwen2.5-VL, SDXL-Turbo, Stable Video Diffusion,
  Bark y Whisper; conviene poder reutilizar lo aprendido como alternativa local.

## Decisión

Python 3.11 + Streamlit multipágina, con Claude como LLM y visión por defecto, edge-tts como TTS gratuito a
dos voces, Whisper para STT, yfinance + RSS como fuentes, matplotlib/plotly para gráficos y moviepy + ffmpeg
para el vídeo. Persistencia en ficheros, configuración en `.env`.

| Capa | Elección | Motivo |
| --- | --- | --- |
| Lenguaje | Python 3.11+ | Ecosistema de IA, conocido por todo el equipo |
| UI | Streamlit multipágina | UI decente en horas, reproductores de audio/vídeo y `st.audio_input` nativos |
| LLM | Claude Sonnet (análisis), Claude Haiku (tareas baratas) | Buena calidad en español y salida estructurada fiable |
| Visión | Claude visión | Misma API y clave que el LLM; sin GPU |
| PDF | `pypdf` + visión en páginas con gráficos | Texto barato; visión solo donde aporta |
| STT | Whisper (local `faster-whisper` o API) | Buen español; local gratis |
| TTS | `edge-tts` | Gratis, sin clave, voces es-ES naturales, dos voces distintas |
| Noticias y precios | `yfinance` + `feedparser` | Gratis y sin registro |
| Gráficos | matplotlib / plotly | Estándar |
| Vídeo | moviepy + ffmpeg | Vídeo determinista y rápido a partir de imágenes, audio y SRT |
| Persistencia | JSON + ficheros en `data/outputs/` | Sin base de datos que desplegar |
| Config | `.env` + pydantic-settings | Simple y tipado |
| Empaquetado | `requirements.txt`, `Dockerfile`, scripts `run.ps1`/`run.sh` | Exigido por la rúbrica |

## Alternativas consideradas

| Opción | A favor | En contra |
| --- | --- | --- |
| Front React + backend FastAPI | UI más flexible y profesional | Doble de trabajo; no cabe en 3 días |
| Gradio | Rápido, buenos componentes de audio | Menos adecuado para app multipágina con histórico |
| Todo con modelos locales (Ollama, Qwen-VL, Bark, Whisper) | 0 € de API, privacidad | Lento en CPU, calidad del TTS y del LLM en español peor, demo frágil |
| OpenAI como LLM principal | Un solo proveedor para LLM, STT y TTS | Sin ventaja clara de calidad; se mantiene como alternativa |
| ElevenLabs como TTS por defecto | Voces más naturales | Coste por carácter alto (ver [04](../04_viabilidad_costes_latencia_compliance.md)); requiere clave |
| Stable Video Diffusion para el vídeo | Vídeo generativo vistoso | Requiere GPU, lento, poco control; queda como extra |
| Base de datos (SQLite/Postgres) | Consultas e histórico robustos | Innecesario para el volumen del MVP |

## Consecuencias

- **Positivas:** MVP alcanzable en plazo; coste de demo de céntimos; cobertura de muchas modalidades con pocas
  dependencias; los modelos del material de clase entran como alternativas locales.
- **Negativas / deuda:**
  - Streamlit limita la personalización de la UI y no es un front de producción.
  - `edge-tts` usa un servicio no oficial: puede cambiar o fallar (mitigado con proveedores alternativos y mock).
  - Sin base de datos ni autenticación: no es multiusuario.
  - Dependencia de un proveedor comercial para la calidad del análisis (mitigado por [ADR-002](ADR-002-proveedores-intercambiables.md)).
- **Para revertir:** la UI solo consume `pipeline` y `storage`, así que cambiar Streamlit por otro front no
  toca la lógica; cambiar de proveedor de modelos es configuración.
