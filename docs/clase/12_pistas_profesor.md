# 12 · Pistas del profesor (transcripción del 2-oct-2026)

> Destilado de la transcripción automática de la primera sesión (`docs/raw/text/transcripcion_2026-10-02.txt`, con
> muchos errores de reconocimiento; aquí se interpreta el sentido, no se copia). Las marcas `[hh:mm]` son tiempo
> aproximado **desde el inicio de la grabación** (la clase empieza hacia `[00:06]`).
> La transcripción solo cubre el día 1 (introducción, datasets, CLIP/SigLIP, arquitectura de MLLM y notebooks 1-3).
> Lo marcado como **[slides]** procede de las diapositivas (`docs/raw/text/slides.txt`) y lo marcado como
> **[notebook N]** del notebook N (`docs/raw/text/nb_*.txt` o sus outputs), no de lo dicho en clase. Lo que no sale de
> ninguna fuente se indica como "(no viene de clase)".
> Se omiten nombres de alumnos y avisos administrativos.

---

## 1. Sobre la práctica (startup FinTech)

- **[00:07] La tarea es asumible.** El profesor comenta que la práctica la ha planteado el director del máster
  a última hora, que este pasaría al día siguiente a explicarla con más detalle y que, por lo que
  sabe, **no es demasiado complicada**. Al inicio de la grabación también se oye que "en una semana da tiempo".
  *Implicación:* priorizar un MVP que funcione de punta a punta antes que modelos sofisticados; el valor está en
  orquestar bien varias modalidades (ver `docs/raw/text/enunciado.txt`).
- **[00:14] No vamos a entrenar modelos multimodales.** Entrenar uno desde cero es prácticamente imposible (datos y
  cómputo); lo realista es usar modelos preentrenados y, como mucho, ajustarlos (*fine-tuning*).
  *Implicación:* nuestra arquitectura de "proveedores intercambiables" + APIs es exactamente lo esperable.
- **[00:15] Más modalidades no siempre es mejor.** Una modalidad puede dominar a las demás y añadir modalidades sin
  sentido mete ruido y empeora el resultado.
  *Implicación:* la rúbrica premia modalidades "con sentido y coherencia"; cada entrada/salida del Market Briefer debe
  justificar su valor para el usuario (no añadir CLAP o SVD solo por sumar).

## 2. Cómo elegir modelo

- **[02:34] Buscar en Hugging Face por tarea.** Para cada pipeline (p. ej. *image-text-to-text*,
  *document-question-answering*) se filtra el Hub por esa etiqueta y se elige modelo; si no se indica, la pipeline usa
  uno por defecto.
- **[02:59] Preferir organizaciones conocidas.** Hay miles de variantes de CLIP subidas por cualquiera; recomienda usar
  las de organizaciones reconocidas (OpenAI, Google, LAION…), no las de usuarios anónimos.
- **[03:01] Tamaño y popularidad como señales.** El nº de parámetros de la ficha da una idea de si el modelo cabrá en
  memoria (aunque la prueba real es cargarlo); el nº de descargas sugiere cuáles funcionan mejor.
- **[03:48] Leer bien la ficha del modelo.** El tamaño del nombre a veces solo cuenta el LLM, no encoder + conector;
  los modelos *Instruct* ya vienen ajustados para seguir instrucciones (preferirlos para uso tipo chat); la ficha trae
  siempre un ejemplo de uso y los resultados en benchmarks.
- **[00:53-01:02] Arenas y comparadores.** Recomienda usar una "arena" (votaciones a ciegas entre dos modelos, con
  rankings por tarea: generación de imagen, preguntas sobre imágenes…) y un comparador independiente que publica
  inteligencia, coste de evaluar, latencia y **relación calidad/precio**. Las slides citan Arena.ai y
  ArtificialAnalysis.ai. Criterio: a igualdad de precio, el mejor; idealmente barato y bueno.
  *Implicación:* justificar en `docs/04_viabilidad_costes_latencia_compliance.md` la elección Sonnet/Haiku con datos de
  coste y calidad de estos comparadores.
- **[01:00] Desconfiar de titulares.** Pone el ejemplo de un modelo presentado como puntero que luego resultó ser un
  derivado ajustado/comprimido de otro. *Implicación:* citar benchmarks independientes, no notas de prensa.
- **[01:03] Benchmarks de las fichas.** Cada empresa publica los benchmarks donde mejor queda; comparar exige el mismo
  conjunto de evaluación.
- **[01:11] Abierto ≠ ejecutable en local.** Los modelos de pesos abiertos más potentes son tan grandes que no caben en
  un portátil. *Implicación:* para la demo, API; local solo modelos pequeños (Whisper base, Qwen-VL 3B, SigLIP).

## 3. Uso práctico de Hugging Face y Colab

- **[02:33] Pipelines vs control fino.** Las *pipelines* son dos líneas y gestionan todo, pero son poco flexibles y solo
  admiten modelos compatibles con esa tarea; si hay que combinar piezas o tocar parámetros de generación, cargar
  `Processor` + `Model` a mano.
  *Implicación:* en `providers/*_local.py` usar pipeline para prototipar y pasar a control fino solo si hace falta.
- **[02:38] Poner `.eval()` siempre** al cargar un modelo de PyTorch para inferencia (dropout y normalizaciones); "a
  mucha gente se le olvida". Y mover a GPU si la hay.
- **[02:41] Fijar semilla siempre** en generación (imagen, etc.) para que sea reproducible; el NB1 (SDXL base) y el
  NB5 (vídeo) la fijan con `manual_seed(42)` **[notebook 1, 5]**; el NB4 de SDXL-Turbo no la fija.
- **[03:51] `device_map="auto"` funciona muy bien**: detecta CUDA y reparte el modelo entre varias GPUs sin cambiar código.
- **[03:52-03:57] GPU en Colab.** Los notebooks con GPU se ejecutaron en Colab T4 **[notebook 1, 3-7, 10]** (metadatos).
  Los pesos de Qwen2.5-VL-3B-Instruct son ~7,5 GB y tardaron un par de minutos en descargarse; describir una imagen
  reducida (600×400 **[notebook 3]**) tardó unos 19 s.
- **[03:55] Formato chat y *chat template*.** Los VLM reciben una lista de mensajes (`role` + `content` con trozos
  `image`/`text`), opcionalmente con *system prompt* o conversación previa simulada; se aplica la plantilla de chat
  propia de cada modelo (`apply_chat_template`), se genera y se recortan los tokens del prompt antes de decodificar
  **[notebook 3]**. *Implicación:* en `providers/vision/qwen_vl_local.py` no construir el prompt a mano.
- **[01:30] Multi-GPU no escala lineal.** Con el doble de GPUs no se va el doble de rápido: los nodos tienen que
  comunicarse y se pierde eficiencia (ejemplo de OpenCLIP, probado hasta ~1024 GPUs).
- **[notebook 10] `remove_unused_columns=False`** en el `SFTConfig` al hacer *fine-tuning* con imágenes: si no, el
  Trainer elimina la columna `images` que no reconoce y el entrenamiento falla.
- **[03:54] Colab/Gemini de pago gratis para estudiantes.** Comenta que con correo universitario Google ofrece un año
  del plan de pago, con mejor GPU en Colab y más uso de Gemini. *Implicación:* opción para probar los modelos locales
  pesados (Qwen-VL, SDXL-Turbo) sin hardware propio.
- **[00:33] Seguimiento de experimentos.** Menciona Weights & Biases para ver en tiempo real descargas o entrenamientos
  (el NB10 usa `trackio`; el NB3 cita MLflow para producción).

## 4. Visión, documentos y gráficos

- **[02:36] DocVQA alucina con mala imagen.** Con un documento borroso o de baja calidad, lo que devuelva el modelo
  probablemente se lo está inventando; un buen modelo debería decir que no lo sabe.
  *Implicación:* en `ingest/chart_reader.py` y `ingest/pdf_reader.py` pedir confianza/"no legible" y validar cifras.
- **[03:26] Resolución = calidad de los embeddings.** Si la imagen es muy pequeña o se reescala mucho, lo extraído es
  "prácticamente basura", sobre todo en tareas de **leer texto** dentro de la imagen; imágenes muy alargadas se deforman
  al forzarlas a cuadrado. Los encoders multirresolución intentan resolverlo.
  *Implicación:* no reducir capturas de gráficos/PDF antes de mandarlas a visión; renderizar páginas de PDF a buena
  resolución; recortar en vez de deformar.
- **[03:55] Compromiso resolución/latencia.** En la demo redujo la imagen "para que tarde menos" y propuso probar a
  agrandarla para ver cuánto sube el tiempo: más resolución = más tokens visuales = mejor lectura pero más latencia.
  Decidir cuánto queremos esperar.
- **[02:47] CLIP para clasificar: añadir "ninguna".** Con softmax el modelo tiene que repartir el 100 % entre las
  opciones (en el notebook, un tanque sale 66 % "gato"); incluir una clase "nada de esto" o fijar un umbral sobre el
  logit bruto **[notebook 2]**.
- **[02:56] SigLIP no obliga a elegir.** Aplica una sigmoide por par (decisiones binarias independientes): en la demo,
  "2 gatos" ≈ 10 % y "2 perros" ≈ 0 %, sin sumar 100 %. En código: `padding="max_length"` en el processor (así se
  entrenó) y `torch.sigmoid` sobre `logits_per_image` **[notebook 2]**.
  *Implicación:* en `providers/image/clip_classifier.py`, con CLIP etiqueta "otra cosa"; con SigLIP, umbral calibrado.
- **[02:44] Prompts para CLIP.** Mejor frases tipo "una foto de…" que palabras sueltas, porque así eran los textos de
  entrenamiento. **[01:22]** Además, para cada clase se usan **varias plantillas** ("una foto de un gato", "una mala
  foto de un gato", "una foto de muchos gatos"…), porque no sabemos cómo se describían las imágenes originales.
- **[notebook 2] `softmax(dim=1)` vs `dim=0`.** Sobre `logits_per_image` (imágenes × textos), `dim=1` reparte entre
  textos (una imagen, varias etiquetas: clasificar) y `dim=0` entre imágenes (un texto, varias imágenes: buscar).
- **[02:23] CLIP cuenta mal** (números), probablemente porque los textos de entrenamiento apenas los incluyen; un
  pequeño ajuste con textos numéricos lo mejora. *Implicación:* no usar CLIP para extraer cifras.
- **[02:25] Sesgo de textura.** Los humanos clasificamos por forma; muchos modelos por textura. Los transformers mejoran,
  pero no igualan al humano.
- **[02:29] La mejor representación puede estar en una capa intermedia**, según la tarea (no siempre la última).
  **[03:01]** Para acceder a ellas, `output_hidden_states=True` devuelve los estados de todas las capas (en ViT-B:
  embeddings + 12 capas) **[notebook 2]**.

## 5. Costes, tokens y contexto

- **[01:01] Coste de razonamiento.** En los comparadores, los modelos que "piensan" son los que más cuestan por los
  tokens de razonamiento; la caché de entradas abarata. *Implicación:* razonamiento solo donde aporte (Analista), y
  Haiku para tareas baratas; considerar *prompt caching* para el contexto repetido.
- **[03:57] `max_new_tokens` es un tope, no un objetivo.** Si es muy bajo, corta la respuesta a medias (en la demo, con
  8 tokens la frase quedó incompleta y por eso tardó menos; con 32 ya la completó; el notebook trae 4); un valor alto no
  obliga a respuestas largas. Pedir "sé preciso" acorta la salida.
- **[03:59] Límite de contexto.** También hay tope de tokens de entrada: un PDF de 100 páginas puede no caber o el modelo
  puede ignorar partes. *Implicación:* en `ingest/pdf_reader.py` extraer/trocear y resumir, no volcar el PDF entero.
- **[04:02] El español gasta más tokens que el inglés** porque los tokenizadores están pensados para inglés.
  *Implicación:* tenerlo en cuenta en `costs.py` (estimación por tokens, no por palabras).
- **[04:03] Cambios de tokenizador disparan la factura.** Cuenta un caso en que, al actualizar un modelo manteniendo el
  precio por token, el nuevo tokenizador generaba más tokens y el gasto subió. *Implicación:* medir tokens reales por
  briefing (`StepMetric`) en vez de suponerlos.

## 6. Datos y evaluación

- **[00:28] Captions cortos → modelos poco descriptivos.** La mayoría de textos de datasets web son cortos; con
  descripciones más largas el modelo aprende a describir con más detalle. **[02:35]** Por eso unos modelos "se enrollan"
  más que otros.
- **[00:20] Datos web contaminados por contenido generado** por otros modelos: la calidad se retroalimenta a peor.
- **[00:38] Enlaces muertos.** Al reintentar descargar un gran dataset web, ~30 % de URLs ya no existían.
- **[01:31] Deduplicar al mezclar datasets.** Si un ejemplo aparece en dos fuentes, eliminarlo de una de ellas; es
  responsabilidad de quien mezcla (las slides incluyen la deduplicación en el pipeline de construcción de datasets
  **[slides]**). *Implicación:* deduplicar noticias de varios RSS antes de pasarlas al Analista.
- **[00:39] Contaminación y saturación de benchmarks.** Si el conjunto de evaluación estaba en internet, puede haberse
  entrenado con él; y los benchmarks se saturan en uno o dos años (uno de preguntas muy difíciles pasó de <10 % a ~60 %).
- **[01:08] Datos sintéticos.** Etiquetar a mano es carísimo; se generan descripciones con otros modelos, más baratas
  pero menos precisas.

## 7. Arquitectura e intuiciones (útiles para el diseño y el pitch)

- **[03:11] "LLM como director" vs "LLM como núcleo".** Dos arquitecturas de MLLM: (a) el LLM recibe texto y decide a qué
  modelo especializado llamar (generar imagen, audio…); ventaja: añadir funcionalidades sin reentrenar; inconveniente:
  se puede perder información al pasar de un modelo a otro. (b) Encoders por modalidad + conector + LLM (estándar hoy,
  >90 % según las slides).
  *Implicación:* nuestro pipeline es del tipo (a) a nivel de sistema (Analista → Guionista → TTS → vídeo). Es lo que pide
  la rúbrica ("encadenar modelos especializados"); mitigar la pérdida de información pasando datos estructurados
  (`schemas.py`) y no solo texto libre entre pasos.
- **[03:28] Whisper como "encoder de audio".** Se puede usar su texto directamente como entrada al LLM (lo que haremos)
  o sus embeddings internos con un conector.
- **[03:34] Fusión temprana vs tardía.** No hay respuesta universal; la temprana es más sencilla de entrenar.
- **[03:40] El LLM concentra los parámetros** y se suele dejar fijo (como mucho LoRA); el encoder visual también.
- **[03:43] Entrenamiento en dos etapas** (alinear conector; luego *instruction tuning*).
- **[01:24] Por qué CLIP generaliza mejor** que un clasificador solo de imagen: la supervisión con texto aporta más
  información que la etiqueta de clase (aunque parte del mérito es la escala de datos, **[03:25]**).

## 8. Agentes y riesgos **[slides]**

- **[slides] Ojo con los permisos de los agentes**, sobre todo si tienen acceso a internet: hay que limitar muy bien lo
  que pueden y no pueden hacer. Las slides ilustran el aviso con un incidente reportado en el que agentes de evaluación
  con acceso a internet escalaron privilegios usando credenciales expuestas.
  *Implicación:* el Agente Q&A solo con herramientas de **lectura**; nada de envío de emails/Telegram decidido por el
  LLM (lo disparan el pipeline o la UI); claves en `.env`; validar entradas del usuario (posible *prompt injection* en
  PDFs subidos).
- **[notebook 9] La docstring de una `@tool` es su manual.** El agente decide qué herramienta usar y cómo a partir de la
  docstring (qué hace, tablas/columnas, argumentos y relaciones como la clave de JOIN); conviene generarla desde el
  esquema real. Las tools **devuelven los errores como texto** (en vez de lanzar excepciones) para que el agente pueda
  autocorregirse; el 8B se equivocó en el SQL antes de acertar.
- **[slides] Mejoras de MLLM:** *chain-of-thought* reduce alucinaciones pero es más caro y lento; alta resolución y
  multirresolución mejoran; MoE da modelos rápidos con pocos parámetros activos.
- **[slides] Alucinaciones** por datos ruidosos, falta de diversidad (tendencia a responder "sí"), encoder visual pobre o
  LLM que prioriza su conocimiento sobre la imagen. *Implicación:* en los prompts de `agents/prompts/*.md`, exigir
  citar fuentes (`KeyPoint.sources`) y no afirmar cifras no presentes en el contexto.
- **[slides] "GPU poor":** no entrenar, solo inferir; cuantización (`bitsandbytes`), LoRA, destilación.
- **[slides] Series temporales** son "una modalidad muy importante en datos económicos" (Time-LLM, OneFitsAll). Idea de
  roadmap para el pitch.

## 9. Generación de imagen y audio (trampas de los notebooks)

- **[notebook 4] SDXL-Turbo:** se usa con `guidance_scale=0.0` y muy pocos pasos (el notebook compara 4 y 10; más pasos
  no garantiza mejor resultado). El rango habitual de 1-4 pasos es de la ficha del modelo (no viene de clase). Escribir
  "8k" en el prompt no cambia la resolución. Fijar semilla (ver §3).
- **Whisper y frecuencia de muestreo (no viene de clase).** El NB7 pasa a la pipeline un array normalizado sin
  `sampling_rate` **[notebook 7]**; en ese caso la pipeline asume 16 kHz, y Bark genera a 24 kHz (micrófonos/móvil:
  44,1-48 kHz) → pasar la ruta del fichero o `{"raw": data, "sampling_rate": sr}`. Otras precauciones: forzar idioma
  (`generate_kwargs={"language": "spanish", "task": "transcribe"}`; sin él, Whisper autodetecta y avisa
  **[notebook 7]**), `chunk_length_s=30` para audios largos y **ffmpeg** instalado para webm/ogg/mp3.
  *Implicación:* `providers/stt/*` y `ingest/voice.py`.
- **Bark ~13 s por llamada (no viene de clase).** Cada generación produce un fragmento corto, así que un podcast exige
  trocear por frases y concatenar; además es estocástico (la voz cambia entre llamadas) → **fijar la voz por locutor**
  (`voice_preset`/`history_prompt`). El notebook solo muestra que el prompt también controla el *cómo* (`♪`, `[laughs]`)
  **[notebook 6]**. *Implicación:* el MVP usa `edge-tts` por defecto (voces fijas A/B).

## 10. Opiniones del profesor

- Es prácticamente imposible estar al día de todo lo que sale en multimodal **[03:08]**.
- Le sorprende que los mejores modelos ya superen al humano medio en benchmarks multimodales universitarios **[00:43]**
  y que acierten un ~60 % en preguntas de nivel experto **[00:48]**; a la vez, avisa de que si no sabes del tema no
  puedes comprobar si la respuesta es buena **[00:48]**.
  *Implicación:* el Market Briefer no da asesoramiento personalizado (MiFID II) y debe mostrar fuentes y disclaimer.
- Recomienda leer el paper de Meta PerceptionLM / Perception Encoder por lo detallado que es **[02:13]**.
