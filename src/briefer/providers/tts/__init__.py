"""Implementaciones reales de ``TTSProvider`` (texto a voz, carril C).

- ``edge_tts_provider.EdgeTTS``: ``edge-tts`` (gratis, sin clave, voces neuronales es-ES). Por defecto.
- ``gemini_tts.GeminiTTS``: Gemini TTS multi-locutor (de pago, premium).

Hoja de ruta (sin código): ElevenLabs, OpenAI TTS, o Bark en local (inspirado en el
notebook 6 de clase, generación de sonido): muy lento en CPU, solo como demostración.
"""
