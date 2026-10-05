# 05 · Generación de imagen: VAE, GAN, difusión, Stable Diffusion y SDXL-Turbo

**Fuentes:** slides ~217-235 (historia VAE/GAN, difusión, latent diffusion, condicionamiento por texto, Stable Diffusion, DreamBooth) y ~254-257 (texto-a-imagen comercial, pix2pix, superresolución, inpainting); notebook `nb_4._Image_generation_with_Stable_Diffusion_XL_Turbo`; transcripción del 2-oct (demo breve de Stable Diffusion: negative prompt, pasos, guidance, semilla).

> **TL;DR**
> - Los modelos de difusión generan imágenes **quitando ruido paso a paso**; la versión *latent* lo hace en un espacio comprimido por un autoencoder, lo que la hace viable en una GPU normal.
> - El texto entra vía un **codificador de texto (CLIP/T5) + cross-attention**; la *guidance* regula cuánto caso se hace al prompt.
> - **SDXL-Turbo** (`stabilityai/sdxl-turbo`) genera con **muy pocos pasos** y `guidance_scale=0.0` (el NB4 prueba 4 y 10; el rango de 1-4 pasos es de la ficha del modelo, no viene de clase); sirve para text2img e img2img (`strength`).
> - Para nosotros: **solo portada/ilustración decorativa opcional**. Nunca gráficos con datos (la difusión inventa números y no escribe texto fiable).

---

## 1. Historia breve de los generativos de imagen

| Familia | Idea | Puntos fuertes | Problemas típicos |
|---|---|---|---|
| **VAE** (Variational Autoencoder) | Encoder → distribución latente (media, varianza) → muestreo → decoder que reconstruye | Espacio latente continuo y estable; entrenamiento sencillo | Imágenes **borrosas** |
| **GAN** (Generative Adversarial Network) | **Generador** contra **discriminador** en un juego adversarial | Imágenes nítidas, generación en una pasada (rápida) | Entrenamiento inestable, **mode collapse**, poca diversidad |
| **Difusión** | Aprender a revertir un proceso de ruido gradual | Calidad y diversidad altas, entrenamiento estable, fácil de condicionar | Lenta en inferencia (muchos pasos) → motivó la destilación (Turbo, LCM...) |

Curiosidad útil: piezas de las tres familias conviven hoy. Stable Diffusion usa un **VAE** para comprimir, y SDXL-Turbo usa una pérdida **adversarial (tipo GAN)** para destilar la difusión a pocos pasos.

## 2. Modelos de difusión

- **Intuición de las slides:** generar una imagen desde ruido "de golpe" es difícil; **ensuciarla es trivial** (sumar números aleatorios). Así que se aprende el camino inverso **pasito a pasito**.
- **Proceso forward (difusión):** a una imagen real se le añade ruido gaussiano en T pasos hasta que queda ruido puro. No se aprende nada, es fijo.
- **Proceso reverse (denoising):** una red (clásicamente una **U-Net**; en modelos recientes, transformers tipo DiT) aprende a **predecir el ruido** presente en cada paso. En inferencia se parte de ruido puro y se aplica la red iterativamente.
- **`num_inference_steps`**: cuántos pasos de denoising. Más pasos ≈ más calidad (en modelos normales) pero más tiempo, casi lineal.
- **Scheduler/sampler** (DDPM, DDIM, Euler, DPM++...): decide cómo se recorren los pasos; distintos schedulers permiten usar menos pasos.

## 3. Latent Diffusion

- Problema: difundir en píxeles es caro. Una imagen de 128×128×3 ya son **49 152 valores** (ejemplo de las slides); a 512×512 son ~786 000.
- Solución: un **autoencoder (VAE)** comprime la imagen a un **latente** pequeño (en Stable Diffusion, 512×512×3 → 64×64×4, factor espacial 8) y la difusión trabaja ahí. Al final el **decoder del VAE** devuelve píxeles.
- Consecuencia práctica: generación de 512-1024 px en GPUs de consumo.

## 4. Condicionamiento por texto

- Sin condicionamiento, el modelo solo "genera imágenes plausibles". Para obedecer un prompt:
  1. Un **codificador de texto** (CLIP text encoder en SD; OpenCLIP ViT-bigG + CLIP ViT-L en SDXL; T5 en otros) convierte el prompt en embeddings.
  2. La U-Net los consume mediante **cross-attention** en sus bloques.
- **Classifier-Free Guidance (CFG, `guidance_scale`)**: se predice el ruido con y sin prompt y se extrapola hacia el condicionado. Valor alto = más fiel al prompt (y más saturado); valor muy bajo = el modelo "inventa lo que quiere" (comentario del profesor en la demo).
- **Negative prompt**: lo que NO quieres que aparezca. Funciona a través de la CFG, así que **con `guidance_scale=0.0` (SDXL-Turbo) no tiene efecto**.
- **Semilla (`generator=torch.manual_seed(n)`)**: el profesor insistió en fijarla siempre para que el resultado sea **reproducible**.

## 5. Stable Diffusion, SDXL y SDXL-Turbo

Valores habituales según las fichas de los modelos (no vienen de clase, salvo `guidance_scale=0.0` y la salida 512×512 de Turbo, que son del NB4):

| Modelo | Resolución nativa | Pasos típicos | Guidance | Notas |
|---|---|---|---|---|
| Stable Diffusion 1.x/2.x | 512 / 768 | 25-50 | 7-8 | VAE + U-Net + CLIP text encoder |
| SDXL | 1024 | 25-50 | 5-8 | U-Net más grande, 2 text encoders, refiner opcional |
| **SDXL-Turbo** | **512** | **1-4** | **0.0** | Destilado con *Adversarial Diffusion Distillation*; ideal para iterar rápido |

Otros texto-a-imagen citados (comerciales/API): Imagen 3, DALL-E, Midjourney, Grok, servicios de stability.ai.

### Text-to-image (notebook 4)
- Pipeline: `AutoPipelineForText2Image` con `torch_dtype=torch.float16`, `variant="fp16"`, `.to("cuda")`.
- El notebook compara `num_inference_steps=4` vs `10`: en Turbo **más pasos no garantiza mejor resultado**, está diseñado para pocos.
- Aviso del notebook: escribir **"8k" en el prompt no cambia la resolución real**; es solo una pista de estilo. La resolución la fijan `height`/`width`.

### Image-to-image (notebook 4)
- `AutoPipelineForImage2Image.from_pipe(pipeline_text2image)` **reutiliza los pesos ya cargados** (no duplica memoria).
- **imagen inicial + prompt → nueva imagen**; la imagen se redimensiona a 512×512.
- **`strength`**: bajo (0.2) conserva la estructura original; alto (0.8) da libertad al modelo. El notebook propone probar 0.2 / 0.5 / 0.8.
- Detalle práctico: en img2img los pasos efectivos son ≈ `num_inference_steps × strength`; con Turbo conviene que ese producto sea ≥ 1 (p. ej. 2 pasos con strength 0.5).

## 6. DreamBooth

- Técnica de **personalización**: con **3-5 fotos de un sujeto** se hace fine-tuning del modelo de difusión asociándolo a un **identificador raro** (p. ej. "a photo of sks dog").
- Usa una **pérdida de preservación de clase** (imágenes genéricas de "dog") para que el modelo no olvide la clase general.
- Hoy suele hacerse con **LoRA** (DreamBooth-LoRA), mucho más ligero.
- Aplicación potencial: una mascota/presentador de marca consistente. **No es prioridad para 3 días.**

## 7. Imagen a imagen (otras tareas)

| Tarea | Qué hace | Texto | Ejemplo |
|---|---|---|---|
| **pix2pix / InstructPix2Pix** | Genera condicionado a otra imagen (bocetos→foto, edición por instrucción) | A menudo sí | "conviértelo en acuarela" |
| **Superresolución** | Aumenta resolución/calidad; es una pieza interna de los generadores de imagen y vídeo en cascada | No | SD x4 upscaler, Real-ESRGAN |
| **Inpainting** | Rellena una zona enmascarada | Normalmente no (o opcional) | Borrar un objeto |

Las slides también enlazan Ultralytics (YOLO) como ejemplo de "imagen a muchas modalidades" (detección, segmentación, pose...).

## Receta de código (del notebook)

```python
import torch
from diffusers import AutoPipelineForText2Image, AutoPipelineForImage2Image
from diffusers.utils import load_image

t2i = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/sdxl-turbo", torch_dtype=torch.float16, variant="fp16").to("cuda")
g = torch.manual_seed(42)  # reproducible
cover = t2i(prompt="abstract editorial illustration of a stock market morning, blue tones",
            guidance_scale=0.0, num_inference_steps=4, generator=g).images[0]  # 512x512 PIL
cover.save("cover.png")

i2i = AutoPipelineForImage2Image.from_pipe(t2i).to("cuda")  # reutiliza pesos
init = load_image("base.png").resize((512, 512))
out = i2i("same scene, watercolor style", image=init, strength=0.5,
          guidance_scale=0.0, num_inference_steps=4, generator=g).images[0]
```

## Requisitos prácticos

Cifras orientativas (estimación, no viene de clase), salvo la GPU T4 de Colab, que es la del NB4.

| Aspecto | SDXL-Turbo |
|---|---|
| VRAM | ~6-8 GB en fp16 (cabe en una T4 de Colab de 16 GB) |
| Tiempo | ~1-3 s por imagen 512×512 a 1-4 pasos en T4 tras la carga; la primera carga descarga ~7 GB de pesos |
| CPU | Posible en fp32 (quitar `variant="fp16"`), pero lento: decenas de segundos a minutos por imagen y ~10 GB de RAM |
| Alternativa API | Stability API, OpenAI Images, Imagen (Gemini) — coste por imagen bajo, sin GPU |
| Licencia | Revisar la licencia de Stability (Community License; el uso comercial tiene condiciones). Importante para un pitch de startup |

## Aplicación a nuestro MVP

- **Módulos:** `src/briefer/providers/image/sdxl_turbo.py` (implementa `ImageGenProvider.generate(prompt, out_path)`) y `src/briefer/media/cover.py` (compone la portada final).
- **Decisión recomendada:**
  1. Por defecto, portada **sin IA**: plantilla PIL/matplotlib con fecha, titular y mini-sparkline. Rápida, determinista y sin licencias.
  2. **SDXL-Turbo opcional** (flag de config) solo para un **fondo abstracto/ilustrativo**; el titular y los números se superponen después con PIL (la difusión no escribe texto legible).
  3. Prompt generado por el Agente Guionista a partir del `market_mood` (p. ej. "calm blue abstract waves" vs "stormy red abstract"), siempre en inglés, con semilla fija derivada de la fecha → reproducible.
  4. Proveedor `mock` que devuelve una imagen sólida para tests.
- **Riesgos:**
  - **Nunca** generar con difusión gráficos de precios ni logos/caras reales (alucinaciones numéricas, marcas registradas, deepfakes). Los gráficos salen de `media/charts.py`.
  - Carga de modelo lenta y pesada: cargar una sola vez (singleton/caché) y no en cada petición de Streamlit.
  - Sin GPU en la demo → usar API o la plantilla sin IA; mostrar en la UI qué proveedor se usó.
  - Licencia comercial a mencionar en el pitch/viabilidad.

## Glosario rápido

- **VAE:** autoencoder probabilístico; en SD comprime a/desde el latente.
- **GAN:** generador vs discriminador.
- **Forward / reverse diffusion:** añadir ruido (fijo) / quitar ruido (aprendido).
- **U-Net:** red encoder-decoder con conexiones de salto que predice el ruido.
- **Latent diffusion:** difusión en espacio comprimido.
- **Cross-attention:** mecanismo por el que la imagen "atiende" a los tokens de texto.
- **CFG / `guidance_scale`:** fuerza con que se sigue el prompt.
- **Negative prompt:** lo que no se desea; requiere CFG > 1.
- **`strength`:** en img2img, cuánto se aleja del original.
- **ADD (Adversarial Diffusion Distillation):** destilación que permite 1-4 pasos (SDXL-Turbo).
- **DreamBooth:** personalización con pocas imágenes y un token identificador.
- **Inpainting / superresolución / pix2pix:** variantes imagen-a-imagen.
