# 04 · Viabilidad: costes, latencias, compliance y monetización

> **Qué está medido y qué no.** Las columnas **«Medido»** salen de los `StepMetric` de ejecuciones reales del
> 05-oct-2026 (ver [método](#método-de-medición)). Todo lo demás (columna «Estimación», escenarios de
> monetización, pasos aún no implementados) sigue siendo **estimación a verificar**. El coste «medido» es a su
> vez una **estimación con tokens reales**: tokens que devuelve la API × tarifas de `src/briefer/costs.py`; no es
> la factura del proveedor (contraste pendiente, ver [05 · D2](05_roadmap_TODO.md#nuevas-y-heredadas-de-d1-prioridad-alta)).

## Método de medición

Hay dos tandas, las dos del lun 5-oct-2026 en un portátil Windows 10 con conexión doméstica, `.env` real y sin UI
(`pipeline.run_briefing` / `pipeline.answer_question` desde un script):

- **Fase 1 (10:56-11:15):** 3 ejecuciones de `run_briefing(settings.default_tickers, uploads=[resultados_ejemplo.pdf,
  grafico_ejemplo.png], mode="real")`, B1 sin caché y B2-B3 con noticias y precios de la caché diaria; 4
  preguntas al Q&A (`speak=True`, 2 por proceso). Son las cifras de referencia de coste medio.
- **Final, tras la revisión de F0 y F1 (≈ 13:05):** 1 briefing con el código revisado, `use_cache=False` (todo
  descargado de nuevo), que es el **pregenerado** de `data/samples/demo_briefing/` (`20261005-130504-0f8ae2`).
  Q&A sobre ese briefing **en dos tiempos, como la UI** (`speak=False` + `speak_answer`), con y sin
  `pipeline.warmup`. STT con 3 preguntas sintetizadas con edge-tts y WER contra el texto.
- **Entradas comunes:** 5 tickers (SAN.MC, ITX.MC, IBE.MC, AAPL, NVDA) + índices de contexto ^IBEX y ^GSPC, el PDF
  y la captura de gráfico de ejemplo.
- **Proveedores:** Claude Sonnet 5.5 (Analista, visión de PDF y gráfico), Claude Haiku 4.5 (Guionista,
  estructurado de documentos, Q&A), edge-tts (2 voces es-ES, 6 hilos), OpenAI `gpt-4o-mini-transcribe` (STT),
  yfinance + RSS (Google News, Bing News, Yahoo, Expansión, Europa Press).
- **Latencia por paso** = `StepMetric.latency_s`; **pared** = reloj de extremo a extremo de `run_briefing`. La
  suma de pasos supera a la pared porque ingesta y subidas van en paralelo.
- Con 4 briefings y 7 preguntas no hay p50/p95 fiables: se dan rangos. p50/p95 con ≥ 5 + 5 ejecuciones en el
  [camino de revisión 1](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2).

## 1. Supuestos y tarifas

| Supuesto | Valor usado | Comentario |
| --- | --- | --- |
| Noticias por briefing tras el filtro | ~20 | **Medido:** 20 seleccionadas, 16 relevantes. Final: 30 fuentes consultadas (0 fallidas), 6 casi duplicadas y 11 fichas de cotización descartadas |
| Noticias con extracto | — | **Medido:** ~45-50 % en frío (el enriquecimiento tiene un presupuesto de 3 s) y ~80 % desde la 2.ª ejecución del día (caché de URL y extractos). Extractos ≤ 200 caracteres |
| Duración del podcast | 4 min (objetivo, banda 3-5) | **Medido:** 3:58-4:20 min en la Fase 1; **5:27** en el pregenerado final (28 intervenciones; por encima del objetivo, ver riesgos en [06](06_estado_actual.md)) |
| Contexto del Q&A | ~6.000 tokens de entrada, ~300 de salida | Briefing del día como contexto (estimación; coste medido abajo) |
| Pregunta por voz | 5-15 s de audio | Las 3 preguntas de prueba duraban unos segundos; coste por minuto de audio |
| Claude Sonnet 5.5 | **2 $/M entrada, 10 $/M salida** | **Verificado** en la tarifa oficial el 05-oct-2026 (`costs.py`) |
| Claude Haiku 4.5 | **1 $/M entrada, 5 $/M salida** | **Verificado** el 05-oct-2026 (`costs.py`) |
| Caché de prompts de Anthropic | lectura 0,1×, escritura 1,25× la tarifa de entrada | `costs.CACHE_READ_MULTIPLIER` / `CACHE_WRITE_MULTIPLIER`; se aplica si la API informa tokens de caché |
| Gemini 2.5 Flash | ~0,30 $/M entrada, ~2,50 $/M salida | Estimación a verificar |
| OpenAI STT | `gpt-4o-mini-transcribe` 0,003 $/min · `whisper-1` 0,006 $/min | `costs.STT_PRICES_USD_PER_MIN`; tarifa pública, a verificar con la factura |
| ElevenLabs | ~0,18-0,30 $ por 1.000 caracteres según plan | Estimación a verificar; muy dependiente del plan |
| edge-tts | 0 € | Servicio gratuito no oficial, sin SLA (ver riesgos) |
| Tipo de cambio | 1 $ ≈ 0,86 € | `costs.USD_TO_EUR`, estimación oct-2026 |

## 2. Coste por briefing

| Paso | Proveedor por defecto | Estimación previa | **Medido F1** (media de 3) | **Medido final** (pregenerado) |
| --- | --- | --- | --- | --- |
| Noticias y precios | yfinance + RSS | 0 € | **0 €** | **0 €** |
| Lectura de gráfico (si se sube) | Claude Sonnet 5.5 visión + Haiku 4.5 (estructura) | ~0,01 € | **0,0170 €** | **0,0157 €** |
| Lectura de PDF (si se sube) | `pypdf` + Sonnet 5.5 visión en páginas pobres + Haiku 4.5 | ~0,05-0,08 € | **0,0152 €** | **0,0145 €** |
| Clasificación CLIP (opcional) | Local | 0 € | no implementado | no implementado |
| Agente Analista | Sonnet 5.5 (`effort="medium"`, incl. reintento de *grounding* si lo hay) | ~0,05 € | **0,0248 €** | **0,0261 €** |
| Agente Guionista | Haiku 4.5 (con puertas deterministas, [ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md)) | ~0,01 € | **0,0081 €** | **0,0100 €** |
| TTS 2 voces | **edge-tts** | 0 € | **0 €** | **0 €** |
| TTS 2 voces (premium) | ElevenLabs | ~0,55-0,90 € (~3.500 caracteres) | no implementado | no implementado |
| Gráficos, transcripción, guardado | matplotlib / local | 0 € | **0 €** | **0 €** |
| Portada (opcional) | API texto→imagen | ~0,02-0,04 € | no implementado | no implementado |
| Vídeo (opcional) | ffmpeg | 0 € | no implementado | no implementado |
| **Total briefing base** (sin subidas, edge-tts) | | ~0,06-0,08 € | **≈ 0,033 €** (derivado) | **≈ 0,036 €** (derivado: Analista + Guionista) |
| **Total con PDF + gráfico** | | ~0,12-0,17 € | **≈ 0,065 €** (0,0640-0,0660 €) | **0,0662 €** |
| **Total con ElevenLabs** | | ~0,80-1,15 € | no medido | no medido |

Lectura: el coste lo domina **Sonnet** (Analista + dos lecturas de visión ≈ 85 % del total con subidas). El
Guionista en Haiku cuesta ~2,6 veces menos que el Analista; pasarlo a Sonnet lo multiplicaría por 2,6-2,9
([ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md)). Si el Analista reintenta (compliance o
*grounding*), un briefing puede subir a 0,10-0,11 € (2 intentos descartados en la tanda final). Gasto estimado
de la sesión de revisión: **≈ 0,31 €** (3 briefings reales ≈ 0,28 €, Q&A, STT, humo y tests `live`); en la Fase 1,
≈ 0,35 €.

### Coste por pregunta Q&A

| Paso | Proveedor | Estimación previa | **Medido** (05-oct) |
| --- | --- | --- | --- |
| STT | OpenAI `gpt-4o-mini-transcribe` | ~0,002 € | ≈ 0,0003 € por 5-10 s de audio (derivado de 0,003 $/min; `qa.stt` lo calcula con `last_duration_s`) |
| LLM | Haiku 4.5 (contexto = briefing) | ~0,007 € | **0,0046-0,0053 €** |
| TTS | edge-tts | 0 € | **0 €** |
| **Total** | | ~0,01 € | **≈ 0,005 €** por texto · **≈ 0,0055 €** por voz |

Otras: `scripts/smoke_real.py` completo ≈ 0,005 € (incluye STT con WER); demo sin claves con voces reales
(`demo.py --demo-voices`) 0 €.

**Conclusión:** con TTS gratuito el coste es de **céntimos por briefing** (≈ 0,035-0,07 €) y de medio céntimo por
pregunta, también por voz. ElevenLabs multiplicaría el coste por ~10-15: solo tiene sentido si el audio se
genera **una vez y se comparte** entre muchos usuarios (ver estrategias).

## 3. Latencias

Dos regímenes distintos:

- **Briefing:** se pregenera en **batch** (madrugada, antes de la apertura). El usuario no lo espera; en la
  demo se genera en vivo y basta con mostrar progreso por pasos.
- **Q&A por voz:** interactivo. Objetivo **< 10 s** desde que el usuario suelta el botón hasta que empieza a
  sonar la respuesta.

### Briefing

| Paso | Objetivo (estimación) | **Medido F1** (B1 sin caché · B2-B3 con caché) | **Medido final** (sin caché) | Cómo se consigue |
| --- | --- | --- | --- | --- |
| Noticias | 2-5 s | **5,8 s** · **0,2-0,3 s** con caché | **11,9 s** (30 fuentes en 8,2 s + enriquecimiento ≤ 3 s) | Fuentes en paralelo (timeout 8 s/petición, 25 s total), presupuesto de 3 s para extractos, caché diaria |
| Precios | (con noticias) | **6,1 s** · **0,0-0,2 s** con caché | **8,0 s** | Una descarga en lote + caché diaria; en paralelo con noticias |
| Lectura de PDF | 5-20 s | **20,8-24,4 s** | **31,8 s** | Visión solo en páginas pobres en texto; en paralelo con la ingesta |
| Lectura de gráfico | 3-8 s | **20,4-25,1 s** | **31,6 s** | Visión + estructurado con Haiku; en paralelo con la ingesta |
| Analista | 10-30 s | **11,1-11,5 s** | **11,0 s** | Salida estructurada, prompt acotado |
| Guionista | 10-20 s | **13,3-14,6 s** | **17,9 s** | Haiku 4.5 + puertas deterministas |
| TTS (~20-28 intervenciones) | 10-40 s | **12,1-13,2 s** | **20,4 s** (5:27 de audio + `loudnorm`) | Síntesis por línea en paralelo (6 hilos) |
| Transcripción + SRT + gráficos + guardado | 1-4 s | **1,5-1,8 s** | **1,7 s** | Tiempos del propio TTS, sin modelo extra |
| Vídeo | 30-90 s | no implementado | no implementado | ffmpeg 720p, imágenes estáticas + audio |
| **Briefing completo** (con PDF + gráfico) | 1-3 min sin vídeo | **61,1-63,6 s** de pared | **82,9 s** de pared (134,4 s de suma) | Batch nocturno; en vivo con barra de progreso |
| Briefing sin subidas | — | **≈ 40 s** (derivado) | **≈ 50 s** (derivado: pared − visión) | |

La final es más lenta que la F1 por tres motivos medidos: la visión de la API tardó ~31 s (variabilidad; en otra
ejecución de la F1 el PDF tardó 63 s), hay más fuentes de noticias y un enriquecimiento de extractos, y el guion
fue más largo (28 intervenciones, 5:27 de audio). **Camino crítico:** visión (~21-32 s, en paralelo con la
ingesta) → Analista (~11 s) → Guionista (~13-18 s) → TTS (~12-20 s) ≈ 60-80 s.

### Q&A

| Caso (medido el 05-oct) | Texto en pantalla | Texto + voz | Coste |
| --- | --- | --- | --- |
| Fase 1: 1.ª pregunta del proceso, `speak=True` | — | **11,0-13,2 s** (no cumple) | 0,0046 € |
| Fase 1: 2.ª pregunta | — | **6,0-7,0 s** | 0,0047-0,0048 € |
| Final: 1.ª pregunta en frío **sin** `warmup` | 9,4 s | 12,9 s (no cumple) | 0,0053 € |
| Final: `pipeline.warmup(mode="real")` (en segundo plano al abrir «Preguntar») | — | 5,8 s, sin coste (LLM 4,1 · visión 0,4 · TTS 1,3) | 0 € |
| Final: 1.ª pregunta en frío **con** `warmup` | **3,0 s** | **5,2 s** (cumple) | 0,0052 € |
| Final: 2.ª pregunta (caliente) | **1,8 s** | **4,4 s** (cumple) | 0,0052 € |
| STT de la pregunta (`gpt-4o-mini-transcribe`, 3 preguntas) | 1,3 s de media, WER 0 | — | ≈ 0,0003 € |
| **Q&A por voz completo** (derivado: STT + Q&A con `warmup`) | ≈ 4,3 s | **≈ 6,5 s** (cumple) | ≈ 0,0055 € |

Antes de `warmup`, la 1.ª pregunta tardaba 16-17 s en la UI: ~4,7 s eran importar el SDK de Anthropic, ~1,4 s
importar `edge_tts` y el resto, crear el cliente y el *handshake* TLS. Ahora la página lanza `warmup` en un hilo
(`st.cache_resource`, una vez por proceso y modo), usa un **cliente Anthropic compartido** y pinta el texto antes
de sintetizar la voz (`speak=False` + `speak_answer`).

STT, comparativa (3 preguntas financieras con «Inditex», «IBEX 35», «Iberdrola», «Nvidia», «S&P 500»):
`whisper-1` WER 0, 2,55 s, 0,006 $/min · **`gpt-4o-mini-transcribe` WER 0, 1,28 s, 0,003 $/min** (por defecto).
Con un WAV mudo, `whisper-1` se inventa texto y cualquier modelo con `prompt` lo repite: no se envía `prompt` y el
silencio se corta en local sin llamar a la API.

## 4. Estrategias de coste y latencia

| Estrategia | Efecto | Estado en MVP |
| --- | --- | --- |
| **Generación por ticker compartida** entre usuarios: el análisis de «SAN.MC hoy» se calcula una vez y se reutiliza para todos los que lo siguen; por usuario solo se compone el guion | El coste deja de crecer con usuarios y pasa a crecer con tickers distintos | Diseño |
| **Caché diaria de entradas** (noticias y precios por fuente y ticker) + caché de 7 días de URL finales, extractos y `robots.txt` | Ingesta de ~6-12 s → ~0,3 s en la 2.ª ejecución del día; extractos del ~45-50 % al ~80 %; menos *rate limit* | **Hecho** (`ingest/cache.py`, `ingest/article_meta.py`; purga automática a 7 días) |
| **Batch nocturno** | Latencia percibida 0 para el briefing; se puede usar la API batch del proveedor (más barata) | Fuera del MVP (script manual) |
| **Modelos baratos donde basta** (Haiku para guion, Q&A y estructurado de documentos; Sonnet para análisis y visión) | Guionista ≈ 0,009 € frente a ≈ 0,025 € con Sonnet | **Hecho** ([ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md); `BRIEFER_SCRIPTWRITER_MODEL` para cambiarlo) |
| **Caché de prompts** del sistema y del contexto del briefing en el Q&A | Menos coste y latencia en preguntas sucesivas | Costes preparados (0,1× / 1,25×); marcar `cache_control` en el Q&A: pendiente |
| **TTS gratuito por defecto** (edge-tts) y premium solo para contenido compartido | Coste de audio 0 € | **Hecho** |
| **STT barato** (`gpt-4o-mini-transcribe`) y silencio cortado en local | Mitad de coste y de latencia que `whisper-1`; sin llamadas inútiles | **Hecho** |
| **Modelos locales** (Whisper, Qwen2.5-VL, SDXL-Turbo, CLIP) | 0 € de API a cambio de hardware | *Stubs*; fuera del MVP |
| **Paralelismo** en ingesta, subidas y TTS | Pared 61-83 s frente a 82-134 s de suma de pasos | **Hecho** (medido) |
| **Precalentar** el SDK, el cliente HTTP compartido y edge-tts al abrir «Preguntar» + texto antes que audio | 1.ª pregunta de 12,9-17 s → 5,2 s con voz (3,0 s el texto) | **Hecho** (`pipeline.warmup`, `speak_answer`; medido) |

## 5. Marco regulatorio

### MiFID II · información genérica, no asesoramiento

| Riesgo | Medida en el producto | Control en código |
| --- | --- | --- |
| Que el contenido se considere asesoramiento personalizado (recomendación sobre un instrumento adaptada a la situación del cliente) | El producto da **información y explicación** de noticias; no evalúa idoneidad ni objetivos del usuario | Prompts `agents/prompts/*.md` |
| Recomendaciones de compra/venta | Prohibidas en los prompts de los tres agentes; segunda barrera determinista que elimina frases con recomendación (y en el Guionista, además, pide reescritura); el Q&A reconduce «¿vendo?» con un recordatorio | `agents/guardrails.py` (`contains_advice`, `strip_advice`, `asks_for_advice`), `scriptwriter.script_problems` |
| Cifras inventadas (*hallucination*) | Puerta de *grounding* en el Analista (contra el contexto) y en el Guionista (contra el análisis): cifras no trazables → un reintento y, si persisten, se eliminan esas frases; resultado visible en la traza | `guardrails.untraceable_figures`, `analyst.analyze`, `scriptwriter.write_script`, `StepMetric.detail` |
| *Prompt injection* en noticias, PDF o gráfico | El contenido de terceros va delimitado y declarado **dato** (`<documento>`, `<descripcion>`); las fuentes con forma de orden se marcan con un aviso al Analista; la pregunta con forma de orden se anota | `pdf_reader.PDF_SYSTEM`, `chart_reader.STRUCTURE_SYSTEM`, `guardrails.looks_like_injection`, `analyst.suspicious_sources` / `INJECTION_NOTE`; red-team en `tests/test_agents_redteam.py` |
| Causas afirmadas sin fuente («sube por…») | Se detectan y se anotan en la traza del Q&A y en la evaluación del guion; aún no se reescriben (riesgo abierto, ver [06](06_estado_actual.md)) | `guardrails.unhedged_causal_claims` |
| Datos simulados presentados como reales | Si un paso cae a mock o a datos de ejemplo, la UI lo avisa y la traza lo pinta en naranja; los gráficos con precios sintéticos lo dicen en el título; la transcripción simulada lleva `[MOCK]`; la portada nunca destaca un briefing simulado | `logging_utils.step_fell_back`, `players.render_run_warnings`, `app/components/trace.py`, `pipeline.SYNTHETIC_PRICES_SOURCE`, `storage.is_simulated_briefing` |
| Falta de transparencia | `Analysis.disclaimer` obligatorio y no vacío; disclaimer **hablado** al final del podcast; pie fijo en la UI y en los gráficos | `schemas.DISCLAIMER_ES`, `scriptwriter.CLOSING_LINE_ES`, `charts.FOOTER_NOTE` |
| Uso de la cartera | Se usa para **seleccionar** qué noticias explicar y como contexto, no para recomendar cambios en ella | `pipeline._normalize_tickers`, prompt del Analista |
| Escalado B2B2C | Si un broker lo integra, el contenido se presenta como comunicación informativa; la responsabilidad regulatoria del canal se fija por contrato | — |

Red-team de la revisión: 31 tests sin red en `tests/test_agents_redteam.py` (inyección en noticias y PDF, consejo
personalizado, preguntas fuera de ámbito, ticker inexistente, contexto vacío, salidas maliciosas de un LLM
simulado) y las mismas familias probadas en real contra Haiku (Q&A) y Sonnet (Analista con una noticia
inyectada).

Texto base del disclaimer: *«Contenido informativo generado con IA. No constituye asesoramiento de inversión
ni recomendación de compra o venta. Puede contener errores. Las voces son sintéticas.»*

### RGPD · datos de cartera

| Principio | Aplicación |
| --- | --- |
| Minimización | Solo se piden tickers y pesos/cantidades; nada de saldos, IBAN, identidad ni credenciales de broker |
| Qué sale a terceros | A los proveedores de datos (Yahoo, Google, Bing) solo los tickers. Al LLM, en memoria, **tickers y pesos** de la cartera (no cantidades) junto a las noticias, nunca con datos identificativos |
| Almacenamiento | **La cartera no se persiste** ([ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md)): `briefing.json` lleva `portfolio: null` y no hay gráfico de cartera en `data/`; el gráfico de la sesión vive en una carpeta temporal del sistema que se borra a las 12 h. `.env`, `data/outputs/` y `data/cache/` fuera de git |
| Ficheros subidos | Cada ejecución guarda las subidas en una carpeta temporal **única** que se borra al terminar (sin colisiones entre sesiones) |
| Audio del usuario | La pregunta grabada se transcribe y **se borra** al terminar; no se guarda. Las respuestas habladas (voz sintética) sí quedan en `data/outputs/<id>/qa/` |
| Secretos y trazas | Claves y tokens se **redactan** en `StepMetric.error`, errores, log y UI (`logging_utils.redact_secrets`, `error_text`); el *traceback* solo se ve con `BRIEFER_LOG_LEVEL=DEBUG` |
| Exposición de la app | `run.ps1` / `run.sh` escuchan solo en `localhost` (`-Expose` / `--expose` para la red); Docker publica en `127.0.0.1:8501`; telemetría de Streamlit desactivada; subida máxima 50 MB |
| Base jurídica y consentimiento | Sin persistencia de la cartera no hace falta consentimiento para guardarla; sí haría falta para envíos por email/Telegram (desactivados) |
| Derechos | Sin cuentas de usuario en el MVP; el histórico se borra con la carpeta `data/outputs/` |
| Encargados de tratamiento | Proveedores de IA con DPA y opción de no entrenar con los datos enviados (a verificar por proveedor); transferencias internacionales (EE. UU.) a documentar |

### Derechos de autor de las noticias

- Por cada noticia solo se guarda, muestra y versiona **titular + extracto breve + fuente + enlace**
  (`NewsItem.title`, `summary`, `source`, `url`); nunca el cuerpo del artículo.
- Los extractos se acotan **en origen** a **≤ 200 caracteres** (`news.SUMMARY_MAX_CHARS`): los del feed y los
  que se completan con la `og:description` del medio.
- `ingest/article_meta.py` solo lee **metadatos de la cabecera** (`<head>`: `og:description`,
  `twitter:description`, `description`, `canonical`) y corta la descarga en `</head>`; respeta el **`robots.txt`**
  de cada medio (agente `market-briefer`; si no se puede leer, no se lee la página).
- El análisis, el guion y el Q&A **resumen con palabras propias** y **citan la fuente** (ids de noticia en
  `KeyPoint.sources`, citas `[id]` en el Q&A). Se enlaza la URL **final del medio**, no la de redirección.
- Fuentes con feed público (Google News, Bing News, Yahoo Finance, Expansión, Europa Press). La resolución de
  enlaces de Google News y el RSS de Bing News son **mecanismos no oficiales**, sin SLA ni licencia: si fallan se
  deja el enlace original. Para uso comercial habría que licenciar las noticias (coste fijo pendiente).

### AI Act · transparencia

- Aviso explícito de que el audio es **generado por IA** y las voces son **sintéticas** (art. 50): en la UI, en
  el cierre hablado del podcast y en los **metadatos ID3 del MP3**
  (`podcast.AI_AUDIO_METADATA`: «Market Briefer (voces sintéticas IA)»).
- No se clonan voces de personas reales (voces neuronales de catálogo es-ES).
- Vídeo y portada generada por IA están **desactivados en la UI** («en desarrollo»); cuando existan, llevarán la
  marca «generado por IA» (también en los metadatos del MP4).

## 6. Monetización

Números **orientativos** para dimensionar, no previsiones. Los costes variables usan los costes **medidos**
(≈ 0,035 € por briefing base, ≈ 0,065 € con dos subidas, ≈ 0,005 € por pregunta, también por voz).

| Plan | Precio | Incluye | Coste variable estimado por usuario y mes |
| --- | --- | --- | --- |
| Free | 0 € | 3 tickers, briefing compartido por ticker, sin Q&A por voz (o 3/mes), edge-tts | ~0,05-0,10 € |
| Pro | 5,99 €/mes *(a validar)* | Cartera completa, Q&A por voz (~20/mes), PDFs y gráficos, vídeo, email/Telegram | ~0,9-1,5 € (22 briefings × ~0,035 € + 20 Q&A × ~0,006 € + ~5 subidas × ~0,015 €; sin compartición por ticker) |
| White-label B2B2C | Fijo de integración + ~0,20-0,50 € por usuario activo/mes *(a negociar)* | Marca del cliente, API, contenido compartido por ticker | ~0,05-0,10 € gracias a la compartición |

Escenario ilustrativo (supuestos, no datos): 10.000 usuarios registrados, 4 % de conversión a Pro.

| Concepto | Cálculo | Mensual |
| --- | --- | --- |
| Ingresos Pro | 400 × 5,99 € | ~2.400 € |
| Coste variable Pro | 400 × ~1,2 € | ~480 € |
| Coste variable Free | 9.600 × ~0,08 € | ~770 € |
| Margen bruto antes de infraestructura, licencias de noticias y personal | | ~1.150 € |

Lectura: el B2C solo es viable con **compartición por ticker** y cuotas al free; el B2B2C (un broker con
50.000 usuarios activos) es donde está el volumen. Faltan los costes fijos (noticias licenciadas, TTS oficial
tipo Azure Speech, hosting), pendientes en D2.
