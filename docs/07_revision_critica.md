# 07 · Revisión crítica del plan (05-oct-2026, tarde)

> Revisión externa de producto, arquitectura y evaluación académica sobre el estado del repo a D0 (esqueleto:
> contratos, mocks, registry, pipeline escrito; ~65 `NotImplementedError` en `ingest/`, `agents/`, `media/`,
> `delivery/`, `storage.py` y proveedores reales). Fuentes: `docs/raw/text/enunciado.txt`, `CLAUDE.md`,
> `README.md`, `docs/00-06`, `docs/decisiones/*`, `docs/clase/00_indice.md`, `docs/clase/12_pistas_profesor.md`,
> `src/briefer/*`, `app/*`. Todas las horas y latencias son **estimaciones**; ninguna está medida.

---

## 1. Veredicto (5 líneas)

1. La idea, la arquitectura por capas y los contratos son **sólidos y por encima de la media**; el riesgo no es de diseño, es de **ejecución en ~90 horas-persona** con 65 *stubs* abiertos.
2. Tal como está, el plan **no maximiza la nota**: el pipeline es **lineal** (A→B→C sin ramas, bucles ni decisiones) y los dos modelos que más "suman" en la rúbrica (CLIP y texto-a-imagen) están **apagados por defecto**, así que la demo enseñaría menos modalidades de las que promete el README.
3. Hay un agujero de **experiencia del evaluador**: si arranca sin claves ve el modo mock con noticias `[EJEMPLO FICTICIO]` y un **podcast de silencio** (MockTTS = WAV mudo). Falta un briefing real pregenerado y un modo "sin claves" que use edge-tts (que no necesita clave).
4. Sobra alcance en proveedores alternativos (3 LLMs, Qwen local, SDXL local, ElevenLabs, Whisper local, email **y** Telegram): es amplitud que no puntúa si no se ve en la demo; conviene cambiarla por **orquestación visible** (enrutado CLIP, puertas de calidad con Whisper/grounding, paralelismo, traza del pipeline en la UI).
5. Con los 8 cambios del resumen final y congelando funcionalidades el miércoles a las 22:00, el plan es **viable y de nota alta**; sin ellos, el riesgo realista es entregar un pipeline correcto pero "plano" y una demo frágil.

---

## 2. Hallazgos críticos (ordenados por impacto en nota / riesgo de entrega)

Formato: **Problema → Evidencia → Mejora → Coste (h) → Fase.**

### H1 · La orquestación no se ve: es un pipeline lineal (4.2, peso alto)

- **Problema.** La rúbrica premia "encadenamiento coordinado de múltiples modelos especializados". Hoy `run_briefing` es una secuencia fija sin ninguna decisión tomada por un modelo: no hay enrutado, ni ramas paralelas, ni bucles de verificación, ni *fallbacks* por paso. Los "agentes" son tres prompts sin herramientas. El evaluador puede leerlo como "un LLM con pasos antes y después".
- **Evidencia.** `src/briefer/pipeline.py` (pasos 1-8 secuenciales; `process_upload` enruta por **extensión**, no por contenido); `docs/02` §"Tolerancia a fallos, estado actual" admite que las excepciones se propagan; `docs/clase/12` §7 ya identifica el patrón "LLM como director" pero no se implementa.
- **Mejora** (en orden de valor/coste):
  1. **Enrutado por contenido** de imágenes subidas: CLIP/SigLIP zero-shot decide `velas | línea | tabla | captura de cartera | no financiera` y cada etiqueta va a un prompt/lector distinto (y "no financiera" se rechaza sin gastar visión). Ya está el *stub* (`chart_reader.classify_image`, `providers/image/clip_classifier.py`). Con SigLIP usar sigmoide + umbral, o CLIP con clase "otra cosa" (pista del profesor, `12 §4`).
  2. **Puertas de calidad con bucle**: (a) *grounding* determinista: toda cifra/ticker del `Analysis` y del guion debe aparecer en `MarketContext`; si falla, se reinvoca al Analista/Guionista **una vez** con la lista de cifras no trazables. (b) **Whisper sobre el podcast generado** → WER contra el guion; líneas con WER alto se re-sintetizan (p. ej. tickers mal pronunciados). Cierra el bucle TTS→STT y da una métrica de calidad visible.
  3. **Paralelismo explícito**: noticias ∥ precios; TTS por línea con `ThreadPoolExecutor` (4-6 hilos); gráficos ∥ TTS. Baja la latencia y se ve en la traza.
  4. **Fallback por paso** (núcleo cae a mock marcado; opcional se omite con aviso) y registro en `StepMetric` (campo `status`/`fallback`, cambio compatible).
  5. **Pestaña "Cómo se hizo"** en la UI: grafo (graphviz/mermaid) del briefing con cada modelo, latencia, coste, decisión del router, resultado de las puertas. Es lo que convierte la orquestación en evidencia visible en 10 segundos.
- **Coste.** Router 2-3 h (incluye instalar torch CPU) · grounding + reintento 2 h · WER 2 h · paralelismo 1,5 h · fallbacks 1,5 h · pestaña traza 1,5 h. **Total ≈ 11 h.**
- **Fase.** Fallbacks y paralelismo D1 tarde; router, grounding, WER y traza D2.

### H2 · La demo sin claves es pobre y la demo con claves no está asegurada (4.3 + entregable 2)

- **Problema.** (a) El modo demo está **activado por defecto** y produce noticias marcadas `[EJEMPLO FICTICIO]`, gráficos de un PNG liso y un audio de silencio: los primeros 30 s del evaluador serían decepcionantes. (b) No hay ningún briefing real versionado; si el día de la corrección falla una API, no hay nada que enseñar. (c) `BRIEFER_FALLBACK_TO_MOCK=true` cae a mock **en silencio** (solo log): se puede grabar una demo "real" que en realidad es mock.
- **Evidencia.** `app/components/players.py::sidebar_controls` (`value=True`); `docs/02` §modo mock ("un WAV de silencio"); `data/samples/` solo tiene JSON/CSV; `.gitignore` ignora `*.mp3/*.wav/*.mp4` salvo `data/samples/**`.
- **Mejora.**
  1. **Briefing pregenerado real** en `data/samples/demo_briefing/` (briefing.json con **rutas relativas**, podcast.mp3 ~1,5 MB, SRT, PNGs, portada; el MP4 fuera de git y enlazado). La portada de la app lo muestra **al cargar**, sin pulsar nada. Regenerarlo el jueves por la mañana con el código final.
  2. **Tres modos explícitos** en lugar de un interruptor: `Ejemplo guardado` (instantáneo, offline) · `Sin claves` (noticias de ejemplo + **LLM mock con guion realista en español** + **edge-tts real** + matplotlib/vídeo reales: suena de verdad sin ninguna clave) · `Real` (APIs de `.env`).
  3. **Insignia por proveedor** en la barra lateral y en el resultado: verde "real" / rojo "MOCK (falta ANTHROPIC_API_KEY)". El fallback silencioso pasa a ser visible.
  4. Ajustar la regla "<1 MB" de `data/samples/README.md` (pasar a <5 MB en total).
- **Coste.** Pregenerado + carga en portada 2 h · modo sin claves (mock LLM con textos buenos) 1,5 h · insignias 1 h. **≈ 4,5 h.**
- **Fase.** Modos e insignias D1; pregenerado D1 noche (primera versión) y D3 mañana (final).

### H3 · Modalidades prometidas ≠ modalidades demostradas (4.2 diversidad)

- **Problema.** El README lista 11 modalidades, pero: dos son el mismo texto→texto (Analista y Guionista); la "transcripción" (#11) no usa ningún modelo (sale del guion); CLIP (#5) y texto→imagen (#9) están en `none` por defecto y SDXL-Turbo exige GPU, así que en la práctica **no saldrán en la demo**; la subida de audio al briefing existe en `pipeline.process_upload` pero el `file_uploader` de `1_Briefing.py` no acepta audio; la "captura de cartera" del diagrama original no está prevista. Un evaluador que cuente lo verá.
- **Evidencia.** `README.md#modalidades-y-modelos`; `.env.example` (`BRIEFER_IMAGE_GEN_PROVIDER=none`, `..._CLASSIFIER_PROVIDER=none`); `app/pages/1_Briefing.py` (`type=["pdf","png","jpg","jpeg","webp"]`); nota bajo el mermaid del README.
- **Mejora.**
  - **Texto→imagen por API** (no SDXL local): portada/infografía del episodio con un modelo de imagen por API (OpenAI o Gemini; ~0,01-0,04 € y 5-20 s por imagen, **verificar tarifa**), con marca "imagen generada por IA" (AI Act). Se reutiliza como primer fotograma del vídeo y miniatura de Telegram: modalidad con sentido, no decorativa. SDXL-Turbo queda como alternativa local documentada.
  - **Captura de la cartera del broker → `Portfolio`** con visión + `response_model=Portfolio`. Es imagen→dato estructurado, un caso de uso FinTech real que el enunciado cita literalmente ("lectura óptica… de documentos") y reutiliza el proveedor de visión. El router CLIP decide si la imagen es una cartera o un gráfico.
  - **Whisper sobre el audio final** → SRT con *timestamps* reales + WER (H1): la fila #11 pasa a ser un modelo de verdad.
  - Añadir `wav/mp3/m4a` al uploader (nota de voz que entra en el análisis): 15 min.
  - Rehacer la tabla del README con una columna **"Activo en la demo"** y numerar *modelos distintos encadenados* aparte de *modalidades*. Honestidad > inflado.
- **Coste.** Imagen por API 2 h · cartera por captura 2 h · uploader audio 0,25 h · tabla 0,5 h. **≈ 5 h** (WER ya contado en H1).
- **Fase.** D2.

### H4 · Camino crítico y riesgos técnicos sin mitigar (robustez, 4.3)

| Riesgo | Probabilidad / impacto | Mitigación concreta | Coste | Fase |
| --- | --- | --- | --- | --- |
| **Claves API**: una sola persona con clave, límite de gasto, ID de modelo inexistente (`claude-sonnet-5-5` en `.env.example`/`costs.py` **sin verificar**) → 404 en la primera llamada real | Media / alto | Hoy: una llamada real de humo por proveedor (`scripts/smoke_real.py`: Anthropic texto + visión, Whisper, edge-tts); clave de grupo con **límite de gasto** (p. ej. 20-30 $); confirmar IDs exactos en la consola del proveedor | 0,5 h | D0 |
| **yfinance pobre en `.MC`**: noticias vacías o en inglés, *rate limit* (429) frecuente en 2025-26 | Alta / medio | Fuente principal de noticias en español: **RSS de Google News por nombre de empresa** (`hl=es`, sin clave) + 1-2 RSS de prensa económica; yfinance solo para precios con caché diaria en `data/cache/`; si el precio falla, snapshot marcado "sin datos" (nunca sintético en modo real) | 1,5 h | D1 |
| **edge-tts**: servicio no oficial, se ha roto otras veces por cambios de token, *throttling* con mucha concurrencia; ToS de Microsoft no ampara uso comercial | Media / alto | Fijar versión que funcione hoy (`edge-tts==x.y.z`); concurrencia ≤ 4; reintento con *backoff*; fallback a pregenerado. En 4.1 decir explícitamente que **en producción** se usaría **Azure AI Speech** (mismas voces neurales es-ES, servicio oficial, del orden de 15 $/M caracteres → ~0,05 € por podcast de 3.500 caracteres, **verificar**) | 1 h | D1 |
| **Normalización para TTS**: "SAN.MC" se lee "san punto eme ce", "1,5 %" o "Q3" mal | Alta / medio (se oye en la demo) | Paso `media.podcast.normalize_for_speech`: ticker → nombre de empresa (`TICKER_UNIVERSE`), cifras y % a forma hablable; además pedirlo en el prompt del Guionista | 1 h | D1 |
| **ffmpeg / moviepy 2.x**: `TextClip` necesita fuente TTF (rutas distintas en Windows/Docker); render 1080×1920 a 24 fps de 4 min en CPU puede tardar varios minutos | Alta / medio | Vídeo con **ffmpeg directo** (`imageio-ffmpeg`): imágenes fijas + audio + subtítulos quemados con filtro `subtitles` desde el SRT, 720×1280 y 1-5 fps (las imágenes son estáticas) → decenas de segundos; incluir una TTF libre en el repo; vídeo opcional y su fallo no rompe el briefing | 3 h | D2 |
| **Streamlit**: la ejecución de 1-3 min es síncrona; si el usuario cambia de página se aborta; sin caché de recursos | Media / medio | `st.status` con pasos (ya está) + aviso "no cambies de página"; `st.cache_resource` para modelos locales (CLIP); el resultado se guarda en `session_state` y en disco antes de pintar | 0,5 h | D2 |
| **Rutas absolutas en `briefing.json`** rompen el histórico y el pregenerado en otra máquina/Docker | Alta si no se hace / alto | Ya previsto en `storage.py` (TODO de rutas relativas): **convertirlo en test** (`save` → mover carpeta → `load` → ficheros existen) | 0,5 h | D0-D1 |
| **torch** al activar CLIP/FinBERT: en Windows `pip install torch` baja la build CUDA (~2,5 GB) | Media / medio | `requirements-local.txt` con `--index-url https://download.pytorch.org/whl/cpu`; Docker principal sin torch (router cae a "sin clasificador" con aviso) o una imagen `-local` aparte | 0,5 h | D2 |
| **Coste** | Baja / bajo | Con edge-tts y Sonnet solo en el Analista: ~0,05-0,10 € por briefing (estimación de `docs/04`); 150 briefings de desarrollo ≈ 15 €. Guionista y Q&A en Haiku | 0 h | — |
| **Prompt injection en PDFs subidos** | Baja en demo / medio en pitch | Delimitar el contenido del documento como datos en el prompt; mencionarlo en compliance | 0,25 h | D2 |

### H5 · UX/UI: qué ve el evaluador en los primeros 30 s (4.3 usabilidad)

- **Problema.** `app/main.py` abre con un párrafo, un `st.warning` grande con el disclaimer (lo primero que se ve es un aviso legal) y cuatro enlaces. No hay producto visible hasta que se pulsa "Generar" y se esperan 1-3 min. La tabla de métricas es un `st.dataframe` crudo. No hay indicador de en qué modo se está.
- **Evidencia.** `app/main.py`, `app/components/players.py::render_briefing`.
- **Mejora (guion de los 30 primeros segundos).**
  1. 0-5 s: cabecera con nombre + propuesta en una línea + **insignia de modo** (Ejemplo / Sin claves / Real).
  2. 5-15 s: tarjeta del **briefing de hoy** (pregenerado o último del histórico): portada, titular, reproductor de audio, 3 puntos clave con chips de ticker y fuentes enlazadas.
  3. 15-30 s: botones grandes "Generar el mío" · "Preguntar por voz" · "Subir gráfico/PDF/captura de cartera", y una franja "Cómo se hizo: 9 modelos, 74 s, 0,07 €" que abre la traza (H1.5).
  - Disclaimer como banda compacta fija (no `st.warning` a toda anchura), y **disclaimer hablado** al final del podcast (ya previsto).
  - Transcripción con nombres de locutor y resaltado; métricas como `st.metric` (latencia total, coste, nº de modelos) + gráfico de barras por paso.
  - Q&A: mostrar el texto en cuanto llega y el audio después; enseñar la latencia medida (<10 s objetivo). **Hoy `QAAnswer` no tiene `metrics`**: añadir `metrics: list[StepMetric] = []` (cambio compatible v0.2), si no el objetivo de latencia del Q&A no se puede demostrar.
  - Estados vacíos y errores amables ya esbozados: mantener.
- **Coste.** Portada 2 h · pulido briefing/métricas 2 h · Q&A métricas 0,5 h. **≈ 4,5 h.**
- **Fase.** Portada D1 noche (con el pregenerado); pulido D2; capturas D3.

### H6 · Viabilidad, compliance y monetización (4.1): correcto pero con huecos que un evaluador FinTech verá

- **Problema / evidencia** (`docs/04`, `docs/01`):
  1. **Datos de mercado y noticias**: no hay coste de **licencias**. yfinance no es usable comercialmente (ToS de Yahoo) y los RSS de prensa tampoco para resumir con fines comerciales sin acuerdo (derecho afín de editores de prensa, art. 15 Directiva 2019/790). En producción hay que pagar un proveedor de datos y/o noticias: es un **coste fijo** que no aparece.
  2. **MAR, no solo MiFID II**: etiquetar cada punto con sentimiento `positivo/negativo` por ticker puede leerse como **recomendación implícita** (definición amplia de "recomendación de inversión" en MAR). Mitigación: renombrar a "impacto de la noticia", explicar el criterio y no agregarlo por ticker en un "semáforo".
  3. **AI Act art. 50** (obligaciones de transparencia aplicables desde el 2-ago-2026, es decir **ya en vigor** en la fecha de entrega): audio sintético y contenido generado deben estar marcados de forma detectable; mencionar metadatos en el MP3/MP4 y aviso hablado.
  4. **RGPD**: falta transferencias internacionales (proveedores de EE. UU.: DPF/cláusulas tipo), plazo de conservación, y en la UI no hay casilla de consentimiento ni botón "borrar mis datos" (marcados como pendientes). La voz del usuario es dato personal: decir que se borra tras transcribir y **hacerlo** en el código.
  5. **Monetización**: el escenario da ~840 €/mes de margen **antes** de costes fijos: con datos, infraestructura y personal sale negativo, y el documento no lo dice. Falta: CAC, punto de equilibrio, precio de referencia de competidores, y que el B2B2C es el modelo principal (no un canal).
  6. **Latencias**: todo es objetivo; nada medido. El evaluador pide "latencias requeridas para una UX fluida": hay que poner p50/p95 medidos con `StepMetric` de 3-5 ejecuciones.
- **Mejora.**
  - Tabla de **costes fijos mensuales** (datos de mercado, noticias licenciadas, TTS oficial, hosting, monitorización) y **punto de equilibrio** B2C vs un contrato B2B2C tipo (p. ej. 50.000 usuarios activos de un neobanco). Todo marcado como estimación con fuente y fecha.
  - Tabla **riesgo regulatorio → control en el código** (con fichero): disclaimer (`schemas.DISCLAIMER_ES`), filtro anti-recomendación (regex de "compra/vende/mantén" + reintento: puerta de calidad), grounding de cifras, marca de IA en audio/imagen, borrado de audio de la pregunta. Que cada control sea **verificable** en el repo vale más que párrafos.
  - Una sola diapositiva de unit economics en el pitch con cifras **medidas** de coste por briefing.
- **Coste.** Docs 2,5 h · filtro anti-recomendación 0,5 h · borrado de audio + casilla de consentimiento 0,5 h · medición p50/p95 1 h. **≈ 4,5 h.**
- **Fase.** Controles en código D2; documento y cifras medidas D3 mañana.

### H7 · Calidad de código, modularidad y tests (4.4)

- **Bien:** separación providers / negocio / UI real y documentada (ADR-002), inyección de dependencias, contratos Pydantic con `extra="forbid"`, `track_step` mide incluso con error, registry perezoso. Es de lo mejor del proyecto: **no tocarlo**.
- **Problemas.**
  1. **Costes mal atribuidos** cuando un paso usa dos modelos: `process_upload` imputa al paso PDF solo el LLM barato (no la visión) y al de gráfico solo la visión (no el LLM). `pipeline.py` líneas de `ingest.pdf` / `ingest.chart`. Solución: sumar `last_usage` de ambos o separar en dos `StepMetric`.
  2. El Guionista usa `providers.llm` (Sonnet); con Haiku bastaría y abarata ~60 % ese paso (`docs/04` §4 ya lo propone; el código no).
  3. **Tests**: solo `test_schemas.py` y un e2e mock saltado. Faltan unitarios de funciones puras que son justo donde se rompe la demo: `format_srt_timestamp`, `filter_by_tickers` con alias, normalización TTS, grounding, rutas relativas de `storage`, router con umbral. Y un test de integración real marcado `@pytest.mark.real` que se salta sin claves.
  4. Sin **CI**: un workflow de GitHub Actions con `pytest -q` en modo mock (15 min de trabajo) da una insignia verde en el README y protege `main` de roturas entre carriles.
  5. Los *stubs* de proveedores que no se implementen (Qwen local, SDXL local, ElevenLabs, OpenAI/Gemini LLM) **no deben entregarse lanzando `NotImplementedError`**: o se implementan, o se retiran del registry y se mencionan como roadmap. Un repo entregado con stubs parece inacabado.
  6. `schemas.py` como fuente de verdad está bien; mantener además `docs/03` (33 KB) sincronizado a mano es caro: congelarlo y añadir solo el registro de cambios.
- **Coste.** Costes 0,5 h · Haiku guionista 0,1 h · tests ~3 h repartidas · CI 0,5 h · limpieza de stubs 0,5 h. **≈ 4,5 h.**
- **Fase.** CI D0; tests a la vez que cada módulo; limpieza D3 antes del *freeze*.

### H8 · Documentación, README y pitch (4.4): mucho texto, faltan las evidencias que se piden

- **Lo que exige el enunciado literalmente:** README **con capturas**, **diagrama de flujo de datos multimodal**, **descripción de arquitectura**, y **pitch deck técnico**. Diagramas y arquitectura: hechos y buenos. **Capturas, demo y pitch: 0 %.**
- **Sobra / riesgo de ruido:** 12 ficheros de `docs/clase/` (útiles como contexto de agentes, irrelevantes para el evaluador) y un README de ~400 líneas donde la mitad son tablas de configuración. El evaluador lee los primeros 2 pantallazos.
- **Mejora.**
  - README: arriba del todo **GIF o captura de la portada + enlace al vídeo de demo + "arranca en 2 comandos"**; luego tabla de modalidades honesta (H3), diagrama, arquitectura, resultados medidos (coste/latencia/WER/grounding). Mover la referencia completa de configuración a `docs/08_configuracion.md` o a un `<details>`.
  - Añadir un diagrama **del grafo de orquestación** (con ramas, router, puertas y fallbacks), no solo el flujo lineal.
  - **Pitch deck** de 10-12 diapositivas exportado a PDF en `pitch/`: problema → usuario → demo (capturas) → cadena de modelos → por qué cada modelo → resultados medidos → costes y unit economics → compliance como controles → monetización → roadmap → equipo.
  - **Vídeo demo** de 3-4 min (no 5) siguiendo el guion del README, subido a enlace externo (YouTube no listado / Drive).
  - `docs/clase/`: mantener, pero sacarlo del índice principal del README (enlace en "Documentación interna").
- **Coste.** README 2 h · capturas 1 h · diagrama orquestación 0,5 h · pitch 3 h · demo grabada 2 h (incluye 2 tomas). **≈ 8,5 h.**
- **Fase.** D3 (pitch puede empezar D2 tarde por quien vaya más desahogado).

### H9 · Organización de 3 personas en 3 días: carriles desequilibrados y sin puntos de integración

- **Problema.** El carril C concentra TTS, podcast, transcripción, gráficos, vídeo, portada, email, Telegram, las 4 páginas de UI y el pulido: es **el doble** que A. Tampoco hay horas de sincronización, ni estrategia de ramas, ni dueño de `schemas.py`, ni quién hace README/pitch/demo el jueves. "Congelar a las 12:00 del jueves" es tarde: deja 5 h para capturas, demo, pitch, README y clon limpio.
- **Evidencia.** `docs/05` (reparto por carril y D3).
- **Mejora.**
  - Rebalanceo: **A** = entradas + visión + router CLIP + captura de cartera + Telegram. **B** = agentes + orquestación + puertas de calidad + fallbacks + métricas + `docs/04` medido + dueño de `schemas.py`. **C** = TTS/podcast/SRT/gráficos/vídeo/portada + UI + pregenerado + capturas.
  - **Ramas cortas por carril** (`a/...`, `b/...`, `c/...`), PR a `main` en cada punto de sincronización; `main` siempre con `pytest` verde (CI). Nada de ramas largas: integración como mínimo 2 veces al día.
  - **Cambios de contrato solo aditivos** desde el martes 13:00; un único dueño hace el merge de `schemas.py`.
  - **Feature freeze miércoles 22:00**; jueves solo arreglos, documentación y demo.
- **Coste.** 0 h de código, 15 min de acuerdo hoy.
- **Fase.** D0 (ahora).

### H10 · Deuda y sobreingeniería que conviene recortar

| Recortar | Por qué | Qué queda |
| --- | --- | --- |
| Gemini **y** OpenAI como LLM alternativo | Uno basta para demostrar intercambiabilidad (ADR-002); dos no suman nota | Implementar solo uno (el que tenga clave el grupo; Gemini tiene capa gratuita, útil para el evaluador) o ninguno |
| Qwen2.5-VL local, SDXL-Turbo local, ElevenLabs, Whisper local | Requieren GPU/clave de pago; no saldrán en la demo | Retirados del registry o documentados como roadmap; mencionados en el pitch como "camino a coste 0" |
| Stable Video Diffusion | Ya está fuera; no reabrir | — |
| Email **y** Telegram | Telegram es 30 min, vistoso en vídeo (el audio llega al móvil) y sin fricción de SMTP/contraseñas de aplicación | Telegram (Should); email (Could). **Invertir** el orden de recorte de `docs/05` |
| Mantener `docs/03` y `docs/06` al día tras cada cambio | Coste de coordinación alto en 3 días | `docs/06` solo al cierre de cada jornada; `docs/03` congelado salvo registro de cambios |
| Vídeo vertical 1080×1920 a 24 fps con moviepy | Lento y frágil | ffmpeg directo, 720×1280, fps bajo |
| Histórico con filtros | Poco valor | Lista + abrir (ya esbozado) |

---

## 3. Mejoras priorizadas (MoSCoW)

Presupuesto realista: ~90 horas-persona hasta el jueves a las 17:00; el núcleo + entrega se lleva ~60. **Las "Should" no deben pasar de ~25 h en total.**

| Prioridad | Mejora | Hallazgo | Coste (h) |
| --- | --- | --- | --- |
| **Must** | Camino mock e2e verde (quitar los 2 `skip`) + CI en GitHub Actions | H7 | 4 + 0,5 |
| **Must** | Prueba de humo real de cada proveedor e IDs de modelo verificados; límite de gasto | H4 | 0,5 |
| **Must** | Núcleo real: noticias (Google News RSS + yfinance precios) → Analista → Guionista (Haiku) → TTS 2 voces normalizado → SRT → gráficos | H4 | ~18 |
| **Must** | Fallback por paso (núcleo → mock marcado; opcional → omitido) + insignias de modo/proveedor | H1, H2 | 2,5 |
| **Must** | Briefing pregenerado real en `data/samples/demo_briefing/` con rutas relativas, mostrado en la portada | H2, H5 | 2 |
| **Must** | Modo "sin claves" con edge-tts real y LLM mock realista | H2 | 1,5 |
| **Must** | Captura de gráfico + PDF por visión, y Q&A por voz (Whisper → Haiku → edge-tts) con métricas | H3, H5 | ~10 |
| **Must** | Vídeo simple con ffmpeg (opcional en ejecución, no rompe) | H4 | 3 |
| **Must** | README con capturas + demo grabada + pitch PDF + clon limpio probado (`run.ps1` y Docker) | H8 | ~10 |
| **Must** | `docs/04` con costes y latencias **medidos** (p50/p95) y costes fijos/licencias | H6 | 3,5 |
| **Should** | Router CLIP/SigLIP de imágenes subidas (velas/línea/tabla/cartera/otra) | H1, H3 | 2,5 |
| **Should** | Puertas de calidad: grounding de cifras + anti-recomendación con 1 reintento | H1, H6 | 2,5 |
| **Should** | Whisper sobre el podcast generado: WER + SRT con *timestamps* reales | H1, H3 | 2 |
| **Should** | Pestaña "Cómo se hizo" (grafo del briefing con modelos, latencias, decisiones) | H1, H5 | 1,5 |
| **Should** | Portada/infografía con texto→imagen por API, marcada como IA, reutilizada en vídeo y Telegram | H3 | 2 |
| **Should** | Captura de cartera del broker → `Portfolio` (visión estructurada) | H3 | 2 |
| **Should** | Telegram (audio + titular + disclaimer) | H10 | 1 |
| **Should** | Paralelismo (ingesta y TTS por línea) | H1 | 1,5 |
| **Should** | Portada de la app rediseñada (30 s) y métricas visuales | H5 | 3 |
| **Could** | Embeddings: búsqueda semántica en el histórico y contexto del Q&A con briefings anteriores ("¿qué dijimos de Inditex el lunes?"); dedupe semántico de noticias | H3 | 3 |
| **Could** | Clasificador de sentimiento financiero especializado (tipo FinBERT; en inglés sobre titulares de yfinance) como **segunda opinión** del Analista, con aviso si discrepan | H1 | 2,5 (+ torch) |
| **Could** | Q&A con herramientas de solo lectura (precio de un ticker, buscar en noticias del día) | H1 | 2 |
| **Could** | Email | H10 | 1 |
| **Could** | Un LLM alternativo (Gemini) funcionando por `.env` | H10 | 1,5 |
| **Could** | Despliegue en la nube (HF Spaces / Streamlit Community Cloud con `packages.txt` para ffmpeg) | entregable 2 | 2 |
| **Won't** | SVD, SDXL local, Qwen-VL local, ElevenLabs, Bark, *fine-tuning*, autenticación/multiusuario, base de datos, segundo LLM alternativo | H10 | — |

**Nota sobre FinBERT y embeddings.** Ambos suman "modelos especializados", pero el router CLIP, la verificación con Whisper y el texto→imagen tienen mejor relación valor/coste porque (a) están en el material de clase (NB2, NB7, NB4) y el profesor los reconocerá, (b) encajan en el flujo existente sin dependencias nuevas salvo torch para CLIP, y (c) cada uno **cambia una decisión o una salida visible**. FinBERT solo aporta si su discrepancia con el LLM se muestra en la UI; los embeddings solo si el Q&A sobre histórico se enseña en la demo. Si se instala torch para CLIP, FinBERT pasa a costar ~1,5 h y puede subir a Should el miércoles si se va por delante.

---

## 4. Plan revisado por fases

Horario de referencia; "sync" = 15 min los tres, con `main` integrado y `pytest` verde. Carriles: **A** entradas/visión/entrega · **B** agentes/orquestación/calidad/viabilidad · **C** media/UI/demo.

### D0 · Lunes 5-oct (tarde-noche)

| Hora | A | B | C |
| --- | --- | --- | --- |
| Ahora-20:00 | `load_sample_news`, `synthetic_snapshots`, `filter_by_tickers`, `load_portfolio_csv` | `analyze`/`write_script` mock, **smoke real** de Anthropic (texto + visión) y verificación de IDs; límite de gasto | `storage` (rutas relativas + test), `synthesize_podcast`/`concat_audio`, `build_transcript`, `make_charts` con mock; **smoke real de edge-tts** (2 voces) |
| 20:00 | **Sync 0**: acuerdo de ramas, dueño de `schemas.py`, rebalanceo de carriles (H9) | | |
| 20:00-23:00 | Elegir y probar fuentes RSS (Google News por empresa) | CI de GitHub Actions; fallback por paso esqueleto | Página Briefing pinta el briefing mock |

**Salida D0:** `pytest -q` sin `skip` en verde en `main` y en CI; `streamlit run` genera un briefing mock completo; las 3 APIs del núcleo responden una llamada real.
**Go/no-go:** si a las 23:00 el e2e mock no pasa, el martes por la mañana **los tres** cierran el camino mock antes de tocar nada real.

### D1 · Martes 6-oct · Núcleo real

| Hora | A | B | C |
| --- | --- | --- | --- |
| 09:00-13:00 | Noticias reales (RSS + yfinance) y precios con caché | `AnthropicLLM.complete` con salida estructurada; Analista real; Guionista en Haiku | `EdgeTTS` + normalización para TTS; podcast real |
| 13:00 | **Sync 1**: `demo.py --tickers SAN.MC AAPL` con noticias y LLM reales; audio real | | |
| 13:00-18:00 | `ClaudeVision.describe` + `read_chart`; datos de ejemplo (PNG de gráfico y PDF propio) | Fallbacks por paso; insignias de proveedor; paralelismo; métricas por paso verificadas | Modos Ejemplo/Sin claves/Real; LLM mock realista; portada de la app |
| 18:00 | **Sync 2**: briefing real e2e desde la UI; primer **briefing pregenerado** guardado en `data/samples/demo_briefing/` | | |
| 18:00-22:00 | `read_pdf` (pypdf + visión en páginas pobres en texto) | Prompts: 3 carteras distintas, sin recomendaciones ni cifras inventadas | Transcripción con locutores, pestañas pulidas, métricas visuales |

**Salida D1:** briefing real (noticias → análisis → guion → podcast 2 voces → SRT → gráficos) en la UI y por CLI, con `StepMetric` reales; pregenerado v1 versionado; modo sin claves suena.
**Go/no-go (22:00):** si el e2e real no funciona, el miércoles **se cancelan todas las Should** salvo fallbacks y pregenerado; el objetivo pasa a ser núcleo + visión + Q&A.

### D2 · Miércoles 7-oct · Multimodalidad, orquestación visible, vídeo

| Hora | A | B | C |
| --- | --- | --- | --- |
| 09:00-13:00 | STT (Whisper API) + `transcribe_question`; uploader con audio | Agente Q&A + `answer_question` con métricas (`QAAnswer.metrics`) | Vídeo con ffmpeg (720×1280, subtítulos quemados) |
| 13:00 | **Sync 3**: PDF + gráfico + Q&A por voz reales; **go/no-go de Should** según reloj | | |
| 13:00-18:00 | Router CLIP/SigLIP (torch CPU) + captura de cartera → `Portfolio` | Puertas de calidad: grounding + anti-recomendación con reintento; WER del podcast con Whisper | Portada por texto→imagen API; pestaña "Cómo se hizo"; página Preguntar pulida |
| 18:00 | **Sync 4**: todo integrado en `main`; Docker probado en una máquina | | |
| 18:00-22:00 | Telegram | `docs/04`: costes fijos, licencias, MAR, AI Act art. 50, RGPD; empezar medición p50/p95 | Histórico y Mi cartera; empezar esqueleto del pitch |
| 22:00 | **Feature freeze** | | |

**Salida D2:** todas las Must funcionando; Should según go/no-go; Docker y `run.ps1` probados al menos una vez.
**Go/no-go (13:00):** si el Q&A por voz o la visión no están, **todo el carril que vaya por delante ayuda** y se recortan, por este orden: FinBERT/embeddings (Could) → captura de cartera → portada IA → WER → router CLIP → Telegram. La pestaña de traza y las puertas de grounding son lo último que se recorta (son baratas y son la evidencia de orquestación).

### D3 · Jueves 8-oct · Entregable (hasta 17:00)

| Hora | Tarea | Responsable |
| --- | --- | --- |
| 09:00-11:00 | Solo bugs; limpieza de stubs no implementados; regenerar **pregenerado final** con el código final; medir 3-5 briefings y 5 Q&A (p50/p95) | Los tres (un carril cada uno: A limpieza y clon limpio, B mediciones y `docs/04`, C pregenerado y capturas) |
| 11:00 | **Code freeze** (adelantado una hora respecto a `docs/05`) | — |
| 11:00-13:00 | Grabar demo (3-4 min, 2 tomas) · capturas · README final | C demo, A README, B pitch |
| 13:00-15:00 | Pitch PDF; `docs/06` y checklist de `docs/00` reflejan lo entregado | B pitch, A/C revisión cruzada |
| 15:00-15:45 | **Clon limpio** en otra máquina: `run.ps1` sin `.env` (modo Ejemplo) y con `.env`; `docker compose up --build` | A + C |
| 16:00 | Etiqueta `v1.0`; comprobación de que no se versiona `.env`, `data/outputs/`, `docs/raw/` | B |
| 16:30 | **Entrega en el aula virtual** (objetivo); 17:00 límite interno; 18:00 límite oficial | — |

**Go/no-go D3:** si a las 15:45 el clon limpio falla en Docker, se documenta `run.ps1`/`run.sh` como camino principal y Docker como "probado en Linux"; no se arregla Docker después de las 16:00.

---

## 5. Checklist de rúbrica → evidencia que verá el evaluador

Leyenda: **OK** existe y es enseñable · **Parcial** existe pero falta lo que se pide · **Hueco** no existe hoy.

| Criterio (enunciado) | Evidencia prevista | Estado hoy | Hueco a cerrar |
| --- | --- | --- | --- |
| 4.1 Esquema visual del producto | PNG del diagrama + mermaid en README y `docs/01` | OK | — |
| 4.1 Problema, público B2C/B2B2C, valor de la multimodalidad | `docs/01`, README | OK | Fusionar en una diapositiva del pitch |
| 4.1 Costes de inferencia y APIs | `docs/04`, `costs.py`, métricas en UI | Parcial | Tarifas verificadas con fecha; **coste medido** por briefing; costes fijos de datos/licencias |
| 4.1 Latencias para UX fluida | `docs/04`, `StepMetric` | Hueco (no medido) | p50/p95 medidos de briefing y Q&A; mostrar en la UI |
| 4.1 Compliance y privacidad | `docs/04`, disclaimer | Parcial | MAR (sentimiento), AI Act art. 50 en vigor, transferencias RGPD, controles **en código** (anti-recomendación, borrado de audio, marca IA) |
| 4.1 Monetización | `docs/01`, `docs/04` | Parcial | Costes fijos, punto de equilibrio, B2B2C como motor principal |
| 4.2 Diversidad de modalidades | Tabla README | Parcial (prometido > demostrado) | Columna "Activo en la demo"; texto→imagen por API; audio al uploader; captura de cartera |
| 4.2 Orquestación multi-modelo | `pipeline.py` | Parcial (lineal) | Router CLIP, puertas de calidad con reintento, Whisper sobre el audio, paralelismo, fallbacks, **pestaña de traza** y diagrama de orquestación |
| 4.3 MVP ejecutable | `app/`, `scripts/demo.py` | Hueco (stubs) | Núcleo real e2e (D1) |
| 4.3 UI, UX, navegación, robustez | `app/` multipágina | Parcial (esbozo) | Portada de 30 s, modos visibles, insignias, errores amables, fallback por paso |
| 4.3 Plug-and-play | `requirements.txt`, Dockerfile, compose, `run.ps1`/`run.sh` | Parcial (no probado) | Clon limpio Windows + Docker; versión fijada de edge-tts; torch CPU en local |
| 4.4 README exhaustivo con capturas | README | Parcial | Capturas, GIF/enlace a demo arriba, resultados medidos, config a un anexo |
| 4.4 Diagrama de flujo multimodal | README, `docs/02` | OK | Añadir diagrama de **orquestación** (ramas/decisiones) |
| 4.4 Descripción de arquitectura | README, `docs/02`, ADRs | OK | — |
| 4.4 Pitch deck técnico | `pitch/` | Hueco | PDF 10-12 diapositivas |
| 4.4 Calidad y modularidad | `providers/` · negocio · `app/`, ADR-002 | OK (diseño) | Tests unitarios de funciones puras, CI, retirar stubs, costes bien atribuidos |
| 5.1 Repositorio GitHub organizado | Estructura actual | OK | Etiqueta `v1.0`; nada de `.env`/salidas |
| 5.2 Demostración funcional | Vídeo enlazado; app en vivo | Hueco | Demo grabada 3-4 min + pregenerado para que la app nunca "falle" en directo |

---

## Resumen: los 8 cambios más importantes al plan

1. **Hacer visible la orquestación** (H1): router CLIP/SigLIP de imágenes, puertas de calidad con reintento (grounding de cifras + anti-recomendación), Whisper sobre el podcast generado (WER + SRT real), paralelismo y una pestaña "Cómo se hizo" con el grafo de modelos, latencias y decisiones. ≈ 11 h, D1-D2.
2. **Demo que no puede fallar** (H2): briefing real pregenerado en `data/samples/demo_briefing/` (rutas relativas) mostrado al abrir la app, modo "sin claves" con edge-tts real, e insignias que delaten cualquier proveedor en mock. ≈ 4,5 h, D1.
3. **Prometer solo lo que se demuestra** (H3): texto→imagen **por API** (no SDXL local), captura de cartera → `Portfolio` por visión, audio al uploader y tabla de modalidades con columna "Activo en la demo". ≈ 5 h, D2.
4. **Blindar el camino crítico hoy** (H4): smoke real de Anthropic/Whisper/edge-tts y verificación del ID `claude-sonnet-5-5`, límite de gasto, Google News RSS en español en lugar de depender de yfinance `.MC`, normalización de tickers/cifras para TTS, vídeo con ffmpeg directo a 720p.
5. **Rebalancear carriles y fijar integración** (H9): C está sobrecargado (Telegram a A, calidad/métricas a B); ramas cortas con PR a `main` en 5 *syncs* (lun 20:00; mar 13:00/18:00; mié 13:00/18:00), CI verde obligatorio, `schemas.py` con un único dueño y solo cambios aditivos.
6. **Adelantar congelaciones** (H9): *feature freeze* el miércoles a las 22:00 y *code freeze* el jueves a las 11:00, con entrega a las 16:30; go/no-go explícitos el martes a las 22:00 y el miércoles a las 13:00 con un orden de recorte nuevo (Telegram antes que email; traza y grounding lo último en caer).
7. **Endurecer el 4.1** (H6): costes fijos de licencias de datos/noticias (yfinance y RSS no valen en producción), punto de equilibrio con B2B2C como motor, MAR (el sentimiento por ticker puede ser recomendación implícita), AI Act art. 50 ya en vigor, Azure Speech como TTS de producción, y latencias/costes **medidos** (p50/p95) en lugar de objetivos.
8. **Recortar amplitud que no puntúa** (H10, H7): un solo LLM alternativo como mucho; fuera del registry Qwen/SDXL/ElevenLabs/Whisper local si no se implementan (no entregar stubs); y reinvertir esas horas en README con capturas arriba, pitch PDF y demo grabada de 3-4 min (hoy al 0 %).
