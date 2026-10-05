"""Texto a voz con **Gemini TTS multi-locutor** (``BRIEFER_TTS_PROVIDER=gemini``, de pago).

Carril C. Opción «D» de la cata a ciegas del 05-oct-2026: la más natural, para la demo y el
pregenerado. El valor por defecto (gratis) sigue siendo edge-tts (opción «B»).

- Modelo ``BRIEFER_GEMINI_TTS_MODEL`` (``gemini-3.8-flash-tts``), idioma ``es-ES``; voces
  precompuestas ``BRIEFER_GEMINI_VOICE_A`` = «Puck» (Toro) y ``BRIEFER_GEMINI_VOICE_B`` = «Kore» (Osa).
- **Diálogo en una petición** (``synthesize_dialogue``): cada intervención es una ``Part`` con
  ``speech_metadata`` (locutor y estilo de locución); el modelo encadena turnos y pausas con
  naturalidad, que es lo que lo hace sonar a conversación y no a lectura. ``media.podcast``
  trocea el episodio en tramos (``podcast.DIALOGUE_MAX_LINES`` / ``DIALOGUE_MAX_CHARS``).
- La respuesta es PCM 16 bits mono a 24 kHz (``inline_data``): se envuelve en un WAV. El
  episodio final pasa a MP3 con ``loudnorm`` e ID3 en ``media.podcast`` (``podcast_extension``).
- **Tiempos por línea aproximados**: Gemini no devuelve marcas de tiempo, así que la duración
  del tramo se reparte en proporción a la longitud hablada de cada línea
  (``proportional_durations``). Sirve para el SRT y la transcripción, no para un karaoke exacto.
- ``last_usage`` acumula ``prompt_token_count`` / ``candidates_token_count`` (tokens de audio)
  de todas las llamadas (seguro entre hilos) para estimar el coste en ``costs.py``.
- Reintentos del SDK ante 408/429/5xx (``HttpRetryOptions``); un audio vacío o demasiado corto
  para el texto se trata como error (``media.podcast`` reintenta el tramo y el pipeline cae a
  edge-tts si no hay manera).
"""

from __future__ import annotations

import os
import re
import threading
import wave
from pathlib import Path
from typing import Any

from briefer.config import Settings
from briefer.logging_utils import get_logger
from briefer.providers.base import TTSProvider

log = get_logger("providers.tts.gemini")

TIMEOUT_MS = 180_000
RETRY_ATTEMPTS = 3  # 1 intento + 2 reintentos del SDK
RETRY_STATUS = [408, 429, 500, 502, 503, 504]
LANGUAGE_CODE = "es-ES"
PCM_SAMPLE_RATE = 24_000
PCM_SAMPLE_WIDTH = 2  # 16 bits
#: Estilos de locución usados en la cata (Toro = A, Osa = B).
STYLE_A = (
    "presentador de radio nocturna en español de España, cercano, energía optimista, "
    "ritmo ágil, conversando, no leyendo"
)
STYLE_B = (
    "presentadora de radio nocturna en español de España, serena y reflexiva, cercana, "
    "ritmo natural, conversando, no leyendo"
)
#: Un tramo con menos de esta fracción de la duración esperada (por palabras) se da por cortado.
MIN_DURATION_RATIO = 0.35
#: Ritmo de referencia para esa comprobación (palabras habladas por minuto, holgado).
REFERENCE_WPM = 150

_RATE_RE = re.compile(r"rate=(\d+)")
_WORD_CHARS = re.compile(r"\w", re.UNICODE)


def spoken_weight(text: str) -> int:
    """Longitud hablada de ``text`` para repartir tiempos: letras y dígitos (mínimo 1)."""
    return max(1, len(_WORD_CHARS.findall(text or "")))


def proportional_durations(texts: list[str], total_s: float) -> list[float]:
    """Reparte ``total_s`` entre ``texts`` en proporción a su ``spoken_weight`` (aproximado)."""
    if not texts:
        return []
    weights = [spoken_weight(t) for t in texts]
    total_w = sum(weights)
    return [total_s * w / total_w for w in weights]


def pcm_to_wav(pcm: bytes, out_path: Path, sample_rate: int = PCM_SAMPLE_RATE) -> Path:
    """Escribe PCM s16le mono en un WAV (escritura atómica)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f"{out_path.stem}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        with wave.open(str(tmp), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(PCM_SAMPLE_WIDTH)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        os.replace(tmp, out_path)
    finally:
        tmp.unlink(missing_ok=True)
    return out_path


def _sample_rate(mime_type: str | None) -> int:
    match = _RATE_RE.search(mime_type or "")
    return int(match.group(1)) if match else PCM_SAMPLE_RATE


class GeminiTTS(TTSProvider):
    """Cliente de Gemini TTS (``from google import genai``), multi-locutor."""

    provider_name = "gemini"
    audio_extension = ".wav"
    podcast_extension = ".mp3"
    supports_dialogue = True

    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.model = settings.briefer_gemini_tts_model
        self.voices = {"A": settings.briefer_gemini_voice_a, "B": settings.briefer_gemini_voice_b}
        self.speakers = {"A": settings.briefer_speaker_a_name, "B": settings.briefer_speaker_b_name}
        self.styles = {"A": STYLE_A, "B": STYLE_B}
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self.calls = 0
        self._lock = threading.Lock()
        self._client = client

    # ── Cliente y respuesta ──────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            from google.genai import types

            if not self.settings.has_secret("gemini_api_key"):
                raise RuntimeError("Falta GEMINI_API_KEY en .env")
            self._client = genai.Client(
                api_key=self.settings.gemini_api_key.get_secret_value(),  # type: ignore[union-attr]
                http_options=types.HttpOptions(
                    timeout=TIMEOUT_MS,
                    retry_options=types.HttpRetryOptions(
                        attempts=RETRY_ATTEMPTS, http_status_codes=RETRY_STATUS
                    ),
                ),
            )
        return self._client

    def _record_usage(self, resp: Any) -> None:
        meta = getattr(resp, "usage_metadata", None)
        with self._lock:
            self.calls += 1
            if meta is None:
                return
            self.last_usage["input_tokens"] += int(getattr(meta, "prompt_token_count", 0) or 0)
            self.last_usage["output_tokens"] += int(getattr(meta, "candidates_token_count", 0) or 0)

    @staticmethod
    def _audio(resp: Any) -> tuple[bytes, int]:
        """PCM y frecuencia de la primera parte con audio de la respuesta."""
        for cand in getattr(resp, "candidates", None) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None)
                if data:
                    return bytes(data), _sample_rate(getattr(inline, "mime_type", None))
        raise RuntimeError("Gemini TTS no devolvió audio")

    def _generate(self, contents: Any, speech_config: Any, texts: list[str], out_path: Path) -> Path:
        from google.genai import types

        resp = self._get_client().models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=speech_config,
                # Sin herramientas: se desactiva el «automatic function calling» (y su aviso en log).
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        self._record_usage(resp)
        pcm, rate = self._audio(resp)
        out = pcm_to_wav(pcm, Path(out_path).with_suffix(self.audio_extension), rate)
        duration = len(pcm) / (PCM_SAMPLE_WIDTH * rate)
        words = sum(len(t.split()) for t in texts)
        expected = words / REFERENCE_WPM * 60
        if duration < MIN_DURATION_RATIO * expected:
            out.unlink(missing_ok=True)
            raise RuntimeError(
                f"Gemini TTS devolvió un audio demasiado corto ({duration:.1f} s para {words} palabras)"
            )
        return out

    # ── API ──────────────────────────────────────────────────────────────────────

    def _speaker_key(self, voice: str) -> str:
        """Locutor ``"A"``/``"B"`` para una voz de ``synthesize`` (nombre edge-tts o de Gemini)."""
        v = (voice or "").strip()
        if v in ("A", self.settings.briefer_voice_a, self.voices["A"]):
            return "A"
        return "B"  # voz B (Osa) por defecto, como la respuesta del Q&A

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        """Una sola voz (configuración de un locutor). El podcast usa ``synthesize_dialogue``."""
        if not text or not text.strip():
            raise ValueError("GeminiTTS.synthesize: el texto está vacío")
        from google.genai import types

        key = self._speaker_key(voice)
        clean = " ".join(text.split())
        prompt = f"Lee con este estilo ({self.styles[key]}): {clean}"
        speech_config = types.SpeechConfig(
            language_code=LANGUAGE_CODE,
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voices[key])
            ),
        )
        return self._generate(prompt, speech_config, [clean], out_path)

    def synthesize_dialogue(
        self, lines: list[tuple[str, str]], out_path: Path
    ) -> tuple[Path, list[float]]:
        """Tramo de diálogo en una petición multi-locutor; duraciones por línea aproximadas."""
        items = [(spk, " ".join(text.split())) for spk, text in lines if text and text.strip()]
        if not items:
            raise ValueError("GeminiTTS.synthesize_dialogue: no hay líneas con texto")
        unknown = {spk for spk, _ in items} - set(self.voices)
        if unknown:
            raise ValueError(f"GeminiTTS.synthesize_dialogue: locutor desconocido {sorted(unknown)}")
        from google.genai import types

        contents = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=text,
                    speech_metadata=types.SpeechMetadata(speaker=self.speakers[spk], style=self.styles[spk]),
                )
                for spk, text in items
            ],
        )
        speech_config = types.SpeechConfig(
            language_code=LANGUAGE_CODE,
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    types.SpeakerVoiceConfig(
                        speaker=self.speakers[key],
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voices[key])
                        ),
                    )
                    for key in ("A", "B")
                ]
            ),
        )
        texts = [text for _, text in items]
        out = self._generate(contents, speech_config, texts, out_path)
        with wave.open(str(out), "rb") as wav:
            total = wav.getnframes() / float(wav.getframerate())
        return out, proportional_durations(texts, total)


__all__ = [
    "GeminiTTS",
    "LANGUAGE_CODE",
    "STYLE_A",
    "STYLE_B",
    "pcm_to_wav",
    "proportional_durations",
    "spoken_weight",
]
