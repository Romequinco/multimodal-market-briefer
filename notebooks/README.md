# Notebooks de exploración

Cuadernos propios del grupo para probar modelos antes de llevarlos a `src/briefer/`.
No se copian aquí los notebooks de clase (están en `docs/raw/`, ignorado por git).

Convención de nombres: `<carril>_<nn>_<tema>.ipynb`, p. ej. `A_01_qwen_vl_graficos.ipynb`.
Antes de versionar un notebook: limpiar salidas pesadas y no dejar claves en las celdas.

Ideas previstas (TODO), con el notebook de clase que las inspira:

| Carril | Exploración | Notebook de clase | Destino en código |
|---|---|---|---|
| A | Clasificación zero-shot de capturas (velas / tabla / otra) con CLIP | 2 (CLIP) | `providers/image/clip_classifier.py` |
| A | Lectura de gráficos con Qwen2.5-VL-3B vs Claude visión | 3 (VQA con Qwen) | `providers/vision/qwen_vl_local.py` |
| A | Whisper local (base) vs API: calidad y latencia en español | 7 (Whisper) | `providers/stt/whisper_local.py` |
| B | Prompts del Analista y del Guionista, salida estructurada | 9 (Agents) | `agents/*.py`, `agents/prompts/*.md` |
| C | Portada con SDXL-Turbo (1 paso) | 4 (Stable Diffusion) | `providers/image/sdxl_turbo.py` |
| C | Voces: edge-tts vs ElevenLabs (vs Bark local, solo curiosidad) | 6 (generación de sonido) | `providers/tts/*.py` |
| C | Vídeo con moviepy; SVD solo como extra | 5 (Stable Video Diffusion) | `media/video.py` |
