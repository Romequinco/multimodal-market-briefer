# 09 · Fine-tuning de un VLM con LoRA, cuantización y destilación ("GPU poor")

**Fuentes:** slides ~126 (LLM del MLLM, fine-tuning y LoRA), ~132-142 (etapas de entrenamiento), ~210-216 (cómo usar MLLM siendo "GPU poor": solo evaluar, cuantización con bitsandbytes, LoRA, destilación); notebook `nb_10_Fine_tuning_a_VLM` (Qwen2-VL-2B en ChartQA); transcripción del 2-oct (LoRA como fine-tuning con menos memoria; `device_map="auto"` reparte el modelo entre GPUs).

> **TL;DR**
> - Siendo "GPU poor" hay 4 palancas: **no entrenar (solo inferencia)**, **cuantizar** (bitsandbytes 8/4 bits), **LoRA** (entrenar matrices pequeñas) y **destilar** (modelo pequeño imita a uno grande).
> - El notebook ajusta **`Qwen/Qwen2-VL-2B-Instruct`** sobre el 2 % de **ChartQA** con **LoRA (r=16, q/v)** + **TRL `SFTTrainer`**, en bf16 y sin cuantizar.
> - ChartQA es **exactamente** nuestra tarea de lectura de gráficos, pero en 3 días **no compensa** entrenar: usar un VLM grande por API (o Qwen2.5-VL zero-shot) y dejar el fine-tuning como roadmap.

---

## 1. Estrategias "GPU poor" (slides)

| Palanca | Idea | Coste | Cuándo |
|---|---|---|---|
| **Solo evaluar/inferir** | No entrenar; usar modelos preentrenados (open o API) | Mínimo | Siempre el punto de partida |
| **Cuantización** | Reducir la precisión de los pesos (fp16 → int8/int4). Librería esencial: **bitsandbytes** | Pérdida pequeña de calidad | Modelo no cabe en VRAM |
| **LoRA** | Congelar el modelo y entrenar matrices de **bajo rango** añadidas a ciertas capas | ~0,1-1 % de parámetros entrenables | Adaptar a un dominio/tarea |
| **QLoRA** | LoRA sobre un modelo base cuantizado a 4 bits | Aún menos VRAM | GPU pequeña (T4) |
| **Destilación** | Entrenar un modelo pequeño (alumno) para imitar a uno grande (profesor). Base de **DINO** | Requiere datos y entrenamiento | Producción a escala/latencia |

Recordatorio de entrenamiento de MLLM (slides/transcripción): normalmente **2 etapas** — (1) preentrenamiento del **conector** con encoder y LLM congelados; (2) **instruction tuning** del conector + LLM (a menudo con LoRA). El encoder de visión casi siempre queda congelado. Los modelos *-Instruct* ya traen esta segunda etapa.

### Cuantización con bitsandbytes (no ejecutado en el notebook)
- 8 bits (`load_in_8bit`) ≈ mitad de memoria que fp16; 4 bits **NF4** (`load_in_4bit`, `bnb_4bit_quant_type="nf4"`, `bnb_4bit_use_double_quant=True`, `bnb_4bit_compute_dtype=torch.bfloat16`) ≈ un cuarto.
- Regla rápida de memoria de pesos: **parámetros × bytes** → 2B en bf16 ≈ 4-5 GB; en 4 bits ≈ 1,5 GB (+ activaciones y caché).
- bitsandbytes necesita **GPU NVIDIA/CUDA** (no ayuda en CPU).

## 2. LoRA en dos frases

- En lugar de actualizar la matriz W (d×d), se aprende ΔW = **B·A** con A (r×d) y B (d×r), r pequeño (8-64). Se escala por `lora_alpha / r`.
- El resultado es un **adaptador** de pocos MB que se carga encima del modelo base (`model.load_adapter(path)`), intercambiable y fusionable.

## 3. El notebook 10 paso a paso

### Datos: ChartQA
- `HuggingFaceM4/ChartQA`: imágenes de gráficos (barras, líneas, tartas...) + pregunta (`query`) + respuesta (`label`). Es **VQA sobre gráficos**.
- Se carga solo el **2 %** de cada split (`train[:2%]`, `val[:2%]`, `test[:2%]`) para que sea rápido.
- Ojo (comentado en el notebook): en el split de validación `label` viene a veces como **lista** → normalizar a string.

### Formato de chat
- **System prompt**: "eres un VLM especializado en gráficos; responde de forma **concisa** (una palabra, número o frase corta)".
- Cada ejemplo → `{"messages": [system, user(image placeholder + texto), assistant(respuesta)], "images": [imagen]}`. El formato concreto depende del modelo (ver su *model card*).
- Se usa **`.map()`** para conservar el tipo `Image` de `datasets`.

### Evaluación zero-shot previa
- `Qwen2VLForConditionalGeneration` + `Qwen2VLProcessor`, `device_map="auto"`, `torch_dtype=torch.bfloat16`.
- Función de inferencia: sustituye el placeholder por la imagen real, `processor.apply_chat_template(..., add_generation_prompt=True)`, `qwen_vl_utils.process_vision_info`, `model.generate`, recorta los tokens del prompt y decodifica.
- Resultado: una respuesta bien y otra **mal y además verbosa** → motivación para el fine-tuning.
- Truco: función `clear_memory()` (borrar variables, `gc.collect()`, `torch.cuda.empty_cache()`) entre fases.

### Fine-tuning
- **Sin cuantización** (2B cabe en la T4 de Colab con la que se ejecutó), bf16.
- `LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", target_modules=["q_proj","v_proj"], task_type="CAUSAL_LM")`.
- **TRL `SFTTrainer`** (Supervised Fine-Tuning) evita escribir el bucle; recibe los datasets ya formateados y el `processor` como `processing_class`. **No hay collator propio**: TRL reciente gestiona `messages` + `images` (en versiones antiguas había que escribir un *collate_fn* que aplicara la plantilla, procesara imágenes y enmascarara con -100 el padding y los tokens de imagen en `labels`).

| Hiperparámetro (`SFTConfig`) | Valor |
|---|---|
| `num_train_epochs` | 1 |
| `per_device_train_batch_size` / `eval` | 2 / 2 |
| `gradient_accumulation_steps` | 8 (batch efectivo 16) |
| `gradient_checkpointing_kwargs` | `{"use_reentrant": False}` |
| `max_length` | 1024 |
| `optim` | `adamw_torch_fused` |
| `learning_rate` | 2e-4 |
| `warmup_steps` / `max_grad_norm` | 10 / 0.3 |
| `logging_steps` / `eval_steps` / `save_steps` | 5 / 10 / 20 (estrategia "steps") |
| `bf16` | True |
| **`remove_unused_columns`** | **False** (si no, el Trainer borra la columna `images` y falla) |
| `push_to_hub` | False |

- `trainer.train()` → `trainer.save_model(output_dir)` guarda **solo el adaptador LoRA**.
- Test: recargar el modelo base, `model.load_adapter(output_dir)` y repetir la pregunta que fallaba.

## Receta de código (del notebook)

```python
import torch
from transformers import Qwen2VLForConditionalGeneration, Qwen2VLProcessor
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer

model_id = "Qwen/Qwen2-VL-2B-Instruct"
model = Qwen2VLForConditionalGeneration.from_pretrained(
    model_id, device_map="auto", torch_dtype=torch.bfloat16)
processor = Qwen2VLProcessor.from_pretrained(model_id)

peft_cfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
                      target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM")
args = SFTConfig(output_dir="qwen2vl-chartqa-lora", num_train_epochs=1,
                 per_device_train_batch_size=2, gradient_accumulation_steps=8,
                 learning_rate=2e-4, bf16=True, max_length=1024,
                 remove_unused_columns=False)   # imprescindible con imágenes
trainer = SFTTrainer(model=model, args=args, train_dataset=train_ds, eval_dataset=eval_ds,
                     peft_config=peft_cfg, processing_class=processor)
trainer.train(); trainer.save_model(args.output_dir)
```

(`train_ds`/`eval_ds` = ChartQA formateado con `format_data` vía `.map()`.)

## Requisitos prácticos

Cifras orientativas (estimación, no viene de clase). Lo único que consta en el NB10 es que se ejecutó en Colab con GPU
T4 (metadatos), en bf16 y sin cuantizar, y que tras `clear_memory()` seguían ocupados ~4,1 GB de VRAM.

| Escenario | VRAM orientativa | Tiempo | Notas |
|---|---|---|---|
| Inferencia Qwen2-VL-2B bf16 | ~6-8 GB | ~1-5 s por pregunta | T4 no tiene bf16 nativo (el notebook lo usa igualmente; puede ir más lento) → fp16 o L4/A100 si hay problemas |
| LoRA bf16 (config del notebook) | ≤16 GB (cabe en la T4 del notebook) | Decenas de minutos con el 2 % de datos | Más holgado en A100/L4 |
| QLoRA 4 bits | ~8-12 GB | Algo más lento | Viable en T4 con batch 1 y fp16 |
| CPU | Entrenamiento inviable; inferencia 2B muy lenta | — | — |
| Alternativa API | VLM grande (Claude/Gemini) lee gráficos zero-shot muy bien | 2-6 s | Pago por token de imagen |

## Aplicación a nuestro MVP

- **Módulos relacionados:** `src/briefer/ingest/chart_reader.py` (captura de gráfico → `DocumentInsight`), `src/briefer/providers/vision/claude_vision.py` (por defecto) y `src/briefer/providers/vision/qwen_vl_local.py` (alternativa local).
- **Decisión recomendada (3 días):**
  1. **No hacer fine-tuning** para el MVP: un VLM grande por API resuelve lectura de gráficos de mercado zero-shot; entrenar, evaluar y empaquetar un adaptador consume el tiempo que falta para UI/robustez.
  2. **Sí reutilizar del notebook:** el **system prompt de respuesta concisa** y el **formato de mensajes** (imagen + pregunta) para `chart_reader.py`; pedir salida estructurada (`key_figures`: ticker, último valor, máximo/mínimo, tendencia).
  3. `qwen_vl_local.py` con `Qwen/Qwen2.5-VL-3B-Instruct` (notebook 3) en **4 bits** como modo offline si hay GPU.
  4. **Roadmap/pitch:** "fine-tuning LoRA de un VLM pequeño sobre ChartQA + capturas reales de brokers → lectura de gráficos local, barata y privada (RGPD)". Es un argumento fuerte de viabilidad de costes.
- **Mini-benchmark barato (sí da nota):** 20-30 ejemplos de ChartQA `test` evaluados con nuestro proveedor de visión (exact match / tolerancia numérica del 5 %) → tabla en README comparando Claude vs Qwen local.
- **Riesgos:** VRAM y bf16 en T4; versiones de TRL/transformers cambiantes (el notebook instala TRL desde git); licencias de los datasets si se reentrena con capturas de terceros.

## Glosario rápido

- **Fine-tuning:** seguir entrenando un modelo preentrenado con datos propios.
- **SFT:** *Supervised Fine-Tuning* con pares entrada/salida.
- **LoRA / adaptador:** matrices de bajo rango entrenables sobre un modelo congelado.
- **`r`, `lora_alpha`, `target_modules`:** rango, escala y capas donde se inserta LoRA.
- **QLoRA:** LoRA sobre modelo cuantizado a 4 bits.
- **Cuantización (int8, NF4):** menos bits por peso → menos memoria.
- **bf16 / fp16:** formatos de 16 bits (bf16 con más rango; requiere GPU Ampere+).
- **Gradient accumulation / checkpointing:** simular batch grande / ahorrar memoria recalculando activaciones.
- **Destilación:** alumno pequeño imita a profesor grande.
- **ChartQA:** benchmark de preguntas sobre gráficos.
- **Chat template:** formato de mensajes propio de cada modelo.
