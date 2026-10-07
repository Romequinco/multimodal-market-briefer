# 09 · Desplegar Briefly en Railway (paso a paso)

> Guía para alguien que no ha desplegado nunca nada. Al terminar tendrás Briefly en una dirección pública
> (`https://algo.up.railway.app`) que se actualiza sola cada vez que se sube un cambio a `main` en GitHub.
> Preparado el 07-oct-2026; las pantallas de Railway pueden cambiar de nombre, pero los pasos son estos.

## Qué hay ya preparado en el repo

| Fichero | Para qué sirve |
|---|---|
| `Dockerfile` | La «receta» de la máquina: Python, ffmpeg, dependencias y la app. Escucha en el puerto que le da Railway (variable `PORT`; 8501 en local). |
| `railway.json` | Le dice a Railway que use el `Dockerfile` y que compruebe que la app está viva en `/_stcore/health`. |
| `BRIEFER_REAL_MODE_PASSWORD` | Variable nueva: si tiene valor, la app pide esa contraseña antes de activar el modo **Real** (el que gasta con tus claves). Los modos demo siguen abiertos. |

No hay que tocar código: todo lo demás se hace en la web de Railway.

## Antes de empezar: decide qué quieres publicar

| Opción | Qué ve la gente | Coste de API | Recomendado para |
|---|---|---|---|
| **A · Solo demo** (sin claves) | El briefing pregenerado real en «Hoy», «Nuevo briefing» con datos de ejemplo y voces reales (edge-tts), chat con respuestas simuladas | **0 €** de APIs | Enseñar la app en clase sin riesgo |
| **B · Demo + modo real con contraseña** | Lo mismo, y quien sepa la contraseña puede generar briefings reales | ≈ 0,03-0,07 € por briefing real (ver [04](04_viabilidad_costes_latencia_compliance.md)) | La demo en directo con datos de hoy |

Empieza por la **A**; pasar a la **B** es solo añadir variables (paso 6).

## Paso 1 · Comprobar que el código está en GitHub

Railway despliega desde GitHub. La rama `main` de `Romequinco/multimodal-market-briefer` ya tiene todo
(incluidos `Dockerfile` y `railway.json`). Nada que hacer si `git status` no muestra cambios pendientes.

## Paso 2 · Crear el proyecto en Railway

1. Entra en <https://railway.com> con tu cuenta y pulsa **New Project** (o «+ New»).
2. Elige **Deploy from GitHub repo**.
3. Si es la primera vez con este repo, Railway pide permiso para leer tu GitHub: pulsa **Configure GitHub
   App**, elige tu cuenta y da acceso **solo** a `multimodal-market-briefer` (no hace falta darle todos).
4. Selecciona el repo `multimodal-market-briefer`. Railway crea un **servicio** y empieza a construirlo.
   Puede fallar o tardar en este primer intento: no pasa nada, en el paso 3 le ponemos las variables y
   vuelve a construir.

## Paso 3 · Variables (la parte importante)

Abre el servicio → pestaña **Variables** → **New Variable** (o **Raw Editor** para pegarlas todas juntas).

**Opción A · Solo demo** — pega esto:

```env
LOCAL_MODELS=false
BRIEFER_IMAGE_GEN_PROVIDER=none
BRIEFER_IMAGE_CLASSIFIER_PROVIDER=none
BRIEFER_FINBERT=false
BRIEFER_LOG_LEVEL=INFO
```

- `LOCAL_MODELS=false` hace que la imagen **no** incluya torch ni los modelos locales (CLIP, FinBERT y la
  portada local): la imagen pasa de varios GB a unos cientos de MB, arranca rápido y gasta poca memoria.
  Railway pasa esta variable al `Dockerfile` al construir (línea `ARG LOCAL_MODELS`).
- No pongas ninguna clave de API: sin ellas el modo Real ni siquiera aparece y nadie puede gastar nada.

Al guardar, Railway vuelve a desplegar solo (si no, botón **Deploy** o **Redeploy**).

## Paso 4 · Darle una dirección pública

1. En el servicio → **Settings** → **Networking** → **Generate Domain**.
2. Si pregunta por el puerto, deja el que propone (la app usa la variable `PORT` que pone Railway). Si
   tienes que escribirlo a mano, mira en los logs del despliegue la línea `Local URL: http://localhost:XXXX` y usa ese número.
3. Railway te da una dirección tipo `https://multimodal-market-briefer-production.up.railway.app`.

## Paso 5 · Comprobar que funciona

1. Pestaña **Deployments** → el último despliegue debe estar en verde (**Active / Success**). En **View
   logs** verás `You can now view your Streamlit app in your browser`.
2. Abre la dirección pública. Debes ver la barra superior (Hoy · Preguntar · Archivo), el chip
   **DEMO · VOCES REALES** y el briefing pregenerado del 06/10 con su audio.
3. Prueba «Nuevo briefing» → «Generar briefing» (en demo tarda unos segundos) y una pregunta en «Preguntar».

## Paso 6 (opcional) · Activar el modo real con contraseña (opción B)

Añade estas variables (los valores de las claves son los de tu `.env` local; **nunca** las subas a GitHub):

```env
BRIEFER_LLM_PROVIDER=anthropic
BRIEFER_VISION_PROVIDER=claude
BRIEFER_STT_PROVIDER=whisper_api
BRIEFER_TTS_PROVIDER=edge
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
BRIEFER_REAL_MODE_PASSWORD=una-frase-larga-que-solo-sepa-el-equipo
```

- Con `BRIEFER_REAL_MODE_PASSWORD` puesta, al elegir **Real** en el chip del modo la app pide la contraseña;
  hasta que se escribe bien sigue en demo. Tras 5 intentos fallidos el formulario se bloquea en esa sesión.
- **Pon un límite de gasto** en la consola de Anthropic (*Settings → Limits*) y en la de OpenAI
  (*Billing → Usage limits*): es la red de seguridad de verdad si la contraseña se filtra.
- Telegram (opcional): `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`, como en local.
- Si alguna vez la contraseña se comparte de más, cámbiala aquí: Railway redespliega y la anterior deja de valer.

## Paso 6b (opcional) · Portada con IA

Con la configuración de arriba (`BRIEFER_IMAGE_GEN_PROVIDER=none`), el interruptor «Portada con IA» del
diálogo sale desactivado en modo Real. Dos formas de activarlo:

| | **Gemini (recomendada en Railway)** | **Local (SDXS en CPU)** |
|---|---|---|
| Variables | `BRIEFER_IMAGE_GEN_PROVIDER=gemini` y `GEMINI_API_KEY=…` | `BRIEFER_IMAGE_GEN_PROVIDER=local` y `LOCAL_MODELS=true` |
| Coste | ≈ 0,03 € por portada (estimación de [04](04_viabilidad_costes_latencia_compliance.md)); exige **facturación activa** en el proyecto de Google de la clave (sin ella responde 429 y el briefing sale sin portada) | 0 € de API, pero más Railway: imagen de ~3,4 GB, ~2-3 GB de RAM al generar (estimación) y ~1,8 GB de modelo que se descarga la primera vez |
| Notas | Nada más que tocar | Para no volver a descargar el modelo en cada despliegue, guárdalo en el volumen con `HF_HOME=/data/huggingface` (ver paso 7: Railway solo admite **un** volumen por servicio); la primera portada tarda más |

La portada siempre lleva el rótulo «Imagen generada por IA» y es opcional: si falla, el briefing sigue sin ella.

## Paso 7 (opcional) · Que el Archivo no se borre en cada despliegue

El disco del contenedor se vacía en cada despliegue: los briefings generados desaparecen (el pregenerado de
«Hoy» no, porque viene en el repo). Railway admite **un solo volumen por servicio**, así que se usa uno para
todo (briefings y, si usas la portada local, los modelos de Hugging Face):

1. En el servicio → **Add Volume** (o clic derecho → *Attach volume*), ruta de montaje **`/data`**. Si ya
   tenías un volumen con otra ruta (p. ej. `/app/data/outputs`), no crees otro: abre ese volumen → *Settings*
   → cambia su **Mount path** a `/data`.
2. Añade estas variables:

   ```env
   RAILWAY_RUN_UID=0
   BRIEFER_OUTPUT_DIR=/data/outputs
   HF_HOME=/data/huggingface
   ```

   - `RAILWAY_RUN_UID=0`: el contenedor corre con un usuario sin privilegios y, sin esto, no podría escribir en el volumen.
   - `BRIEFER_OUTPUT_DIR`: los briefings generados se guardan en el volumen.
   - `HF_HOME`: solo hace falta con la portada local (`LOCAL_MODELS=true`); el modelo (~1,8 GB) se descarga una vez.

No montes el volumen en `/app/data`: taparía `data/samples/` (el briefing pregenerado de la portada).
La cartera del usuario sigue sin guardarse nunca en disco (ADR-005), haya volumen o no.

## Paso 8 · Actualizar la app más adelante

Cada `git push` a `main` redespliega solo (Railway lo detecta). Si algo sale mal, en **Deployments** puedes
volver a un despliegue anterior con **Rollback**.

## Costes (estimación, no medidos)

- **Railway** cobra por uso (CPU, memoria y tráfico). Con `LOCAL_MODELS=false` la app usa del orden de
  300-600 MB de RAM en reposo: unos pocos dólares al mes en tu plan. Puedes poner un tope en
  *Workspace → Usage → Usage limits*.
- **APIs**: 0 € en la opción A; en la B, lo que se genere en modo real (medido en [04](04_viabilidad_costes_latencia_compliance.md):
  ≈ 0,034 € p50 por briefing, ≈ 0,005 € por pregunta).

## Si algo falla

| Síntoma | Causa probable | Solución |
|---|---|---|
| El build tarda mucho o se queda sin memoria | Falta `LOCAL_MODELS=false` (está instalando torch) | Añádela en Variables y redespliega |
| *Application failed to respond* / 502 | El dominio apunta a otro puerto | Settings → Networking: puerto = el de `PORT` en los logs |
| La página carga pero se queda en blanco o «Connecting…» | Websockets cortados por una extensión o red | Prueba en otra red o en ventana privada; Railway admite websockets |
| No aparece el modo Real | Falta `BRIEFER_LLM_PROVIDER=anthropic` o `ANTHROPIC_API_KEY` | Paso 6 |
| Pide contraseña y no la acepta | Espacios o comillas en la variable | Escribe el valor sin comillas en Railway |
| El Archivo aparece vacío tras desplegar | Disco efímero | Paso 7 (volumen) |
| Error de permisos al guardar con volumen | Falta `RAILWAY_RUN_UID=0` | Paso 7 |
| Sin voz en la demo | edge-tts necesita salir a Internet (Railway lo permite) | Mira los logs; como respaldo, el modo «Demo offline» funciona sin red |

## Qué NO hacer

- No subas el `.env` a GitHub ni pegues claves en el código: van solo en **Variables** de Railway.
- No pongas claves de API sin `BRIEFER_REAL_MODE_PASSWORD` y sin límite de gasto: cualquiera con el enlace podría gastar.
- No cambies `data/samples/demo_briefing/` a mano: es el briefing de la portada (se regenera con `storage.export_briefing`).
