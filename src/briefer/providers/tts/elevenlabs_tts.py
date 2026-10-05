"""Texto a voz con ElevenLabs (API REST) — alternativa de mayor calidad.

Carril C. Implementa ``TTSProvider.synthesize``. Requiere ``ELEVENLABS_API_KEY`` y los ids de
voz ``ELEVENLABS_VOICE_A`` / ``ELEVENLABS_VOICE_B`` (si ``voice`` es un nombre de edge-tts,
se traduce al id de ElevenLabs según el hablante). Modelo: ``ELEVENLABS_MODEL``.
"""

from __future__ import annotations

from pathlib import Path

from briefer.config import Settings
from briefer.providers.base import TTSProvider


class ElevenLabsTTS(TTSProvider):
    """Síntesis vía ``POST /v1/text-to-speech/{voice_id}`` con ``requests``."""

    provider_name = "elevenlabs"
    audio_extension = ".mp3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.elevenlabs_model

    def _voice_id(self, voice: str) -> str:
        """Traduce ``voice`` (id de ElevenLabs o voz A/B de edge-tts) a un voice_id."""
        # TODO: si voice == settings.briefer_voice_a -> settings.elevenlabs_voice_a;
        # si == briefer_voice_b -> elevenlabs_voice_b; si no, asumir que ya es un id.
        # Si falta el id configurado -> ValueError con mensaje claro.
        raise NotImplementedError("ElevenLabsTTS._voice_id: pendiente (carril C, opcional)")

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        """Llama a la API y guarda el MP3."""
        # TODO:
        # 1. import requests; url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}".
        # 2. headers={"xi-api-key": ..., "accept": "audio/mpeg"};
        #    json={"text": text, "model_id": self.model}; timeout=60.
        # 3. raise_for_status(); escribir resp.content en out_path.with_suffix(".mp3").
        # Casos borde: 401 (clave), 429 (cuota agotada -> mensaje claro / fallback a edge).
        raise NotImplementedError("ElevenLabsTTS.synthesize: pendiente (carril C, opcional)")
