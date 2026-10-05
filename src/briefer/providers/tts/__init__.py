"""Implementaciones reales de ``TTSProvider`` (texto a voz, carril C).

- ``edge_tts_provider.EdgeTTS``: ``edge-tts`` (gratis, sin clave, voces neuronales es-ES). Por defecto.
- ``elevenlabs_tts.ElevenLabsTTS``: ElevenLabs (más natural, de pago).

Extras posibles (no previstos en el MVP): OpenAI TTS, o Bark en local (inspirado en el
notebook 6 de clase, generación de sonido): muy lento en CPU, solo como demostración.
"""
