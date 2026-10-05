"""Texto a voz con ``edge-tts`` (voces neuronales de Microsoft Edge, sin clave).

Carril C. Implementa ``TTSProvider.synthesize(text, voice, out_path) -> Path`` (MP3).
Voces por defecto: ``BRIEFER_VOICE_A=es-ES-AlvaroNeural`` y ``BRIEFER_VOICE_B=es-ES-ElviraNeural``.
Lo usa ``media.podcast`` (una llamada por línea del guion) y el Q&A hablado.

Decisiones:

- **Un ``asyncio.run`` por llamada.** ``edge_tts.Communicate`` es asíncrono; cada llamada crea y
  cierra su propio bucle de eventos, así que es seguro llamarlo desde varios hilos a la vez
  (``synthesize_podcast`` usa un ``ThreadPoolExecutor``). Si el hilo que llama ya tiene un bucle
  en marcha (p. ej. un notebook), la síntesis se ejecuta en un hilo auxiliar.
- **Reintentos con espera creciente** solo ante errores de red / del servicio (websocket cerrado,
  ``NoAudioReceived``, *timeouts*, 429/503): edge-tts es un servicio no oficial y sin SLA que a
  veces corta conexiones si hay mucha concurrencia. Los errores de uso (texto vacío, voz o
  ``rate`` mal formados) no se reintentan.
- **Escritura atómica**: se sintetiza en un ``.part`` y se renombra; nunca queda un MP3 a medias.
- El escape XML y el troceo de textos largos (> 4 KB) los hace la propia librería.
- En producción se usaría **Azure AI Speech** (mismas voces es-ES, servicio oficial con SLA).
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from pathlib import Path

from briefer.config import Settings
from briefer.logging_utils import get_logger
from briefer.providers.base import TTSProvider

log = get_logger("providers.tts.edge")

# Versión probada (fijada en requirements.txt). Si edge-tts cambia el protocolo, actualizar ambas.
TESTED_EDGE_TTS_VERSION = "7.2.8"

_RATE_RE = re.compile(r"^[+-]\d{1,3}%$")
_PITCH_RE = re.compile(r"^[+-]\d{1,3}Hz$")


def _check_rate(value: str) -> str:
    if not _RATE_RE.match(value):
        raise ValueError(f"rate de edge-tts no válido: {value!r} (formato '+0%', '-10%'…)")
    return value


def _check_pitch(value: str) -> str:
    if not _PITCH_RE.match(value):
        raise ValueError(f"pitch de edge-tts no válido: {value!r} (formato '+0Hz', '-5Hz'…)")
    return value


def _transient_errors() -> tuple[type[BaseException], ...]:
    """Excepciones que merecen reintento (red o servicio); se importan de forma perezosa."""
    errors: list[type[BaseException]] = [asyncio.TimeoutError, TimeoutError, ConnectionError, OSError]
    try:
        from edge_tts import exceptions as edge_exc

        errors.append(edge_exc.EdgeTTSException)
    except Exception:  # pragma: no cover - edge-tts no instalado
        pass
    try:
        import aiohttp

        errors.append(aiohttp.ClientError)
    except Exception:  # pragma: no cover
        pass
    return tuple(errors)


def _run_coroutine(factory) -> None:
    """Ejecuta la corrutina que crea ``factory()`` con ``asyncio.run``.

    Si el hilo actual ya tiene un bucle de eventos activo (``asyncio.run`` fallaría con
    «cannot be called from a running event loop»), la ejecuta en un hilo auxiliar y espera.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(factory())
        return

    box: dict[str, BaseException] = {}

    def _target() -> None:
        try:
            asyncio.run(factory())
        except BaseException as exc:  # se relanza en el hilo que llama
            box["exc"] = exc

    worker = threading.Thread(target=_target, name="edge-tts-loop", daemon=True)
    worker.start()
    worker.join()
    if "exc" in box:
        raise box["exc"]


class EdgeTTS(TTSProvider):
    """Síntesis con ``edge_tts.Communicate`` (API asíncrona) a MP3 de 24 kHz mono.

    Args:
        settings: configuración (las voces llegan por parámetro a ``synthesize``).
        rate: velocidad relativa (``"+0%"``, ``"+8%"``, ``"-5%"``). Si no se pasa, se usa
            ``settings.briefer_tts_rate`` si existe, y si no ``"+0%"``.
        pitch: tono relativo (``"+0Hz"``, ``"-2Hz"``). Igual que ``rate``.
        retries: reintentos ante errores de red o del servicio.
        backoff_s: espera base entre reintentos (crece linealmente: 1×, 2×, 3×…).
        connect_timeout, receive_timeout: *timeouts* del websocket (segundos).
    """

    provider_name = "edge"
    audio_extension = ".mp3"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        rate: str | None = None,
        pitch: str | None = None,
        retries: int = 2,
        backoff_s: float = 1.0,
        connect_timeout: int = 10,
        receive_timeout: int = 60,
    ) -> None:
        self.settings = settings
        self.model = "edge-tts"
        self.rate = _check_rate(rate or getattr(settings, "briefer_tts_rate", None) or "+0%")
        self.pitch = _check_pitch(pitch or getattr(settings, "briefer_tts_pitch", None) or "+0Hz")
        self.retries = max(0, int(retries))
        self.backoff_s = max(0.0, float(backoff_s))
        self.connect_timeout = connect_timeout
        self.receive_timeout = receive_timeout

    def synthesize(
        self,
        text: str,
        voice: str,
        out_path: Path,
        *,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> Path:
        """Sintetiza ``text`` con la voz ``voice`` y guarda un MP3; devuelve la ruta escrita.

        La extensión de ``out_path`` se cambia siempre a ``.mp3``. ``rate``/``pitch`` permiten
        ajustar una llamada concreta sin cambiar los del proveedor.

        Raises:
            ValueError: texto o voz vacíos, o ``rate``/``pitch`` mal formados.
            RuntimeError: el servicio no devolvió audio tras agotar los reintentos (con la causa
                original encadenada).
        """
        if not text or not text.strip():
            raise ValueError("EdgeTTS.synthesize: el texto está vacío")
        if not voice or not voice.strip():
            raise ValueError("EdgeTTS.synthesize: falta la voz")
        rate = _check_rate(rate) if rate else self.rate
        pitch = _check_pitch(pitch) if pitch else self.pitch

        import edge_tts  # perezoso: solo hace falta si se usa este proveedor

        out = Path(out_path).with_suffix(self.audio_extension)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{out.stem}.{os.getpid()}.{threading.get_ident()}.part")
        clean_text = " ".join(text.split())

        async def _save() -> None:
            communicate = edge_tts.Communicate(
                clean_text,
                voice.strip(),
                rate=rate,
                pitch=pitch,
                connect_timeout=self.connect_timeout,
                receive_timeout=self.receive_timeout,
            )
            await communicate.save(str(tmp))

        transient = _transient_errors()
        last_exc: BaseException | None = None
        try:
            for attempt in range(self.retries + 1):
                try:
                    _run_coroutine(_save)
                    if not tmp.exists() or tmp.stat().st_size == 0:
                        raise edge_tts.exceptions.NoAudioReceived("edge-tts no escribió audio")
                    os.replace(tmp, out)
                    return out
                except transient as exc:
                    last_exc = exc
                    if attempt >= self.retries:
                        break
                    wait = self.backoff_s * (attempt + 1)
                    log.warning(
                        "edge-tts falló (%s: %s); reintento %d/%d en %.1f s",
                        type(exc).__name__, exc, attempt + 1, self.retries, wait,
                    )
                    time.sleep(wait)
        finally:
            tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"edge-tts no pudo sintetizar tras {self.retries + 1} intentos "
            f"({type(last_exc).__name__}: {last_exc})"
        ) from last_exc


__all__ = ["EdgeTTS", "TESTED_EDGE_TTS_VERSION"]
