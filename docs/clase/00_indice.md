# 00 · Índice de `docs/clase/`

Documentación derivada de la clase **Modelos Fundacionales y Multimodales** (MIAX, prof. Pablo Hernández Cámara,
2-3 oct 2026), resumida con palabras propias para servir de **contexto a agentes IA y al equipo** que construye el
*Market Briefer* (noticias de mercado → podcast a 2 voces + vídeo, lectura de gráficos/PDF y preguntas por voz).

## Ficheros

| Fichero | Contenido |
|---|---|
| [`01_intro_multimodalidad.md`](01_intro_multimodalidad.md) | Definición de modelo multimodal y modalidades (texto, imagen, audio, vídeo, series temporales, LiDAR, IoT…); problemas (dominancia de una modalidad, ruido al añadir más, coste); espacio común (CLIP) vs modalidad ancla (MLLM, ImageBind); *early/intermediate/late fusion*; multimodalidad "por composición" (encadenar modelos), que es el enfoque del MVP. |
| [`02_tareas_y_datasets.md`](02_tareas_y_datasets.md) | Familias de tareas texto-imagen (matching, captioning, VQA, texto→imagen; *grounding* y DocVQA con Donut); datasets curados vs web (MSCOCO, LAION, img2dataset, enlaces muertos, datos sintéticos); benchmarks (MMMU, HLE, IKEA…), contaminación, saturación, arenas y ArtificialAnalysis; causas de alucinación; mitigaciones de alucinación numérica y mini-benchmark interno para el MVP. |
| [`03_contrastivos_clip_siglip.md`](03_contrastivos_clip_siglip.md) | CLIP (arquitectura, pérdida InfoNCE, usos zero-shot/retrieval/métrica, robustez), OpenCLIP y leyes de escala, SigLIP (sigmoide), MaMMUT, variantes (AltCLIP, ALIGN, EVA-CLIP…), receta de Meta Perception Encoder, limitaciones (contar, textura, color, trampa de la softmax) y uso práctico del NB2; enrutador de imágenes `clip_classifier.py`. |
| [`04_mllm_vlm_arquitectura_entrenamiento.md`](04_mllm_vlm_arquitectura_entrenamiento.md) | "LLM como director" vs encoder + conector + LLM (+ generador); encoders, conectores, generadores (NExT-GPT); entrenamiento en dos etapas, RLHF, PerceptionLM, modelos nativos y catálogo; alucinaciones y mejoras (CoT, multirresolución, MoE, uso agéntico); "GPU poor"; demo de Qwen2.5-VL-3B-Instruct (chat template, resolución, `max_new_tokens`, contexto, tokens y coste). |
| [`05_difusion_imagen.md`](05_difusion_imagen.md) | VAE/GAN/difusión, *latent diffusion*, condicionamiento por texto (CFG, negative prompt, semilla), SD/SDXL/SDXL-Turbo (text2img e img2img con `strength`, NB4), DreamBooth, pix2pix/superresolución/inpainting; receta, requisitos y decisión de portada (sin IA por defecto, Turbo opcional). |
| [`06_video.md`](06_video.md) | De imagen a vídeo (operaciones 3D, atención temporal, interpolación), Imagen Video en cascada, Omni-Video, Stable Video Diffusion (parámetros del NB5), text2video (Veo, Sora, Wan), VQA y *highlights* de vídeo (SmolVLM2); decisión: montaje con moviepy + ffmpeg y SVD solo como extra. |
| [`07_audio_whisper_clap_tts.md`](07_audio_whisper_clap_tts.md) | Mel-espectrograma; Whisper (NB7) y sus trampas (frecuencia de muestreo, idioma, audios largos, ffmpeg); CLAP (NB8); TTS con Bark (NB6: marcadores expresivos, voces); MusicGen y Live Music Models; series temporales (Time-LLM, OneFitsAll); decisiones de STT/TTS para el MVP. |
| [`08_agentes_y_riesgos.md`](08_agentes_y_riesgos.md) | Uso agéntico y "LLM como director"; smolagents (`@tool`, `CodeAgent`, NB9 texto→SQL con Llama-3.1-8B y Qwen2.5-72B); incidente de seguridad narrado en las slides; tabla de guardrails; decisión: Analista/Guionista sin tools, Q&A con tools de solo lectura. |
| [`09_finetuning_lora_cuantizacion.md`](09_finetuning_lora_cuantizacion.md) | Palancas "GPU poor" (solo inferencia, cuantización con bitsandbytes, LoRA/QLoRA, destilación); NB10 paso a paso (Qwen2-VL-2B-Instruct + LoRA sobre el 2 % de ChartQA con TRL `SFTTrainer`, hiperparámetros, `remove_unused_columns=False`); decisión: sin *fine-tuning* en el MVP, roadmap y mini-benchmark ChartQA. |
| [`10_iqa_metricas.md`](10_iqa_metricas.md) | NB11: métricas clásicas (RMSE, PSNR, SSIM) vs perceptuales (LPIPS, TPIPS), CLIP como métrica (CLIPScore, CLIP-IQA), lecciones de evaluación; propuesta de evaluación de las salidas del MVP (grounding de cifras, WER del audio, round-trip VLM sobre gráficos, LLM-as-judge). |
| [`11_recetario_notebooks.md`](11_recetario_notebooks.md) | Recetario práctico de los 11 notebooks: modelo HF exacto, snippet mínimo, requisitos, trampas y uso en el MVP, con tabla resumen. |
| [`12_pistas_profesor.md`](12_pistas_profesor.md) | Pistas de la transcripción del día 1 con marcas `[hh:mm]` y pistas de slides/notebooks marcadas `[slides]`/`[notebook N]`: práctica, elección de modelo, uso de HF/Colab, visión y CLIP, costes/tokens, datos, arquitectura, agentes, generación de imagen/audio, opiniones. |

## Material original

- El material de clase (PDF de slides, notebooks con outputs, transcripción, enunciado) está en **`docs/raw/`**, que
  **no se versiona** (ignorado por git).
- Su texto extraído está en **`docs/raw/text/`**: `nb_*.txt` (11 notebooks), `slides.txt`, `transcripcion_2026-10-02.txt`
  (automática, con errores) y `enunciado.txt` (enunciado de la práctica B5-T4).
- Estos `docs/clase/*.md` son resúmenes propios: no copiar fragmentos largos del material original a docs versionados.

## Cómo usar estos docs como contexto de agentes

Leer siempre primero [`CLAUDE.md`](../../CLAUDE.md), [`docs/02_arquitectura_y_flujo_datos.md`](../02_arquitectura_y_flujo_datos.md) y
[`docs/03_contratos_modulos.md`](../03_contratos_modulos.md); después, según la tarea. Las rutas de módulos de las tablas
son relativas a [`src/briefer/`](../../src/briefer/) (todas existen en el repo; `app/pages/*` está en la raíz).

| Tarea en el repo | Leer |
|---|---|
| TTS / podcast a 2 voces (`providers/tts/*`, `media/podcast.py`) | 07 + 11 (NB6) + 12 §9 |
| Voz a texto, pregunta por voz (`providers/stt/*`, `ingest/voice.py`, `app/pages/2_Preguntar.py`) | 07 + 11 (NB7, NB8) + 12 §9 |
| Lectura de gráficos / capturas (`ingest/chart_reader.py`, `providers/vision/*`) | 03 + 04 + 09 + 11 (NB1-3, NB10) + 12 §3-4 |
| Lectura de PDF de resultados (`ingest/pdf_reader.py`) | 04 + 11 (NB1 DocVQA, NB3) + 12 §4-5 |
| Clasificar/enrutar imagen subida (`providers/image/clip_classifier.py`) | 03 + 11 (NB2) + 12 §4 |
| Portada / infografía (`media/cover.py`, `providers/image/sdxl_turbo.py`) | 05 + 11 (NB4) + 12 §9 |
| Vídeo corto (`media/video.py`) | 06 + 11 (NB5) |
| Agentes Analista / Guionista / Q&A (`agents/*`, prompts) | 04 + 08 + 11 (NB9) + 12 §7-8 |
| Elección de proveedor LLM, costes y latencia (`providers/llm/*`, `costs.py`, `docs/04_viabilidad_costes_latencia_compliance.md`) | 02 + 04 §8 + 12 §2, §5 |
| Control de calidad de imágenes subidas o generadas | 10 + 11 (NB11) |
| Modelos locales y *fine-tuning* (`providers/vision/qwen_vl_local.py`, `providers/stt/whisper_local.py`, roadmap) | 04 §7-8 + 09 + 11 (NB3, NB10) + 12 §3 |
| Pitch, README y roadmap (argumentos técnicos) | 01 + 04 + 09 + 12 |

## Mapa modalidad → modelo de clase → módulo del MVP

| Modalidad | Modelo visto en clase | Módulo del MVP | Opción por defecto en el MVP |
|---|---|---|---|
| Texto → texto (análisis, guion, Q&A) | Llama-3.1-8B / Qwen2.5-72B vía `smolagents` (NB9) | `agents/analyst.py`, `agents/scriptwriter.py`, `agents/qa.py`, `providers/llm/*` | Claude (Sonnet; Haiku para tareas baratas) |
| Imagen (gráfico) → texto | Qwen2.5-VL-3B-Instruct (NB3), LLaVA 0.5B (NB1), Qwen2-VL-2B + LoRA (NB10) | `ingest/chart_reader.py`, `providers/vision/claude_vision.py`, `providers/vision/qwen_vl_local.py` | Claude visión |
| Documento/PDF → texto | Donut DocVQA (NB1), Qwen2.5-VL (NB3) | `ingest/pdf_reader.py` | `pypdf` + Claude visión para páginas con gráficos |
| Imagen ↔ texto (clasificar) | CLIP ViT-B/32, SigLIP2 (NB2) | `providers/image/clip_classifier.py` | Opcional (desactivado por defecto: `BRIEFER_IMAGE_CLASSIFIER_PROVIDER=none`) |
| Audio → texto | Whisper base (NB7) | `ingest/voice.py`, `providers/stt/*` | Whisper API (`whisper_api`); local `whisper_local` (`faster-whisper`) como alternativa |
| Audio ↔ texto (clasificar) | CLAP (NB8) | (idea) control de calidad en `ingest/voice.py` | No |
| Texto → audio (voz) | Bark (NB6) | `media/podcast.py`, `providers/tts/*` | `edge-tts` (ElevenLabs opcional; Bark no implementado) |
| Texto → imagen | SDXL base (NB1), SDXL-Turbo (NB4) | `media/cover.py`, `providers/image/sdxl_turbo.py` | Opcional (desactivado por defecto: `BRIEFER_IMAGE_GEN_PROVIDER=none`) |
| Imagen → vídeo | Stable Video Diffusion (NB5) | `media/video.py` | `moviepy` + ffmpeg (SVD solo como extra precalculado) |
| Imagen × imagen → calidad | LPIPS, TPIPS (NB11) | (idea) validación de capturas | No |
| Datos → gráfico | — (no es modelo) | `media/charts.py` | matplotlib/plotly |

Las opciones por defecto coinciden con `.env.example` (Claude + edge-tts + Whisper API); en el código, sin `.env`, todos
los proveedores son `mock`.
