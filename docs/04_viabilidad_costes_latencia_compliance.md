# 04 · Viabilidad: costes, latencias, compliance y monetización

> **Qué está medido y qué no.** La columna **«Medido»** sale de los `StepMetric` de ejecuciones reales del
> 05-oct-2026 (ver [método](#método-de-medición)). Todo lo demás (columna «Estimación», escenarios de
> monetización, pasos aún no implementados) sigue siendo **estimación a verificar**. El coste «medido» es a su
> vez una **estimación con tokens reales**: tokens que devuelve la API × tarifas de `src/briefer/costs.py`; no es
> la factura del proveedor (contraste pendiente, ver [05 · D2](05_roadmap_TODO.md#nuevas-y-heredadas-de-d1-prioridad-alta)).

## Método de medición

- **Fecha y entorno:** lun 5-oct-2026, 10:56-11:15 (hora local), portátil Windows 10 con conexión doméstica,
  código final de la integración de la Fase 1.
- **Briefing:** 3 ejecuciones de `pipeline.run_briefing(settings.default_tickers, uploads=[resultados_ejemplo.pdf,
  grafico_ejemplo.png], mode="real")` desde un script, sin UI. **5 tickers** (SAN.MC, ITX.MC, IBE.MC, AAPL, NVDA)
  + índices de contexto ^IBEX y ^GSPC. B1 sin caché (todo por red); B2 y B3 con noticias y precios servidos por la
  caché diaria (`data/cache`); IA y TTS se ejecutan siempre de verdad. B2 (`20261005-110721-a127a9`) es el
  briefing pregenerado de `data/samples/demo_briefing/`.
- **Q&A:** `answer_question(texto, briefing_pregenerado, speak=True, mode="real")`, 2 preguntas × 2 procesos
  (la 1.ª pregunta de cada proceso arranca en frío).
- **Proveedores:** Claude Sonnet 5.5 (Analista, visión de PDF y gráfico), Claude Haiku 4.5 (Guionista,
  estructurado de documentos, Q&A), edge-tts (2 voces es-ES, 6 hilos), yfinance + RSS (Google News, Yahoo,
  Expansión, Europa Press).
- **Latencia por paso** = `StepMetric.latency_s`; **pared** = reloj de extremo a extremo de `run_briefing`. La
  suma de pasos supera a la pared porque ingesta y subidas van en paralelo.
- Con 3 briefings y 4 preguntas no hay p50/p95 fiables: se dan rangos. p50/p95 con ≥ 5 + 5 ejecuciones en el
  [camino de revisión 1](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2).

## 1. Supuestos y tarifas

| Supuesto | Valor usado | Comentario |
| --- | --- | --- |
| Noticias por briefing tras el filtro | ~20 | **Medido:** 20 obtenidas, 16 relevantes (3 de índices de contexto) con 5 tickers |
| Duración del podcast | 4 min | **Medido:** 3:58-4:20 min, 18-20 intervenciones (~590 palabras, ~3.500 caracteres) |
| Contexto del Q&A | ~6.000 tokens de entrada, ~300 de salida | Briefing del día como contexto (estimación; coste medido abajo) |
| Pregunta por voz | ~15 s de audio | STT sin implementar: estimación |
| Claude Sonnet 5.5 | **2 $/M entrada, 10 $/M salida** | **Verificado** en la tarifa oficial el 05-oct-2026 (`costs.py`) |
| Claude Haiku 4.5 | **1 $/M entrada, 5 $/M salida** | **Verificado** el 05-oct-2026 (`costs.py`) |
| Gemini 2.5 Flash | ~0,30 $/M entrada, ~2,50 $/M salida | Estimación a verificar |
| Whisper API | ~0,006 $/min | Estimación a verificar; local = 0 € de API |
| ElevenLabs | ~0,18-0,30 $ por 1.000 caracteres según plan | Estimación a verificar; muy dependiente del plan |
| edge-tts | 0 € | Servicio gratuito no oficial, sin SLA (ver riesgos) |
| Tipo de cambio | 1 $ ≈ 0,86 € | `costs.USD_TO_EUR`, estimación oct-2026 |

## 2. Coste por briefing

| Paso | Proveedor por defecto | Estimación previa | **Medido** (media de 3, 05-oct) |
| --- | --- | --- | --- |
| Noticias y precios | yfinance + RSS | 0 € | **0 €** |
| Lectura de gráfico (si se sube) | Claude Sonnet 5.5 visión + Haiku 4.5 (estructura) | ~0,01 € | **0,0170 €** |
| Lectura de PDF (si se sube) | `pypdf` + Sonnet 5.5 visión en páginas pobres + Haiku 4.5 | ~0,05-0,08 € | **0,0152 €** |
| Clasificación CLIP (opcional) | Local | 0 € | no implementado |
| Agente Analista | Sonnet 5.5 (`effort="medium"`, incl. reintento de *grounding* si lo hay) | ~0,05 € | **0,0248 €** |
| Agente Guionista | Haiku 4.5 | ~0,01 € | **0,0081 €** |
| TTS 2 voces | **edge-tts** | 0 € | **0 €** |
| TTS 2 voces (premium) | ElevenLabs | ~0,55-0,90 € (~3.500 caracteres) | no implementado |
| Gráficos, transcripción, guardado | matplotlib / local | 0 € | **0 €** |
| Portada (opcional) | API texto→imagen | ~0,02-0,04 € | no implementado |
| Vídeo (opcional) | ffmpeg | 0 € | no implementado |
| **Total briefing base** (sin subidas, edge-tts) | | ~0,06-0,08 € | **≈ 0,033 €** (Analista + Guionista; derivado de la medición) |
| **Total con PDF + gráfico** | | ~0,12-0,17 € | **≈ 0,065 €** (0,0640-0,0660 €) |
| **Total con ElevenLabs** | | ~0,80-1,15 € | no medido |

Lectura: el coste lo domina **Sonnet** (Analista + dos lecturas de visión ≈ 87 % del total con subidas). El
Guionista en Haiku cuesta ~3 veces menos que el Analista. Gasto real total de la sesión de integración (estimado
con `costs.py`): ≈ 0,35 € (5 briefings ≈ 0,32 €, 4 preguntas ≈ 0,02 €, humo + tests `live` ≈ 0,01 €).

### Coste por pregunta Q&A

| Paso | Proveedor | Estimación previa | **Medido** (4 preguntas, 05-oct) |
| --- | --- | --- | --- |
| STT | Whisper API | ~0,002 € | no implementado |
| LLM | Haiku 4.5 (contexto = briefing) | ~0,007 € | **0,0046-0,0048 €** |
| TTS | edge-tts | 0 € | **0 €** |
| **Total** | | ~0,01 € | **≈ 0,005 €** (+ ~0,002 € cuando haya STT por API) |

Otras: `scripts/smoke_real.py` completo ≈ 0,0046 €; demo sin claves con voces reales (`demo.py --demo-voices`)
0 €.

**Conclusión:** con TTS gratuito el coste es de **céntimos por briefing** (≈ 0,03-0,07 €) y de medio céntimo por
pregunta. ElevenLabs multiplicaría el coste por ~10-15: solo tiene sentido si el audio se genera **una vez y se
comparte** entre muchos usuarios (ver estrategias).

## 3. Latencias

Dos regímenes distintos:

- **Briefing:** se pregenera en **batch** (madrugada, antes de la apertura). El usuario no lo espera; en la
  demo se genera en vivo y basta con mostrar progreso por pasos.
- **Q&A por voz:** interactivo. Objetivo **< 10 s** desde que el usuario suelta el botón hasta que empieza a
  sonar la respuesta.

| Paso | Objetivo (estimación) | **Medido** (05-oct; B1 sin caché · B2-B3 con caché) | Cómo se consigue |
| --- | --- | --- | --- |
| Noticias | 2-5 s | **5,8 s** sin caché · **0,2-0,3 s** con caché | Fuentes en paralelo (timeout 8 s/petición, 25 s total) + caché diaria |
| Precios | (con noticias) | **6,1 s** sin caché · **0,0-0,2 s** con caché | Una descarga en lote + caché diaria; en paralelo con noticias |
| Lectura de PDF | 5-20 s | **20,8-24,4 s** | Visión solo en páginas pobres en texto; en paralelo con la ingesta |
| Lectura de gráfico | 3-8 s | **20,4-25,1 s** | Visión + estructurado con Haiku; en paralelo con la ingesta |
| Analista | 10-30 s | **11,1-11,5 s** | Salida estructurada, prompt acotado |
| Guionista | 10-20 s | **13,3-14,6 s** | Haiku 4.5 |
| TTS (~20 intervenciones) | 10-40 s | **12,1-13,2 s** | Síntesis por línea en paralelo (6 hilos) |
| Transcripción + SRT + gráficos + guardado | 1-4 s | **1,5-1,8 s** | Tiempos del propio TTS, sin modelo extra |
| Vídeo | 30-90 s | no implementado | ffmpeg 720p, imágenes estáticas + audio |
| **Briefing completo** (con PDF + gráfico) | 1-3 min sin vídeo | **61,1-63,6 s** de pared | Batch nocturno; en vivo con barra de progreso |
| Briefing sin subidas | — | **≈ 40 s** (derivado: pared − visión; no medido directamente) | |
| STT de la pregunta | 1-3 s | no implementado | Whisper API |
| LLM Q&A | 3-6 s | **2,0-2,3 s** en caliente · **6,6-7,5 s** 1.ª pregunta (frío) | Haiku; contexto del briefing ya resumido |
| TTS de la respuesta | 1-2 s | **3,4-6,6 s** | edge-tts; texto normalizado para voz |
| **Q&A completo** (texto → respuesta hablada) | **< 10 s** | **6,0-7,0 s** en caliente (cumple) · **11,0-13,2 s** en frío (**no cumple**) | Solo texto (sin audio): < 8 s siempre. Mitigación en D2: precalentar clientes, respuesta más corta, mostrar texto antes que audio |

**Camino crítico del briefing:** visión del PDF o del gráfico (~21-25 s, en paralelo con la ingesta) → Analista
(~11 s) → Guionista (~13 s) → TTS (~13 s) ≈ 60 s. Antes de paralelizar las subidas (mismo día, código previo):
91,8 s sin caché y 127,1 s con caché (el PDF tardó 63 s en esa ejecución por variabilidad de la API).

## 4. Estrategias de coste y latencia

| Estrategia | Efecto | Estado en MVP |
| --- | --- | --- |
| **Generación por ticker compartida** entre usuarios: el análisis de «SAN.MC hoy» se calcula una vez y se reutiliza para todos los que lo siguen; por usuario solo se compone el guion | El coste deja de crecer con usuarios y pasa a crecer con tickers distintos | Diseño |
| **Caché diaria de entradas** (noticias y precios por fuente y ticker) | Ingesta de ~6 s → ~0,3 s en la 2.ª ejecución del día; menos *rate limit* de Yahoo/Google | **Hecho** (`ingest/cache.py`; medido) |
| **Batch nocturno** | Latencia percibida 0 para el briefing; se puede usar la API batch del proveedor (más barata) | Fuera del MVP (script manual) |
| **Modelos baratos donde basta** (Haiku para guion, Q&A y estructurado de documentos; Sonnet para análisis y visión) | Guionista ≈ 0,008 € frente a ≈ 0,025 € del Analista | **Hecho** (configurable por `BRIEFER_LLM_MODEL_CHEAP`) |
| **Caché de prompts** del sistema y del contexto del briefing en el Q&A | Menos coste y latencia en preguntas sucesivas | Pendiente de evaluar |
| **TTS gratuito por defecto** (edge-tts) y premium solo para contenido compartido | Coste de audio 0 € | **Hecho** |
| **Modelos locales** (Whisper, Qwen2.5-VL, SDXL-Turbo, CLIP) | 0 € de API a cambio de hardware | *Stubs*; fuera del MVP |
| **Paralelismo** en ingesta, subidas y TTS | Pared 61-64 s frente a 82-100 s de suma de pasos | **Hecho** (medido) |
| **Precalentar** clientes HTTP (Anthropic, edge-tts) en la página Preguntar | Q&A en frío de 11-13 s → objetivo < 10 s | Pendiente (D2) |

## 5. Marco regulatorio

### MiFID II · información genérica, no asesoramiento

| Riesgo | Medida en el producto | Control en código |
| --- | --- | --- |
| Que el contenido se considere asesoramiento personalizado (recomendación sobre un instrumento adaptada a la situación del cliente) | El producto da **información y explicación** de noticias; no evalúa idoneidad ni objetivos del usuario | Prompts `agents/prompts/*.md` |
| Recomendaciones de compra/venta | Prohibidas en los prompts de los tres agentes; segunda barrera determinista que elimina frases con recomendación; el Q&A reconduce «¿vendo?» con un recordatorio | `agents/guardrails.py` (`contains_advice`, `strip_advice`, `asks_for_advice`) |
| Cifras inventadas (*hallucination*) | Puerta de *grounding*: cifras del análisis que no estén en el contexto → un reintento y, si persisten, se eliminan esas frases; resultado visible en la traza | `guardrails.untraceable_figures`, `analyst.analyze`, `StepMetric.detail` |
| Datos simulados presentados como reales | Si un paso cae a mock o a datos de ejemplo, la UI lo avisa y la traza lo pinta en naranja | `logging_utils.step_fell_back`, `players.render_run_warnings`, `app/components/trace.py` |
| Falta de transparencia | `Analysis.disclaimer` obligatorio y no vacío; disclaimer **hablado** al final del podcast; pie fijo en la UI, email y Telegram | `schemas.DISCLAIMER_ES`, `scriptwriter.CLOSING_LINE_ES` |
| Uso de la cartera | Se usa para **seleccionar** qué noticias explicar, no para recomendar cambios en ella | `pipeline._normalize_tickers` |
| Escalado B2B2C | Si un broker lo integra, el contenido se presenta como comunicación informativa; la responsabilidad regulatoria del canal se fija por contrato | — |

Texto base del disclaimer: *«Contenido informativo generado con IA. No constituye asesoramiento de inversión
ni recomendación de compra o venta. Puede contener errores. Las voces son sintéticas.»*

### RGPD · datos de cartera

| Principio | Aplicación |
| --- | --- |
| Minimización | Solo se piden tickers y pesos/cantidades; nada de saldos, IBAN, identidad ni credenciales de broker |
| Qué sale a terceros | Al LLM solo van tickers y noticias; los pesos solo si aportan contexto y nunca junto a datos identificativos |
| Base jurídica y consentimiento | Consentimiento explícito al guardar la cartera y para el envío por email/Telegram (pendiente en la UI, D2) |
| Almacenamiento | Local en `data/` en el MVP; `.env` y `data/outputs/` fuera de git |
| Derechos | Borrado de cartera e histórico desde la UI (pendiente) |
| Encargados de tratamiento | Proveedores de IA con DPA y opción de no entrenar con los datos enviados (a verificar por proveedor) |
| Audio del usuario | La pregunta grabada se transcribe y se descarta; no se guarda salvo opt-in (pendiente con el STT real, D2) |

### Derechos de autor de las noticias

- Por cada noticia solo se muestra y se versiona **titular + extracto breve + fuente + enlace**
  (`NewsItem.title`, `summary`, `source`, `url`); nunca el cuerpo del artículo.
- El análisis, el guion y el Q&A **resumen con palabras propias** y **citan la fuente** (ids de noticia en
  `KeyPoint.sources`, citas `[id]` en el Q&A).
- **Briefing pregenerado versionado** (`data/samples/demo_briefing/briefing.json`): los extractos (`summary`) de
  las noticias reales se han recortado a **≤ 200 caracteres** (con «…»); titulares, fuentes y URL intactos.
- Pendiente (D2): la ingesta guarda hoy extractos de hasta 600 caracteres (`news.SUMMARY_MAX_CHARS`) para dar
  contexto al Analista; hay que acotar lo que se **muestra** y lo que se exporta a ~200 caracteres.
- Se priorizan fuentes con feed público (RSS de Google News, Yahoo Finance, Expansión, Europa Press). Para uso
  comercial habría que licenciar las noticias (coste fijo a añadir en D2).

### AI Act · transparencia

- Aviso explícito de que el audio y el vídeo son **generados por IA** y las voces son **sintéticas**: en la UI,
  en el cierre hablado del podcast y en los **metadatos ID3 del MP3** (`podcast.AI_AUDIO_METADATA`, hecho).
- No se clonan voces de personas reales (voces neuronales de catálogo es-ES).
- Las portadas generadas llevarán la marca «imagen generada por IA» (portada pendiente, D2).

## 6. Monetización

Números **orientativos** para dimensionar, no previsiones. Los costes variables usan ahora los costes **medidos**
(≈ 0,033 € por briefing base, ≈ 0,065 € con dos subidas, ≈ 0,005 € por pregunta + STT estimado).

| Plan | Precio | Incluye | Coste variable estimado por usuario y mes |
| --- | --- | --- | --- |
| Free | 0 € | 3 tickers, briefing compartido por ticker, sin Q&A por voz (o 3/mes), edge-tts | ~0,05-0,10 € |
| Pro | 5,99 €/mes *(a validar)* | Cartera completa, Q&A por voz (~20/mes), PDFs y gráficos, vídeo, email/Telegram | ~0,9-1,5 € (22 briefings × ~0,035 € + 20 Q&A × ~0,007 € + ~5 subidas × ~0,016 €; sin compartición por ticker) |
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
tipo Azure Speech, hosting), que se añaden en D2.
