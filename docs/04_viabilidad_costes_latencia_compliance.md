# 04 · Viabilidad: costes, latencias, compliance y monetización

> **Qué está medido y qué no.** Las columnas **«Medido»** salen de los `StepMetric` de ejecuciones reales del
> 05-oct-2026 y, para la fase 1 (vídeo, router CLIP, cartera desde captura), del 06-oct-2026 (ver
> [método](#método-de-medición)). La portada local (SDXS) se midió el 06-oct por la tarde; la portada con Gemini
> imagen y el envío por Telegram **no se han ejecutado en real**: su coste es la tarifa oficial y su latencia no
> está medida. Todo lo demás (columna «Estimación», escenarios de
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
- **Voces y FinBERT (05-oct, noche):** cata a ciegas de 6 opciones de voz sobre el mismo guion y un briefing
  real con `BRIEFER_TTS_PROVIDER=gemini` y `BRIEFER_FINBERT=true`, `use_cache=True` (noticias y precios de la caché
  del día), que es el **pregenerado actual** (`20261005-213416-87a2a9`). Cifras de `Briefing.metrics` de ese
  briefing; las de Gemini TTS son **estimación** (tarifa sin verificar, ver § 1).
- **Fase 1 (mar 6-oct-2026):** mismo portátil. (1) Vídeo sobre el pregenerado (`media.video.make_video` con su
  audio de 217,8 s y sus gráficos) y dentro de un briefing real. (2) Router CLIP en local (CPU) con las 5 imágenes
  de `tests/fixtures/images/` (velas, líneas, tabla, cartera, paisaje) más `grafico_ejemplo.png` y
  `cartera_ejemplo.png`, cronometrando descarga, imports, carga y clasificación. (3) `pipeline.portfolio_from_screenshot`
  real sobre `data/samples/cartera_ejemplo.png` (cartera ficticia). (4) Un briefing real de verificación:
  `run_briefing(["SAN.MC", "AAPL"], uploads=[grafico_ejemplo.png, cartera_ejemplo.png, paisaje.jpg],
  make_video=True, mode="real")` con edge-tts, `BRIEFER_IMAGE_CLASSIFIER_PROVIDER=clip` y sin verificación STT.
  Tarifa de Gemini imagen: página oficial de precios de la API de Gemini (ai.google.dev/gemini-api/docs/pricing),
  consultada el 06-oct-2026.
- **Entradas comunes:** 5 tickers (SAN.MC, ITX.MC, IBE.MC, AAPL, NVDA) + índices de contexto ^IBEX y ^GSPC, el PDF
  y la captura de gráfico de ejemplo.
- **Proveedores:** Claude Sonnet 5.5 (Analista, visión de PDF y gráfico), Claude Haiku 4.5 (Guionista,
  estructurado de documentos, Q&A), edge-tts (2 voces es-ES, 6 hilos), OpenAI `gpt-4o-mini-transcribe` (STT),
  yfinance + RSS (Google News, Bing News, Yahoo, Expansión, Europa Press).
- **Latencia por paso** = `StepMetric.latency_s`; **pared** = reloj de extremo a extremo de `run_briefing`. La
  suma de pasos supera a la pared porque ingesta y subidas van en paralelo.
- Con 4 briefings y 7 preguntas no hay p50/p95 fiables: se dan rangos. p50/p95 con ≥ 5 + 5 ejecuciones en el
  [camino de revisión 1](05_roadmap_TODO.md#caminos-de-revisión-y-mejora-paralelos-a-d2).
- **Desde los briefings guardados:** `python scripts/metrics_report.py [--dir …] [--include-demo] [--markdown|--json]`
  recalcula latencia y coste por paso (p50/p95) a partir de `Briefing.metrics` en disco, sin red ni coste. Ver
  [§ 3 · Medido con `metrics_report.py`](#medido-con-metrics_reportpy-briefings-guardados).

## 1. Supuestos y tarifas

| Supuesto | Valor usado | Comentario |
| --- | --- | --- |
| Noticias por briefing tras el filtro | ~20 | **Medido:** 20 seleccionadas, 16 relevantes. Final: 30 fuentes consultadas (0 fallidas), 6 casi duplicadas y 11 fichas de cotización descartadas |
| Noticias con extracto | — | **Medido:** ~45-50 % en frío (el enriquecimiento tiene un presupuesto de 3 s) y ~80 % desde la 2.ª ejecución del día (caché de URL y extractos). Extractos ≤ 200 caracteres |
| Duración del podcast | 4 min (objetivo, banda 3-5) | **Medido:** 3:58-4:20 min en la Fase 1; 5:27 en el pregenerado de la revisión (28 intervenciones, edge-tts); **3:38** en el pregenerado actual (18 intervenciones, Gemini TTS). Ritmo recalibrado: edge-tts opción «B» **158 palabras habladas/min** (543 en 206,8 s); Gemini ≈ 163 |
| Contexto del Q&A | ~6.000 tokens de entrada, ~300 de salida | Briefing del día como contexto (estimación; coste medido abajo) |
| Pregunta por voz | 5-15 s de audio | Las 3 preguntas de prueba duraban unos segundos; coste por minuto de audio |
| Claude Sonnet 5.5 | **2 $/M entrada, 10 $/M salida** | **Verificado** en la tarifa oficial el 05-oct-2026 (`costs.py`) |
| Claude Haiku 4.5 | **1 $/M entrada, 5 $/M salida** | **Verificado** el 05-oct-2026 (`costs.py`) |
| Caché de prompts de Anthropic | lectura 0,1×, escritura 1,25× la tarifa de entrada | `costs.CACHE_READ_MULTIPLIER` / `CACHE_WRITE_MULTIPLIER`; se aplica si la API informa tokens de caché |
| Gemini 2.5 Flash | ~0,30 $/M entrada, ~2,50 $/M salida | Estimación a verificar |
| OpenAI STT | `gpt-4o-mini-transcribe` 0,003 $/min · `whisper-1` 0,006 $/min | `costs.STT_PRICES_USD_PER_MIN`; tarifa pública, a verificar con la factura |
| ElevenLabs | ~0,18-0,30 $ por 1.000 caracteres según plan | Estimación a verificar; muy dependiente del plan |
| edge-tts | 0 € | Servicio gratuito no oficial, sin SLA (ver riesgos). TTS **por defecto** |
| Gemini TTS (`gemini-3.8-flash-tts`) | ~0,50 $/M tokens de texto, ~10 $/M tokens de audio | **Estimación, verificar** (`costs.TTS_PRICES_USD_PER_MTOK`: se toma la tarifa publicada de los modelos *flash* TTS anteriores). Medido: ≈ 25 tokens de audio por segundo → **≈ 0,013 €/min de audio** (estimado) |
| FinBERT (`ProsusAI/finbert`) | 0 € | Modelo abierto, local en CPU; solo cuesta la traducción previa con Haiku |
| CLIP (`openai/clip-vit-base-patch32`) | 0 € | Modelo abierto, local en CPU (router de imágenes). Se ignora la electricidad |
| SDXS (`IDKiro/sdxs-512-dreamshaper`) | 0 € | Portada local en CPU (diffusers, 1 paso; CreativeML OpenRAIL++, permite uso comercial). Se ignora la electricidad |
| Gemini imagen (`gemini-3.1-flash-lite-image`) | **0,0336 $ por imagen 1K** (≈ 0,029 €) | **Tarifa oficial** consultada el 06-oct-2026 (`costs.IMAGE_GEN_PRICES_USD_PER_IMAGE`; `gemini-3.1-flash-image` 0,067 $). Los < 200 tokens de texto del prompt se ignoran. **No tiene nivel gratuito**: sin facturación, la API responde 429 con cuota 0. Un modelo de imagen de pago desconocido se cobra con la tarifa más alta conocida de su proveedor (con aviso de log), y el coste se anota aunque falle el titular (`pipeline._MeteredImageGen`) |
| ffmpeg (`imageio-ffmpeg`) y Telegram Bot API | 0 € | Local / gratuita |
| Tipo de cambio | 1 $ ≈ 0,86 € | `costs.USD_TO_EUR`, estimación oct-2026 |

## 2. Coste por briefing

| Paso | Proveedor por defecto | Estimación previa | **Medido F1** (media de 3) | **Medido final** (pregenerado) |
| --- | --- | --- | --- | --- |
| Noticias y precios | yfinance + RSS | 0 € | **0 €** | **0 €** |
| Lectura de gráfico (si se sube) | Claude Sonnet 5.5 visión + Haiku 4.5 (estructura) | ~0,01 € | **0,0170 €** | **0,0157 €** |
| Lectura de PDF (si se sube) | `pypdf` + Sonnet 5.5 visión en páginas pobres + Haiku 4.5 | ~0,05-0,08 € | **0,0152 €** | **0,0145 €** |
| Router CLIP (opcional) | Local (CPU) | 0 € | — | **0 €** medido (06-oct). Además **ahorra** la visión de las imágenes que descarta: ≈ 0,016 € (derivado: coste medido de una lectura de gráfico) por imagen no financiera o captura de cartera subida al briefing |
| Agente Analista | Sonnet 5.5 (`effort="medium"`, incl. reintento de *grounding* si lo hay) | ~0,05 € | **0,0248 €** | **0,0261 €** |
| Agente Guionista | Haiku 4.5 (con puertas deterministas, [ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md)) | ~0,01 € | **0,0081 €** | **0,0100 €** |
| TTS 2 voces | **edge-tts** | 0 € | **0 €** | **0 €** |
| TTS 2 voces (premium) | **Gemini TTS multi-locutor** (`BRIEFER_TTS_PROVIDER=gemini`) | — | — | **0,0471 €** estimado (pregenerado actual: 856 tokens de texto + 5.436 de audio, 3:38) |
| TTS 2 voces (premium alternativo) | ElevenLabs | ~0,55-0,90 € (~3.500 caracteres) | no implementado | no implementado |
| «Impacto de la noticia» (opcional) | Haiku 4.5 (traducción) + FinBERT local | — | — | **0,0082 €** (19 noticias, 19 traducidas) |
| Verificación del podcast con STT (opcional) | OpenAI STT | — | — | **0,0187 €** con `whisper-1` (pregenerado actual, 3:38); ≈ la mitad con `gpt-4o-mini-transcribe` |
| Gráficos, transcripción, guardado | matplotlib / local | 0 € | **0 €** | **0 €** |
| Portada (opcional) | SDXS local en CPU (`BRIEFER_IMAGE_GEN_PROVIDER=local`) | 0 € | — | **0 €** medido (06-oct) |
| Portada alternativa (de pago) | Gemini imagen `gemini-3.1-flash-lite-image` | ~0,02-0,04 € | — | **≈ 0,029 €** por portada (**tarifa oficial, no medida**: sin prueba real por falta de facturación) |
| Vídeo (opcional) | Pillow + ffmpeg (libx264) | 0 € | — | **0 €** medido (06-oct) |
| Envío por Telegram (opcional) | Bot API | 0 € | — | 0 € (tarifa; sin prueba real) |
| **Total briefing base** (sin subidas, edge-tts) | | ~0,06-0,08 € | **≈ 0,033 €** (derivado) | **≈ 0,036 €** (derivado: Analista + Guionista) · **0,0340 €** medido en 1 briefing sin subidas (`20261005-135612-88b415`, [§ 3](#medido-con-metrics_reportpy-briefings-guardados)) |
| **Total con PDF + gráfico** | | ~0,12-0,17 € | **≈ 0,065 €** (0,0640-0,0660 €) | **0,0662 €** |
| **Total pregenerado actual** (PDF + gráfico + Gemini TTS + FinBERT + verificación STT) | | — | — | **≈ 0,1836 €** estimado (Analista 0,0637 € con 1 reintento de *grounding* · podcast 0,0471 € · PDF 0,0204 € · verificación 0,0187 € · gráfico 0,0165 € · Guionista 0,0089 € · FinBERT + Haiku 0,0082 €) |
| **Total con ElevenLabs** | | ~0,80-1,15 € | no medido | no medido |

Lectura: el coste lo domina **Sonnet** (Analista + dos lecturas de visión ≈ 85 % del total con subidas). El
Guionista en Haiku cuesta ~2,6 veces menos que el Analista; pasarlo a Sonnet lo multiplicaría por 2,6-2,9
([ADR-006](decisiones/ADR-006-guionista-haiku-puertas-deterministas.md)). Si el Analista reintenta (compliance o
*grounding*), un briefing puede subir a 0,10-0,11 € (2 intentos descartados en la tanda final). Gasto estimado
de la sesión de revisión: **≈ 0,31 €** (3 briefings reales ≈ 0,28 €, Q&A, STT, humo y tests `live`); en la Fase 1,
≈ 0,35 €.

**Fase 1 (06-oct).** Briefing real de verificación (SAN.MC y AAPL, edge-tts, sin verificación STT, con vídeo y
tres subidas: gráfico, captura de cartera y una foto de paisaje): **0,0569 €** en total, 0 sustitutos. El gráfico
fue a visión (0,0157 €); la captura de cartera se desvió y el paisaje se rechazó **sin llamar a visión** (0 €);
el vídeo, 0 €. Sin el router, esas dos imágenes habrían costado otra lectura de visión cada una (sin CLIP, la
captura de cartera también se desvía, pero tras una llamada de visión, ≈ 0,016 €). **Cartera desde captura en un
briefing** (06-oct, tarde): `cartera_ejemplo.png` → 5/5 posiciones → briefing real con vídeo de 4:11, 0 fallos,
**≈ 0,039 €** en total (captura 0,0054 € + briefing 0,0332 €), `portfolio: null` y sin gráfico de cartera en disco.
Gasto real de toda la fase 1: **≈ 0,07 €** (sin contar esta última prueba).

### Coste de la cartera desde captura (página «Mi cartera»)

| Paso | Proveedor | **Medido** (06-oct, `cartera_ejemplo.png`) |
| --- | --- | --- |
| Transcripción de la tabla | Claude Sonnet 5.5 visión | incluido abajo |
| Estructurado | Claude Haiku 4.5 (`response_model`) | incluido abajo |
| Mapeo a tickers y pesos | local | 0 € |
| **Total** (`ingest.portfolio_image`) | | **≈ 0,0054 €** por captura (5/5 posiciones correctas, pesos por valor) |

Es un coste puntual (cuando el usuario carga o cambia su cartera), no por briefing.

**Voz premium (Gemini) frente a gratuita (edge-tts).** El pregenerado actual cuesta ≈ 0,18 € frente a ≈ 0,066 €
del anterior con edge-tts: la diferencia la explican la voz de Gemini (≈ 0,047 € estimado), un reintento de
*grounding* del Analista (que ese día costó 0,064 € en vez de ≈ 0,026 €), la verificación con `whisper-1` y
FinBERT. Por eso Gemini TTS es **premium**, para la demo y el contenido compartido; el valor por defecto sigue
siendo edge-tts (0 €).

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
| Vídeo (opcional) | 30-90 s | — | **8,5 s** de pared para los 217,8 s de audio del pregenerado (MP4 de 4,5 MB) · **6,3 s** en el briefing real del 06-oct | Una diapositiva fija por imagen (Pillow) + concat de ffmpeg, `-tune stillimage`, `-preset veryfast`, 720×1280 a 12 fps |
| Router CLIP (opcional, por imagen) | — | — | **70-85 ms** por imagen con el modelo cargado · 1.ª clasificación del proceso 3,7 s · carga del modelo 0,5 s · imports en frío ≈ 11 s · **1.ª descarga** (~600 MB) ≈ 28 s | Modelo cargado una vez por proceso; embeddings de texto en caché; en paralelo con la ingesta |
| Cartera desde captura (página «Mi cartera», fuera del briefing) | — | — | **8,5 s** (visión + Haiku) | Una llamada de visión + una de Haiku; el mapeo es determinista |
| Portada local (opcional; SDXS en CPU de 12 hilos, 768x432) | — | — | **4-7 s** por portada · 1.ª del proceso 23-36 s (calentamiento) · carga del modelo 15-138 s en frío (1-5 s con caché de disco caliente) · import de torch/diffusers ≈ 35 s en frío · 1.ª descarga ~1,8 GB | Modelo cargado una vez por proceso + textos con Pillow |
| Portada con Gemini (opcional) | — | — | **no medida** (sin prueba real) | Una llamada a Gemini imagen (1 reintento del SDK ante 408/429/5xx, *timeout* 90 s) + textos con Pillow |
| TTS premium Gemini (por tramos de ≤ 12 líneas / ≤ 2.000 caracteres, hasta 3 en paralelo) | — | — | **24,7 s** (3:38 de audio; pregenerado actual) · 27,4 s para un episodio de 3:20 en la cata | Diálogo entero por tramos; si falla, cae a edge-tts |
| «Impacto de la noticia» (Haiku + FinBERT, opcional) | — | — | **32,1 s** en paralelo con el Analista (19 noticias) | 1.ª carga del modelo ≈ 28 s con descarga (~840 MB en Windows sin enlaces simbólicos); después ≈ 13 s por proceso con importaciones; clasificar < 0,1 s |
| **Briefing completo** (con PDF + gráfico) | 1-3 min sin vídeo | **61,1-63,6 s** de pared | **82,9 s** de pared (134,4 s de suma) · **109,8 s** el pregenerado actual (Gemini TTS + FinBERT + verificación STT, noticias de la caché) | Batch nocturno; en vivo con barra de progreso |
| **Briefing de verificación de la fase 1** (06-oct: 2 tickers, gráfico + captura de cartera + paisaje, vídeo, edge-tts, sin verificación STT) | — | — | **82,1 s** de pared (3:00 de audio; vídeo 6,3 s) | Las dos imágenes descartadas por CLIP no esperan a visión |
| Briefing sin subidas | — | **≈ 40 s** (derivado) | **≈ 50 s** (derivado: pared − visión) · **≈ 55 s** de pared medida en 1 briefing sin caché (63,0 s de suma; [abajo](#medido-con-metrics_reportpy-briefings-guardados)) | |

La final es más lenta que la F1 por tres motivos medidos: la visión de la API tardó ~31 s (variabilidad; en otra
ejecución de la F1 el PDF tardó 63 s), hay más fuentes de noticias y un enriquecimiento de extractos, y el guion
fue más largo (28 intervenciones, 5:27 de audio). **Camino crítico:** visión (~21-32 s, en paralelo con la
ingesta) → Analista (~11 s) → Guionista (~13-18 s) → TTS (~12-20 s) ≈ 60-80 s. FinBERT no alarga el camino
crítico mientras tarde menos que el Analista (en el pregenerado actual, 32,1 s frente a 25,1 s: alargó la pared
unos 7 s, porque incluía cargar el modelo en un proceso nuevo).

### Medido con `metrics_report.py` (briefings guardados)

Salida de `python scripts/metrics_report.py --dir data/outputs --include-demo --markdown` ejecutado el
**05-oct-2026** sobre los briefings guardados en disco (sin llamadas nuevas a la API):

- **N = 2 briefings reales** (0 `demo_voices`, 0 `mock`): el pregenerado `20261005-130504-0f8ae2` (PDF + gráfico,
  sin caché, ≈ 13:05) y `20261005-135612-88b415` (sin subidas, sin caché, ≈ 13:56). Mismos 5 tickers + índices de
  contexto. La carpeta original del pregenerado en `data/outputs/` no tiene `briefing.json` (solo `qa/`) y se salta.
- El modo no se guarda en el briefing: el script lo deduce de los `StepMetric` (noticias de `samples` sin fallback
  → offline; podcast `edge` → `demo_voices`). Las cifras son solo de los reales.
- **Percentiles por interpolación lineal** (tipo 7, como `numpy.percentile`). **Con N = 2 el p50 es la media y
  el p95 casi el máximo: solo orientativos**; sirven para fijar el método, no como SLA.
- **Pared aproximada** = `created_at` − hora del id (`YYYYMMDD-HHMMSS`, se fija al empezar `run_briefing`) +
  pasos posteriores (`delivery.*`, `storage.save`); el id va truncado al segundo (error 0 a +1 s). Para el
  pregenerado da 83,1 s frente a los 82,9 s cronometrados en la tanda final.
- Coste = suma de `StepMetric.est_cost_eur` (tokens reales × tarifas de `costs.py`, no factura).

| Briefing | Subidas | Pared (aprox.) | Suma de pasos | Coste | Fallbacks |
| --- | --- | --- | --- | --- | --- |
| 20261005-130504-0f8ae2 (pregenerado) | PDF + gráfico | 83,1 s | 134,4 s | 0,0662 € | 0 |
| 20261005-135612-88b415 | sin subidas | 55,1 s | 63,0 s | 0,0340 € | 0 |
| **p50 · p95 (N = 2, orientativo)** | | 69,1 s · 81,7 s | 98,7 s · 130,8 s | 0,0501 € · 0,0646 € | 0 en 0 de 2 |

| Paso | Proveedor/modelo | N | Latencia p50 | Latencia p95 | Latencia máx | Coste p50 | Coste p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ingest.news | yfinance+rss | 2 | 10,5 s | 11,8 s | 11,9 s | 0 € | 0 € |
| ingest.prices | yfinance | 2 | 8,1 s | 8,2 s | 8,2 s | 0 € | 0 € |
| ingest.tickers | local | 2 | 0,0 s | 0,0 s | 0,0 s | 0 € | 0 € |
| ingest.pdf | anthropic/claude-sonnet-5-5 | 1 | 31,8 s | 31,8 s | 31,8 s | 0,0145 € | 0,0145 € |
| ingest.chart | anthropic/claude-sonnet-5-5 | 1 | 31,6 s | 31,6 s | 31,6 s | 0,0157 € | 0,0157 € |
| agents.analyst | anthropic/claude-sonnet-5-5 | 2 | 11,2 s | 11,3 s | 11,3 s | 0,0256 € | 0,0260 € |
| agents.scriptwriter | anthropic/claude-haiku-4-5-20251001 | 2 | 15,5 s | 17,7 s | 17,9 s | 0,0094 € | 0,0099 € |
| media.podcast | edge/edge-tts | 2 | 19,7 s | 20,3 s | 20,4 s | 0 € | 0 € |
| media.transcript | local | 2 | 0,0 s | 0,0 s | 0,0 s | 0 € | 0 € |
| media.charts | matplotlib | 2 | 1,9 s | 2,2 s | 2,2 s | 0 € | 0 € |
| storage.save | local | 2 | 0,0 s | 0,0 s | 0,0 s | 0 € | 0 € |

Lectura: sin subidas el briefing cuesta **0,034 €** y tarda **≈ 55 s** de pared (camino crítico ingesta ~9-12 s →
Analista ~11 s → Guionista ~13 s → TTS ~19 s), en línea con lo derivado arriba (≈ 0,036 € y ≈ 50 s). El **Q&A no
sale en este informe**: `QAAnswer.metrics` no se guarda en disco (en `<id>/qa/` solo queda el audio de la
respuesta; hay 2), así que sus cifras siguen siendo las de la tabla siguiente, medidas en vivo. Para p50/p95
con valor hay que acumular ≥ 5 briefings reales y volver a ejecutar el script.

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
| **Cadena de voz medida de punta a punta** (`scripts/measure_qa_voice.py`, 3 procesos nuevos; audio edge-tts → STT → Q&A → TTS, como la UI), **frío** con `warmup` (incluye STT) y caché de prompt | p50 **3,9 s** | p50 **6,4 s** (5,7-14,4 s) | ≈ 0,0014 € |
| Ídem, **caliente** (2.ª pregunta del proceso) | p50 **4,0 s** | p50 **6,0 s** (5,9-7,5 s) | ≈ 0,0013 € |
| Ídem, frío **antes** de precalentar el STT y sin caché de prompt (1.ª medición) | p50 11,5 s | p50 16,4 s (`qa.stt` 7,6-15,1 s: importar `openai`) | ≈ 0,0058 € |

**Voz del Q&A con Gemini en el podcast (05-oct):** la respuesta hablada **sigue saliendo por edge-tts** (Osa con
la voz Ximena, `pipeline.qa_tts`), así que las latencias de esta tabla no cambian: una petición a un TTS de
diálogo de pago tarda bastantes segundos más y rompería el objetivo de < 10 s. En la cata de voces se descartó
OpenAI `gpt-4o-mini-tts` por latencia: expresivo, pero tardó **309 s para 6 líneas** ese día.

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
| **Caché de prompts** del sistema y del contexto del briefing en el Q&A | Menos coste y latencia en preguntas sucesivas | **Hecho** (05-oct): contexto en el 1.er mensaje `user` con `cache_control`. Medido con Haiku: 1.ª pregunta 0,0065 € (escritura 1,25×, 5.441 tokens), siguientes **0,0011 €** (lectura 0,1×) mientras la caché siga viva (5 min) |
| **TTS gratuito por defecto** (edge-tts) y premium solo para contenido compartido | Coste de audio 0 € por defecto; Gemini ≈ 0,013 €/min (estimado) solo en la demo y el pregenerado | **Hecho** (05-oct: Gemini TTS premium con caída a edge-tts; el Q&A habla siempre con edge-tts) |
| **STT barato** (`gpt-4o-mini-transcribe`) y silencio cortado en local | Mitad de coste y de latencia que `whisper-1`; sin llamadas inútiles | **Hecho** |
| **Modelos locales** (Whisper, Qwen2.5-VL, SDXL-Turbo, CLIP) | 0 € de API a cambio de hardware | **CLIP y portada local hechos** (06-oct: router de imágenes y portada con SDXS, 0 €); Whisper local y Qwen2.5-VL, *stubs* fuera del MVP |
| **Filtrar antes de pagar**: un modelo local y gratis (CLIP) decide si una imagen merece la llamada de visión | Ahorra ≈ 0,016 € (derivado) por imagen no financiera o captura de cartera subida al briefing | **Hecho** (06-oct; medido en el briefing de verificación) |
| **Vídeo sin re-codificar fotogramas**: diapositivas fijas + concat de ffmpeg | Vídeo del episodio completo en 6-9 s y 0 € | **Hecho** (06-oct; medido) |
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
| Causas afirmadas sin fuente («sube por…») | Q&A: se detectan, se pide **una** reescritura atribuyéndolas a la fuente y, si persisten, se antepone «Según las noticias del briefing, …» (determinista); queda en la traza. Guion: se anotan en su evaluación | `guardrails.unhedged_causal_claims`, `qa.hedge_causal_claims` |
| Imagen de portada leída como dato o como recomendación | El prompt de la portada **nunca** lleva cifras, empresas, tickers ni el titular (solo estilo de marca + tono del día) y pide no dibujar flechas ni símbolos de compra/venta; los textos los pone Pillow; placa «Imagen generada por IA» | `media/cover.build_cover_prompt`, `cover.AI_LABEL` |
| Datos simulados presentados como reales | Si un paso cae a mock o a datos de ejemplo, la UI lo avisa y la traza lo pinta en naranja; los gráficos con precios sintéticos lo dicen en el título; la transcripción simulada lleva `[MOCK]`; la portada nunca destaca un briefing simulado | `logging_utils.step_fell_back`, `players.render_run_warnings`, `app/components/trace.py`, `pipeline.SYNTHETIC_PRICES_SOURCE`, `storage.is_simulated_briefing` |
| Falta de transparencia | `Analysis.disclaimer` obligatorio y no vacío; disclaimer **hablado** al final del podcast; pie fijo en la UI y en los gráficos | `schemas.DISCLAIMER_ES`, `scriptwriter.CLOSING_LINE_ES`, `charts.FOOTER_NOTE` |
| Tono de las noticias (FinBERT) leído como señal sobre el valor (MAR / recomendación implícita) | Se etiqueta el **tono de cada noticia** («impacto de la noticia: ▲ positiva · FinBERT»), junto a su fuente y con la aclaración «tono de la noticia, no recomendación»; **nunca** se agrega por ticker ni se da una puntuación del valor; opcional y apagado por defecto | `ingest/sentiment.py`, `components/theme.IMPACT_TOOLTIP`, `BRIEFER_FINBERT` |
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
| Captura de cartera (06-oct) | La captura de la pantalla de posiciones **va entera** al proveedor de visión (Anthropic) para leerla, y su transcripción al LLM barato; puede contener nombre, nº de cuenta o saldo si el usuario no recorta. Medidas: la página «Mi cartera» **recomienda recortarla** para que solo se vean las posiciones, sin nombre ni número de cuenta; la imagen se procesa como `bytes` **en memoria** (sin fichero temporal) y **no se guarda**; la `Portfolio` resultante sigue las reglas de ADR-005; el `StepMetric.detail` del paso `ingest.portfolio_image` no lleva nombres ni cifras y el log de errores solo registra el tipo de excepción; los errores de salida estructurada al leer la captura o un gráfico se registran con mensaje genérico (sin nombres ni importes en log, `StepMetric` ni UI). Si se sube en «Briefing», se desvía también sin CLIP (el prompt de visión la clasifica) sin estructurarla ni guardar nada. Si los pesos leídos no cubren todas las posiciones con una misma base, no se asigna ninguno (solo tickers) y la UI lo avisa. El vídeo nunca incluye el gráfico de cartera. Mejora pendiente: recorte o difuminado automático de cabeceras antes de enviar | `ingest/portfolio.portfolio_from_image`, `pipeline.portfolio_from_screenshot`, `app/pages/3_Mi_cartera.py` |
| Qué sale a terceros | A los proveedores de datos (Yahoo, Google, Bing) solo los tickers. Al LLM, en memoria, **tickers y pesos** de la cartera (no cantidades) junto a las noticias, nunca con datos identificativos |
| Almacenamiento | **La cartera no se persiste** ([ADR-005](decisiones/ADR-005-privacidad-cartera-no-persistida.md)): `briefing.json` lleva `portfolio: null` y no hay gráfico de cartera en `data/`; el gráfico de la sesión vive en una carpeta temporal del sistema que se borra a las 12 h. `.env`, `data/outputs/` y `data/cache/` fuera de git |
| Ficheros subidos | Cada ejecución guarda las subidas en una carpeta temporal **única** que se borra al terminar (sin colisiones entre sesiones) |
| Audio del usuario | La pregunta grabada se transcribe y **se borra** al terminar; no se guarda. Las respuestas habladas (voz sintética) sí quedan en `data/outputs/<id>/qa/` |
| Secretos y trazas | Claves y tokens se **redactan** en `StepMetric.error`, errores, log y UI (`logging_utils.redact_secrets`, `error_text`); el *traceback* solo se ve con `BRIEFER_LOG_LEVEL=DEBUG` |
| Exposición de la app | `run.ps1` / `run.sh` escuchan solo en `localhost` (`-Expose` / `--expose` para la red); Docker publica en `127.0.0.1:8501`; telemetría de Streamlit desactivada; subida máxima 50 MB |
| Base jurídica y consentimiento | Sin persistencia de la cartera no hace falta consentimiento para guardarla. El envío por Telegram (06-oct) lo configura el propio usuario con su bot y su chat (`scripts/telegram_setup.py`) y se elige en cada briefing; en un producto con usuarios haría falta consentimiento expreso para enviar a un canal externo. El envío nunca incluye el gráfico de cartera. Email: pendiente |
| Derechos | Sin cuentas de usuario en el MVP; el histórico se borra con la carpeta `data/outputs/` |
| Encargados de tratamiento | Proveedores de IA con DPA y opción de no entrenar con los datos enviados (a verificar por proveedor); transferencias internacionales (EE. UU.) a documentar. Telegram (si se usa) también recibe el resumen, el audio y el vídeo del briefing |

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
- No se clonan voces de personas reales: voces neuronales de catálogo (edge-tts es-ES por defecto; voces
  precompuestas de Gemini TTS en la versión premium).
- **Vídeo** (06-oct): rótulo fijo **«Voces sintéticas generadas con IA»** y «Información, no asesoramiento
  financiero» en todos los fotogramas (`video.SYNTHETIC_VOICE_LABEL`, `video.FOOTER_NOTE`), subtítulos con el
  nombre del locutor sintético y metadatos de IA en el MP4 (los de `podcast.AI_AUDIO_METADATA`: artista «Briefly
  (voces sintéticas IA)», comentario y *copyright* «Contenido generado por IA»). El pie de Telegram del audio y del vídeo repite «Voces sintéticas generadas con IA».
- **Portada** (06-oct): placa **«Imagen generada por IA»** siempre visible en la esquina superior derecha
  (`cover.AI_LABEL`), dibujada por Pillow y no por el modelo (los modelos de imagen escriben mal el texto). La
  ilustración no representa datos (no lleva cifras ni empresas) y no imita marcas ni personas reales.

### Riesgos de proveedor de la fase 1

| Riesgo | Efecto | Mitigación |
| --- | --- | --- |
| **Facturación de Google para Gemini imagen**: los modelos de imagen no tienen nivel gratuito; con la clave actual (nivel gratuito) responden 429 con cuota 0 | Solo afecta a `gemini`: sin portada (paso opcional fallido, aviso claro: `gemini_image.is_no_billing_error`); el resto del briefing sale igual | **Mitigado** (06-oct): la opción recomendada es la portada local (`BRIEFER_IMAGE_GEN_PROVIDER=local`, SDXS, 0 €). Gemini queda como alternativa de pago |
| **Portada local**: ~1,8 GB de descarga y carga en frío lenta en CPU (hasta ~2 min la primera vez) | La primera portada del día puede tardar | Descargar el modelo antes de la demo (caché de Hugging Face; en Docker, volumen `hf-cache`); el paso es opcional y un fallo no rompe el briefing |
| **Descarga de CLIP** (~600 MB la 1.ª vez, ≈ 28 s) y `torch` + `transformers` en `requirements-local.txt` | La primera subida del día puede tardar; sin las dependencias, no hay router | `route_image` nunca rompe: sin CLIP, la imagen va a visión sin pista (como antes). Descargar el modelo antes de la demo (caché de Hugging Face) |
| **Telegram**: sin bot creado, sin prueba real | El canal no aparece en la UI (solo se ofrece con token y chat) | Crear el bot y ejecutar `scripts/telegram_setup.py --write --test` antes de la demo |

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
