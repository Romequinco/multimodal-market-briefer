"""Voz a texto con la API de OpenAI (``whisper-1`` / ``gpt-4o-mini-transcribe``).

Carril A. Implementa ``STTProvider.transcribe(audio_path, language) -> str``.
Lo usa ``ingest.voice`` (pregunta por voz y notas de voz). Modelo: ``BRIEFER_WHISPER_API_MODEL``.
Coste aproximado en ``costs.STT_PRICES_USD_PER_MIN`` (el pipeline lo calcula con ``last_duration_s``).

Límites de la API (documentación de OpenAI): **25 MB** por fichero y formatos ``flac, mp3, mp4,
mpeg, mpga, m4a, ogg, wav, webm``. Aquí se valida antes de llamar (error claro en español, sin
gastar): fichero vacío, demasiado grande o con extensión no admitida -> ``ValueError``.

Elección del modelo (medido el 05-oct-2026 con 3 preguntas financieras sintetizadas con edge-tts:
«Inditex», «IBEX 35», «Iberdrola», «Nvidia», «S&P 500»): los dos aciertan al 100 % (WER 0), pero
``gpt-4o-mini-transcribe`` tarda ≈1,3 s frente a ≈2,5 s y cuesta la mitad (0,003 frente a
0,006 USD/min). Es el valor por defecto; ``whisper-1`` sigue siendo válido.

Silencio y alucinaciones: con un audio mudo, ``whisper-1`` se inventa frases («Más información
www…») y cualquier modelo al que se le pase un ``prompt`` lo repite tal cual. Por eso un WAV sin
voz (energía por debajo de ``SILENCE_RMS``) devuelve ``""`` sin llamar a la API (``st.audio_input``
graba WAV PCM). El ``prompt`` es opcional y solo lleva vocabulario (nombres de las empresas del
briefing, ``ingest.voice.vocabulary_hint``): sin él, «Apple» se transcribía «Yabel» con la voz
sintética. ``ingest.voice`` descarta la salida si es un eco de esa pista.
"""

from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path
from typing import Any

from briefer.config import Settings
from briefer.providers.base import STTProvider

#: Límite de la API de transcripción de OpenAI por fichero.
MAX_BYTES = 25 * 1024 * 1024
#: Extensiones admitidas por la API.
SUPPORTED_EXTS = frozenset({".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"})
#: RMS (muestras de 16 bits) por debajo del cual un WAV se considera silencio (≈ -50 dBFS).
SILENCE_RMS = 100.0
#: Tokens de audio por segundo de ``gpt-4o-*-transcribe`` (medido: 37 tokens en 3,7 s); solo
#: para estimar la duración (coste) cuando la respuesta no la trae.
AUDIO_TOKENS_PER_S = 10.0
TIMEOUT_S = 60.0


def _wav_duration(path: Path) -> float:
    """Duración de un WAV PCM leyendo la cabecera (0.0 si no se puede)."""
    try:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
            return wav.getnframes() / rate if rate else 0.0
    except Exception:  # noqa: BLE001 - no es WAV PCM: la duración saldrá de la respuesta o será 0
        return 0.0


def is_silent_wav(path: Path, threshold: float = SILENCE_RMS) -> bool:
    """``True`` si ``path`` es un WAV PCM de 16 bits sin voz (RMS < ``threshold``).

    ``False`` si no es WAV PCM de 16 bits o no se puede leer (entonces decide la API).
    """
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                return False
            frames = wav.readframes(wav.getnframes())
    except Exception:  # noqa: BLE001 - mp3/webm/ogg…: no se analiza
        return False
    samples = array("h")
    samples.frombytes(frames[: len(frames) - len(frames) % 2])
    if not samples:
        return True
    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    return rms < threshold


class WhisperAPI(STTProvider):
    """Transcripción remota con ``openai.audio.transcriptions``."""

    provider_name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.briefer_whisper_api_model
        self._client: Any = None
        #: Duración (s) del último audio transcrito, para estimar el coste (``costs``).
        self.last_duration_s: float = 0.0

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            if not self.settings.has_secret("openai_api_key"):
                raise RuntimeError("Falta OPENAI_API_KEY en .env")
            self._client = OpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),  # type: ignore[union-attr]
                timeout=TIMEOUT_S,
                max_retries=2,
            )
        return self._client

    @staticmethod
    def validate_audio(audio_path: Path) -> Path:
        """Comprueba existencia, tamaño (0 < bytes ≤ 25 MB) y formato antes de llamar a la API.

        Raises:
            FileNotFoundError: no existe. ``ValueError``: vacío, demasiado grande o formato no admitido.
        """
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"No existe el audio: {path.name}")
        size = path.stat().st_size
        if size == 0:
            raise ValueError("El audio está vacío: vuelve a grabar la pregunta")
        if size > MAX_BYTES:
            raise ValueError(
                f"El audio ocupa {size / 1_048_576:.1f} MB y el límite de la transcripción es 25 MB: "
                "graba una pregunta más corta"
            )
        if path.suffix.lower() not in SUPPORTED_EXTS:
            raise ValueError(
                f"Formato de audio no admitido ({path.suffix or 'sin extensión'}). "
                f"Usa {', '.join(sorted(e.lstrip('.') for e in SUPPORTED_EXTS))}"
            )
        return path

    def transcribe(self, audio_path: Path, language: str = "es", prompt: str | None = None) -> str:
        """Transcribe ``audio_path`` en ``language`` y devuelve el texto (espacios normalizados).

        ``prompt`` (opcional): pista de vocabulario para nombres propios (ver la cabecera).

        Devuelve ``""`` si no se reconoce voz (``ingest.voice`` lo convierte en un aviso claro).

        Raises:
            FileNotFoundError / ValueError: ver ``validate_audio``.
            openai.APIError: fallo de la API tras los reintentos del SDK.
        """
        path = self.validate_audio(audio_path)
        self.last_duration_s = _wav_duration(path)
        if is_silent_wav(path):
            self.last_duration_s = 0.0  # no se llama a la API: sin coste
            return ""
        kwargs: dict[str, Any] = {"model": self.model, "language": (language or "es")[:2]}
        if prompt:
            kwargs["prompt"] = prompt[:800]
        if self.model == "whisper-1":
            kwargs["response_format"] = "verbose_json"  # trae ``duration`` (para el coste)
        with path.open("rb") as fh:
            resp = self._get_client().audio.transcriptions.create(file=fh, **kwargs)
        duration = getattr(resp, "duration", None)
        usage = getattr(resp, "usage", None)
        seconds = getattr(usage, "seconds", None) if usage is not None else None
        details = getattr(usage, "input_token_details", None) if usage is not None else None
        audio_tokens = getattr(details, "audio_tokens", None) if details is not None else None
        from_tokens = float(audio_tokens) / AUDIO_TOKENS_PER_S if audio_tokens else None
        for value in (duration, seconds, None if self.last_duration_s else from_tokens):
            if value:
                self.last_duration_s = float(value)
                break
        text = resp if isinstance(resp, str) else getattr(resp, "text", "")
        return " ".join(str(text or "").split())
