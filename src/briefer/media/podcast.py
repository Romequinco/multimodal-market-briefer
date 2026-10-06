"""Síntesis del podcast a 2 voces: TTS por línea del guion + concatenación.

Carril C. Entrada: ``PodcastScript`` + ``TTSProvider`` + voces A/B. Salida: ``AudioAsset``
(fichero final + ``segments`` con tiempos de inicio/fin por línea, que usa
``media.transcript`` para el SRT y ``media.video`` para los subtítulos).

Decisiones:

- Las líneas se sintetizan **en paralelo** con un ``ThreadPoolExecutor`` limitado
  (``max_workers``): edge-tts es I/O (websocket) y cada hilo puede ejecutar su propio
  ``asyncio.run``. El orden del episodio se conserva siempre.
- Los tiempos de cada ``AudioSegment`` se calculan con la duración **real** de cada parte
  (no con estimaciones por palabras), más la pausa entre intervenciones.
- **Pausas variables** (v0.3.4, ``line_pauses``; por defecto, ``pause_s=None``): ~0,15 s cuando
  la intervención responde a una pregunta (la anterior acaba en «?»), ~0,30 s lo normal y
  ~0,45 s al cambiar de tema (tras la apertura o si la línea empieza por «Vamos con», «Pasamos
  a», «Por otro lado»…, ``TOPIC_CUES``). Regla determinista; ``pause_s=<float>`` la fija.
- **Diálogo en una petición** (v0.3.4): si el TTS lo admite (``tts.supports_dialogue``, Gemini
  multi-locutor), el episodio se trocea en tramos de como mucho ``DIALOGUE_MAX_LINES`` líneas y
  ``DIALOGUE_MAX_CHARS`` caracteres hablados (≈ 2 min), cada tramo se sintetiza de una vez (el
  modelo pone sus propias pausas dentro) y los tramos se unen con la pausa variable de la
  frontera. Los tiempos por línea **dentro** de un tramo son aproximados: los da el proveedor
  repartiendo la duración del tramo en proporción a la longitud hablada de cada línea.
- Concatenación: si todas las partes son WAV PCM con el mismo formato (``MockTTS``) se usa
  solo la stdlib (``wave``); en cualquier otro caso (MP3 de edge-tts, mezclas, distintas
  frecuencias) se usa el ffmpeg de ``imageio-ffmpeg`` con el filtro ``concat`` y ``apad``
  para la pausa, re-codificando todo al formato de salida. No se asume ffmpeg en el PATH.
- Cada línea pasa por ``normalize_for_speech`` (``media.speech``) **antes** del TTS: tickers,
  cifras, porcentajes, periodos y siglas se leen como lo diría un locutor. Los ``segments`` (y por
  tanto la transcripción y el SRT) conservan el texto **original** del guion.
- Volumen homogéneo: el MP3 final pasa por ``loudnorm`` de ffmpeg (EBU R128) a
  ``PODCAST_LOUDNESS_LUFS`` (-16 LUFS integrados, el estándar habitual de podcast; pico real
  <= -1,5 dBTP). edge-tts entrega las voces a unos -23 LUFS: sin normalizar, el episodio suena
  bajo en el móvil frente a otros podcasts. Medido con ``volumedetect`` por locutor.
- Ficheros temporales: ``out_dir/parts`` se borra también si la síntesis falla a medias; ffmpeg
  se lanza sin ventana de consola en Windows y con un tiempo máximo (``FFMPEG_TIMEOUT_S``).
- Transparencia (AI Act art. 50): el MP3 final lleva metadatos ID3 que lo identifican como voz
  sintética generada por IA (``AI_AUDIO_METADATA``), además del aviso hablado del cierre del guion.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from briefer.brand import BRAND_NAME
from briefer.logging_utils import error_text, get_logger
from briefer.media.speech import normalize_for_speech
from briefer.providers.base import TTSProvider
from briefer.schemas import AudioAsset, AudioSegment, PodcastScript, ScriptLine

log = get_logger("media.podcast")
T = TypeVar("T")

# Frecuencia y canales de salida cuando se re-codifica con ffmpeg (edge-tts emite 24 kHz mono).
OUTPUT_SAMPLE_RATE = 24_000
OUTPUT_MP3_BITRATE = "64k"
DEFAULT_MAX_WORKERS = 4
# Sonoridad objetivo del episodio (EBU R128 / recomendación habitual de podcast) y pico real máximo.
PODCAST_LOUDNESS_LUFS = -16.0
TRUE_PEAK_DB = -1.5
LOUDNESS_RANGE_LU = 11.0
FFMPEG_TIMEOUT_S = 300

# Pausas variables entre intervenciones (opción «B» de la cata del 05-oct-2026).
PAUSE_ANSWER_S = 0.15  # la intervención responde a una pregunta
PAUSE_NORMAL_S = 0.30
PAUSE_TOPIC_S = 0.45  # cambio de tema
#: Comienzos de intervención que anuncian un cambio de tema (minúsculas, sin signos iniciales).
TOPIC_CUES: tuple[str, ...] = (
    "vamos con", "vamos ahora", "pasamos a", "pasemos a", "y en ", "por otro lado", "cambiamos",
    "cambiando de", "en cuanto a", "y ahora", "ahora vamos", "otro tema", "mientras tanto",
    "al otro lado", "para terminar", "para cerrar", "y antes de despedirnos",
)
_LEADING_PUNCT = "¿¡«\"'“‘—–-…. "

# Diálogo en una petición (TTS con ``supports_dialogue``): tamaño máximo de cada tramo.
DIALOGUE_MAX_LINES = 12
DIALOGUE_MAX_CHARS = 2000  # caracteres hablados (≈ 2 min de audio)
DIALOGUE_MAX_WORKERS = 3

# Metadatos del audio final (AI Act art. 50: contenido sintético marcado de forma detectable).
SYNTHETIC_VOICE_NOTICE = "Voces sintéticas generadas por IA. No constituye asesoramiento financiero."
AI_AUDIO_METADATA: dict[str, str] = {
    "artist": f"{BRAND_NAME} (voces sintéticas IA)",
    "album": BRAND_NAME,
    "genre": "Podcast",
    "comment": SYNTHETIC_VOICE_NOTICE,
    "copyright": "Contenido generado por IA",
}


# ── ffmpeg ─────────────────────────────────────────────────────────────────────────


def ffmpeg_exe() -> str:
    """Ruta al ejecutable de ffmpeg (el de ``imageio-ffmpeg``; si no, el del PATH)."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - depende del entorno
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        raise RuntimeError(
            "No se encontró ffmpeg: instala imageio-ffmpeg (requirements.txt) o ffmpeg en el PATH."
        ) from None


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta ffmpeg sin ventana ni stdin; lanza ``RuntimeError`` con el final del log si falla."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", *args]
    # En Windows, sin ventana de consola que parpadee al lanzarlo desde Streamlit.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=FFMPEG_TIMEOUT_S, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg no terminó en {FFMPEG_TIMEOUT_S} s") from exc
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg falló (código {proc.returncode}):\n{tail}")
    return proc


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _hms_to_s(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


# ── Duración ───────────────────────────────────────────────────────────────────────


def _wav_params(path: Path) -> tuple[int, int, int, str] | None:
    """(canales, ancho de muestra, frecuencia, compresión) si es un WAV PCM legible, si no ``None``."""
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()
    except (wave.Error, EOFError, OSError, RuntimeError):  # RuntimeError: bloque de tamaño imposible
        return None


def audio_duration_s(path: Path) -> float:
    """Duración en segundos de un fichero de audio.

    - WAV PCM: exacta con ``wave`` (frames / frecuencia), sin dependencias.
    - Resto (MP3 de edge-tts, etc.): ffmpeg decodifica el fichero entero (``-f null``) y se lee
      el último ``time=``; es exacto también con MP3 VBR, donde la cabecera solo da una estimación.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() / float(wav.getframerate())
        except (wave.Error, EOFError, RuntimeError):
            pass  # WAV no PCM (p. ej. float) o dañado: se mide con ffmpeg
    proc = _run_ffmpeg(["-i", str(path), "-vn", "-f", "null", "-"])
    times = _TIME_RE.findall(proc.stderr)
    if times:
        return _hms_to_s(*times[-1])
    match = _DURATION_RE.search(proc.stderr)
    if match:
        return _hms_to_s(*match.groups())
    raise RuntimeError(f"No se pudo medir la duración de {path.name}")


# ── Concatenación ──────────────────────────────────────────────────────────────────


def _concat_wav_stdlib(paths: list[Path], out_path: Path, gaps: list[float]) -> Path:
    """Concatena WAV PCM con el mismo formato intercalando silencio (solo stdlib).

    ``gaps[i]`` es el silencio tras la parte ``i`` (``len(gaps) == len(paths) - 1``).
    """
    with wave.open(str(paths[0]), "rb") as first:
        params = first.getparams()
    frame_bytes = params.nchannels * params.sampwidth
    tmp = out_path.with_name(f"{out_path.stem}.{os.getpid()}.{threading.get_ident()}.tmp{out_path.suffix}")
    try:
        with wave.open(str(tmp), "wb") as out:
            out.setnchannels(params.nchannels)
            out.setsampwidth(params.sampwidth)
            out.setframerate(params.framerate)
            for i, p in enumerate(paths):
                with wave.open(str(p), "rb") as part:
                    out.writeframes(part.readframes(part.getnframes()))
                if i < len(paths) - 1:
                    silence = b"\x00" * (int(round(gaps[i] * params.framerate)) * frame_bytes)
                    if silence:
                        out.writeframes(silence)
        tmp.replace(out_path)
    finally:
        tmp.unlink(missing_ok=True)
    return out_path


def _metadata_args(metadata: dict[str, str] | None) -> list[str]:
    """Argumentos ``-metadata clave=valor`` de ffmpeg (ID3v2.3 en MP3)."""
    args: list[str] = []
    for key, value in (metadata or {}).items():
        if value:
            args += ["-metadata", f"{key}={value}"]
    return args


def tag_audio(path: Path, metadata: dict[str, str] | None = None) -> Path:
    """Escribe etiquetas (por defecto ``AI_AUDIO_METADATA``) en un MP3 sin recodificar (``-c copy``).

    Para audios sueltos como la respuesta del Q&A (décimas de segundo). Los WAV (``MockTTS``) se
    dejan tal cual. Si ffmpeg falla, se registra y se devuelve el fichero sin etiquetas.
    """
    if path.suffix.lower() != ".mp3":
        return path
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tag.mp3")
    try:
        _run_ffmpeg(["-y", "-i", str(path), "-map", "0:a", "-c", "copy", "-id3v2_version", "3",
                     *_metadata_args(AI_AUDIO_METADATA if metadata is None else metadata), str(tmp)])
        tmp.replace(path)
    except Exception as exc:  # las etiquetas son un extra: nunca rompen la respuesta
        log.warning("No se pudieron etiquetar los metadatos de %s: %s", path.name, error_text(exc))
    finally:
        tmp.unlink(missing_ok=True)
    return path


def loudnorm_filter(lufs: float, true_peak_db: float = TRUE_PEAK_DB, lra: float = LOUDNESS_RANGE_LU) -> str:
    """Filtro ``loudnorm`` de ffmpeg (una pasada, EBU R128) seguido del remuestreo de salida.

    ``loudnorm`` trabaja internamente a 192 kHz: se vuelve a ``OUTPUT_SAMPLE_RATE`` al final.
    """
    return (f"loudnorm=I={lufs:.1f}:TP={true_peak_db:.1f}:LRA={lra:.1f},"
            f"aresample={OUTPUT_SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=mono")


def _concat_ffmpeg(
    paths: list[Path],
    out_path: Path,
    gaps: list[float],
    metadata: dict[str, str] | None = None,
    loudness_lufs: float | None = None,
) -> Path:
    """Concatena cualquier mezcla de formatos con ffmpeg re-codificando a ``out_path``.

    Cada entrada se normaliza (mono, ``OUTPUT_SAMPLE_RATE``, s16) y se le añade ``gaps[i]`` de
    silencio al final (``apad``) salvo a la última; después, filtro ``concat``. El grafo se pasa
    por fichero para no superar el límite de longitud de la línea de comandos en Windows.
    """
    n = len(paths)
    chains = []
    for i in range(n):
        chain = f"[{i}:a]aresample={OUTPUT_SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=mono"
        if i < n - 1 and gaps[i] > 0:
            chain += f",apad=pad_dur={gaps[i]:.3f}"
        chains.append(chain + f"[a{i}]")
    joined = "".join(f"[a{i}]" for i in range(n))
    if loudness_lufs is None:
        graph = ";".join(chains) + ";" + joined + f"concat=n={n}:v=0:a=1[out]"
    else:
        graph = (";".join(chains) + ";" + joined + f"concat=n={n}:v=0:a=1[cat];"
                 + f"[cat]{loudnorm_filter(loudness_lufs)}[out]")

    ext = out_path.suffix.lower()
    if ext == ".mp3":
        codec = ["-c:a", "libmp3lame", "-b:a", OUTPUT_MP3_BITRATE, "-id3v2_version", "3"]
    elif ext == ".wav":
        codec = ["-c:a", "pcm_s16le"]
    else:
        codec = []  # que ffmpeg elija por extensión (.m4a, .ogg…)

    unique = f"{os.getpid()}.{threading.get_ident()}"
    tmp = out_path.with_name(f"{out_path.stem}.{unique}.tmp{out_path.suffix}")
    graph_file = out_path.with_name(f"{out_path.stem}.{unique}.filtergraph.txt")
    graph_file.write_text(graph, encoding="utf-8")
    try:
        inputs: list[str] = []
        for p in paths:
            inputs += ["-i", str(p)]
        _run_ffmpeg(
            ["-y", *inputs, "-filter_complex_script", str(graph_file), "-map", "[out]", "-vn", *codec,
             *_metadata_args(metadata), str(tmp)]
        )
        tmp.replace(out_path)
    finally:
        graph_file.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return out_path


def concat_audio(
    paths: list[Path],
    out_path: Path,
    pause_s: float = 0.35,
    *,
    pauses: list[float] | None = None,
    metadata: dict[str, str] | None = None,
    loudness_lufs: float | None = None,
) -> Path:
    """Concatena audios con una pausa corta entre intervenciones; devuelve ``out_path``.

    Elige automáticamente la vía: stdlib si todo es WAV PCM homogéneo y la salida es ``.wav``;
    ffmpeg en el resto de casos (MP3, mezclas de formatos o frecuencias distintas).
    ``pauses`` (v0.3.4) da una pausa distinta tras cada parte (``len(paths) - 1`` valores, p. ej.
    ``line_pauses``); si es ``None``, todas valen ``pause_s``.
    ``metadata`` (p. ej. ``AI_AUDIO_METADATA``) se escribe como etiquetas del fichero cuando se
    usa ffmpeg (ID3 en MP3); la vía WAV de la stdlib no admite etiquetas.
    ``loudness_lufs`` (p. ej. ``PODCAST_LOUDNESS_LUFS``) normaliza la sonoridad del resultado con
    ``loudnorm``; fuerza la vía ffmpeg (``None`` = sin normalizar).
    """
    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("concat_audio: la lista de audios está vacía")
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(p)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if pauses is None:
        gaps = [max(0.0, float(pause_s))] * (len(paths) - 1)
    else:
        if len(pauses) != len(paths) - 1:
            raise ValueError(f"concat_audio: {len(pauses)} pausas para {len(paths)} audios")
        gaps = [max(0.0, float(p)) for p in pauses]

    if out_path.suffix.lower() == ".wav" and loudness_lufs is None:
        params = [_wav_params(p) for p in paths]
        if all(params) and len(set(params)) == 1 and params[0][3] == "NONE":  # type: ignore[index]
            return _concat_wav_stdlib(paths, out_path, gaps)
    return _concat_ffmpeg(paths, out_path, gaps, metadata, loudness_lufs)


# ── Pausas y tramos de diálogo ─────────────────────────────────────────────────────


def _starts_with_topic_cue(text: str) -> bool:
    head = text.strip().lstrip(_LEADING_PUNCT).casefold()
    return any(head.startswith(cue) for cue in TOPIC_CUES)


def pause_between(prev: ScriptLine, nxt: ScriptLine, *, after_opening: bool = False) -> float:
    """Pausa (s) entre ``prev`` y ``nxt``: respuesta (``PAUSE_ANSWER_S``) si ``prev`` acaba en
    «?»; cambio de tema (``PAUSE_TOPIC_S``) tras la apertura o si ``nxt`` empieza por una de
    ``TOPIC_CUES``; si no, ``PAUSE_NORMAL_S``. La pregunta manda sobre el cambio de tema."""
    if prev.text.rstrip().rstrip("»\"'”’ ").endswith("?"):
        return PAUSE_ANSWER_S
    if after_opening or _starts_with_topic_cue(nxt.text):
        return PAUSE_TOPIC_S
    return PAUSE_NORMAL_S


def line_pauses(lines: list[ScriptLine]) -> list[float]:
    """Pausas variables tras cada intervención salvo la última (``len(lines) - 1`` valores)."""
    return [
        pause_between(lines[i], lines[i + 1], after_opening=i == 0) for i in range(len(lines) - 1)
    ]


def chunk_dialogue(
    texts: list[str], max_lines: int = DIALOGUE_MAX_LINES, max_chars: int = DIALOGUE_MAX_CHARS
) -> list[tuple[int, int]]:
    """Trocea las intervenciones en tramos ``[(inicio, fin)]`` (fin exclusivo) de como mucho
    ``max_lines`` líneas y ``max_chars`` caracteres; una línea más larga que ``max_chars`` va
    sola en su tramo. Codicioso y determinista; conserva el orden."""
    chunks: list[tuple[int, int]] = []
    start, chars = 0, 0
    for i, text in enumerate(texts):
        size = len(text)
        if i > start and (i - start >= max_lines or chars + size > max_chars):
            chunks.append((start, i))
            start, chars = i, 0
        chars += size
    if texts:
        chunks.append((start, len(texts)))
    return chunks


# ── Podcast ────────────────────────────────────────────────────────────────────────


class PodcastAborted(RuntimeError):
    """Otra línea del episodio ya falló sin remedio: esta no se sintetiza (falla rápido)."""


def _synthesize_with_retry(
    tts: TTSProvider, text: str, voice: str, out_path: Path, retries: int,
    abort: threading.Event | None = None,
) -> Path:
    """Llama a ``tts.synthesize`` con reintentos y espera creciente (fallos de red de edge-tts).

    Si ``abort`` se activa (otra línea agotó sus reintentos), deja de intentarlo: el episodio ya no
    se puede completar y el pipeline debe pasar cuanto antes al sustituto.
    """
    for attempt in range(retries + 1):
        if abort is not None and abort.is_set():
            raise PodcastAborted("síntesis cancelada: otra intervención falló")
        try:
            written = Path(tts.synthesize(text, voice, out_path))
            if not written.exists() or written.stat().st_size == 0:
                raise RuntimeError(f"El TTS no escribió audio en {written}")
            return written
        except Exception as exc:
            if attempt >= retries:
                raise
            log.warning("TTS falló (%s); reintento %d/%d", exc, attempt + 1, retries)
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("inalcanzable")


def _synthesize_dialogue_with_retry(
    tts: TTSProvider, items: list[tuple[str, str]], out_path: Path, retries: int,
    abort: threading.Event | None = None,
) -> tuple[Path, float, list[float]]:
    """Llama a ``tts.synthesize_dialogue`` con reintentos (mismo criterio que ``_synthesize_with_retry``).

    Devuelve ``(ruta, duración medida, duraciones por línea)``; estas se reescalan para que sumen
    la duración **medida** del tramo (el proveedor las estima).
    """
    for attempt in range(retries + 1):
        if abort is not None and abort.is_set():
            raise PodcastAborted("síntesis cancelada: otro tramo falló")
        try:
            written, durations = tts.synthesize_dialogue(items, out_path)
            written = Path(written)
            if not written.exists() or written.stat().st_size == 0:
                raise RuntimeError(f"El TTS no escribió audio en {written}")
            if len(durations) != len(items):
                raise RuntimeError(f"El TTS devolvió {len(durations)} duraciones para {len(items)} líneas")
            measured = audio_duration_s(written)
            total = sum(durations)
            if total > 0:
                scaled = [d * measured / total for d in durations]
            else:
                scaled = [measured / len(items)] * len(items)
            return written, measured, scaled
        except Exception as exc:
            if attempt >= retries:
                raise
            log.warning("TTS (diálogo) falló (%s); reintento %d/%d", exc, attempt + 1, retries)
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("inalcanzable")


def _run_jobs(n: int, job: Callable[[int, threading.Event], T], workers: int) -> list[T]:
    """Ejecuta ``job(i, abort)`` para ``i`` en ``0..n-1`` con hasta ``workers`` hilos, en orden.

    Si un trabajo falla sin remedio, activa ``abort`` (los demás dejan de reintentar), no se
    esperan los pendientes y se propaga la causa real, no la cancelación (``PodcastAborted``).
    """
    abort = threading.Event()
    first_error: dict[str, BaseException] = {}

    def _guarded(i: int) -> T:
        try:
            return job(i, abort)
        except Exception as exc:
            if not isinstance(exc, PodcastAborted):
                first_error.setdefault("exc", exc)
            abort.set()
            raise

    try:
        workers = max(1, min(int(workers), n))
        if workers == 1:
            return [_guarded(i) for i in range(n)]
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tts")
        try:
            return list(pool.map(_guarded, range(n)))  # map conserva el orden
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    except PodcastAborted:
        if "exc" in first_error:
            raise first_error["exc"] from None
        raise


def synthesize_podcast(
    script: PodcastScript,
    tts: TTSProvider,
    out_dir: Path,
    voice_a: str,
    voice_b: str,
    pause_s: float | None = None,
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    retries: int = 2,
    keep_parts: bool = False,
    normalize: bool = True,
    metadata: dict[str, str] | None = None,
    loudness_lufs: float | None = PODCAST_LOUDNESS_LUFS,
) -> AudioAsset:
    """Genera el audio completo del episodio.

    Args:
        script: guion A/B (las líneas vacías se omiten).
        tts: proveedor de voz (``MockTTS``, ``EdgeTTS``, ``GeminiTTS``…); se usa la ruta que
            devuelve. Si ``tts.supports_dialogue``, se sintetiza por tramos de diálogo.
        out_dir: carpeta del briefing; el resultado es ``out_dir/podcast<ext>`` con la
            extensión del proveedor (``.wav`` mock, ``.mp3`` edge-tts y Gemini).
        voice_a, voice_b: voces de los locutores A y B (las de Gemini salen de su configuración).
        pause_s: silencio entre intervenciones; ``None`` (por defecto, v0.3.4) = pausas variables
            (``line_pauses``).
        max_workers: líneas (o tramos de diálogo, hasta ``DIALOGUE_MAX_WORKERS``) en paralelo.
        retries: reintentos por línea (o tramo) ante errores del TTS.
        keep_parts: conservar ``out_dir/parts`` (útil para depurar); por defecto se borra.
        normalize: pasar cada línea por ``normalize_for_speech`` antes del TTS (los segmentos
            guardan siempre el texto original).
        metadata: etiquetas del fichero final; por defecto ``AI_AUDIO_METADATA`` + el título.
        loudness_lufs: sonoridad objetivo del episodio (``loudnorm``) cuando la salida no es WAV;
            ``None`` la desactiva. Con ``MockTTS`` (WAV de silencio) no se aplica.
    """
    lines = [line for line in script.lines if line.text.strip()]
    if not lines:
        raise ValueError("synthesize_podcast: el guion no tiene líneas con texto")
    out_dir = Path(out_dir)
    parts_dir = out_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    gaps = line_pauses(lines) if pause_s is None else [max(0.0, float(pause_s))] * (len(lines) - 1)
    texts = [line.text.strip() for line in lines]
    if normalize:
        texts = [normalize_for_speech(t) or t for t in texts]
    try:
        if getattr(tts, "supports_dialogue", False):
            parts, part_gaps, durations, seg_gaps = _dialogue_parts(
                lines, texts, gaps, tts, parts_dir, max_workers, retries
            )
        else:
            parts, durations = _line_parts(lines, texts, tts, parts_dir, voice_a, voice_b, max_workers, retries)
            part_gaps = seg_gaps = gaps
        segments = _segments(lines, durations, seg_gaps)
        return _assemble(script, lines, segments, parts, part_gaps, out_dir, tts, metadata, loudness_lufs)
    finally:
        # También si una línea falla tras sus reintentos: no dejar partes huérfanas en disco.
        if not keep_parts:
            shutil.rmtree(parts_dir, ignore_errors=True)


def _line_parts(
    lines: list[ScriptLine], texts: list[str], tts: TTSProvider, parts_dir: Path,
    voice_a: str, voice_b: str, max_workers: int, retries: int,
) -> tuple[list[Path], list[float]]:
    """Una parte por intervención: ``(partes, duración de cada línea)``."""
    voices = {"A": voice_a, "B": voice_b}

    def _job(i: int, abort: threading.Event) -> tuple[Path, float]:
        """Sintetiza la línea ``i`` y mide su duración (en el mismo hilo: ffmpeg también va en paralelo)."""
        line = lines[i]
        target = parts_dir / f"{i:03d}_{line.speaker}{tts.audio_extension}"
        written = _synthesize_with_retry(tts, texts[i], voices[line.speaker], target, retries, abort)
        return written, audio_duration_s(written)

    results = _run_jobs(len(lines), _job, max_workers)
    return [p for p, _ in results], [d for _, d in results]


def _dialogue_parts(
    lines: list[ScriptLine], texts: list[str], gaps: list[float], tts: TTSProvider, parts_dir: Path,
    max_workers: int, retries: int,
) -> tuple[list[Path], list[float], list[float], list[float]]:
    """Una parte por tramo de diálogo (``chunk_dialogue``): ``(partes, pausas entre tramos,
    duración aproximada de cada línea, silencio añadido tras cada línea)``. Las pausas solo se
    añaden entre tramos (dentro, las pone el modelo)."""
    chunks = chunk_dialogue(texts, DIALOGUE_MAX_LINES, DIALOGUE_MAX_CHARS)  # leídos al llamar (tests)

    def _job(k: int, abort: threading.Event) -> tuple[Path, float, list[float]]:
        start, end = chunks[k]
        items: list[tuple[str, str]] = [(lines[i].speaker, texts[i]) for i in range(start, end)]
        target = parts_dir / f"tramo_{k:03d}{tts.audio_extension}"
        return _synthesize_dialogue_with_retry(tts, items, target, retries, abort)

    results = _run_jobs(len(chunks), _job, min(int(max_workers), DIALOGUE_MAX_WORKERS))
    log.info("Podcast por diálogo: %d líneas en %d tramos", len(lines), len(chunks))
    durations = [d for _, _, per_line in results for d in per_line]
    ends = {end - 1 for _, end in chunks[:-1]}
    part_gaps = [gaps[end - 1] for _, end in chunks[:-1]]
    seg_gaps = [gaps[i] if i in ends else 0.0 for i in range(len(lines) - 1)]
    return [p for p, _, _ in results], part_gaps, durations, seg_gaps


def _segments(lines: list[ScriptLine], durations: list[float], seg_gaps: list[float]) -> list[AudioSegment]:
    """Tiempos de cada intervención en el episodio final: cada línea empieza donde acaba la
    anterior más ``seg_gaps[i]`` (silencio añadido tras la línea ``i``; 0 dentro de un tramo de
    diálogo, cuya pausa interna ya está en el audio)."""
    segments: list[AudioSegment] = []
    cursor = 0.0
    for i, (line, dur) in enumerate(zip(lines, durations, strict=True)):
        start, end = cursor, cursor + dur
        segments.append(AudioSegment(speaker=line.speaker, text=line.text.strip(), start_s=round(start, 3),
                                     end_s=round(end, 3)))
        cursor = end + (seg_gaps[i] if i < len(lines) - 1 else 0.0)
    return segments


def _assemble(
    script: PodcastScript,
    lines: list[ScriptLine],
    segments: list[AudioSegment],
    parts: list[Path],
    part_gaps: list[float],
    out_dir: Path,
    tts: TTSProvider,
    metadata: dict[str, str] | None,
    loudness_lufs: float | None,
) -> AudioAsset:
    """Concatena las partes en el episodio (con ``loudnorm`` e ID3 si no es WAV)."""
    ext = getattr(tts, "podcast_extension", None) or parts[0].suffix or tts.audio_extension
    tags = dict(AI_AUDIO_METADATA if metadata is None else metadata)
    if metadata is None and script.title:
        tags["title"] = script.title
    loud = loudness_lufs if ext.lower() != ".wav" else None  # MockTTS: silencio, nada que normalizar
    final = concat_audio(parts, out_dir / f"podcast{ext}", pauses=part_gaps, metadata=tags, loudness_lufs=loud)
    try:
        total = audio_duration_s(final)
    except Exception:  # medir es secundario: usar la suma teórica
        total = segments[-1].end_s
    log.info("Podcast: %d líneas, %.1f s -> %s", len(lines), total, final.name)
    return AudioAsset(path=final, duration_s=round(total, 3), segments=segments)


__all__ = [
    "AI_AUDIO_METADATA",
    "tag_audio",
    "DIALOGUE_MAX_CHARS",
    "DIALOGUE_MAX_LINES",
    "PAUSE_ANSWER_S",
    "PAUSE_NORMAL_S",
    "PAUSE_TOPIC_S",
    "PODCAST_LOUDNESS_LUFS",
    "TOPIC_CUES",
    "loudnorm_filter",
    "SYNTHETIC_VOICE_NOTICE",
    "audio_duration_s",
    "chunk_dialogue",
    "concat_audio",
    "ffmpeg_exe",
    "line_pauses",
    "normalize_for_speech",
    "pause_between",
    "synthesize_podcast",
]
