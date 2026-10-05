# 03 · Modelos contrastivos: CLIP, SigLIP y compañía

**Fuentes:** slides 40–99 (modelos texto-imagen, CLIP, OpenCLIP, SigLIP, MaMMUT, variantes, receta de Meta Perception Encoder, limitaciones); transcripción 2-oct-2026, min 01:09:50–01:37:30 y 02:04:10–02:32:30 (teoría), 02:42:30–03:05:30 (demo del notebook); notebook `2. Playing with CLIP`.

> **TL;DR**
> - **CLIP** (OpenAI, enero 2021) entrena un encoder de imagen y uno de texto para que los pares correctos queden **cerca** en un espacio común (pérdida contrastiva **InfoNCE** con softmax por filas y columnas). Resultado: **clasificación zero-shot** escribiendo las clases como texto y una **robustez** muy superior a los modelos entrenados solo con imágenes.
> - **SigLIP** (Google) cambia la softmax por una **sigmoide por par**: cada par imagen-texto es una decisión binaria independiente → depende menos del tamaño de batch y **no obliga a elegir** una opción.
> - **OpenCLIP** (LAION) lo hizo todo abierto y estudió **leyes de escala**: más modelo, más datos y más entrenamiento = mejor, con rendimientos predecibles.
> - Receta práctica de **Meta Perception Encoder**: resolución progresiva, batch mayor, optimizador LAMB, RoPE 2D, *attention pooling*, *data augmentation* y enmascarado de parches.
> - Limitaciones: **contar**, sesgo de **textura** frente a forma, alineamiento imperfecto con la percepción humana, y la "trampa de la softmax" (siempre reparte el 100 %).

---

## 1. Antes y después de CLIP

- Antes de CLIP ("AC"): trabajos con **CNN para la imagen + RNN para generar texto** (Ngiam 2011; Karpathy y Fei-Fei 2015; *Show and Tell*, Vinyals 2015).
- El cambio llega el **5 de enero de 2021** con **CLIP** (*Contrastive Language-Image Pretraining*). Objetivo: **entrenar un modelo de imagen usando texto** como supervisión. OpenAI construyó un dataset propio de **~400M pares** que **no publicó** (ni el código de entrenamiento).

## 2. Cómo funciona CLIP

### 2.1 Arquitectura

```
imagen ──▶ [Image encoder (ViT, o CNN)] ──▶ proyección lineal ──▶ embedding (p. ej. 512) ─┐
                                                                                         ├─▶ similitud coseno
texto  ──▶ [Text encoder (Transformer)] ──▶ proyección lineal ──▶ embedding (p. ej. 512) ─┘
```

- Imagen: se trocea en **parches**, proyección lineal, se añade el **token de clasificación [CLS]** y pasa por un ViT; el estado final del [CLS] es la representación de la imagen. Texto: igual con un transformer de texto.
- En `clip-vit-base-patch32`: encoder de texto ~63M parámetros, de visión ~87M, total ~151M. Imagen 224×224 con parches de 32 → 7×7 = 49 parches + [CLS] = **50 tokens** de 768 dimensiones, proyectados a **512**.

### 2.2 Pérdida contrastiva (InfoNCE)

En cada batch de $N$ pares se calcula la matriz $N\times N$ de similitudes. Se quiere la **diagonal alta** (pares correctos) y el resto baja ($N^2-N$ negativos).

Con embeddings normalizados $u_i$ (imagen) y $v_j$ (texto) y temperatura aprendida $\tau$:

$$
s_{ij} = \frac{u_i^\top v_j}{\tau}
$$

$$
\mathcal{L}_{\text{img}\to\text{txt}} = -\frac{1}{N}\sum_{i=1}^{N}\log\frac{e^{s_{ii}}}{\sum_{j=1}^{N} e^{s_{ij}}}, \qquad
\mathcal{L}_{\text{txt}\to\text{img}} = -\frac{1}{N}\sum_{j=1}^{N}\log\frac{e^{s_{jj}}}{\sum_{i=1}^{N} e^{s_{ij}}}
$$

$$
\mathcal{L}_{\text{CLIP}} = \tfrac{1}{2}\left(\mathcal{L}_{\text{img}\to\text{txt}} + \mathcal{L}_{\text{txt}\to\text{img}}\right)
$$

Es decir: **softmax por filas** ("esta imagen, ¿con qué texto va?") y **por columnas** ("este texto, ¿con qué imagen va?"), entropía cruzada contra la diagonal y media de ambas.

En la práctica (notebook): `logits = exp(logit_scale) · cos(imagen, texto)`, con `exp(logit_scale) ≈ 100`. Los cosenos crudos de CLIP son pequeños (≈0.1–0.35) y difíciles de interpretar por sí solos.

**Intuición del profesor:** el modelo **no sabe** qué es un gato; aprende los **pares que tú le das**. Si le pasas la foto de un gato con el texto "un perro", aprenderá eso. La "etiqueta" está implícita al exigir que la matriz sea diagonal.

### 2.3 Usos tras el entrenamiento

- **Retrieval texto→imagen**: muchas imágenes y un texto → la de mayor similitud (ejemplo de clase: buscar prendas en un catálogo de una tienda de ropa con una descripción).
- **Retrieval imagen→texto**: una imagen y muchos textos.
- **Clasificación zero-shot**: escribir cada clase como frase ("a photo of a {clase}") y quedarse con la de mayor probabilidad. Se suele usar **varias plantillas por clase** ("una mala foto de…", "una foto de muchos…") porque no sabemos cómo eran los captions originales.
- **Similitud imagen↔imagen y texto↔texto**: todos los embeddings viven en el mismo espacio.
- **Métrica perceptual**: distancia entre embeddings visuales de CLIP como medida de parecido entre imágenes; en el ejemplo del notebook el RMSE píxel a píxel elegía la imagen "equivocada" y CLIP coincidía con el juicio humano.
- **Encoder visual de los MLLM** (ver `04_...`): es su uso más importante hoy.

### 2.4 ¿Por qué es tan bueno? Robustez

- En ImageNet "normal", CLIP zero-shot iguala a una ResNet supervisada (~76 %). La diferencia aparece en **distribuciones desplazadas** (dibujos, bocetos, imágenes adversarias…): la CNN cae en picado y CLIP mantiene mucho mejor el rendimiento.
- **Intuición del profesor:** la ganancia viene del **texto**, que describe la imagen con más riqueza que una etiqueta de clase. Matiz crítico: la comparación justa habría sido contra un *transformer* supervisado, no una CNN.

## 3. OpenCLIP y leyes de escala

- **OpenCLIP** (LAION / mlfoundations): reimplementación **abierta** con datos, código y pesos; entrenamiento lanzable con un CSV de pares (soporta mezclar varias fuentes) y probado hasta ~1024 GPU. El escalado multi-GPU **no es lineal** (comunicación entre nodos).
- Dos trabajos clave:
  1. *Reproducible scaling laws for contrastive language-image learning* (CVPR 2023): muchos modelos con distintos tamaños de modelo, datos y "muestras vistas" → **cuanto más grande todo, mejor**, siguiendo curvas predecibles. Más de un millón de horas de GPU.
  2. *Scaling laws for robust comparison of open foundation language-vision models and datasets* (NeurIPS 2025): compara **distintos datasets del mismo tamaño** (qué datos tienen más calidad) y CLIP frente a MaMMUT.
- Las **leyes de escala** sirven para predecir el comportamiento de modelos más grandes antes de pagarlos (según las slides, entrenar Llama 3 costó más de 720 M$).
- "Muestras vistas" ≠ tamaño del dataset: un modelo entrenado con 2B pares puede haber visto ~15 épocas.
- **Cuidado al mezclar datasets**: puede haber duplicados entre fuentes; con miles de millones de ejemplos unos pocos repetidos no importan, pero la deduplicación es responsabilidad tuya.

## 4. SigLIP: sigmoide en lugar de softmax

SigLIP (*Sigmoid Loss for Language-Image Pre-training*, Google) aplica una **sigmoide a cada celda** de la matriz de similitudes: cada par es una clasificación binaria "match / no match".

$$
\mathcal{L}_{\text{SigLIP}} = -\frac{1}{N}\sum_{i=1}^{N}\sum_{j=1}^{N}\log \sigma\!\big(z_{ij}\,(t\,u_i^\top v_j + b)\big), \quad z_{ij}=\begin{cases}+1 & i=j\\-1 & i\neq j\end{cases}
$$

| | **CLIP** | **SigLIP** |
|---|---|---|
| Idea | alinear imagen y texto (contrastivo) | alinear imagen y texto (contrastivo/binario) |
| Función | softmax por filas/columnas | sigmoide por par |
| Pregunta que aprende | "¿cuál de estos textos es el correcto?" | "¿este par encaja?" |
| Competición entre candidatos | alta (todos contra todos) | baja (pares independientes) |
| Probabilidades | suman 1 → **obliga a elegir** | independientes → pueden ser todas bajas o varias altas |
| Dependencia del tamaño de batch | alta (batches típicos 32K–86K) | menor; mejor con batch pequeño |
| Escalabilidad | buena | muy buena (menos comunicación entre dispositivos) |

**Intuición del profesor:** CLIP es "aquí tienes una foto, ¿cuál de estas 100 frases la describe?"; SigLIP son "muchas decisiones independientes de sí/no". Por eso CLIP necesita muchos negativos (batch enorme) y SigLIP no.

Demo del notebook: con `google/siglip2-base-patch16-224`, "2 gatos" ≈ 10 % y "2 perros" ≈ 0 %, **sin sumar 100 %**. Ojo práctico: SigLIP requiere `padding="max_length"` en el processor y `torch.sigmoid` sobre los logits.

## 5. MaMMUT: contrastivo + captioning

**MaMMUT** = CLIP + un **decoder generativo de texto** que, a partir de las features de la imagen, genera el caption. La pérdida es la suma de la contrastiva y la generativa. Permite, además del *matching*, **generar descripciones**, y se estudió si así se generaliza mejor (aparece en las curvas de escala de OpenCLIP).

## 6. Variantes de CLIP

| Variante | Qué cambia |
|---|---|
| **AltCLIP** | sustituye el encoder de texto por uno **multilingüe** → CLIP en muchos idiomas sin tocar la parte visual |
| **ALIGN** (*Scaling up… with noisy text supervision*) | escala con texto ruidoso; algo de ruido (cambiar palabras) actúa como **regularizador** |
| **Chinese CLIP, clip-italian…** | CLIP por idioma: basta tener captions en ese idioma |
| **BioCLIP** y otros de dominio | entrenar con pares del dominio deseado (biología, satélite…) si hay datos suficientes |
| **EVA-CLIP** | CLIP más grande y con más datos, mejores resultados |

En Hugging Face hay miles de checkpoints "clip"; el nombre codifica tamaño (`base`/`large`), parche (`patch32/16/14`) y resolución (224 por defecto, 336…). Parche más pequeño = más tokens = más detalle pero atención más cara (cuadrática).

## 7. Receta de entrenamiento: Meta Perception Encoder (paso a paso)

Meta detalla en un paper de ~40 páginas cómo entrenó su encoder contrastivo (imagen y también vídeo). Partiendo de un baseline, cada paso se evaluó en ImageNet y en conjuntos de **robustez**:

| Paso | Cambio | Por qué |
|---|---|---|
| 1. Baseline | 224 px, batch 32K, AdamW, 12B muestras vistas sobre MetaCLIP-2.3B | punto de partida |
| 2. Resolución progresiva | 98 → 154 → 224 px, 4B muestras en cada fase | imágenes pequeñas = ~4× menos píxeles al dividir el lado entre 2 → entrenamiento mucho más barato; el modelo aprende primero lo grueso y luego los detalles |
| 3. Batch 32K → 64K | más negativos (CLIP rinde mejor con batches grandes) | ojo: también aumenta las muestras vistas, comparación no del todo limpia |
| 4. AdamW → **LAMB** | optimizador pensado para redes enormes y batches grandes | el optimizador óptimo **cambia** si cambias otras cosas |
| 5. Resolución + reparto de cómputo | 98 px (10B), 154 (8B), 224 (4B), 336 (2B) | muchas muestras baratas a baja resolución y pocas caras a alta: "¿cómo reparto el presupuesto entre resolución y nº de imágenes?" es la pregunta clave del *scaling* |
| 6. **RoPE 2D** | posición relativa en **todas** las capas de atención, no solo al inicio | mejor información espacial y extrapolación a otras resoluciones |
| 7. **Attention pooling** | en lugar de quedarse solo con [CLS], un bloque de atención consulta todos los tokens de parches para formar el embedding | aprovecha la información espacial |
| 8. **Data augmentation** | rotaciones leves, volteo horizontal… con el **texto fijo** | más diversidad sin cambiar el significado |
| 9. **Mask regularization** | tapar aleatoriamente algunos parches | evita depender siempre de los parches centrales → más robustez |

Resultado: muy buenas curvas de escala; algunas siguen subiendo, es decir, con más cómputo seguirían mejorando. Para vídeo: se **promedian frames** y se tratan como imagen. Un mensaje del paper: los **mejores embeddings no siempre están en la última capa** (depende de la tarea).

## 8. Limitaciones de CLIP y los contrastivos

1. **Contar**: confunde "3 jirafas" con otras cantidades; probablemente porque los captions casi no incluyen números. *Teaching CLIP to Count to Ten* lo mejora con un fine-tuning con referencias numéricas explícitas.
2. **Sesgo textura vs forma**: con imágenes "gato con textura de piel de elefante", los humanos clasificamos por **forma** y las CNN de ImageNet casi siempre por **textura**. Los transformers y CLIP mejoran pero siguen lejos del humano. Seguir esa evolución a lo largo del entrenamiento (checkpoints de OpenCLIP) muestra que CLIP empieza muy texturizado y va derivando hacia la forma.
3. **Alineamiento con la percepción humana**: en tareas "¿cuál de estas dos variaciones se parece más a la referencia?" CLIP acierta ~80 % en la capa final, pero el alineamiento varía de forma no monótona por capas (sube, baja y vuelve a subir). En tareas de más alto nivel ("¿cuál de estas tres imágenes sobra?") va **peor** de lo esperado.
4. **Color**: errores llamativos al asociar colores a objetos (el profesor recordó un trabajo de su grupo en el que CLIP "cree" que los huevos son azules).
5. **Trampa de la softmax**: si ninguna clase encaja, CLIP reparte igualmente el 100 % (en el notebook, un tanque salía 66 % "gato").
6. **Datos**: hereda los problemas de los datasets web (ruido, sesgos, copyright).

Aun así, capta bien los **detalles descriptivos**: con "dos gatos tumbados en un sofá rosa" la probabilidad sube a medida que el texto es más específico y correcto.

## 9. Uso práctico (resumen del notebook)

```python
from transformers import AutoProcessor, CLIPModel
model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").eval()
processor = AutoProcessor.from_pretrained("openai/clip-vit-base-patch32")
inputs = processor(text=["a photo of a candlestick chart", "a photo of a table", "something else"],
                   images=img, return_tensors="pt", padding=True)
probs = model(**inputs).logits_per_image.softmax(dim=1)   # dim=1: 1 imagen vs N textos
```

- `logits_per_image` (imágenes × textos) y `logits_per_text` (su traspuesta). `softmax(dim=1)` reparte entre textos; `dim=0` entre imágenes. Truco: si dudas, prueba con 1 imagen y 3 textos y mira cuántos valores salen.
- `model.text_model` y `model.vision_model` se pueden usar por separado (solo texto o solo imagen).
- `output_hidden_states=True` devuelve los estados de todas las capas (13 en ViT-B: embeddings + 12 capas) para usar features intermedias.

---

## Aplicación a nuestro MVP

- **Enrutador de imágenes subidas** (`providers/image/clip_classifier.py`, interfaz `ImageClassifier.classify(image, labels) -> dict[str, float]`): antes de llamar al VLM caro, clasificar la imagen en "gráfico de velas / gráfico de líneas / tabla / documento / otra cosa" para:
  - elegir el prompt adecuado en `ingest/chart_reader.py`;
  - rechazar imágenes irrelevantes (fotos personales, memes) y ahorrar coste.
- **Preferir SigLIP** (`google/siglip2-base-patch16-224`) a CLIP para este enrutado (ojo: `config.py` trae por defecto `BRIEFER_CLIP_MODEL=openai/clip-vit-base-patch32` y el clasificador está desactivado, `BRIEFER_IMAGE_CLASSIFIER_PROVIDER=none`; cambiar el modelo implica usar `padding="max_length"` + sigmoide): sus probabilidades **no suman 1**, así que podemos fijar un **umbral** (p. ej. si ninguna etiqueta supera 0.3 → "otra cosa"). Si se usa CLIP, **incluir siempre una etiqueta "otra cosa"**.
- **Prompts como frases**: etiquetas tipo `"a screenshot of a stock candlestick chart"` funcionan mejor que `"candlestick"`; usar varias plantillas por clase y promediar. Las etiquetas en **inglés** suelen rendir mejor con los CLIP originales (AltCLIP/SigLIP multilingüe si se quiere español).
- **No usar CLIP para leer cifras ni contar** (velas, barras, número de picos): es justo donde falla. Para eso, VLM (`claude_vision` / `qwen_vl_local`) y, si es posible, datos estructurados de `yfinance`.
- **Coste/latencia**: CLIP/SigLIP base (~150–200M parámetros) corre en CPU en <1 s por imagen (estimación, no viene de clase); cargar el modelo una sola vez (caché a nivel de proveedor en `registry.py`) y con `.eval()` + `torch.no_grad()`.
- **Mock**: `providers/mock.py` debe devolver un `dict` de probabilidades fijo para que tests y UI no dependan de descargar pesos.
- **Ideas futuras** (roadmap): búsqueda semántica en el histórico (`app/pages/4_Historico.py`) con embeddings texto↔imagen de los gráficos generados; deduplicar noticias con embeddings de texto.

## Glosario rápido

- **CLIP**: modelo contrastivo imagen-texto de OpenAI (2021) con dos encoders y espacio común.
- **InfoNCE**: pérdida contrastiva basada en softmax sobre positivos y negativos del batch.
- **Zero-shot**: clasificar sin entrenamiento adicional, describiendo las clases en texto.
- **SigLIP**: variante con pérdida sigmoide por par; probabilidades independientes.
- **logit_scale / temperatura**: factor aprendido (≈100 en CLIP) que escala los cosenos antes de la softmax.
- **OpenCLIP**: reimplementación abierta de CLIP (LAION) con datos, código y checkpoints.
- **Leyes de escala**: relaciones predecibles entre tamaño de modelo, datos, cómputo y rendimiento.
- **Attention pooling**: agregación del embedding final mediante atención sobre todos los tokens.
- **RoPE 2D**: codificación posicional rotatoria relativa en 2D aplicada en cada capa de atención.
- **Sesgo de textura**: tendencia de los modelos a clasificar por textura en lugar de por forma.
