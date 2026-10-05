"""Texto a voz con ``edge-tts`` (voces neuronales de Microsoft Edge, sin clave).

Carril C. Implementa ``TTSProvider.synthesize(text, voice, out_path) -> Path`` (MP3).
Voces por defecto: ``BRIEFER_VOICE_A=es-ES-AlvaroNeural`` y ``BRIEFER_VOICE_B=es-ES-ElviraNeural``.
Lo usa ``media.podcast`` (una llamada por línea del guion) y el Q&A hablado.
Ojo: servicio no oficial y sin SLA -> mantener ElevenLabs/mock como alternativa.
"""

from __future__ import annotations

from pathlib import Path

from briefer.config import Settings
from briefer.providers.base import TTSProvider


class EdgeTTS(TTSProvider):
    """Síntesis con ``edge_tts.Communicate`` (API asíncrona)."""

    provider_name = "edge"
    audio_extension = ".mp3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = "edge-tts"

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        """Sintetiza ``text`` y guarda un MP3; devuelve la ruta escrita."""
        # TODO:
        # 1. import asyncio, edge_tts (perezoso).
        # 2. out = Path(out_path).with_suffix(".mp3"); out.parent.mkdir(parents=True, exist_ok=True).
        # 3. async def _run(): await edge_tts.Communicate(text, voice, rate="+0%").save(str(out))
        # 4. Ejecutar: asyncio.run(_run()). OJO en Streamlit puede haber un event loop
        #    activo -> si asyncio.get_running_loop() existe, ejecutar en un hilo aparte
        #    (concurrent.futures.ThreadPoolExecutor) para evitar "event loop is running".
        # 5. Reintentar 2 veces ante errores de red (edge_tts.exceptions.*).
        # Casos borde: texto vacío -> ValueError; texto muy largo -> trocear por frases;
        # caracteres SSML (<, &) -> escapar.
        raise NotImplementedError("EdgeTTS.synthesize: pendiente (carril C)")
