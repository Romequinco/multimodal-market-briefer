# Guion de la demo en vivo · Briefly

La demo es la **app desplegada**: <https://multimodal-market-briefer-production.up.railway.app/> (Railway, rama
`entrega-v1`, versión entregada con la etiqueta `v1.0`). Cualquiera puede abrirla: entra en modo demo, sin claves
ni gasto, con un briefing real pregenerado en «Hoy». El modo **Real** (datos de hoy, modelos de pago) pide una
contraseña que el equipo da aparte. Ya no hay vídeo grabado: este guion sirve para presentarla en directo
(**3:30-4:00 min**) y acompaña a la diapositiva 7 («Demo en vivo») del [pitch](pitch_briefly.pdf). Despliegue y variables, en
[docs/09](../docs/09_despliegue_railway.md).

Convenciones: **Pantalla** = qué se ve y qué se pulsa (los nombres entre comillas son los textos exactos de la
UI) · **Locución** = qué se dice (frases cortas, tono «radio nocturna»; nunca lenguaje de recomendación).

---

## 1. Checklist previa (la víspera y 30 min antes)

### La app desplegada

- [ ] Abrir la URL en el portátil de la presentación: carga «Hoy» con el briefing pregenerado y su reproductor.
  Si el servicio estaba dormido o se acaba de redesplegar, la primera carga tarda más: abrirla **antes** de empezar.
- [ ] En Railway, servicio activo y variables puestas (nunca se enseñan en pantalla): `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `BRIEFER_REAL_MODE_PASSWORD` y, si se quiere enseñar, `TELEGRAM_BOT_TOKEN` y
  `TELEGRAM_CHAT_ID`. Límite de gasto activo en las consolas de los proveedores.
- [ ] **Dos pestañas** de la app abiertas (A y B). En las dos: chip del modo (arriba a la derecha) → **«Real»** →
  contraseña. Cada pestaña es una sesión distinta, así que la contraseña se pide en cada una.
- [ ] **Ensayo completo** en la URL con los mismos valores y opciones: deja en caché las noticias y precios del día
  y, si la portada local está activa en el despliegue, el modelo SDXS cargado (en frío tarda bastante más).
- [ ] Abrir una vez «Preguntar» en la pestaña A para que se lance el precalentamiento (`warmup`) del LLM, el STT y
  edge-tts.
- [ ] Tras el ensayo, «Hoy» enseña el último briefing real guardado. Si se prefiere arrancar con el pregenerado
  (marcado «Demo» en «Archivo»), abrirlo desde «Archivo» en la pestaña A antes de empezar.

### Pantalla y material

- [ ] Navegador a pantalla completa, zoom 100-110 %, sin marcadores ni pestañas con datos personales.
- [ ] Ficheros a mano en una carpeta corta: `data/samples/grafico_ejemplo.png` y, de respaldo,
  `data/samples/cartera_ejemplo.png` (captura de broker **ficticia**; el diálogo ya ofrece «Usar captura de ejemplo»).
- [ ] Micrófono probado en el navegador (permiso concedido a la URL de Railway).
- [ ] Si se enseña Telegram: móvil con el chat del bot abierto, en «No molestar» y duplicado en pantalla.
- [ ] **Plan B** si falla la red o Railway: la app en local con `scripts\run.ps1` (o `docker compose up`) ya
  arrancada en `http://localhost:8501`, con el mismo pregenerado. Sin red: modo «Demo offline» del chip.

---

## 2. Guion paso a paso

La generación real tarda ≈ 1-2 min con vídeo, portada y una subida (medido: p50 52,7 s sin extras; 82-114 s con
vídeo, portada y subidas). En directo no se puede cortar: **se lanza en la pestaña B y, mientras genera, se enseña
el resto en la pestaña A**.

| # | Tiempo | Pantalla y acciones | Locución |
| --- | --- | --- | --- |
| 1 | 0:00-0:25 | Pestaña A, vista **«Hoy»** con el briefing pregenerado. Pulsar *play* y dejar sonar 5-6 s a Toro y Osa; señalar la franja «Cómo se hizo: … modelos de IA encadenados · … pasos · … €». | «Esto es Briefly, y está en la nube: cualquiera puede abrir esta dirección. El cierre del día, mientras vuelves a casa: lo que ha movido tu cartera, contado a dos voces, Toro y Osa. Son voces sintéticas y lo dicen. Y aquí: cuántos modelos ha encadenado y cuánto ha costado.» |
| 2 | 0:25-1:00 | Pestaña B → **«Nuevo briefing»**. En el buscador de valores escribir «santander» (sale SAN.MC del catálogo de 169 activos validados) y dejar también IBE.MC, AAPL y NVDA; si sobra tiempo, «¿No está en la lista? Buscar en Yahoo Finance» con «Ryanair». En «Documentos» subir `grafico_ejemplo.png`; en «Opciones», «Vídeo corto» y, si está disponible, «Portada con IA». Pulsar **«Generar briefing»** y dejarlo trabajando. | «Elijo mis valores: el buscador conoce el IBEX, Europa, Estados Unidos, índices, materias primas y cripto, y si algo no está, lo busca en Yahoo Finance. Añado la captura de un gráfico y pido también el vídeo. Mientras se genera, os enseño lo demás.» |
| 3 | 1:00-1:40 | Pestaña A → **«Preguntar»**. Pulsar el **micrófono** de la barra del chat y decir: *«¿Por qué ha subido hoy el Santander?»*. Esperar al texto y a la respuesta hablada de Osa; abrir su «Cómo se hizo». | «Si tengo una duda, pregunto hablando.» *(pregunta)* … «Voz a texto, Claude Haiku responde citando las noticias del briefing y Osa lo dice en voz alta: unos seis segundos. Si le pido que me diga si vendo, no lo hace: te contamos el mercado; tú decides.» |
| 4 | 1:40-2:10 | Pestaña A → **«Nuevo briefing»** → sección **«Tu cartera»** → «Captura del broker» → **«Usar captura de ejemplo»**. Enseñar las 5 posiciones leídas y cerrar el diálogo sin generar. | «La cartera la puedo cargar desde una captura del broker: visión lee la tabla, Haiku la estructura y un mapeo determinista da los tickers. Cinco de cinco. Y no se guarda en disco: al modelo solo van tickers y pesos.» |
| 5 | 2:10-2:45 | Pestaña B: el briefing ya está. Titular, reproductor y **«Puntos clave»**: pasar el ratón por una fuente enlazada. Abrir **«Transcripción»** y **«Gráficos»** un par de segundos cada una. | «Primero un modelo local, CLIP, ha mirado la imagen: es un gráfico, así que merecía la pena pagar la lectura con visión. Luego Sonnet ha analizado las noticias de hoy, Haiku ha escrito el guion y dos voces lo han grabado. Cada punto clave lleva su fuente: si no hay fuente, no ha pasado.» |
| 6 | 2:45-3:30 | Pestaña **«Vídeo»**: 4-5 s del vídeo 9:16 (subtítulos TORO / OSA y rótulo «Voces sintéticas generadas con IA»). Luego **«Cómo se hizo»**: pasos, modelo, latencia, coste y la decisión de CLIP. | «El mismo episodio en vídeo vertical, con subtítulos por locutor; cero euros, en local. Y esto lo hace auditable: cada paso con su modelo, cuánto ha tardado y cuánto ha costado. Si un proveedor fallara, aquí se vería el sustituto en naranja.» |
| 7 | 3:30-3:45 | **«Archivo»**: el briefing nuevo junto al pregenerado, filtros y «Privacidad y datos». Si Telegram está configurado y se activó «Enviar por Telegram», enseñar el móvil con el resumen, el audio y el vídeo. | «Todo queda en el archivo, con la opción de borrarlo. Y, si lo configuro, me llega a Telegram mientras vuelvo a casa.» |
| 8 | 3:45-4:00 | Volver a «Hoy» o a la última diapositiva del pitch (URL y QR). | «Briefly: modelos de lenguaje, visión, voz e imagen encadenados, céntimos por episodio y el cumplimiento en el propio código. La dirección está en la diapositiva: probadlo. Información, no asesoramiento; voces sintéticas. Gracias.» |

**Pregunta alternativa** si el Santander no encaja: el pregenerado habla también de Iberdrola («¿Qué ha pasado hoy
con Iberdrola?»); con el gráfico subido, «¿Qué se ve en el gráfico?». Evitar preguntas que pidan opinión de
inversión, salvo para enseñar a propósito que el agente la reconduce.

**Si algo falla en directo:**

- La generación tarda más de lo previsto: seguir con los pasos 3-4 y, si aún no ha terminado, abrir el briefing
  del ensayo desde «Archivo» y contar el nuevo al final.
- El Analista o el Guionista caen a sustituto: la UI lo avisa en «Cómo se hizo»; se cuenta como robustez.
- El micrófono no transcribe: escribir la pregunta en la misma barra del chat.
- La URL no responde: pasar al plan B en local (misma app, mismo pregenerado); mientras arranca, contar el
  recorrido sobre la diapositiva 6 del pitch («La app», 4 capturas reales).

---

## 3. Consejos para la presentación

- Repartir: una persona maneja la app y otra cuenta; la tercera vigila el tiempo y el plan B.
- Ratón lento y deliberado; zoom del navegador suficiente para que se lea desde el fondo del aula.
- No enseñar la contraseña del modo Real, las variables de Railway, `.env`, ni el ID del chat de Telegram.
- Dejar el Q&A por voz **sin interrupciones**: es la latencia que más luce (≈ 6 s).
- Revisar con la checklist de compliance: ninguna frase que suene a recomendación, aviso de voces sintéticas
  visible y fuentes en pantalla.
- Quien quiera probarla después: la URL abre en modo demo, sin contraseña y sin gasto.
