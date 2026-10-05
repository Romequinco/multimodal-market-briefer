# 06 · Generación y comprensión de vídeo

**Fuentes:** slides ~236-244 (de imagen a vídeo, Video Diffusion Models, Imagen Video, Omni-Video) y ~259-262 (img2vid, text2vid: Veo 3, Sora, Wan 2.1; VQA sobre vídeo y highlights con SmolVLM2); notebook `nb_5._Video_generation_with_Stable_Video_Diffusion`. La transcripción del 2-oct no llega a esta parte.

> **TL;DR**
> - Un modelo de vídeo es un modelo de imagen "extendido en el tiempo": **operaciones 3D (espacio+tiempo)**, **atención temporal** para coherencia y generación de pocos frames + **interpolación/superresolución**.
> - **Stable Video Diffusion** (`stabilityai/stable-video-diffusion-img2vid-xt`) anima una imagen fija: ~25 frames 1024×576 → ~2 s de clip a 12 fps. Pesado y lento.
> - Text-to-video de calidad (Veo, Sora, Wan) existe, pero para nosotros es caro/lento.
> - **Decisión MVP:** vídeo = **montaje con moviepy/ffmpeg** (gráficos + portada + audio + subtítulos). SVD solo como extra cosmético precalculado.

---

## 1. De imagen a vídeo

- **Vídeo = muchas imágenes**: los modelos de vídeo heredan la arquitectura de los de imagen.
- Tres cambios clave (slides):
  1. Las operaciones **2D (espaciales)** pasan a **3D (espaciales + temporales)**.
  2. Mecanismos de **coherencia temporal**, sobre todo **atención temporal** (cada píxel/patch atiende a su posición en otros frames).
  3. Se generan **pocos frames clave** y luego se **interpolan** o se generan los intermedios.
- **Video Diffusion Models:** igual que la difusión de imagen pero con una **3D U-Net ("Video U-Net")** en lugar de la 2D.
- El cuello de botella es la **memoria**: se procesan decenas de imágenes a la vez.

## 2. Google Imagen Video (cascada)

Genera vídeo de **1280×768 a 24 fps** encadenando modelos; la parte "creativa" solo ocurre al principio:

| Etapa | Función |
|---|---|
| **T5-XXL** | Codificador de texto: prompt → embeddings |
| **Base** | Difusión de vídeo a **baja resolución espacial y temporal**; convoluciones/atención espaciales (por frame) + temporales (entre frames) |
| **SSR** (Spatial Super-Resolution) | Aumenta la resolución de cada frame |
| **TSR** (Temporal Super-Resolution) | Interpola frames intermedios → más fps |

Patrón general a recordar: **base pequeña + cascada de superresolución espacial y temporal**.

## 3. Omni-Video

- Ejemplo de **MLLM que además genera vídeo**: un LLM multimodal entiende la petición y un decoder de difusión de vídeo la materializa (patrón "encoder + conector + LLM + generador" visto en la parte de MLLM). También aparece en VQA sobre vídeo.

## 4. Stable Video Diffusion (SVD) — notebook 5

- **Image-to-video sin texto**: recibe una imagen y "imagina" el movimiento.
- Pipeline `StableVideoDiffusionPipeline`, checkpoint `stabilityai/stable-video-diffusion-img2vid-xt` (la variante *xt* genera 25 frames; la base, 14).

| Parámetro (notebook) | Valor | Para qué |
|---|---|---|
| `torch_dtype` / `variant` | `float16` / `"fp16"` | Mitad de memoria que fp32 |
| `enable_model_cpu_offload()` | activado | Mueve submódulos entre CPU y GPU → cabe en Colab (más lento) |
| Tamaño de entrada | **1024×576** | Resolución panorámica con la que se entrenó |
| `generator` | `torch.manual_seed(42)` | Reproducibilidad |
| `decode_chunk_size` | **8** | Decodifica frames por bloques (menos pico de VRAM; bajar a 2-4 si hay OOM) |
| `export_to_video(..., fps=12)` | 12 fps | Empaqueta la lista de frames PIL en `.mp4` |

Otros parámetros útiles de la pipeline (no usados en el notebook): `motion_bucket_id` (más alto = más movimiento), `noise_aug_strength` (cuánto se aleja de la imagen inicial), `num_frames`.

- La salida intermedia **no es un mp4**: es una lista de imágenes (`frames`).
- Advertencia del notebook: el modelo **infiere** el movimiento; no es una simulación física. Zonas pequeñas o poco definidas se deforman y puede inventar movimientos.

## 5. Text-to-video y otros (slides)

| Modelo | Tipo | Comentario |
|---|---|---|
| Video Diffusion Model, Imagen Video, Omni-Video | Investigación | Base conceptual |
| **Veo 3** (Google DeepMind) | API comercial | Alta calidad, genera también audio |
| **Sora** (OpenAI) | Producto/API | Alta calidad |
| **Wan 2.1** (Alibaba) | Abierto, Space en HF | La versión pequeña (1.3B) corre en GPUs de consumo (dato externo, no viene de clase) |
| SVD, **LivePortrait** (Kling) | Img2vid | LivePortrait anima un retrato (cabeza que habla/gestos) |

## 6. Comprensión de vídeo: VQA y highlights

- **VQA sobre vídeo**: Perception LM (Meta), **SmolVLM2** (Hugging Face, modelos de 256M-2.2B, muy ligeros), Omni-Video. Se muestrean frames y se pasan como secuencia de imágenes al VLM.
- **Highlights video generator** (Space de SmolVLM2): el modelo detecta los momentos relevantes de un vídeo largo y monta un resumen.
- Qwen2.5-VL (visto en el notebook 3) también acepta vídeo.

## Receta de código (del notebook)

```python
import torch
from diffusers import StableVideoDiffusionPipeline
from diffusers.utils import load_image, export_to_video

pipe = StableVideoDiffusionPipeline.from_pretrained(
    "stabilityai/stable-video-diffusion-img2vid-xt",
    torch_dtype=torch.float16, variant="fp16")
pipe.enable_model_cpu_offload()          # en vez de .to("cuda") si hay poca VRAM

image = load_image("cover.png").resize((1024, 576))
frames = pipe(image, decode_chunk_size=8,
              generator=torch.manual_seed(42)).frames[0]   # lista de PIL
export_to_video(frames, "cover_loop.mp4", fps=12)
```

## Requisitos prácticos

Cifras orientativas (estimación, no viene de clase); del NB5 solo constan la GPU T4 de Colab, la salida de 25 frames 1024×576 y `fps=12`.

| Aspecto | SVD-xt | Montaje moviepy (nuestro MVP) |
|---|---|---|
| GPU / VRAM | Sí; ~10-16 GB en fp16, menos con CPU offload y `decode_chunk_size` bajo | No |
| Tiempo | 1-3 min por clip de ~2 s en T4/A10 (descarga inicial ~10 GB) | Segundos (depende de la duración del audio) |
| CPU | Inviable en la práctica | Sí |
| Alternativa API | Veo / Sora / Runway / Stability (coste por segundo de vídeo alto) | — |

## Aplicación a nuestro MVP

- **Módulo:** `src/briefer/media/video.py` → `VideoAsset`.
- **Decisión recomendada:** vídeo corto (formato vertical 9:16 o 16:9) montado con **moviepy + ffmpeg**:
  1. Secuencia de imágenes: portada (`media/cover.py`) + gráficos del día (`media/charts.py`), cada una durante el tramo de audio que la menciona (usar los `AudioSegment.start_s/end_s`).
  2. Efecto **Ken Burns** (zoom/paneo lento) para dar movimiento sin IA.
  3. Subtítulos quemados desde el SRT de `media/transcript.py`, con color por locutor A/B.
  4. Audio del podcast como pista principal.
- **SVD como extra opcional:** animar solo la portada para un intro de 2 s, **precalculado offline** y cacheado; nunca en el camino crítico de la demo. Jamás animar gráficos con datos (deformaría ejes/números).
- **Idea para el pitch (no MVP):** VQA de vídeo con SmolVLM2 para resumir vídeos de resultados/earnings calls; LivePortrait para un avatar presentador **sintético** (nunca la cara de una persona real).
- **Riesgos:** ffmpeg debe estar en el Dockerfile; tiempos de render en Streamlit (hacerlo en segundo plano y mostrar progreso); tamaño de fichero para email/Telegram (Telegram bot: límite de 50 MB por envío, dato externo, no viene de clase; comprimir a 720p).

## Glosario rápido

- **3D U-Net / Video U-Net:** U-Net con convoluciones espacio-temporales.
- **Atención temporal:** atención entre el mismo punto en distintos frames → coherencia.
- **SSR / TSR:** superresolución espacial / temporal (interpolación de frames).
- **Img2vid / text2vid:** vídeo desde imagen / desde texto.
- **CPU offload:** mover partes del modelo a CPU cuando no se usan.
- **`decode_chunk_size`:** frames decodificados por el VAE a la vez.
- **`motion_bucket_id`:** control de cantidad de movimiento en SVD.
- **Ken Burns:** zoom/paneo lento sobre una imagen fija.
- **Highlights:** resumen automático de momentos clave de un vídeo.
