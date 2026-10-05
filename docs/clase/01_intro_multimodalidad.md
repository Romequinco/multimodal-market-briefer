# 01 · Introducción a la multimodalidad

**Fuentes:** slides 1–14 y 250–267 (índice, introducción, "Otras modalidades"); transcripción 2-oct-2026, min 00:08–00:15:40 (introducción) y 03:05–03:18 (modelos con modalidad "ancla" y fusión); notebook `1. Check tasks with Transformers` (visión general de tareas). Las slides de "Otras modalidades" (series temporales, any-to-any) no tienen transcripción (se impartieron el segundo día).

> **TL;DR**
> - Un modelo **multimodal** procesa, entiende y **combina** varios tipos de dato (texto, imagen, audio, vídeo, series temporales, LiDAR, sensores IoT…) dentro de una misma arquitectura.
> - Más modalidades = más "puntos de vista" sobre el mismo problema, pero **no siempre mejor**: una modalidad puede dominar a las demás o añadir ruido.
> - Hay dos grandes formas de juntar modalidades: llevarlas a un **espacio común** (contrastivos tipo CLIP) o llevarlas a una **modalidad ancla** (normalmente texto → LLM multimodal).
> - Entrenar un multimodal desde cero es inviable para nosotros: lo realista es **usar modelos preentrenados**, como mucho con un ajuste fino ligero.
> - Aunque un modelo no sea multimodal, **podemos encadenar modelos especializados** (STT → LLM → TTS…) y obtener un sistema multimodal: es justo lo que hace nuestro MVP.

---

## 1. ¿Por qué multimodalidad?

- Vivimos en un mundo multimodal: percibimos con varios sentidos y cada uno aporta información distinta. Memes, artículos con imágenes, videollamadas, notas de voz, redes sociales… casi todo el contenido actual mezcla modalidades.
- Si un modelo solo ve una modalidad, se limita a la información que esa modalidad contiene. Añadir modalidades le da **una representación del mundo más completa** y, en principio, mejores capacidades para la tarea.
- **Intuición del profesor:** citó la idea (de estudios de comunicación de los años 70) de que en una conversación oral gran parte de la información está en el tono, la voz y el lenguaje corporal, no solo en las palabras. Ejemplo de que "todas las modalidades importan".

## 2. Definición

**Modelo multimodal**: aquel capaz de procesar, comprender y combinar simultáneamente distintos tipos de datos **en una misma arquitectura**. La clave no es aceptar varias entradas por separado, sino **fusionarlas** dentro del modelo.

Distinción útil:

| Tipo | Entrada → salida | Ejemplos |
|---|---|---|
| Unimodal de texto | texto → texto | LLM clásicos |
| Unimodal de imagen | imagen → imagen | superresolución, inpainting, edición |
| Multimodal texto→imagen | texto → imagen | Stable Diffusion, DALL·E, Midjourney |
| Multimodal imagen→texto | imagen (+texto) → texto | captioning, VQA, chat con imágenes (GPT, Gemini, Claude…) |
| Audio | audio ↔ texto | transcripción (Whisper), TTS, generación musical |
| Any-to-any | cualquier → cualquiera | NExT-GPT, Unified-IO 2, AnyGPT |

**Intuición del profesor:** muchos LLM "de chat" actuales ya son multimodales sin que lo pensemos: en cuanto subes una foto y preguntas sobre ella, estás usando un modelo multimodal.

## 3. Modalidades

- **Básicas y más usadas:** texto, imagen, audio (y vídeo como secuencia de imágenes + audio).
- **Muchas más:** cualquier fuente de datos puede tratarse como una modalidad nueva:
  - **LiDAR** (coches autónomos: distancia a objetos), mapas de profundidad, nubes de puntos 3D, mapas térmicos.
  - **IoT**: cualquier objeto que genera datos es, en la práctica, una modalidad.
  - Dominios específicos: medicina (BioGPT…), química (ChemLLM, MolCA…), geografía (GeoGPT).
- **Series temporales** (slide 251): modalidad clave en datos económicos. Los modelos texto+serie se entrenan y alinean como los VLM (preentrenamiento + instruction tuning) y sirven tanto para **análisis** como para **predicción**. Ejemplos: **Time-LLM**, **OneFitsAll**.
- **Audio** (slides 245–249): Whisper (audio→texto, trabaja sobre el **espectrograma Mel**, una "imagen" del audio), **CLAP** (el "CLIP del audio"), generación musical autoregresiva y modelos de música en casi tiempo real.
- **Vídeo**: los modelos de vídeo derivan de los de imagen (operaciones 2D → 3D, atención temporal, generar pocos frames e interpolar). VQA sobre vídeo: PerceptionLM, SmolVLM2.

## 4. Problemas de la multimodalidad

1. **Dominancia de una modalidad**: si hay muchos más datos de una, o es más informativa para la tarea, el modelo puede **ignorar las demás**.
2. **Más modalidades no siempre es mejor**: igual que con las *features* en aprendizaje no supervisado, llega un punto en que añadir modalidades solo mete **ruido** y empeora el rendimiento.
3. **Relaciones complejas** entre modalidades, difíciles de aprender.
4. **Coste**: los modelos son enormes y requieren muchísimos datos; entrenarlos desde cero es "prácticamente imposible" fuera de grandes laboratorios. Para nosotros: **usar modelos ya entrenados** o hacer *fine-tuning* ligero.

## 5. Cómo se fusionan las modalidades

### 5.1 Dos familias de modelos texto-imagen

| Familia | Idea | Ejemplo | Para qué |
|---|---|---|---|
| **Espacio común (contrastivos)** | Texto e imagen se proyectan a un espacio interno **nuevo** donde los pares correctos quedan cerca | CLIP, SigLIP | búsqueda, clasificación zero-shot, encoders de imagen |
| **Modalidad ancla** | Una modalidad (casi siempre **texto**, porque es como nos comunicamos con los modelos) actúa de ancla y el resto se traduce a ella | LLaVA, Qwen-VL, PerceptionLM (MLLM/VLM) | VQA, chat con imágenes, documentos |

Variante: **ImageBind** usa la **imagen** como ancla para unir 6 modalidades (texto, audio, profundidad, térmico, IMU…); al alinear audio↔imagen y texto↔imagen, obtiene audio↔texto "de rebote".

### 5.2 Dónde se produce la fusión (dentro de un MLLM)

| Estrategia | Encoders | Conectores | Comentario del profesor |
|---|---|---|---|
| **Early fusion** | uno común para todas las modalidades (p. ej. tipo CLIP) | uno | más sencillo de entrenar; menos parámetros |
| **Intermediate fusion** | uno por modalidad | uno compartido que aprende a traducir todos | punto intermedio |
| **Late fusion** | uno por modalidad | uno por modalidad | más parámetros y más piezas |

No hay una respuesta "buena" universal: distintos trabajos llegan a conclusiones distintas. Un estudio de *scaling laws* para modelos nativamente multimodales (slide 148) encontró que **early fusion** rinde mejor con pocos parámetros, es más eficiente de entrenar y más fácil de desplegar, y que añadir **MoE** ayuda a aprender pesos específicos por modalidad.

### 5.3 Multimodalidad "por composición"

Slide 252: aunque los modelos individuales no sean multimodales, **podemos juntar nosotros las modalidades** encadenando modelos: imagen→texto, texto→imagen, imagen→imagen (pix2pix, superresolución, inpainting), imagen→vídeo (Stable Video Diffusion, LivePortrait), texto→vídeo (Veo, Sora, Wan 2.1), detección/segmentación (YOLO/Ultralytics). Esto equivale al patrón **"LLM como director"** (ver `04_mllm_vlm_arquitectura_entrenamiento.md`).

## 6. Mapa del curso (para orientarse)

1. Introducción (este documento).
2. Texto-imagen: tareas y datasets → `02_tareas_y_datasets.md`.
3. Modelos contrastivos (CLIP, SigLIP…) → `03_contrastivos_clip_siglip.md`.
4. MLLM / VLM → `04_mllm_vlm_arquitectura_entrenamiento.md`.
5. Generación de imagen y vídeo, audio, otras modalidades, agentes, fine-tuning → resto de ficheros de `docs/clase/`.

---

## Aplicación a nuestro MVP

- **Nuestro producto es multimodal "por composición"**: no entrenamos nada; encadenamos modelos especializados (rúbrica: *encadenar modelos especializados > un monolito*):
  - Entradas: texto (noticias `ingest/news.py`), **imagen** (captura de gráfico `ingest/chart_reader.py`), **PDF** (`ingest/pdf_reader.py`, texto + visión para páginas con gráficos), **voz** (`ingest/voice.py` → `providers/stt/`), **serie temporal** de precios (`ingest/prices.py`).
  - Salidas: texto (análisis y guion), **audio a 2 voces** (`media/podcast.py`), gráficos PNG (`media/charts.py`), **vídeo** (`media/video.py`), portada opcional (`media/cover.py`).
- **Series temporales**: el profesor las destaca como modalidad clave en finanzas. En el MVP las tratamos de forma simple (precios → gráfico + cifras en el `MarketContext`). Modelos tipo Time-LLM quedan como línea futura del roadmap (no prometer predicción: además, MiFID II).
- **Riesgo de dominancia de modalidad**: si el analista recibe mucho texto de noticias y una sola captura, puede ignorar el gráfico. Mitigación: convertir cada entrada no textual en un `DocumentInsight` con resumen y `key_figures` explícitos, y pedir en el prompt del analista que cite cada insight.
- **Más modalidades ≠ mejor**: añadir vídeo o portada solo si aporta valor y no degrada latencia/coste (medir con `StepMetric`).
- Para el pitch/README: explicar el diagrama como "fusión tardía por composición", con el LLM como orquestador y el texto como modalidad ancla.

## Glosario rápido

- **Modalidad**: tipo de dato (texto, imagen, audio, vídeo, serie temporal, LiDAR…).
- **Modelo multimodal**: procesa y combina varias modalidades en una misma arquitectura.
- **Espacio común (embedding space)**: espacio vectorial donde representaciones de distintas modalidades son comparables.
- **Modalidad ancla**: modalidad a la que se traducen las demás (normalmente texto en los MLLM; imagen en ImageBind).
- **Early / intermediate / late fusion**: punto de la arquitectura donde se combinan las modalidades.
- **Any-to-any**: modelos que aceptan y generan cualquier modalidad (NExT-GPT, AnyGPT).
- **Espectrograma Mel**: representación tipo imagen de un audio (frecuencias en el tiempo) usada por Whisper.
- **Dominancia de modalidad**: el modelo se apoya en una sola modalidad e ignora las demás.
