# Guion de la demo grabada · Briefly

Demo de **3:30-4:00 min** para la entrega del jueves 8-oct-2026. Se graba en **modo real** (claves del equipo) en
la máquina de la demo, con la app en `http://localhost:8501`. Acompaña a la diapositiva 10 del
[pitch](pitch_briefly.pdf).

Convenciones: **Pantalla** = qué se ve y qué se pulsa (los nombres entre comillas son los textos exactos de la
UI) · **Locución** = qué se dice (frases cortas, tono «radio nocturna»; nunca lenguaje de recomendación).

---

## 1. Checklist previa (la víspera y 30 min antes)

### Entorno

- [ ] Rama y código finales (`git pull --rebase`), *code freeze* respetado.
- [ ] Arranque elegido y probado **en la máquina de grabación**:
  - Windows: `powershell -ExecutionPolicy Bypass -File scripts\run.ps1 -Local` (con modelos locales), o
  - Docker: imagen construida **con antelación** (`docker compose up --build` puede tardar 6-60 min con red lenta;
    el día de la demo solo `docker compose up`).
- [ ] `.env` con claves y proveedores reales (no se enseña nunca en pantalla):
  - `ANTHROPIC_API_KEY` (Analista, Guionista, Q&A, visión) y `OPENAI_API_KEY` (pregunta por voz).
  - `BRIEFER_IMAGE_CLASSIFIER_PROVIDER=clip` (router de imágenes) y `BRIEFER_IMAGE_GEN_PROVIDER=local` (portada
    SDXS gratis; ruta relativa en `BRIEFER_SDXL_MODEL`, p. ej. `data/cache/models/sdxs-512-dreamshaper`).
  - `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (`python scripts/telegram_setup.py --test` envía un mensaje de prueba).
  - Voz: `BRIEFER_TTS_PROVIDER=edge` (por defecto, más rápida y fiable). `gemini` suena más natural pero añade
    ≈ 25 s y ≈ 0,047 € (estimación) por episodio; si falla cae a edge-tts.
  - `BRIEFER_VERIFY_PODCAST=false` para la grabación (ahorra tiempo y céntimos; la verificación por STT ya está
    medida y se cuenta en el pitch).
- [ ] **Modelos descargados** antes de grabar (la primera vez tardan): CLIP (~600 MB), SDXS (~1,8 GB) y, si se
  activa FinBERT, ~840 MB. Basta con un briefing de ensayo con vídeo, portada y una imagen subida.
- [ ] Humo real: `python scripts/smoke_real.py` → todo `OK` (< 0,01 €).

### Calentar sin que se note

- [ ] **Ensayo completo dentro de la app** (mismo proceso de Streamlit que se va a grabar): modo real, los mismos
  valores, «Vídeo corto» + «Portada con IA» + `grafico_ejemplo.png`. Así quedan cargados CLIP y SDXS (en frío,
  la carga de SDXS va de 15 a 138 s) y las noticias y precios del día en la caché.
- [ ] Abrir una vez «Preguntar» para que se lance el precalentamiento (`warmup`) del LLM, el STT y edge-tts.
- [ ] **Limpiar salidas sin tocar la caché**: borrar a mano las carpetas de `data/outputs/` del ensayo para que la
  portada vuelva a mostrar el **briefing pregenerado** (`data/samples/demo_briefing/`). No usar «Borrar mis
  datos» del Histórico: borra también `data/cache/` y se perdería el calentamiento de noticias.
- [ ] Recargar la portada y comprobar que se ve el pregenerado con su reproductor.

### Pantalla y material

- [ ] Navegador a pantalla completa, zoom 100-110 %, sin marcadores ni pestañas con datos personales; resolución
  de grabación 1920×1080.
- [ ] Barra lateral: interruptor «Modo real (APIs de .env)» **encendido** (insignias «real» en «Proveedores de IA»).
- [ ] Ficheros a mano en una carpeta corta: `data/samples/grafico_ejemplo.png` y `data/samples/cartera_ejemplo.png`
  (captura de broker **ficticia**).
- [ ] Móvil con Telegram abierto en el chat del bot, en «No molestar», con grabación de pantalla preparada.
- [ ] Micro externo o auriculares con micro; habitación sin eco. Notificaciones del sistema desactivadas.

---

## 2. Guion paso a paso

Tiempos orientativos del vídeo **ya montado**. La generación real del briefing tarda ≈ 1-2 min con vídeo, portada
y una subida (medido: p50 52,7 s sin extras; 82-114 s con vídeo, portada y subidas): **se graba entera y se
recorta en edición** (ver el truco en el paso 3).

| # | Tiempo | Pantalla y acciones | Locución |
| --- | --- | --- | --- |
| 1 | 0:00-0:25 | **Portada** con el briefing pregenerado. Pulsar *play* en el reproductor y dejar sonar 5-6 s a Toro y Osa; señalar la franja «Cómo se hizo: … modelos de IA encadenados · … pasos · … €». | «Esto es Briefly: el cierre del día, mientras vuelves a casa. Cada tarde, lo que ha movido tu cartera, contado a dos voces, Toro y Osa, en unos cuatro minutos. Son voces sintéticas y lo dicen. Y aquí debajo: cuántos modelos ha encadenado y cuánto ha costado.» |
| 2 | 0:25-0:55 | Menú **«Briefing»**. En «Valores a seguir» dejar SAN.MC, ITX.MC, IBE.MC, AAPL y NVDA (o escribir «santander» para enseñar que normaliza a SAN.MC). Abrir **«Opciones avanzadas: vídeo, portada y Telegram»** y marcar «Vídeo corto», «Portada con IA» y «Enviar por Telegram». En «Documentos opcionales…» subir `grafico_ejemplo.png`. | «Elijo mis valores. Puedo añadir un PDF de resultados o, como ahora, la captura de un gráfico. Pido además el vídeo vertical, una portada generada con IA y que me lo mande a Telegram.» |
| 3 | 0:55-1:10 | Pulsar **«Generar briefing»**. Enseñar 3-4 s la barra de progreso por pasos y **cortar** hasta el resultado (rótulo en edición: «≈ 1,5 min después · tiempo real»). | «Primero, un modelo local, CLIP, mira la imagen: es un gráfico de velas, así que merece la pena pagar la lectura con visión. Luego Claude Sonnet analiza las noticias, Haiku escribe el guion y dos voces sintéticas lo graban.» |
| 4 | 1:10-1:35 | Resultado: titular, reproductor y pestaña **«Puntos clave»**. Pasar el ratón por una fuente enlazada. Abrir **«Transcripción»** y **«Gráficos»** un par de segundos cada una. | «Cada punto clave lleva su fuente con enlace y un extracto breve: si no hay fuente, no ha pasado. Y todo se puede leer y ver: transcripción sincronizada y gráficos del día.» |
| 5 | 1:35-1:55 | Pestaña **«Vídeo»**: reproducir 4-5 s del vídeo 9:16 (subtítulos con TORO / OSA y el rótulo «Voces sintéticas generadas con IA»). | «El mismo episodio en vídeo vertical, con subtítulos por locutor, listo para el móvil. Cero euros: Pillow y ffmpeg en local.» |
| 6 | 1:55-2:20 | Pestaña **«Cómo se hizo»**: recorrer la traza (pasos, modelo, latencia y coste estimado; decisión de CLIP en el paso del gráfico). | «Y esto es lo que lo hace auditable: cada paso con su modelo, cuánto ha tardado y cuánto ha costado. Este briefing completo cuesta unos céntimos. Si un proveedor fallara, aquí se vería en naranja el sustituto.» |
| 7 | 2:20-2:45 | Menú **«Mi cartera»** → **«Usar captura de ejemplo»** (o subir `cartera_ejemplo.png` y «Leer captura»). Enseñar las 5 posiciones leídas. | «Mi cartera la puedo cargar desde una captura del broker: visión lee la tabla, Haiku la estructura y un mapeo determinista da los tickers. Cinco de cinco. Y la cartera no se guarda en disco: al modelo solo van tickers y pesos.» |
| 8 | 2:45-3:20 | Volver al briefing → **«Preguntar sobre este briefing»** (o menú «Preguntar»). En **«Graba tu pregunta»** decir: *«¿Por qué ha subido hoy el Santander?»*. Esperar a que salga el texto y suene la respuesta de Osa. Abrir el desplegable «Cómo se hizo (voz → texto → respuesta → voz)». | «Y si tengo una duda, pregunto hablando.» *(pregunta)* … «Voz a texto, Claude Haiku responde citando las noticias del briefing y Osa lo dice en voz alta: unos seis segundos de punta a punta. Si le pido que me diga si vendo, no lo hace: te contamos el mercado; tú decides.» |
| 9 | 3:20-3:45 | **Telegram en el móvil** (grabación del teléfono, a pantalla completa o en recuadro): mensaje con titular, puntos clave y aviso legal; audio; portada con la placa «Imagen generada por IA»; vídeo. | «Y sin abrir la app: el resumen, el audio, la portada y el vídeo me llegan a Telegram mientras vuelvo a casa.» |
| 10 | 3:45-4:00 | Volver a la portada o a la última diapositiva del pitch (logo + eslogan). | «Briefly: trece modalidades encadenadas, céntimos por episodio y cumplimiento en el propio código. Información, no asesoramiento; voces sintéticas. Gracias.» |

**Pregunta alternativa** si hoy el Santander no sale en los puntos clave: elegir un valor que sí aparezca
(«¿Qué ha pasado hoy con Iberdrola?») o, con el PDF subido, «¿Qué dice el PDF de resultados?». Evitar preguntas
que pidan opinión de inversión, salvo para enseñar a propósito que el agente la reconduce.

**Si algo falla en directo:** el vídeo se monta igualmente con el ensayo; si el Analista o el Guionista caen a
sustituto, la UI lo avisa (se puede contar como robustez, pero mejor regenerar). Si el Q&A por voz no transcribe,
escribir la pregunta en «…o escríbela».

---

## 3. Trucos de edición

- **Espera de la generación (paso 3):** grabar la espera completa y cortar a 3-4 s de barra de progreso + rótulo
  «≈ 1,5 min después · tiempo real». No acelerar sin decirlo: el pitch da latencias medidas.
- **Alternativa sin espera:** generar el briefing justo antes (mismos valores y opciones) y, en la toma, abrirlo
  desde **«Histórico»**; enseñar la pulsación de «Generar briefing» de otra toma. Si se hace así, el briefing de la
  portada (paso 1) será el recién generado: rehacer la limpieza de `data/outputs/` después de grabar el paso 1.
- **Q&A (paso 8):** dejarlo **sin cortes** (es la latencia que más luce, ≈ 6 s).
- **Telegram (paso 9):** grabar la pantalla del móvil aparte y sincronizar con la llegada de los mensajes; mostrar
  el chat del bot, nunca la lista de chats personales.
- Música de fondo suave solo en la portada y el cierre; bajarla bajo la locución y quitarla cuando suenan Toro y
  Osa o la respuesta del Q&A.
- Rótulo fijo en una esquina durante todo el vídeo: «Voces sintéticas generadas con IA · información, no
  asesoramiento financiero».

## 4. Consejos de grabación

- Grabar **por bloques** (pasos 1-2, 3-6, 7, 8, 9) y montar: es más fácil repetir un bloque que todo el vídeo.
- Locución grabada **aparte** (o regrabada) leyendo esta tabla; frases cortas, ritmo tranquilo, una idea por frase.
- Ratón lento y deliberado; resaltar el cursor si la herramienta lo permite (OBS, ScreenToGif, Clipchamp).
- No enseñar `.env`, terminal con claves, el ID del chat de Telegram ni la consola del proveedor.
- Exportar en MP4 1080p, < 200 MB; subirlo a un enlace externo (los `.mp4` pesados no se versionan) y poner la URL
  en el marcador `[enlace a la demo]` de `pitch/pitch_briefly.html` (y QR con
  `python scripts/build_pitch.py --demo-url <URL>`, que necesita `pip install segno`).
- Revisar el vídeo final con la checklist de compliance: ninguna frase que suene a recomendación, aviso de voces
  sintéticas visible y fuentes en pantalla.
