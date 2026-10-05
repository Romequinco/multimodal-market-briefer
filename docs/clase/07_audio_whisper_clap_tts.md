# 07 · Audio: Whisper (STT), CLAP, TTS con Bark, MusicGen y series temporales

**Fuentes:** slides ~118 (encoders de audio en MLLM), ~245-249 (Whisper, mel-espectrograma, CLAP, MusicGen, Live Music Models), ~250-251 (series temporales: Time-LLM, OneFitsAll); notebooks `nb_6._Generating_sound_with_Suno` (Bark), `nb_7._Audio_transcription_with_Whisper`, `nb_8._After_CLIP_is_CLAP`; transcripción del 2-oct (mención de Whisper y CLAP como encoders de audio).

> **TL;DR**
> - Casi todos los modelos de audio "ven" el sonido como una imagen: el **mel-espectrograma** (frecuencias en el tiempo).
> - **Whisper** (`openai/whisper-base` en clase) transcribe y detecta idioma; ojo a la **frecuencia de muestreo (16 kHz)** y a trocear audios largos.
> - **CLAP** (`laion/clap-htsat-unfused`) = CLIP para audio: clasificación **zero-shot** audio↔texto.
> - **Bark** (`suno/bark`) hace TTS expresivo con marcadores (`[laughs]`, `♪`) y voces predefinidas, pero es lento e impredecible → para el MVP, `edge-tts` por defecto (Bark no está implementado como proveedor).

---

## 1. El mel-espectrograma

- La señal de audio es una serie de muestras (p. ej. 16 000 por segundo). Se trocea en ventanas cortas (~25 ms, salto ~10 ms), se calcula la **FFT** de cada una (STFT) y se agrupan las frecuencias en **bandas mel** (escala perceptual: más resolución en graves, como el oído humano). Se aplica logaritmo.
- Resultado: una "imagen" **tiempo × frecuencia** que se procesa con CNN/Transformers igual que una imagen. Whisper usa 80 bandas (128 en large-v3) y ventanas de **30 s** (detalle técnico, no viene de clase).
- Encoders de audio citados para MLLM: **Whisper, AudioCLIP, CLAP, HuBERT, BEATs**. El profesor comentó que se puede usar Whisper "completo" (audio→texto→LLM) o quedarse con sus **embeddings intermedios** y ponerles un conector hacia el LLM.

## 2. Whisper (audio → texto) — notebook 7

- **ASR** (*Automatic Speech Recognition*), encoder-decoder Transformer entrenado con cientos de miles de horas multilingües con supervisión débil. Tareas: **transcribir**, **traducir al inglés**, **detectar idioma**, **timestamps**.
- Tamaños: `tiny`, `base` (el del notebook), `small`, `medium`, `large-v3`, `large-v3-turbo`. Cuanto más grande, mejor en español y con ruido, pero más lento.
- Carga del notebook: `AutoModelForSpeechSeq2Seq` + `AutoProcessor`, con `device = "cuda:0" if disponible else "cpu"` y `torch_dtype = float16` en GPU / `float32` en CPU, `low_cpu_mem_usage=True`, `use_safetensors=True`. Luego usa la **`pipeline`** (más simple).
- **Preprocesado (normalización):** un WAV PCM de 16 bits contiene enteros en [-32768, 32767]; se pasan a `float32` dividiendo por **32768** → rango [-1, 1].
- El notebook enlaza con el anterior: transcribe el audio generado por Bark (ciclo **TTS → STT**).

### Trampas prácticas (importantes)

El NB7 no las menciona explícitamente (pasa a la pipeline un array sin `sampling_rate` y deja que Whisper autodetecte el
idioma, con aviso en el output); son comportamientos conocidos de la librería (no vienen de clase).

| Trampa | Solución |
|---|---|
| Si pasas un **array numpy sin frecuencia**, la pipeline asume **16 kHz**; Bark genera a 24 kHz y un móvil a 44,1/48 kHz → transcripción errónea | Pasar la ruta del fichero (la pipeline remuestrea con ffmpeg) o `{"raw": data, "sampling_rate": sr}` |
| Audio **estéreo** (`data.shape` con 2 columnas) | Promediar canales a mono |
| Audios **> 30 s** | `chunk_length_s=30` (+ `batch_size`) en la pipeline, o `return_timestamps=True` |
| Idioma mal detectado en clips cortos | `generate_kwargs={"language": "spanish", "task": "transcribe"}` |
| Formatos webm/ogg de navegador/Telegram | Necesitan **ffmpeg** instalado |

## 3. CLAP (audio ↔ texto) — notebook 8

- *Contrastive Language-Audio Pretraining* (LAION): misma idea que CLIP cambiando imagen por audio. Encoder de audio (HTS-AT) + encoder de texto en un espacio común.
- Uso: **clasificación zero-shot** — dado un audio y varias descripciones, ¿cuál encaja mejor? Sin entrenar un clasificador.
- Ejemplo del notebook con ESC-50 (`hf-internal-testing/ashraq-esc50-1-dog-example`): "Sound of a dog" vs "vacuum cleaner" → gana perro; "big dog" vs "small dog" → el modelo da preferencia aunque **el audio quizá no contenga esa información**.
- Lección clave del notebook: la softmax es una **preferencia relativa entre las opciones que tú das**, no una probabilidad absoluta.
- Detalle: el output del notebook avisa de que hay que pasar `sampling_rate` al feature extractor (si no, errores silenciosos). El modelo espera audio a **48 kHz** (dato de la ficha, no viene de clase): pasar `sampling_rate=48000` y remuestrear si hace falta.

## 4. Texto a voz con Bark (Suno) — notebook 6

- `pipeline("text-to-speech", "suno/bark")`; la salida es un dict con `audio` (array) y `sampling_rate` (24 kHz). Se reproduce con `IPython.display.Audio`.
- Internamente: texto → tokens semánticos → tokens acústicos (códec EnCodec) → waveform; modelo tipo GPT, **generativo y estocástico** (cada ejecución suena distinta).
- **El prompt también indica *cómo* decirlo** (idea del notebook):

| Marcador | Efecto |
|---|---|
| `♪ texto ♪` | Intenta cantarlo |
| `[laughs]`, `[sighs]`, `[gasps]`, `[clears throat]` | Sonidos no verbales |
| `—` o `...` | Dudas, pausas |
| MAYÚSCULAS | Énfasis |
| `[music]` | Música de fondo |

- **Voces / speaker presets** (no viene de clase): se fija la voz con un preset tipo `v2/es_speaker_0` … `v2/es_speaker_9` (español) vía `voice_preset` del processor de `BarkModel` o `history_prompt`. Útil para tener **2 locutores consistentes**.
- **Limitaciones** (no vienen de clase): ~13 s de audio como máximo por llamada (hay que **trocear por frases** y concatenar), lento sin GPU, puede alucinar palabras, cambiar de voz o meter ruidos; los marcadores funcionan mejor en inglés. Existe `suno/bark-small` (más rápido, peor calidad).
- El notebook termina con un enlace a una noticia económica de El Mundo (25-sep-2026) como sugerencia de texto para sintetizar.

## 5. Generación de música

- **MusicGen** ("Simple and Controllable Music Generation", Meta): modelo **autoregresivo** sobre tokens de audio, condicionado por texto (y opcionalmente melodía). Las slides citan ~25k horas de música de entrenamiento. Checkpoints `facebook/musicgen-small/medium/large`. Pesos con licencia **no comercial** (dato de la ficha, no viene de clase).
- **Live Music Models** (p. ej. Magenta RealTime / Lyria RealTime de Google): arquitectura **encoder-decoder** que genera en bloques de ~2 s y permite **cambiar el estilo casi en tiempo real**.

## 6. Series temporales (otras modalidades)

- Modalidad clave en finanzas. Se entrenan/alinean como los VLM (**preentrenamiento + instruction tuning**) y sirven para **análisis y predicción**.
- **Time-LLM:** "reprograma" parches de la serie a prototipos de texto para un **LLM congelado**.
- **OneFitsAll (GPT4TS):** reutiliza un GPT-2 preentrenado, congelado salvo capas pequeñas (normalización, embeddings), para muchas tareas de series.
- Recordatorio de las slides: aunque un modelo no sea multimodal, **podemos encadenar modelos** para juntar modalidades (justo lo que hace nuestro producto).

## Receta de código (de los notebooks)

```python
import torch
from transformers import pipeline

dev = "cuda:0" if torch.cuda.is_available() else "cpu"
stt = pipeline("automatic-speech-recognition", model="openai/whisper-base",
               device=dev, chunk_length_s=30)
q = stt("pregunta.wav", generate_kwargs={"language": "spanish", "task": "transcribe"})["text"]

tts = pipeline("text-to-speech", "suno/bark-small", device=dev)  # o "suno/bark"
out = tts("Hoy el IBEX abre en verde... [laughs] bueno, casi.")
audio, sr = out["audio"], out["sampling_rate"]                    # 24 kHz

from transformers import ClapModel, AutoProcessor
clap = ClapModel.from_pretrained("laion/clap-htsat-unfused")
proc = AutoProcessor.from_pretrained("laion/clap-htsat-unfused")
inp = proc(text=["clear speech", "noise"], audio=wave48k, sampling_rate=48000,
           return_tensors="pt", padding=True)
probs = clap(**inp).logits_per_audio.softmax(dim=-1)
```

## Requisitos prácticos

Cifras orientativas (estimación, no viene de clase). De los notebooks solo constan las descargas: `whisper-base` ~290 MB
y CLAP ~615 MB.

| Modelo | GPU/VRAM | CPU | Tiempos orientativos | Alternativa API |
|---|---|---|---|---|
| Whisper base/small | <2 GB | **Sí** (mejor con `faster-whisper` int8) | Pregunta de 10 s: ~1-3 s en CPU | OpenAI Whisper/`gpt-4o-transcribe`, Deepgram |
| Whisper large-v3 | ~6-10 GB | Lento | Tiempo real o mejor en GPU | Ídem |
| CLAP | ~1 GB | Sí | <1 s | — |
| Bark | ~8-12 GB (small: menos) | Muy lento (minutos por frase) | Varios s por frase en GPU | ElevenLabs, OpenAI TTS |
| edge-tts (no visto en clase) | No | Sí (servicio online gratuito) | ~1 s por línea | — |
| MusicGen small | ~4-6 GB | Lento | ~10-30 s por clip corto en GPU | — |

## Aplicación a nuestro MVP

- **STT** → `src/briefer/providers/stt/whisper_local.py` y `whisper_api.py`, usados por `src/briefer/ingest/voice.py` y la página `app/pages/2_Preguntar.py`.
  - Decisión (alineada con `.env.example`): **Whisper API por defecto** (`BRIEFER_STT_PROVIDER=whisper_api`) y local `whisper_local` (`faster-whisper`, modelo `base` por defecto, o `small`) como alternativa sin coste, **forzando `language="es"`**. Siempre pasar la **ruta del fichero** (evita el error de frecuencia) y tener ffmpeg en el Dockerfile para el audio del navegador/Telegram (webm/ogg).
- **TTS 2 voces** → `src/briefer/providers/tts/edge_tts_provider.py` (por defecto, dos voces es-ES distintas para A y B) y premium `elevenlabs_tts.py`. Un `bark_tts.py` (modo expresivo local) **no existe**: habría que crearlo y añadir su nombre a `TTSProviderName` en `config.py`.
  - Si se usa Bark: presets fijos por locutor (p. ej. A = `v2/es_speaker_1`, B = `v2/es_speaker_6`), síntesis **línea a línea** (cada `ScriptLine` < ~13 s) y semilla fija.
  - El Guionista puede emitir marcadores (`[laughs]`, `...`) **solo si el proveedor declara soportarlos**; `media/podcast.py` debe eliminarlos para edge-tts/ElevenLabs.
- **Control de calidad automático (idea con nota):** round-trip **TTS → Whisper** para comprobar que cada línea se entiende (WER entre guion y transcripción, ver `10_iqa_metricas.md`). Y la transcripción del podcast (`media/transcript.py`) puede salir del propio guion + tiempos de `AudioSegment` (sin STT).
- **CLAP:** opcional para validar audios subidos ("¿es voz o ruido?") antes de transcribir. No prioritario.
- **Música:** una cortinilla de intro/outro; mejor un recurso libre de derechos que MusicGen (licencia no comercial).
- **Series temporales:** fuera de alcance. Solo describimos precios históricos (`PriceSnapshot.history`); **no predecimos** (MiFID II: sin recomendaciones personalizadas).
- **Riesgos:** latencia de Bark (inaceptable en demo en directo sin GPU), clonación de voces reales (no hacerlo), privacidad de la voz del usuario (RGPD: no guardar audios más de lo necesario).

## Glosario rápido

- **Sampling rate:** muestras por segundo (16 kHz Whisper, 24 kHz Bark, 48 kHz CLAP).
- **Mel-espectrograma:** representación tiempo-frecuencia en escala perceptual.
- **ASR / STT:** reconocimiento de voz, voz a texto.
- **TTS:** texto a voz.
- **Chunking:** trocear audio largo en ventanas (30 s en Whisper).
- **WER:** *Word Error Rate*, métrica de error de transcripción.
- **Speaker preset / history prompt:** voz predefinida en Bark.
- **Zero-shot:** clasificar sin entrenar, solo con descripciones de texto.
- **EnCodec:** códec neuronal que convierte audio en tokens discretos.
- **Time-LLM / OneFitsAll:** LLMs adaptados a series temporales.
