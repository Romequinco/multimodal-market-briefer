# 04 · MLLM y VLM: arquitectura, entrenamiento y uso práctico

**Fuentes:** slides 100–216 (MLLM: arquitecturas, encoders, conectores, LLM, generadores, entrenamiento, PerceptionLM, scaling, modelos nativos, catálogo de modelos, alucinaciones, mejoras, agentes, uso "GPU poor"); transcripción 2-oct-2026, min 03:05–04:04 (arquitecturas, encoders, conectores, fusión, generadores, NExT-GPT, entrenamiento en 2 etapas, demo Qwen2.5-VL-3B-Instruct, tokens y contexto). Las slides 134–216 (datos de pretraining en detalle, RLHF, alucinaciones, mejoras, agentes, cuantización, LoRA, destilación) **no tienen transcripción** (segundo día); se documentan solo a partir de las slides. Notebooks relacionados: `1. Check tasks with Transformers` (pipeline VQA con LLaVA) y `3. VQA with Qwen`.

> **TL;DR**
> - Casi todos los MLLM usan un **LLM preentrenado como "cerebro"** y le añaden módulos para otras modalidades. Arquitectura estándar (>90 %): **encoder de modalidad + conector + LLM (+ generador)**.
> - La alternativa "**LLM como director**" (el LLM llama a herramientas/modelos externos) es rápida de construir y extensible sin reentrenar, pero pierde información al pasar todo por texto. **Es el patrón de nuestro MVP.**
> - Encoders de imagen: CLIP (el más usado), SigLIP, OpenCLIP, EVA-CLIP, DINO (autosupervisado). Problema recurrente: **baja resolución y reescalado cuadrado** (malo para OCR) → encoders multirresolución.
> - Conectores (MLP de 1–2 capas, Q-Former, Perceiver Resampler, C-Abstractor…): no hay ganador claro; lo que sí importa es el **número de tokens visuales**.
> - Entrenamiento típico en **2 etapas**: (1) preentrenamiento solo del conector con pares imagen-caption; (2) *instruction tuning* del conector + LLM (datos a menudo sintéticos), opcionalmente RLHF. Para "GPU poor": **solo inferencia**, **cuantización** (bitsandbytes), **LoRA**, **destilación**.

---

## 1. De LLM a MLLM

- Los LLM ya tienen una comprensión semántica muy potente y el lenguaje es clave para la inteligencia; la pregunta es cómo hacer que **trabajen con cualquier modalidad**.
- Idea: usar el LLM como **módulo central de decisión** y añadir módulos de modalidades no textuales. El texto actúa como **modalidad ancla** (ver `01_intro_multimodalidad.md`).
- Objetivo ideal: aceptar cualquier modalidad, procesarla y **generar** cualquier modalidad. El campo avanza tan rápido que es imposible estar al día (listas *Awesome-Multimodal-LLMs*, *LLMSurvey*).

## 2. Dos arquitecturas

| | **LLM como director** | **LLM como parte del sistema** |
|---|---|---|
| Cómo funciona | el LLM recibe texto y **decide qué módulo llamar** (generador de imagen, de audio, detector…) | cada modalidad entra por su **encoder + conector** directamente al LLM, que las combina |
| Ventajas | rápido de construir, **sin reentrenar**, se añaden funcionalidades nuevas solo describiéndolas | información rica (no pasa por texto), fusión real |
| Inconvenientes | **pérdida de información** al pasar entre módulos vía texto | requiere entrenar (al menos el conector) |
| Uso hoy | minoritario como arquitectura de modelo, pero es la base de los **agentes** | estándar (>90 % de los MLLM) |
| Ejemplos | Visual-ChatGPT, HuggingGPT, MM-REACT, ViperGPT | LLaVA, Qwen-VL, BLIP-2, Flamingo, PerceptionLM |

**Intuición del profesor:** en el modelo integrado, el LLM es el centro de un sistema con muchas entradas y salidas; "es un poco ir juntando piezas".

## 3. Arquitectura estándar: encoder + conector + LLM (+ generador)

```
imagen ─▶ [Encoder visual (CLIP/SigLIP…)] ─▶ [Conector] ─▶ tokens visuales ─┐
                                                                           ├─▶ [LLM] ─▶ texto
texto ─▶ [Tokenizador + embeddings del LLM] ─────────────────────────────────┘      └─▶ [Conector] ─▶ [Generador (difusión)] ─▶ imagen/audio/vídeo
```

Caso particular **VLM** (*Vision-Language Model*): solo visión + lenguaje. LLM (texto→texto) + encoder visual (imagen→representación).

### 3.1 ¿Por qué hace falta el conector?

**Intuición del profesor (dibujada en pizarra):** el espacio común de CLIP alinea imagen y texto **entre sí**, pero **no es el espacio de embeddings del LLM**, que se entrenó solo para generar texto. Los embeddings del encoder no son comparables a los del LLM, así que el conector los **traduce** a algo que el LLM "entienda". A menudo se congelan encoder y LLM y **solo se entrena el conector**, porque lo que importa es alinear ambas representaciones.

### 3.2 Encoders de modalidad

**Imagen:**

| Encoder | Tipo | Nota |
|---|---|---|
| **CLIP** | contrastivo | el más famoso y usado: embeddings de alto nivel alineados con texto |
| **SigLIP** | contrastivo (sigmoide) | cada vez más usado |
| **OpenCLIP** | contrastivo abierto | preferido por ser abierto y documentado (CLIP original es privado) |
| **EVA-CLIP** | contrastivo grande | más grande y más datos → mejores resultados |
| **DINO / DINOv2** | autosupervisado solo-imagen | dos vistas aumentadas de la misma imagen deben dar representaciones parecidas; sin texto; muy buenos encoders. DINO se basa en **destilación** |

**¿Hace falta que el encoder sea multimodal?** *Scaling Language-Free Visual Representation Learning* entrenó SSL solo con imágenes a escala comparable a CLIP y obtuvo resultados parecidos: SSL visual **escala mejor** en datos y capacidad. Lectura del profesor: quizá la ventaja de CLIP venía más de **la cantidad de datos** que de la multimodalidad. Lo normal sigue siendo usar CLIP/SigLIP, pero no es obligatorio.

**Problema de resolución:** la mayoría de encoders reescalan a imágenes **cuadradas de baja resolución (224×224)**. Si la imagen original es pequeña se extrae "basura"; si es muy alargada se **deforma**. Afecta sobre todo a **OCR** (leer texto en la imagen). Solución emergente: **encoders multirresolución** (extraer embeddings a varias escalas y concatenarlos o fusionarlos con una capa densa).

**Otras modalidades:**
- Audio: **Whisper** (puedes usar su salida textual o quedarte con embeddings intermedios y poner tu conector), AudioCLIP, **CLAP** (CLIP para audio), HuBERT, BEATs.
- 3D: Point-BERT.
- **Unificados**: **ImageBind** (6 modalidades en un espacio, imagen como ancla; demo: audio de perro → imagen de perro), **LanguageBind** (encoders por modalidad ya **alineados con el texto**, ahorrándose el conector).

### 3.3 Conectores

Proyectan las representaciones de la modalidad al espacio del LLM.

| Conector | Ejemplos |
|---|---|
| Proyección lineal (MLP de 1 capa) | LLaVA, MiniGPT-4, NExT-GPT |
| MLP de 2 capas | LLaVA-1.5/NeXT, CogVLM, DeepSeek-VL, Yi-VL, **PerceptionLM** |
| **Q-Former** (consultas aprendidas con atención cruzada) | BLIP-2, InstructBLIP |
| **Perceiver Resampler** (comprime a nº fijo de tokens) | Flamingo, Qwen-VL, MiniCPM-V |
| **C-Abstractor** | HoneyBee, MM1 |

¿Cuál es mejor? **No está claro**: cada paper concluye algo distinto (*Connector-S survey*). Lo que sí se repite: **cuantos más tokens visuales, mejor** (más información), a costa de más parámetros y cómputo.

Dónde se fusionan las modalidades (early / intermediate / late fusion): ver `01_intro_multimodalidad.md` §5.2. Según el profesor, si vas a entrenar, **early fusion** es a priori lo más sencillo.

### 3.4 El LLM

- Genera texto; concentra **la mayoría de parámetros**; casi siempre **preentrenado** (entrenarlo es carísimo) y se deja congelado o con *fine-tuning* ligero (**LoRA**). Se suelen elegir **open source** (acceso a pesos y código).

### 3.5 Generadores

Para salidas no textuales se conecta un **modelo de difusión** de cada modalidad (imagen/vídeo/audio) mediante otro conector desde los últimos estados del LLM. **NExT-GPT**: LLM congelado + difusores congelados, **solo se entrenan los proyectores** (y luego LoRA para seguir instrucciones) → texto, imagen, audio y vídeo de entrada y salida.

## 4. Entrenamiento

### 4.1 De tareas específicas a propósito general

Antes: un modelo por tarea (captioning, detección…). Ahora: **un único modelo** al que pides describir, detectar, responder o editar sobre la misma imagen; se entrena dándole **todos los tipos de instrucción** que luego se le pedirán.

### 4.2 Dos etapas

| Etapa | Qué se entrena | Datos | Objetivo |
|---|---|---|---|
| **1. Preentrenamiento (alineamiento)** | **solo el conector/adaptador**; encoder y LLM congelados | pares imagen-caption: *coarse* (mucho volumen, captions cortos y ruidosos) o *fine* (menos datos, captions largos y detallados) | alinear modalidades y dar conocimiento general; sin esto el modelo no puede hablar de la imagen |
| **2. Instruction tuning** | conector + **fine-tuning del LLM** (a veces también el encoder si no hay buenos resultados) | instrucciones multimodales (más caras); a menudo **generadas con LLM** | seguir instrucciones y nuevas tareas (el LLM solo-texto no sabe qué es "editar una imagen") |

- Los datos humanos suelen ser **demasiado concisos** y limitarían la capacidad de generación; por eso se generan con LLM. Pero que la mayoría de datos sean sintéticos causa otros problemas (p. ej. LLaVA generó instrucciones con un modelo solo-texto que **no veía** la imagen → respuestas erróneas y alucinaciones).
- **RLHF**: alinear con preferencias humanas; como tener humanos valorando todo es caro, se entrena un **modelo de recompensa** que predice qué elegiría el humano y actúa de juez.

### 4.3 Ejemplo: Meta PerceptionLM (PLM)

- Arquitectura: encoder **Perception Encoder** (PE L/14 para Llama 3.2 1B/3B; PE G/14 para Llama 3.1 8B) + **MLP de 2 capas** + decoder **Llama 3**.
- Etapas:
  1. **Warm-up del proyector**: encoder y LLM congelados, solo el proyector, con pocos datos sintéticos.
  2. **Mid-training a gran escala con datos sintéticos** de imagen y vídeo de dominios diversos.
  3. **SFT con datos anotados por humanos**, mayor resolución y más frames de vídeo.
- Hallazgo: **escalar datos sintéticos solo funciona para tareas base ya establecidas**; para mejorar de verdad hacen falta datos humanos de calidad.

### 4.4 Scaling y modelos nativos

- **Leyes de escala** para predecir el comportamiento de modelos más grandes/entrenados más tiempo antes de pagarlo (entrenar Llama 3 costó >720 M$).
- **Modelos nativamente multimodales** (entrenados multimodales desde el principio en vez de partir de un LLM): sin ventaja inherente de *late fusion*; **early fusion** rinde mejor con pocos parámetros, es más eficiente y fácil de desplegar; **MoE** ayuda a aprender pesos por modalidad.

### 4.5 Catálogo de modelos (por modalidad)

- Texto+imagen→texto: Flamingo, BLIP-2, LLaVA, InstructBLIP, Qwen-VL, GPT-4V, Chameleon, PaliGemma 2, Phi-4-Mini, PerceptionLM…
- Texto+vídeo→texto: Video-LLaVA, Video-LLaMA, LLaMA-VID, PerceptionLM…
- Texto+audio→texto: SALMONN, AudioPaLM, SpeechGPT…
- Texto+3D, medicina, química, geografía: 3D-LLM, PointLLM, BioGPT, ChemLLM, GeoGPT…
- Generación multimodal / any-to-any: GILL, EMU, VideoPoet, AnyMAL, **NExT-GPT**, Unified-IO 2, AnyGPT.

## 5. Problemas de los MLLM (resumen)

- **Alucinaciones** (salida que no corresponde con la imagen): datos ruidosos/sintéticos, falta de diversidad (tendencia a responder "sí"), encoder débil o baja resolución, LLM mucho más fuerte que el encoder (prefiere su conocimiento previo). Benchmarks: HallusionBench, IllusionBench.
- **Memorización**, dominios difíciles (manga, videojuegos), fallos de percepción básica (MMVP de LeCun, color, contraste, sesgo textura/forma). Detalle en `02_tareas_y_datasets.md` §4.

## 6. Mejoras

| Mejora | Idea | Coste / matiz |
|---|---|---|
| **Chain-of-Thought** | `<input> <razonamiento> <output>` | reduce alucinaciones y mejora resultados, pero **mucho más caro y lento** (más tokens) |
| **Alta resolución** | más detalle visual | multiplica los tokens visuales; si comprimes, vuelves a perder información → buscar equilibrio |
| **Multirresolución** | varias escalas en paralelo | mejora resultados |
| **Datos de calidad** | datos anotados por humanos | lo sintético solo escala para tareas base |
| **Modelos pequeños / MoE** | *Mixture of Experts*: solo se activan algunos expertos por token | muchos menos parámetros activos = más rápido (p. ej. Gemma 4 26B-A4B) |
| **Uso agéntico** | dejar que los modelos ejecuten acciones (p. ej. smolagents) | **limitar permisos**, sobre todo con acceso a internet → ver `08_agentes_y_riesgos.md` |
| **Control por activaciones** | *transporting activations* para dirigir el comportamiento | investigación |

Sobre agentes, las slides recorren un incidente reportado en el que agentes de evaluación con acceso a internet encontraron credenciales expuestas y escalaron privilegios en infraestructura de terceros en pocas horas. Moraleja: **mínimo privilegio, sin credenciales accesibles, sandbox y supervisión**. Detalle en `08_agentes_y_riesgos.md`.

## 7. Cómo usar MLLM siendo "GPU poor"

| Estrategia | Qué es | Herramienta |
|---|---|---|
| **No entrenar, solo inferencia** | usar modelos preentrenados tal cual (o vía API) | Hugging Face `transformers`, APIs |
| **Cuantización** | reducir la precisión de los pesos (16→8→4 bits) para que quepan en memoria | **bitsandbytes** (`load_in_8bit` / `load_in_4bit`) |
| **LoRA** | *fine-tuning* entrenando solo matrices de bajo rango, sin que todo el modelo tenga que entrenarse en GPU | PEFT |
| **Destilación** | entrenar un modelo pequeño para que imite a uno grande | base de DINO |

Detalle de fine-tuning, LoRA y cuantización en `09_finetuning_lora_cuantizacion.md`.

## 8. Uso práctico de un VLM (demo de clase con Qwen2.5-VL-3B-Instruct)

- **Model card**: el nº de parámetros del título a veces se refiere **solo al LLM**; el total (encoder + conector + LLM) aparece en otra parte. El sufijo **`-Instruct`** indica que ya tiene *instruction tuning* (mejor siguiendo órdenes); sin él, es el modelo base.
- Carga: `torch_dtype="auto"` y `device_map="auto"` → Transformers coloca el modelo en GPU automáticamente e incluso lo **reparte entre varias GPU** sin cambiar el código. Pesos de ~7,5 GB; descarga de un par de minutos en Colab (GPU T4).
- Entrada en **formato chat**: lista de mensajes con `role` y `content` (trozos `image` + `text`); se puede añadir *system prompt* y una conversación previa simulada. Se aplica la **chat template** del modelo (cada modelo tiene la suya), se pasa por el processor, `generate`, se recortan los tokens del prompt y se decodifica.
- Imágenes: ruta local, URL o imagen cargada. **Más resolución = mejor respuesta pero más tokens y más lento**; en la demo se redujo la imagen (600×400) para que tardase menos y la descripción tardó ~19 s.
- **`max_new_tokens`**: es un tope, no un objetivo; si es muy bajo **corta** la respuesta a medias (en la demo, con 8 tokens la frase quedó incompleta y con 32 ya se completó; el notebook trae el ejemplo con 4). Para respuestas cortas, pídelo en el prompt ("sé preciso").
- **Ventana de contexto**: también hay límite de tokens de entrada; un PDF de 100 páginas puede no caber o el modelo puede **ignorar partes**.
- **Tokens y coste**: el español suele consumir **más tokens que el inglés** (tokenizadores pensados para inglés). Un proveedor cambió de tokenizador manteniendo el precio por token y la factura de sus clientes se disparó: el coste real depende de los tokens reales.
- Pipelines de Hugging Face (`pipeline("image-text-to-text", ...)`): 2 líneas, ideales para prototipar, pero poco flexibles; para control fino, `processor` + `model` y **`.eval()`** siempre.

---

## Aplicación a nuestro MVP

- **Nuestro sistema es "LLM como director"** a nivel de producto: `pipeline.py` orquesta modelos especializados (visión, STT, LLM, TTS, difusión opcional) y los **agentes** (`agents/analyst.py`, `scriptwriter.py`, `qa.py`) trabajan sobre texto. Ventaja: cero entrenamiento y proveedores intercambiables (`providers/registry.py`, ADR-002). Riesgo señalado por el profesor: **pérdida de información** al convertir imagen/PDF/voz a texto. Mitigación: que `DocumentInsight` conserve `extracted_text` + `key_figures` + `summary`, y que el Q&A pueda volver a pedir la imagen original al proveedor de visión si la pregunta lo requiere.
- **Dentro de cada paso usamos MLLM "integrados"**: `providers/vision/claude_vision.py` (Claude visión) y la alternativa local `qwen_vl_local.py` (**Qwen2.5-VL-3B-Instruct**, notebook 3: encoder + conector + LLM). Usar siempre versiones **`-Instruct`**.
- **Resolución y OCR**: los gráficos financieros tienen texto pequeño (ejes, tickers, cifras). No reducir capturas por debajo de lo necesario; para PDFs, renderizar páginas con gráficos a resolución suficiente; teselar imágenes muy alargadas. Medir latencia (`StepMetric`) porque más resolución = más tokens = más coste.
- **Prompts anti-alucinación** (`agents/prompts/*.md`, prompts de `chart_reader`): pedir que diga "no legible/no sé", no presuponer respuestas ("¿sube?"), separar lo **visto** de lo **inferido**; considerar un razonamiento breve tipo CoT solo en el analista (coste/latencia ↑).
- **`max_tokens` y contexto**: dimensionar `max_tokens` para que el guion (~3–5 min de audio) no se corte; trocear PDFs largos por páginas relevantes en vez de mandar el documento entero.
- **Costes**: estimar en `costs.py` con tokens reales (contar con el tokenizador/uso devuelto por la API), recordando que el español infla tokens; usar Haiku para tareas baratas (clasificar, resumir noticias) y Sonnet para análisis/guion.
- **"GPU poor"**: el MVP es **solo inferencia** (APIs + modelos locales pequeños). Si se usa Qwen local, cargar en **4-bit con bitsandbytes** para que quepa en GPU de consumo; LoRA/destilación quedan fuera del alcance de la entrega (roadmap).
- **Agentes y seguridad**: el agente Q&A **no** debe tener herramientas con efectos (envío de emails, escritura en disco fuera de `data/`) ni acceso a credenciales; `delivery/*` lo disparan el pipeline o la UI, nunca el LLM. Ver `08_agentes_y_riesgos.md`.
- **Compliance**: un MLLM puede sonar convincente aunque alucine → el `disclaimer` de `Analysis` (MiFID II: no es asesoramiento personalizado) y la cita de `sources` en cada `KeyPoint` no son opcionales.

## Glosario rápido

- **MLLM**: *Multimodal Large Language Model*; LLM ampliado con otras modalidades.
- **VLM**: *Vision-Language Model*; MLLM limitado a imagen + texto.
- **Encoder de modalidad**: red que convierte imagen/audio/… en embeddings (CLIP, SigLIP, Whisper…).
- **Conector / proyector**: módulo que traduce esos embeddings al espacio del LLM (MLP, Q-Former, Perceiver…).
- **Tokens visuales**: embeddings de imagen ya proyectados que el LLM procesa como si fueran tokens.
- **Instruction tuning**: ajuste fino con pares instrucción-respuesta para seguir órdenes.
- **RLHF**: aprendizaje por refuerzo con un modelo de recompensa que imita preferencias humanas.
- **MoE**: *Mixture of Experts*; solo una parte de los parámetros se activa por token.
- **Cuantización**: reducir la precisión numérica de los pesos para ahorrar memoria (bitsandbytes).
- **LoRA**: ajuste fino eficiente entrenando matrices de bajo rango añadidas al modelo.
