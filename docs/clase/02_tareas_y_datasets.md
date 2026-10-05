# 02 · Tareas texto-imagen, datasets y evaluación

**Fuentes:** slides 15–39 (tareas, datasets de entrenamiento y evaluación, PerceptionLM) y 157–179 (alucinaciones y benchmarks diagnósticos); transcripción 2-oct-2026, min 00:15:50–01:09:50 (tareas, MSCOCO, LAION, img2dataset, MMMU, VQA, HLE, benchmark IKEA, arenas, ArtificialAnalysis, datos sintéticos) y 02:32–02:42 (demo de tareas); notebook `1. Check tasks with Transformers`.

> **TL;DR**
> - Cuatro familias de tareas texto-imagen: **emparejar/recuperar** (retrieval), **describir** (captioning), **responder sobre la imagen** (VQA/razonamiento) y **generar imagen desde texto**. Variantes importantes: *grounding* y **DocVQA** (OCR + comprensión de layout).
> - Los datasets han pasado de miles de pares **curados** (MSCOCO) a miles de millones extraídos de la **web** (LAION-5B, CommonPool hasta 12.8B). Escala ↑, calidad ↓: ruido, duplicados, enlaces muertos (~30 %), copyright, contenido generado por IA.
> - Un **benchmark** es una medición bajo un protocolo, no una propiedad del modelo. Cuidado con **contaminación**, **saturación** y con que cada empresa publique los que le favorecen.
> - Para elegir modelo en la práctica: arenas (votos humanos) y **ArtificialAnalysis** (calidad vs coste vs latencia).

---

## 1. Familias de tareas texto-imagen

| Familia | Entrada → salida | Ejemplo | Modelos típicos |
|---|---|---|---|
| **a) Matching / retrieval / alignment** | imagen + texto → puntuación de encaje | "¿qué foto encaja con *un perro en el césped*?" | CLIP, SigLIP |
| **b) Image captioning** | imagen → texto | "un perro corriendo por un parque" | BLIP, MLLM |
| **c) VQA / razonamiento multimodal** | imagen + pregunta → respuesta | "¿de qué color es el coche?" → "rojo" | LLaVA, Qwen-VL, GPT/Gemini/Claude |
| **d) Text-to-image** | texto → imagen | prompt → imagen nueva | Stable Diffusion, DALL·E |

Variantes y subtareas que aparecieron en clase:

- **Grounding / localización por texto**: dada una frase ("un perro en el césped cerca de…"), devolver las cajas de cada objeto mencionado.
- **Captioning condicionado vs no condicionado**: en el condicionado le das el arranque de la frase ("a photography of…") y el modelo completa; en el no condicionado decide libremente.
- **DocVQA (Document VQA)**: VQA especializada en documentos (facturas, nóminas, formularios, informes). Combina **OCR** (leer caracteres) con **comprensión del layout** (saber que una cifra es el valor de una etiqueta concreta). Ejemplo de clase: modelo **Donut** extrayendo el "líquido a percibir" de una nómina española; funciona incluso preguntando en castellano.

**Intuición del profesor (DocVQA):** si la imagen está borrosa o con poca calidad, lo más probable es que el modelo **se invente** la cifra; un buen modelo debería decir que no lo sabe. Recomendó probar a degradar la imagen para verlo.

## 2. Datasets de entrenamiento

### 2.1 Tres escalas

| Escala | Cómo se construyen | Tamaño | Ejemplos |
|---|---|---|---|
| **Curados** | selección y anotación manual | miles – pocos millones | **MSCOCO** (~328k imágenes, **5 captions por imagen** + detección/segmentación), **Conceptual Captions** (3M) |
| **Web** | extracción automática con filtros y heurísticas | cientos de millones – ~2B | **ALIGN** (1.8B pares) |
| **Web a gran escala** | extracción masiva apoyada en el texto *alt* e índices públicos, sin filtrado humano profundo | miles de millones | **LAION** (400M, 5B; referencia abierta), **CommonPool** (12.8M → 12.8B), **LAION Big Video** (vídeo: ~80M vídeos, ~10M horas) |

Hoy se entrena con los más grandes, y un modelo suele combinar **muchos** datasets a la vez (ejemplo: Meta **PerceptionLM** mezcla datasets imagen-texto, vídeo-texto y solo-texto).

**Intuición del profesor:**
- Lo valioso de MSCOCO es tener **varias descripciones por imagen**, algo poco común que enriquece mucho el entrenamiento.
- LAION nació haciendo datasets y luego modelos, todo abierto y replicable; publicar solo el dataset ya fue un trabajo aceptado en una conferencia top de ML.
- La **longitud de los captions** condiciona al modelo: si se entrena con textos cortos, describirá de forma escueta; con descripciones largas y detalladas, aprenderá a ser detallado. En LAION la mayoría de textos son cortos y la mayoría de imágenes pequeñas (solo ~5 % supera 1024 px).

### 2.2 Cómo se descargan: img2dataset

- Librería Python (de la comunidad LAION) que descarga estos datasets a partir de listas de **URL + caption**, con filtrado durante la descarga. Fácil, pero **no rápida**: MSCOCO baja en ~10 min (~20 GB); LAION-5B requiere del orden de **una semana con 10 nodos** y muchos terabytes.
- Se puede integrar con **Weights & Biases (wandb)** para monitorizar la descarga (y, en general, entrenamientos) en tiempo real.

Pipeline típico de construcción/descarga:

1. URL + caption → 2. descarga → 3. obtención de la imagen → 4. validación (que abra y no esté corrupta) → 5. filtrado (proporciones extremas, duplicados, contenido inapropiado…) → 6. dataset final.

### 2.3 Qué puede salir mal con miles de millones de URLs

- Ruido, **duplicados**, **copyright/licencias**, contenido inapropiado, calidad desigual, coste computacional y de almacenamiento.
- **Enlaces muertos**: al reintentar descargar un subconjunto de LAION-5B unos años después, **~30 % de las URL ya no existían**. El dataset publicado ≠ el dataset que realmente usas (URLs muertas, contenido eliminado, errores, filtros, deduplicación).
- **Tamaños heterogéneos**: hay que recortar o redimensionar a un tamaño fijo. Redimensionar una imagen muy alargada a cuadrado la **deforma**; se hace porque no hay alternativa a mano, pero afecta a la calidad del modelo.
- **Retroalimentación**: cada vez más contenido web está generado por IA; entrenar con él degrada progresivamente los datos.
- **Datos sintéticos**: anotar a mano a esta escala es imposible y caro, así que se usan modelos para generar captions (incluso encadenando un modelo de captions de vídeo + uno de imagen + metadatos). Es **barato pero menos preciso** que el etiquetado humano y hereda las limitaciones de los modelos usados.

### 2.4 Vídeo como imágenes

Truco habitual para aprovechar vídeo con modelos de imagen: agrupar los frames de cada segundo y **promediarlos**, obteniendo pocas imágenes representativas. Es barato, pero **se pierde la dimensión temporal** y el modelo puede no "entender" el vídeo.

## 3. Evaluación y benchmarks

### 3.1 Principios

- Los datasets de evaluación son **mucho más pequeños**: para saber si un modelo domina un tema no hacen falta miles de millones de ejemplos.
- **Un benchmark mide al modelo bajo un protocolo concreto** (prompt, formato, métrica…); no es una propiedad intrínseca suya.
- Problemas:
  - **Contaminación**: si entrenas "con todo internet", el conjunto de evaluación probablemente estaba dentro → mides memoria, no generalización.
  - **Saturación**: un benchmark que hoy nadie resuelve, en 1–2 años está cerca del 100 % y ya no discrimina entre modelos (ejemplo de clase: un benchmark matemático que pasó de ~0 % a >80 %).
  - **Automática vs humana**: métricas automáticas baratas frente a juicio humano caro.
  - **Selección interesada**: cada empresa reporta los benchmarks que mejor le van; comparar modelos exige el mismo conjunto y protocolo.

### 3.2 Benchmarks y recursos citados

| Benchmark / recurso | Qué mide | Nota de clase |
|---|---|---|
| **MMMU** | ~11.5K preguntas multimodales de nivel universitario (ingeniería, ciencias, medicina, arte…) con diagramas, tablas, imágenes médicas | distingue **3 niveles de dificultad** y una vs varias imágenes; los modelos punteros ya superan al humano medio, el experto humano ronda el 85 % |
| **VQA** | preguntas de sentido común sobre imágenes de COCO | clásico, ya muy explotado |
| **Humanity's Last Exam (HLE)** | preguntas en la "frontera del conocimiento humano" | solo se aceptaban preguntas que fallaban los modelos punteros; pasó de <10 % a ~60 % en poco más de un año. El profesor contribuyó con una pregunta |
| **Benchmark de montaje de muebles IKEA** | detectar errores en una foto de un mueble a medio montar | ejemplo de tarea visual fina; los mejores modelos rondan el 80 % |
| **Arena (lmarena / arena.ai)** | ranking por **votos humanos** en duelos ciegos; también para generación de imágenes | las empresas prueban modelos con nombre en clave antes del lanzamiento |
| **ArtificialAnalysis.ai** | evaluación independiente: calidad vs **coste** vs **latencia**, coste de evaluar, evolución temporal, abiertos vs cerrados | útil para elegir "el más barato que sea suficientemente bueno" |
| **HallusionBench, IllusionBench** | alucinación e ilusiones visuales | ver §4 |
| **MangaVQA, VideoGameBench** | dominios que aún se resisten | |
| **MMVP ("Eyes Wide Shut", LeCun)** | pares de imágenes que CLIP confunde → fallos visuales de los MLLM | |
| **ColorBench, color naming, contraste, sesgo textura/forma** | percepción básica, poco evaluada | |

Un modelo moderno se evalúa en **muchas áreas** (conocimiento, razonamiento, visión, código, uso agéntico, idiomas, instrucciones largas); las *model cards* de Hugging Face y los blogs de lanzamiento listan decenas de benchmarks.

**Intuición del profesor:**
- En ArtificialAnalysis lo que importa es la curva calidad/precio: a igual coste, elegir el que rinde claramente más.
- Desconfiar de titulares: citó un modelo anunciado como "nuevo y top" que resultó ser un ajuste/compresión de otro modelo existente.
- Los modelos abiertos grandes (pesos descargables) suelen **no caber en un portátil**.

## 4. Alucinaciones y fallos de percepción (resumen)

Una **alucinación** multimodal es una salida que no corresponde con el contenido de la imagen (u otra entrada). Causas señaladas en las slides:

1. **Datos ruidosos** (web o generados; p. ej. instruction data creada por un LLM solo-texto que no veía la imagen).
2. **Falta de diversidad**: casi todas las descripciones son afirmativas → los modelos tienden a **responder "sí"**.
3. **Encoder visual débil o baja resolución**: se pierden detalles; solo subir resolución ya mejora resultados.
4. **LLM mucho más fuerte que el encoder**: el modelo prioriza su conocimiento previo frente a lo que "ve".

También: memorización, campos difíciles (manga, videojuegos), confusiones de color/contraste y sesgo de textura.

---

## Aplicación a nuestro MVP

- **Tareas que usamos**:
  - **VQA / razonamiento sobre gráficos** → `ingest/chart_reader.py` con `providers/vision/claude_vision.py` (alternativa local `qwen_vl_local.py`).
  - **DocVQA** sobre PDFs de resultados → `ingest/pdf_reader.py`: `pypdf` para el texto y visión solo para páginas con gráficos/tablas.
  - **Matching zero-shot** (opcional) → `providers/image/clip_classifier.py` para enrutar la imagen subida ("gráfico de velas / tabla / otra cosa").
  - **Text-to-image** (opcional) → portada en `media/cover.py`.
- **Riesgo de alucinación numérica** (crítico en finanzas): un VLM puede inventar cifras de un gráfico o PDF borroso. Mitigaciones:
  - exigir en el prompt que responda "no legible" si no está seguro y que devuelva `key_figures` solo con valores leídos;
  - **contrastar cifras** con `PriceSnapshot` de `yfinance` cuando exista dato estructurado;
  - preferir el texto extraído por `pypdf` frente a la lectura visual cuando ambos existan;
  - evitar preguntas de sí/no sesgadas ("¿sube la acción?") → pedir descripción abierta.
- **Resolución**: no reducir en exceso las capturas antes de mandarlas al modelo de visión (perjudica OCR de ejes y etiquetas); si son muy alargadas, recortar/teselar en lugar de deformar.
- **Elección de modelo** (docs de viabilidad, `docs/04_viabilidad_costes_latencia_compliance.md`): justificar Sonnet vs Haiku con la lógica de ArtificialAnalysis (calidad/coste/latencia) y no con benchmarks del propio proveedor.
- **Evaluación propia**: crear un mini-benchmark interno en `data/samples/` (5–10 capturas y PDFs con cifras conocidas) para medir aciertos del lector de gráficos; es un "benchmark bajo protocolo", útil para el README y el pitch.
- **Datos de noticias**: igual que con LAION, los enlaces RSS caducan; guardar en `storage.py` el texto ya descargado del briefing, no solo la URL.

## Glosario rápido

- **Retrieval / matching**: recuperar la imagen (o texto) que mejor encaja con una consulta de la otra modalidad.
- **Captioning**: generar una descripción textual de una imagen (condicionado o no).
- **VQA**: responder en lenguaje natural preguntas sobre una imagen.
- **DocVQA**: VQA sobre documentos; combina OCR y comprensión del layout.
- **img2dataset**: librería para descargar datasets imagen-texto a partir de listas de URL.
- **Contaminación**: que datos de evaluación estén en el entrenamiento.
- **Saturación**: benchmark que ya no distingue modelos porque todos puntúan casi al máximo.
- **Datos sintéticos**: anotaciones generadas por modelos; baratas pero menos precisas.
- **Arena**: ranking de modelos basado en votos humanos en comparaciones ciegas.
