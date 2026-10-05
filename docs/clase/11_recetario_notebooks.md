# 11 · Recetario de los notebooks de clase

> Resumen operativo de los 11 notebooks de la clase *Modelos Fundacionales y Multimodales* (MIAX, 2-3 oct 2026).
> Para cada uno: qué hace, modelo exacto de Hugging Face, snippet mínimo reescrito, requisitos, trampas y cómo encaja en
> nuestro MVP (rutas según la spec del repo). Originales en `docs/raw/notebooks/` (no versionados) y texto extraído en
> `docs/raw/text/nb_*.txt`.

**Contexto común a todos los notebooks**

- Se ejecutaron en **Google Colab con GPU T4 (16 GB VRAM)**, salvo CLIP, CLAP, agentes e IQA, que no fijan GPU.
- Patrón general: `pipeline(tarea, model=...)` para prototipar rápido; `Processor` + `Model` cuando hace falta control
  fino (parámetros de generación, lotes, tensores intermedios). Ver `12_pistas_profesor.md`.
- Todo descarga pesos del Hub en la primera ejecución. Sin `HF_TOKEN` funciona, pero con límites de descarga más bajos
  (aviso visible en los outputs). Los modelos con acceso restringido (p. ej. Llama) sí requieren login.
- En nuestro MVP la opción por defecto es **API** (Claude, Whisper API, edge-tts). Los modelos locales de clase son
  alternativas intercambiables por config (`BRIEFER_*_PROVIDER`) o extras para subir nota por "pluralidad de modelos".

---

## NB1 · Repaso de tareas texto-imagen con `transformers`

**Objetivo.** Recorrer en un solo notebook las cuatro familias texto-imagen: VQA, DocVQA, captioning y generación de
imagen, contrastando *pipeline* frente a *processor + model*.

**Modelos (HF).**
| Tarea | Modelo | Pipeline / clase |
|---|---|---|
| VQA | `llava-hf/llava-interleave-qwen-0.5b-hf` (~1,7 GB) | `pipeline("image-text-to-text")` |
| DocVQA | `naver-clova-ix/donut-base-finetuned-docvqa` | `pipeline("document-question-answering")` |
| Captioning | `Salesforce/blip-image-captioning-base` / `-large` | pipeline o `BlipProcessor` + `BlipForConditionalGeneration` |
| Texto→imagen | `stabilityai/stable-diffusion-xl-base-1.0` (fp16) | `diffusers.DiffusionPipeline` |

**Librerías.** `transformers`, `torch`, `Pillow`, `requests`, `diffusers`, `accelerate`, `safetensors`, `invisible_watermark`.

**Snippet mínimo (VQA + DocVQA con pipelines).**
```python
from transformers import pipeline
from PIL import Image

img = Image.open("grafico.png").convert("RGB")
vqa = pipeline("image-text-to-text", model="llava-hf/llava-interleave-qwen-0.5b-hf", device_map="auto")
msgs = [{"role": "user", "content": [{"type": "image", "image": img},
                                     {"type": "text", "text": "¿Qué tendencia muestra el gráfico?"}]}]
respuesta = vqa(msgs, max_new_tokens=128)[0]["generated_text"][-1]["content"]

doc = pipeline("document-question-answering", model="naver-clova-ix/donut-base-finetuned-docvqa")
cifra = doc(image=img, question="What is the net income?")[0]["answer"]
```

**Requisitos.** GPU recomendada (el NB1 corrió en T4). LLaVA 0,5B y BLIP son ligeros; SDXL base en fp16 necesita
~8-10 GB y tarda decenas de segundos por imagen con 30 pasos (estimación, no viene de clase).

**Trampas / gotchas.**
- La salida de la pipeline de chat devuelve **la conversación entera**; la respuesta está en el último mensaje.
- Avisos `max_new_tokens` vs `max_length`: fijar explícitamente `max_new_tokens`.
- DocVQA (Donut) "lee" bien una nómina limpia, pero el formato numérico puede salir alterado (p. ej. separadores de
  miles/decimales) y **con imagen borrosa se inventa la cifra** en lugar de decir que no lo sabe.
- Olvidar `.eval()` al cargar el modelo a mano (dropout/normalizaciones activas) — el profesor insiste en ello.
- En SDXL: usar siempre `generator` con semilla para reproducibilidad; `negative_prompt`, `num_inference_steps` y
  `guidance_scale` son los mandos principales.

**Uso en nuestro MVP.** Referencia conceptual para `ingest/chart_reader.py` y `ingest/pdf_reader.py` (VQA/DocVQA). En
producción usamos Claude visión (`providers/vision/claude_vision.py`); Donut podría servir como extractor local barato de
cifras en páginas de PDF escaneadas. Captioning: no aplica. SDXL base: no (usamos Turbo, NB4).

---

## NB2 · Jugando con CLIP (y SigLIP)

**Objetivo.** Entender el modelo contrastivo imagen-texto: clasificación *zero-shot*, la trampa del softmax, anatomía de
salidas, similitud imagen-imagen, estados intermedios y CLIP como métrica perceptual.

**Modelos (HF).** `openai/clip-vit-base-patch32` (151 M parámetros: 63 M texto + 87 M visión) y
`google/siglip2-base-patch16-224`. Variantes comentadas: `clip-vit-base-patch16`, `clip-vit-large-patch14` (y `-336`).

**Librerías.** `transformers` (`CLIPModel`, `AutoModel`, `AutoProcessor`), `torch`, `Pillow`.

**Snippet mínimo (clasificar una imagen subida para enrutarla).**
```python
import torch
from transformers import AutoModel, AutoProcessor

repo = "google/siglip2-base-patch16-224"
model, proc = AutoModel.from_pretrained(repo).eval(), AutoProcessor.from_pretrained(repo)
labels = ["a candlestick stock chart", "a line chart of a stock price",
          "a table of financial figures", "a photo of something else"]
inputs = proc(text=labels, images=img, padding="max_length", return_tensors="pt")
with torch.no_grad():
    probs = torch.sigmoid(model(**inputs).logits_per_image)[0]   # independientes, no suman 1
scores = dict(zip(labels, probs.tolist()))
```

**Requisitos.** CPU suficiente (modelos base, <1 GB). Inferencia de milisegundos a ~1 s por imagen en CPU.

**Trampas / gotchas.**
- **Softmax de CLIP siempre reparte el 100 %**: ante opciones absurdas elige una con confianza (tanque → "gato" 66 %).
  Incluir siempre una clase "otra cosa / none" o umbralizar el logit bruto. SigLIP (sigmoide) da probabilidades
  independientes que pueden ser todas bajas — pero ojo, sus valores absolutos son pequeños (10 % para la respuesta
  correcta en el ejemplo): calibrar umbral con ejemplos propios.
- SigLIP necesita `padding="max_length"` (así se entrenó).
- Usar frases tipo "a photo of a …" en vez de palabras sueltas; CLIP rinde mejor en inglés.
- CLIP cuenta mal objetos; sí capta bien detalles descriptivos (más detalle en el texto → más probabilidad).
- `softmax(dim=1)` = una imagen frente a varios textos; `dim=0` = un texto frente a varias imágenes.
- `pooler_output` del `vision_model` **no está normalizado**: para comparar imágenes, normalizar (coseno) o usar
  `image_embeds`.
- Patch más pequeño / modelo *large* = más detalle pero coste de atención cuadrático en nº de tokens.

**Uso en nuestro MVP.** Opcional: `providers/image/clip_classifier.py` (`ImageClassifier.classify`) para decidir si una
captura subida es gráfico de velas, tabla u otra cosa antes de llamar a visión (y rechazar imágenes no financieras). Suma
un modelo especializado más a la cadena (bueno para la rúbrica) con coste casi nulo.

---

## NB3 · VQA con un VLM (Qwen2.5-VL)

**Objetivo.** Usar un *Vision-Language Model* de verdad: descripción, preguntas cerradas, varias imágenes, preguntas en
español y lectura de documentos (aproximación a OCR), incluida la degradación por baja resolución.

**Modelo (HF).** `Qwen/Qwen2.5-VL-3B-Instruct` (~7,5 GB de pesos; tarda ~2 min en descargar en Colab).

**Librerías.** `transformers` (`Qwen2_5_VLForConditionalGeneration`, `AutoProcessor`), `qwen-vl-utils[decord]==0.0.8`
(`process_vision_info`), `torch`, `accelerate`.

**Snippet mínimo.**
```python
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info

repo = "Qwen/Qwen2.5-VL-3B-Instruct"
model = Qwen2_5_VLForConditionalGeneration.from_pretrained(repo, torch_dtype="auto", device_map="auto")
proc = AutoProcessor.from_pretrained(repo)
msgs = [{"role": "user", "content": [{"type": "image", "image": img},
         {"type": "text", "text": "Extrae ticker, periodo y variación del gráfico. Responde en JSON."}]}]
text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
imgs, vids = process_vision_info(msgs)
inp = proc(text=[text], images=imgs, videos=vids, padding=True, return_tensors="pt").to(model.device)
out = model.generate(**inp, max_new_tokens=256)
answer = proc.batch_decode(out[:, inp.input_ids.shape[1]:], skip_special_tokens=True)[0]
```

**Requisitos.** GPU con ≥8 GB (T4 OK). En clase, describir una imagen de 600×400 tardó ~19 s en T4 **[03:57]**. En CPU
es impracticable para una demo.

**Trampas / gotchas.**
- Hay que **recortar los tokens de entrada** de la salida de `generate` para quedarse solo con la respuesta.
- `max_new_tokens` corta en seco (con 4 tokens en el notebook, 8 en la demo de clase, la respuesta quedó a medias); un
  límite alto no obliga a responder largo.
- `device_map="auto"` reparte solo en varias GPUs y elige CUDA si existe (no hace falta `.to("cuda")`).
- Más resolución → más tokens visuales → mejor lectura pero más lento: compromiso explícito.
- Con un documento pequeño (miniatura) el modelo 3B **no supo leer la cifra** y contestó con generalidades; con la imagen
  degradada, peor aún. En finanzas un dígito mal leído cambia el significado: validar cifras extraídas.
- Tips del cierre del notebook: usar los parámetros de generación recomendados por el autor del modelo; los modos "que
  piensan" tardan mucho más; para salida estructurada pedir **JSON** (hay librerías para forzarlo); MLflow para registrar
  interacciones en producción.

**Uso en nuestro MVP.** Alternativa local de `providers/vision/qwen_vl_local.py` (`VisionProvider.describe`) para
`ingest/chart_reader.py` y páginas-imagen de `ingest/pdf_reader.py`. Por defecto usamos Claude visión (sin GPU, mejor
lectura de cifras). Mantener el prompt pidiendo JSON con `key_figures` para mapear a `DocumentInsight`.

---

## NB4 · Generación de imágenes con SDXL-Turbo

**Objetivo.** Texto→imagen e imagen→imagen con un modelo de difusión destilado para muy pocos pasos.

**Modelo (HF).** `stabilityai/sdxl-turbo` (fp16).

**Librerías.** `diffusers` (`AutoPipelineForText2Image`, `AutoPipelineForImage2Image`), `transformers`, `accelerate`, `torch`.

**Snippet mínimo (portada del briefing).**
```python
import torch
from diffusers import AutoPipelineForText2Image

pipe = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/sdxl-turbo", torch_dtype=torch.float16, variant="fp16").to("cuda")
g = torch.Generator("cuda").manual_seed(42)
img = pipe(prompt="minimalist editorial illustration of a stock market morning, blue tones, no text",
           guidance_scale=0.0, num_inference_steps=4, generator=g).images[0]
img.save("data/outputs/portada.png")
```

**Requisitos.** GPU (el NB4 corrió en T4); 1-4 pasos → del orden de 1-3 s por imagen 512×512 tras la carga. En CPU es
lento (minutos). Tiempos: estimación, no viene de clase.

**Trampas / gotchas.**
- Turbo se usa con `guidance_scale=0.0` y muy pocos pasos (el notebook compara 4 y 10; 1-4 según la ficha del modelo);
  subir pasos no siempre mejora.
- Poner "8k" en el prompt no cambia la resolución real.
- Img2img: `strength` bajo conserva la imagen original; alto da libertad al modelo.
- Los modelos de difusión **no escriben texto legible**: nunca generar gráficos con cifras así; las cifras van en
  matplotlib/plotly.
- Avisos de deprecación (`torch_dtype` → `dtype`) en versiones nuevas de diffusers: inofensivos.

**Uso en nuestro MVP.** Opcional: `providers/image/sdxl_turbo.py` (`ImageGenProvider.generate`) desde `media/cover.py`
para la portada/miniatura del podcast y fondo del vídeo. Si no hay GPU, desactivar o usar API de imagen.

---

## NB5 · Generación de vídeo con Stable Video Diffusion

**Objetivo.** Imagen→vídeo: el modelo infiere movimiento a partir de una sola imagen.

**Modelo (HF).** `stabilityai/stable-video-diffusion-img2vid-xt` (fp16).

**Librerías.** `diffusers` (`StableVideoDiffusionPipeline`, `load_image`, `export_to_video`), `transformers`,
`accelerate`, `torch`.

**Snippet mínimo.**
```python
import torch
from diffusers import StableVideoDiffusionPipeline
from diffusers.utils import load_image, export_to_video

pipe = StableVideoDiffusionPipeline.from_pretrained(
    "stabilityai/stable-video-diffusion-img2vid-xt", torch_dtype=torch.float16, variant="fp16")
pipe.enable_model_cpu_offload()                      # ahorra VRAM
img = load_image("data/outputs/portada.png").resize((1024, 576))
frames = pipe(img, decode_chunk_size=8, generator=torch.manual_seed(42)).frames[0]
export_to_video(frames, "data/outputs/intro.mp4", fps=12)   # 25 frames ≈ 2 s
```

**Requisitos.** GPU obligatoria; en T4 con *cpu offload* funciona pero tarda minutos por clip (estimación, no viene de
clase). Produce solo 25 fotogramas (≈2 s a 12 fps).

**Trampas / gotchas.**
- La salida son fotogramas, no un `.mp4`: hay que exportar.
- `decode_chunk_size` controla la memoria al decodificar; la VRAM es el cuello de botella en vídeo.
- Resolución esperada 1024×576 (panorámica).
- El movimiento es inventado: no es una simulación física fiable; zonas pequeñas se degradan.

**Uso en nuestro MVP.** Solo como extra vistoso (intro animada de 2 s). El vídeo del briefing se monta en `media/video.py`
con `moviepy` + ffmpeg (imágenes de gráficos/portada + audio + subtítulos), que es determinista, barato y rápido.

---

## NB6 · Generación de audio con Bark (Suno)

**Objetivo.** Texto→voz con un modelo generativo que también responde a pistas expresivas en el prompt.

**Modelo (HF).** `suno/bark` (el título dice "Suno" porque Bark es de Suno; no es su app de música).

**Librerías.** `transformers` (`pipeline("text-to-speech")`), `IPython.display.Audio`; para guardar, `scipy` o `soundfile`.

**Snippet mínimo.**
```python
from transformers import pipeline
import soundfile as sf

tts = pipeline("text-to-speech", model="suno/bark", device_map="auto")
out = tts("Buenos días. Hoy el Ibex abre en verde [laughs] y la banca tira del índice.")
sf.write("data/outputs/linea_A.wav", out["audio"].squeeze(), out["sampling_rate"])
```

**Requisitos.** GPU muy recomendable; lento incluso en T4. Cada llamada genera como máximo ~13 s de audio (límite
conocido de Bark, no viene de clase), así que un podcast exige trocear por frases y fijar la voz de cada locutor.

**Trampas / gotchas.**
- La salida es `{"audio": ndarray, "sampling_rate": int}`: hay que usar su `sampling_rate` al guardar/reproducir.
- El prompt también controla el *cómo*: `♪` induce canto, `[laughs]` risas; el resultado es estocástico (voz y tono
  pueden variar entre llamadas → difícil mantener dos voces consistentes).
- No controla bien acento español ni nombres de tickers (estimación, no viene de clase).

**Uso en nuestro MVP.** Posible alternativa local para `media/podcast.py`, **no implementada** (en `providers/tts/` solo
existen `edge_tts_provider.py` y `elevenlabs_tts.py`; habría que añadir un proveedor y su nombre en `config.py`). Por
defecto `edge-tts` (gratis, voces es-ES fijas para A y B, rápido); premium `elevenlabs_tts.py`. Bark solo si se quiere
demostrar un TTS abierto local.

---

## NB7 · Transcripción de audio con Whisper

**Objetivo.** Audio→texto (ASR) cerrando el bucle con el NB6: generar voz y volver a transcribirla.

**Modelo (HF).** `openai/whisper-base` (ligero). Se carga `AutoModelForSpeechSeq2Seq` + `AutoProcessor`, aunque al final
se usa `pipeline(model="openai/whisper-base")`.

**Librerías.** `transformers`, `torch`, `scipy.io.wavfile`, `numpy`, `datasets`.

**Snippet mínimo (pregunta por voz).**
```python
import torch
from transformers import pipeline

asr = pipeline("automatic-speech-recognition", model="openai/whisper-base",
               torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
               device_map="auto")
res = asr("data/cache/pregunta.wav",                # ruta: la pipeline decodifica y remuestrea (requiere ffmpeg)
          generate_kwargs={"language": "spanish", "task": "transcribe"},
          chunk_length_s=30)                        # audios > 30 s (alternativa: return_timestamps=True)
texto = res["text"].strip()
```

**Requisitos.** Corre en CPU para audios cortos (segundos); GPU acelera mucho. `whisper-base` es pequeño; `small`/`medium`
mejoran el español a cambio de latencia.

**Trampas / gotchas.**
- WAV PCM16 llega como enteros: normalizar a `float32` dividiendo por 32768.
- El notebook pasa un array crudo sin frecuencia: en ese caso la pipeline asume 16 kHz (no viene de clase); pasar
  `{"raw": data, "sampling_rate": sr}` o remuestrear (Bark genera a 24 kHz). Pasar ruta de fichero evita el problema.
- Sin fijar idioma, Whisper lo autodetecta y avisa (aviso visible en el output); fijar `language="spanish"`.
- Errores típicos en palabras (en el output del notebook transcribió "huye" por "audio"); tickers y siglas
  financieras se transcriben mal: normalizar con un diccionario de tickers en `ingest/tickers.py`.
- Probar con ruido: la calidad cae.

**Uso en nuestro MVP.** Sí: `providers/stt/whisper_api.py` (por defecto) y `whisper_local.py` (`faster-whisper`) para
`ingest/voice.py` y el Q&A por voz (`answer_question` → STT → `agents/qa.py` → TTS).

---

## NB8 · CLAP: CLIP para audio

**Objetivo.** Relacionar audio y texto en un espacio común: clasificar sonidos *zero-shot* con descripciones.

**Modelo (HF).** `laion/clap-htsat-unfused`. Datos de ejemplo: `hf-internal-testing/ashraq-esc50-1-dog-example` (ESC-50).

**Librerías.** `transformers` (`ClapModel`, `AutoProcessor`), `datasets`, `torch`.

**Snippet mínimo.**
```python
import torch
from transformers import ClapModel, AutoProcessor

model = ClapModel.from_pretrained("laion/clap-htsat-unfused").eval()
proc = AutoProcessor.from_pretrained("laion/clap-htsat-unfused")
labels = ["a person speaking clearly", "background noise", "music", "silence"]
inp = proc(text=labels, audio=audio_48k, sampling_rate=48_000, return_tensors="pt", padding=True)
with torch.no_grad():
    probs = model(**inp).logits_per_audio.softmax(dim=-1)[0]
```

**Requisitos.** CPU suficiente.

**Trampas / gotchas.**
- Pasar siempre `sampling_rate` (CLAP espera 48 kHz); sin él hay errores silenciosos (aviso en el notebook).
- Mismo problema de softmax que CLIP: es preferencia entre las opciones dadas, no probabilidad absoluta (prefiere "perro
  grande" aunque el audio no contenga esa información).

**Uso en nuestro MVP.** No en el camino principal. Idea opcional: control de calidad del audio subido en `ingest/voice.py`
(¿hay voz o solo ruido/silencio?) antes de gastar STT. Baja prioridad.

---

## NB9 · Agentes: de lenguaje natural a SQL con `smolagents`

**Objetivo.** Construir un agente que convierte preguntas en lenguaje natural en consultas SQL ejecutadas por una
herramienta Python, y comprobar su respuesta contra una consulta de referencia.

**Modelos.** Vía API de inferencia de HF (`InferenceClientModel`): `meta-llama/Llama-3.1-8B-Instruct` (requiere login y
acceso) y `Qwen/Qwen2.5-72B-Instruct` para la consulta con JOIN.

**Librerías.** `smolagents` (`tool`, `CodeAgent`, `InferenceClientModel`), `sqlalchemy` (SQLite en memoria),
`huggingface_hub` (`notebook_login`).

**Snippet mínimo (herramienta de solo lectura sobre nuestros datos).**
```python
from smolagents import tool, CodeAgent, InferenceClientModel

@tool
def get_prices(ticker: str) -> str:
    """Devuelve el último precio y la variación diaria de un ticker.

    Args:
        ticker: símbolo bursátil, p. ej. "SAN.MC".
    """
    snap = prices.get_snapshot(ticker)            # ingest/prices.py
    return f"{snap.ticker}: {snap.last} ({snap.change_pct:+.2f} %)"

agent = CodeAgent(tools=[get_prices], model=InferenceClientModel("Qwen/Qwen2.5-72B-Instruct"))
print(agent.run("¿Cómo ha cerrado hoy Santander?"))
```

**Requisitos.** Sin GPU (inferencia remota); necesita token de HF. En los outputs, cada pregunta consumió 2-3 pasos de
2-7 s (~9-14 s en total) y de 2.000 a ~7.000 tokens de entrada acumulados (crecen en cada paso porque se reenvía el
historial).

**Trampas / gotchas.**
- La **docstring de la herramienta es su manual** (el modelo decide con ella): describir tablas/columnas, argumentos y
  relaciones (p. ej. la clave de JOIN). Mejor generar la descripción desde el esquema real.
- La tool **devuelve los errores como texto** en vez de lanzar excepciones, para que el agente pueda autocorregirse.
- Modelos pequeños se equivocan más (el 8B falló SQL antes de acertar); para tareas con JOIN usaron un 72B.
- La protección "solo SELECT" del ejemplo es mínima: en producción, permisos de solo lectura reales en la BD.
- Verificar siempre la respuesta del agente contra una referencia determinista.
- Ojo a la forma de la respuesta final (devolvió una tupla serializada como texto).

**Uso en nuestro MVP.** Inspira `agents/qa.py`: el agente Q&A puede tener herramientas de solo lectura (precios,
noticias del briefing, `storage`), nunca de escritura ni de envío. Implementación por defecto con Claude (tool use) vía
`providers/llm/anthropic_llm.py`; `smolagents` es alternativa. Encaja con la advertencia de clase sobre permisos de
agentes (ver `08_agentes_y_riesgos.md`).

---

## NB10 · Fine-tuning de un VLM con LoRA (ChartQA)

**Objetivo.** Mejorar un VLM pequeño en preguntas sobre gráficos mediante SFT + LoRA, comparando antes/después.

**Modelo y datos (HF).** `Qwen/Qwen2-VL-2B-Instruct` (bfloat16) sobre `HuggingFaceM4/ChartQA` (2 % de cada split: 1.415
train / 96 val / 125 test).

**Librerías.** `trl` (`SFTConfig`, `SFTTrainer`), `peft` (`LoraConfig`), `transformers` (`Qwen2VLForConditionalGeneration`,
`Qwen2VLProcessor`), `qwen-vl-utils`, `datasets`, `accelerate`, `bitsandbytes`, `torchao`, `trackio`.

**Snippet mínimo (configuración clave).**
```python
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer

lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
                  target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM")
args = SFTConfig(output_dir="qwen2vl-chartqa-lora", num_train_epochs=1,
                 per_device_train_batch_size=2, gradient_accumulation_steps=8,
                 learning_rate=2e-4, bf16=True, max_length=1024, max_grad_norm=0.3,
                 warmup_steps=10, eval_strategy="steps", eval_steps=10,
                 remove_unused_columns=False)          # imprescindible: si no, borra la columna "images"
trainer = SFTTrainer(model=model, args=args, train_dataset=train_ds, eval_dataset=eval_ds,
                     peft_config=lora, processing_class=processor)
trainer.train(); trainer.save_model(args.output_dir)   # luego: model.load_adapter(args.output_dir)
```

**Requisitos.** GPU (el NB10 corrió en T4 de 16 GB según sus metadatos; el 2B en bf16 cabe sin cuantizar). Entrenamiento
de una época sobre 1.415 ejemplos: del orden de decenas de minutos (estimación, no viene de clase). Para modelos mayores: cuantización 4/8 bit con `bitsandbytes` (QLoRA).

**Trampas / gotchas.**
- Formatear cada ejemplo como conversación (system + user con `{"type": "image"}` + assistant) siguiendo la *model card*.
- En ChartQA la etiqueta a veces viene como lista: normalizar a `str`.
- Usar `.map()` para conservar el tipo `Image` de `datasets`.
- Antes de inferir, sustituir el *placeholder* de imagen por la imagen real para `process_vision_info`.
- Liberar VRAM entre fases (`del model`, `gc.collect()`, `torch.cuda.empty_cache()`); aun así quedaron ~4 GB ocupados.
- En *zero-shot* el modelo base respondió de más y con errores: el fine-tuning busca respuestas concisas y correctas.

**Uso en nuestro MVP.** No para la entrega del 8-oct (no hay tiempo ni datos propios). Sí como argumento en el pitch y en
`docs/05_roadmap_TODO.md`: un VLM pequeño ajustado a gráficos financieros reduciría coste/latencia frente a la API de
visión en `ingest/chart_reader.py`.

---

## NB11 · IQA: calidad de imagen y métricas perceptuales

**Objetivo.** Comparar métricas clásicas (RMSE, PSNR, SSIM) con métricas aprendidas (LPIPS) y multimodales (TPIPS) para
decidir qué imagen distorsionada se parece más a la original, como lo haría un humano.

**Modelos.** `lpips` con redes `alex` y `vgg`; `tpips.load_model("embedding")`, que descarga
`sywang/TPIPS-Embed-Qwen3VL-8B` (basado en un VLM de 8B). Imágenes del repositorio KonIQ/MMSP.

**Librerías.** `numpy`, `Pillow`, `matplotlib`, `tensorflow` (SSIM), `torch`, `lpips`, `tpips`.

**Snippet mínimo (LPIPS).**
```python
import lpips, numpy as np, torch

def to_t(img):  # PIL RGB → tensor [-1, 1]
    return torch.from_numpy(np.array(img).transpose(2, 0, 1)[None].astype(np.float32) / 127.5 - 1.0)

metric = lpips.LPIPS(net="alex")
with torch.inference_mode():
    d = metric(to_t(ref_img), to_t(dist_img)).item()   # menor = más parecida perceptualmente
```

**Requisitos.** RMSE/PSNR/SSIM y LPIPS en CPU. TPIPS carga un modelo de 8B (`Qwen3-VL-Embedding-8B`): en el notebook se
forzó CPU (muy lento); en GPU necesita bastante VRAM.

**Trampas / gotchas.**
- RMSE/PSNR pueden contradecir la percepción humana (una imagen desplazada "parece" muy distinta píxel a píxel).
- Distancias (menor = mejor) frente a similitudes (mayor = mejor): no confundir el sentido.
- LPIPS espera tensores en [-1, 1] y formato NCHW.
- El notebook imprime por error `similarity_ref_2` donde debería ir `distance_ref_2` (errata del original).

**Uso en nuestro MVP.** No aplica directamente. Posible uso marginal: control de calidad de capturas subidas (rechazar
imágenes demasiado degradadas antes de la lectura con visión) o evaluación de la portada generada. Ver
`10_iqa_metricas.md`.

---

## Tabla resumen

| NB | Modalidad (entrada → salida) | Modelo de clase | ¿En el MVP? | Alternativa API / por defecto |
|---|---|---|---|---|
| 1 | imagen + texto → texto (VQA, DocVQA, caption); texto → imagen | LLaVA-interleave-0.5B, Donut DocVQA, BLIP, SDXL base | Opcional (referencia para visión/PDF) | Claude visión; `pypdf` para texto de PDF |
| 2 | imagen ↔ texto (similitud / zero-shot) | CLIP ViT-B/32, SigLIP2 base | Opcional (`clip_classifier.py`) | Claude visión con prompt de clasificación |
| 3 | imagen(es) + texto → texto | Qwen2.5-VL-3B-Instruct | Opcional (`qwen_vl_local.py`) | Claude visión (por defecto), Gemini |
| 4 | texto (+imagen) → imagen | SDXL-Turbo | Opcional (`sdxl_turbo.py` → `media/cover.py`) | API de imagen (OpenAI/Gemini) |
| 5 | imagen → vídeo | Stable Video Diffusion img2vid-xt | No (solo extra) | `moviepy` + ffmpeg (por defecto) |
| 6 | texto → audio (voz) | Bark (`suno/bark`) | No implementado (local, lento) | `edge-tts` (por defecto), ElevenLabs, OpenAI TTS |
| 7 | audio → texto | Whisper base | **Sí** (`whisper_api.py` por defecto / `whisper_local.py`) | Whisper API de OpenAI |
| 8 | audio ↔ texto (similitud) | CLAP HTSAT unfused | No (idea de QA de audio) | — |
| 9 | texto → acciones/herramientas → texto | Llama-3.1-8B / Qwen2.5-72B vía `smolagents` | **Sí** (patrón para `agents/qa.py`) | Claude tool use |
| 10 | imagen + texto → texto (ajustado a gráficos) | Qwen2-VL-2B + LoRA (ChartQA) | No (roadmap/pitch) | Claude visión |
| 11 | imagen × imagen → puntuación de calidad | LPIPS, TPIPS (Qwen3-VL-8B emb.) | No | — |
