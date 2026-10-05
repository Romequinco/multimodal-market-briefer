# 04 · Viabilidad: costes, latencias, compliance y monetización

> **Todo número de este documento es una estimación a verificar.** Los precios de APIs cambian y los tokens
> reales dependen de los prompts finales. Cuando el pipeline funcione, los valores se contrastan con los
> `StepMetric` registrados en cada briefing y se actualiza la columna «Medido» (hoy vacía).

## 1. Supuestos

| Supuesto | Valor usado | Comentario |
| --- | --- | --- |
| Noticias por briefing tras el filtro | ~20 | Cartera de 5-10 tickers |
| Tokens de entrada del Analista | ~8.000 | 20 noticias × ~300 tokens + precios + insights + prompt |
| Tokens de salida del Analista | ~1.500 | `Analysis` en JSON con 4-6 puntos clave |
| Duración del podcast | 4 min | ~600 palabras, ~3.500 caracteres, ~40 líneas de guion |
| Tokens de entrada / salida del Guionista | ~2.000 / ~1.500 | |
| Contexto del Q&A | ~6.000 tokens de entrada, ~300 de salida | Briefing del día como contexto |
| Pregunta por voz | ~15 s de audio | |
| Precio LLM gama media (tipo Sonnet) | ~3 $/M entrada, ~15 $/M salida | **Verificar** en la tarifa vigente del proveedor |
| Precio LLM barato (tipo Haiku) | ~1 $/M entrada, ~5 $/M salida | **Verificar** |
| Whisper API | ~0,006 $/min | **Verificar**; local = 0 € de API |
| ElevenLabs | ~0,20-0,30 $ por 1.000 caracteres según plan | **Verificar**; muy dependiente del plan |
| Tipo de cambio | 1 $ ≈ 1 € | Simplificación; el error es menor que la incertidumbre de los tokens |

## 2. Coste estimado por briefing

| Paso | Proveedor por defecto | Cálculo | Coste estimado | Medido |
| --- | --- | --- | --- | --- |
| Noticias y precios | yfinance + RSS | Gratis | 0 € | — |
| Lectura de gráfico (si se sube) | Claude visión | ~1.500 tok entrada + 500 salida | ~0,01 € | — |
| Lectura de PDF (si se sube) | `pypdf` + visión en ~3 páginas | ~10.000 tok texto + 3 imágenes | ~0,05-0,08 € | — |
| Clasificación CLIP (opcional) | Local | CPU | 0 € | — |
| Agente Analista | Sonnet | 8k × 3 $/M + 1,5k × 15 $/M | ~0,05 € | — |
| Agente Guionista | Sonnet / Haiku | 2k entrada + 1,5k salida | ~0,03 € / ~0,01 € | — |
| TTS 2 voces | **edge-tts** | Gratis, sin clave | **0 €** | — |
| TTS 2 voces (premium) | ElevenLabs | ~3.500 caracteres | ~0,70-1,05 € | — |
| Gráficos | matplotlib | Local | 0 € | — |
| Portada (opcional) | SDXL-Turbo local / API | GPU local o ~0,02-0,04 € por API | 0-0,04 € | — |
| Vídeo (opcional) | moviepy + ffmpeg | CPU local | 0 € | — |
| **Total briefing base** (sin subidas, edge-tts) | | | **~0,06-0,08 €** | — |
| **Total con PDF + gráfico** | | | **~0,12-0,17 €** | — |
| **Total con ElevenLabs** | | | **~0,80-1,15 €** | — |

### Coste por pregunta Q&A

| Paso | Proveedor | Coste estimado |
| --- | --- | --- |
| STT | Whisper local / API | 0 € / ~0,002 € |
| LLM | Sonnet (6k entrada + 300 salida) | ~0,02 € |
| LLM | Haiku | ~0,007 € |
| TTS | edge-tts | 0 € |
| **Total** | | **~0,01-0,025 €** |

**Conclusión provisional:** con TTS gratuito el coste lo domina el LLM y es de céntimos por briefing.
ElevenLabs multiplica el coste por ~10-15: solo tiene sentido si el audio se genera **una vez y se comparte**
entre muchos usuarios (ver estrategias).

## 3. Latencias objetivo

Dos regímenes distintos:

- **Briefing:** se pregenera en **batch** (madrugada, antes de la apertura). El usuario no lo espera; en la
  demo se genera en vivo y basta con mostrar progreso por pasos.
- **Q&A por voz:** interactivo. Objetivo **< 10 s** desde que el usuario suelta el botón hasta que empieza a
  sonar la respuesta.

| Paso | Objetivo (estimación) | Medido | Cómo se consigue |
| --- | --- | --- | --- |
| Noticias + precios | 2-5 s | — | Llamadas en paralelo + caché en `data/cache/` |
| Lectura de PDF | 5-20 s | — | Visión solo en páginas con gráficos |
| Lectura de gráfico | 3-8 s | — | Una llamada de visión |
| Analista | 10-30 s | — | Salida estructurada, prompt acotado |
| Guionista | 10-20 s | — | Modelo barato posible |
| TTS (~40 líneas) | 10-40 s | — | Síntesis por línea **en paralelo** (asyncio) |
| Transcripción + SRT | < 1 s | — | Tiempos del propio TTS, sin modelo extra |
| Gráficos | 1-3 s | — | |
| Vídeo | 30-90 s | — | Resolución 720p, imágenes estáticas + audio |
| **Briefing completo** | **1-3 min sin vídeo; 2-4 min con vídeo** | — | Batch nocturno; en vivo con barra de progreso |
| STT de la pregunta | 1-3 s | — | Whisper base local o API |
| LLM Q&A | 3-6 s | — | Contexto del briefing ya resumido; respuesta corta |
| TTS de la respuesta | 1-2 s | — | Respuesta de 2-4 frases |
| **Q&A completo** | **< 10 s** | — | Mostrar el texto en cuanto llega, audio después |

## 4. Estrategias de coste y latencia

| Estrategia | Efecto | Estado en MVP |
| --- | --- | --- |
| **Generación por ticker compartida** entre usuarios: el análisis de «SAN.MC hoy» se calcula una vez y se reutiliza para todos los que lo siguen; por usuario solo se compone el guion | El coste deja de crecer con usuarios y pasa a crecer con tickers distintos | Diseño; caché por hash de entrada en `data/cache/` |
| **Batch nocturno** | Latencia percibida 0 para el briefing; se puede usar la API batch del proveedor (más barata) | Fuera del MVP (script manual) |
| **Modelos baratos donde basta** (Haiku para guion y Q&A, Sonnet solo para el análisis) | ~-60 % en guion y Q&A | Configurable por paso |
| **Caché de prompts** del sistema y del contexto del briefing en el Q&A | Menos coste y latencia en preguntas sucesivas | Pendiente de verificar soporte |
| **TTS gratuito por defecto** (edge-tts) y premium solo para contenido compartido | Coste de audio ~0 | Hecho por diseño |
| **Modelos locales** (Whisper, Qwen2.5-VL, SDXL-Turbo, CLIP) | 0 € de API a cambio de hardware | Alternativa por config |
| **Paralelismo** en ingesta y TTS | Latencia del briefing / 2-4 | Pendiente |

## 5. Marco regulatorio

### MiFID II · información genérica, no asesoramiento

| Riesgo | Medida en el producto |
| --- | --- |
| Que el contenido se considere asesoramiento personalizado (recomendación sobre un instrumento adaptada a la situación del cliente) | El producto da **información y explicación** de noticias; no evalúa idoneidad ni objetivos del usuario |
| Recomendaciones de compra/venta | Prohibidas en los prompts de los tres agentes; el Q&A reconduce «¿vendo?» a información genérica |
| Falta de transparencia | `Analysis.disclaimer` obligatorio y no vacío; disclaimer **hablado** al final del podcast; pie fijo en la UI, email y Telegram |
| Uso de la cartera | Se usa para **seleccionar** qué noticias explicar, no para recomendar cambios en ella |
| Escalado B2B2C | Si un broker lo integra, el contenido se presenta como comunicación informativa; la responsabilidad regulatoria del canal se fija por contrato |

Texto base del disclaimer: *«Contenido informativo generado con IA. No constituye asesoramiento de inversión
ni recomendación de compra o venta. Puede contener errores. Las voces son sintéticas.»*

### RGPD · datos de cartera

| Principio | Aplicación |
| --- | --- |
| Minimización | Solo se piden tickers y pesos/cantidades; nada de saldos, IBAN, identidad ni credenciales de broker |
| Qué sale a terceros | Al LLM solo van tickers y noticias; los pesos solo si aportan contexto y nunca junto a datos identificativos |
| Base jurídica y consentimiento | Consentimiento explícito al guardar la cartera y para el envío por email/Telegram |
| Almacenamiento | Local en `data/` en el MVP; `.env` y `data/outputs/` fuera de git |
| Derechos | Borrado de cartera e histórico desde la UI (pendiente) |
| Encargados de tratamiento | Proveedores de IA con DPA y opción de no entrenar con los datos enviados (a verificar por proveedor) |
| Audio del usuario | La pregunta grabada se transcribe y se descarta; no se guarda salvo opt-in |

### Derechos de autor de las noticias

- Se **resume con palabras propias** y se **cita la fuente** (`NewsItem.source` + `url`) en análisis,
  transcripción y Q&A.
- No se reproduce el texto íntegro de artículos; solo título, extracto del feed y enlace.
- Se priorizan fuentes con feed público (RSS) y las noticias que expone yfinance.

### AI Act · transparencia

- Aviso explícito de que el audio y el vídeo son **generados por IA** y las voces son **sintéticas** (UI,
  inicio o cierre del podcast, metadatos del fichero).
- No se clonan voces de personas reales.
- Las portadas generadas llevan la marca «imagen generada por IA».

## 6. Monetización

Números **orientativos** para dimensionar, no previsiones.

| Plan | Precio | Incluye | Coste variable estimado por usuario y mes |
| --- | --- | --- | --- |
| Free | 0 € | 3 tickers, briefing compartido por ticker, sin Q&A por voz (o 3/mes), edge-tts | ~0,05-0,15 € |
| Pro | 5,99 €/mes *(a validar)* | Cartera completa, Q&A por voz (~20/mes), PDFs y gráficos, vídeo, email/Telegram | ~0,8-2 € (22 briefings × ~0,06 € + 20 Q&A × ~0,02 € + subidas) |
| White-label B2B2C | Fijo de integración + ~0,20-0,50 € por usuario activo/mes *(a negociar)* | Marca del cliente, API, contenido compartido por ticker | ~0,05-0,10 € gracias a la compartición |

Escenario ilustrativo (supuestos, no datos): 10.000 usuarios registrados, 4 % de conversión a Pro.

| Concepto | Cálculo | Mensual |
| --- | --- | --- |
| Ingresos Pro | 400 × 5,99 € | ~2.400 € |
| Coste variable Pro | 400 × ~1,5 € | ~600 € |
| Coste variable Free | 9.600 × ~0,10 € | ~960 € |
| Margen bruto antes de infraestructura y personal | | ~840 € |

Lectura: el B2C solo es viable con **compartición por ticker** y cuotas al free; el B2B2C (un broker con
50.000 usuarios activos) es donde está el volumen. Estos números se recalcularán con costes medidos.
