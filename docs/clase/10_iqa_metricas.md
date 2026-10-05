# 10 · Calidad de imagen (IQA) y métricas para evaluar nuestras salidas

**Fuentes:** notebook `nb_11_IQA` (RMSE, PSNR, SSIM, LPIPS, TPIPS); slides ~89-99 (¿qué tan "humanos" son CLIP y los modelos contrastivos? sesgo textura/forma, alineamiento con humanos), ~144-149 (benchmarks y su saturación/contaminación), ~157-179 (alucinaciones, color, contraste en MLLM). La transcripción del 2-oct no cubre el notebook 11.

> **TL;DR**
> - **IQA (Image Quality Assessment)** mide cuánto se parece una imagen distorsionada a una de referencia *como lo percibiría una persona*.
> - Las métricas clásicas (**RMSE, PSNR, SSIM**) son baratas pero a menudo **no coinciden con la percepción humana**; las basadas en redes (**LPIPS**, **TPIPS**) se alinean mejor.
> - CLIP también sirve como métrica: **CLIPScore** (imagen ↔ prompt) y **CLIP-IQA** (calidad sin referencia).
> - Para el MVP: evaluación ligera y automatizable de **portadas, gráficos, audio y guion** (sección final), que además da material para el README/pitch.

---

## 1. Planteamiento del notebook 11

- Una **imagen de referencia** y **dos versiones distorsionadas** (descargadas de la web del grupo MMSP de la Universidad de Konstanz, autores de KonIQ). Pregunta inicial: ¿cuál se parece más a la original *a simple vista*?
- Luego se compara lo que dicen las métricas con esa intuición. Mensaje implícito: **las métricas píxel a píxel y el ojo humano no siempre coinciden**.

## 2. Métricas clásicas (con referencia, *full-reference*)

| Métrica | Qué mide | Escala | Limitación |
|---|---|---|---|
| **RMSE** | Error cuadrático medio píxel a píxel (imágenes en [0,1]) | 0 = idénticas, ↑ peor | Un desplazamiento de 1 px o un cambio de brillo global la dispara aunque no se note |
| **PSNR** | 10·log10(MAX²/MSE), en dB | ↑ mejor | Mismo problema que MSE |
| **SSIM** | Similitud de luminancia, contraste y estructura (medias, varianzas, covarianza locales) | [−1, 1], 1 = idénticas | Mejor que PSNR, pero sigue siendo "hecha a mano" |

En el notebook SSIM se calcula con `tf.image.ssim(..., max_val=1.0)` (TensorFlow); alternativa sin TF: `skimage.metrics.structural_similarity`.

## 3. Métricas perceptuales basadas en redes

### LPIPS (*Learned Perceptual Image Patch Similarity*)
- Compara **activaciones internas** de una red preentrenada (AlexNet `net='alex'` o VGG `net='vgg'`) entre las dos imágenes, con pesos calibrados con juicios humanos.
- **Distancia**: 0 = idénticas, mayor = más diferentes.
- Entrada: tensor **NCHW** en **[−1, 1]** (`x/127.5 − 1`). Inferencia en `torch.inference_mode()`.
- `alex` es la recomendada como métrica (rápida); `vgg` se usa más como *loss* de entrenamiento.

### TPIPS
- Paquete `tpips`; `tpips.load_model("embedding", device="cpu")` y métodos `model.similarity(ref, dist, factor="lighting")` / `model.distance(...)` sobre imágenes PIL.
- Es una métrica perceptual de nueva generación que permite medir la similitud **respecto a un factor concreto** (en el notebook, la **iluminación**), es decir, preguntar "¿se parecen en cuanto a X?" en vez de una única distancia global. Por debajo carga un VLM de 8B (`Qwen3-VL-Embedding-8B`): el notebook lo fuerza a CPU, donde funciona pero es muy lento.
- Pequeño error en el notebook: el último `print` muestra `similarity_ref_2` donde debería ir `distance_ref_2`.

### CLIP como métrica perceptual
- **CLIPScore**: similitud coseno entre el embedding de la imagen y el del texto → mide **si la imagen corresponde al prompt** (sin referencia). Disponible en `torchmetrics.multimodal.CLIPScore`.
- **CLIP-IQA**: calidad **sin referencia** comparando la imagen con pares de prompts opuestos ("good photo" / "bad photo", "sharp" / "blurry"...). `torchmetrics.multimodal.CLIPImageQualityAssessment`.
- Cautela de las slides: CLIP y los VLM tienen **sesgo hacia la textura**, problemas para **contar**, nombrar **colores** y percibir **contraste**; su alineamiento con humanos varía según el nivel de abstracción. Úsalos como señal, no como verdad.

## 4. Lecciones de evaluación de las slides

- Un **benchmark** es una medida bajo un protocolo, no una propiedad del modelo; cuidado con **contaminación** y **saturación**.
- Las **alucinaciones** de los MLLM se detectan mejor con preguntas de control (ilusiones visuales, preguntas con respuesta "no"); los MLLM tienden a contestar **"sí"**.
- Evaluación automática vs humana: combinar ambas. Para comparar modelos rápidamente: Arena.ai y Artificial Analysis (también para coste/latencia).

## Receta de código (del notebook)

```python
import numpy as np, torch, lpips, tpips
from PIL import Image

ref = Image.open("ref.png").convert("RGB"); dist = Image.open("dist.png").convert("RGB")
a, b = np.asarray(ref) / 255.0, np.asarray(dist) / 255.0

rmse = np.sqrt(np.mean((a - b) ** 2))
psnr = 10 * np.log10(1.0 / max(np.mean((a - b) ** 2), 1e-10))

to_t = lambda im: torch.from_numpy(np.asarray(im).transpose(2, 0, 1)[None].astype(np.float32) / 127.5 - 1)
lp = lpips.LPIPS(net="alex")
with torch.inference_mode():
    d_lpips = lp(to_t(ref), to_t(dist)).item()          # 0 = idénticas

tp = tpips.load_model("embedding", device="cpu")
with torch.inference_mode():
    s_light = tp.similarity(ref, dist, factor="lighting").item()
print(rmse, psnr, d_lpips, s_light)
```

## Requisitos prácticos

- RMSE/PSNR/SSIM y LPIPS (AlexNet) corren **en CPU** en segundos, con descargas de pocos MB (estimación, no viene de clase). **TPIPS no es ligero**: descarga y carga un modelo de 8B; en CPU es muy lento y en GPU pide bastante VRAM → no meterlo en el MVP.
- CLIPScore/CLIP-IQA: CPU suficiente (ViT-B ~600 MB; estimación, no viene de clase).
- Whisper (para WER del audio): ver `07_audio_whisper_clap_tts.md`.
- No hace falta API; un juez LLM (Claude Haiku) costaría céntimos por briefing (estimación, no viene de clase).

## Aplicación a nuestro MVP: cómo evaluar nuestras salidas

Propuesta de un script nuevo `scripts/eval_outputs.py` (todavía no existe; o tests marcados como lentos) que lea un briefing de `data/outputs/<fecha>/` y genere una tabla de métricas para el README/pitch:

| Salida | Módulo | Métrica propuesta | Umbral orientativo |
|---|---|---|---|
| **Portada IA** | `media/cover.py`, `providers/image/sdxl_turbo.py` | **CLIPScore** imagen↔prompt; **CLIP-IQA** (nitidez/calidad); LPIPS entre portadas de días distintos para comprobar **variedad** | CLIPScore por encima del de prompts aleatorios; LPIPS entre días no ≈ 0 |
| **Gráficos** | `media/charts.py` | **Round-trip VLM** estilo ChartQA: preguntar al proveedor de visión el último precio/tendencia del PNG generado y comparar con `PriceSnapshot` (tolerancia 1-5 %). SSIM/LPIPS contra un PNG "golden" en tests de regresión visual | ≥ 90 % de aciertos; SSIM ≈ 1 en regresión |
| **Lectura de gráfico subido** | `ingest/chart_reader.py` | Exact match / tolerancia numérica en 20-30 ejemplos de ChartQA test | Reportar % |
| **Audio podcast** | `media/podcast.py`, `providers/tts/*` | **WER** con `jiwer` entre el guion y la transcripción Whisper del audio (inteligibilidad); duración real vs `est_duration_s`; silencios/clipping; opcional CLAP "clear speech" vs "noise" | WER < 10-15 % |
| **STT de preguntas** | `ingest/voice.py` | WER sobre 5-10 grabaciones propias | WER < 15 % |
| **Guion / análisis** | `agents/analyst.py`, `agents/scriptwriter.py` | **Grounding**: toda cifra y ticker del guion aparece en `MarketContext` (check determinista con regex); **LLM-as-judge** con rúbrica (claridad, fidelidad, tono, balance A/B, sin recomendaciones personalizadas); disclaimer presente | 0 cifras no trazables; disclaimer 100 % |
| **Vídeo** | `media/video.py` | Duración = audio ± 0,5 s; subtítulos sincronizados (muestreo de frames) | — |

- **Decisión recomendada:** implementar primero los checks **deterministas y baratos** (grounding de cifras, disclaimer, duración, WER del audio). CLIPScore/LPIPS solo si se activa la portada IA. Registrar resultados junto a `StepMetric` para mostrarlos en la página de histórico.
- **Riesgos:** sobreinterpretar métricas de CLIP (sesgos); el juez LLM del mismo proveedor que genera el guion es indulgente → usar otro modelo o una rúbrica estricta; no meter pesos grandes (CLIP, Whisper) en la imagen Docker si no se usan (dependencias opcionales).

## Glosario rápido

- **IQA:** evaluación de la calidad de imagen.
- **Full-reference / no-reference:** con o sin imagen original para comparar.
- **RMSE / PSNR / SSIM:** métricas clásicas píxel/estructura.
- **LPIPS:** distancia perceptual con features de redes profundas.
- **TPIPS:** métrica perceptual que permite medir similitud según un factor (p. ej. iluminación).
- **CLIPScore:** alineamiento imagen-texto con CLIP.
- **CLIP-IQA:** calidad sin referencia con prompts antónimos.
- **WER:** tasa de error de palabras en transcripción.
- **Grounding:** que cada afirmación esté respaldada por los datos de entrada.
- **LLM-as-judge:** usar un LLM con una rúbrica para puntuar salidas.
- **Regresión visual:** comparar una imagen generada con una de referencia aprobada.
