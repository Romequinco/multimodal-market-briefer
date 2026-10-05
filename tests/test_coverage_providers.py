"""Cobertura de ramas de los proveedores reales sin red ni claves: validación de mensajes de Gemini,
falta de clave al crear clientes, reescalado de imágenes para Claude visión y detección de silencio
en audios para Whisper."""

from __future__ import annotations

import io
import os
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from briefer.config import Settings
from briefer.providers.llm import gemini_llm
from briefer.providers.stt import whisper_api
from briefer.providers.vision import claude_vision


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# ── Gemini ────────────────────────────────────────────────────────────────────────


def test_gemini_contents_skip_and_validation() -> None:
    contents = gemini_llm.to_gemini_contents([
        {"role": "system", "content": "se ignora"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Buenas"},
    ])
    assert [c["role"] for c in contents] == ["user", "model"]
    with pytest.raises(ValueError, match="solo admite contenido de texto"):
        gemini_llm.to_gemini_contents([{"role": "user", "content": [{"type": "image"}]}])
    with pytest.raises(ValueError, match="empezar por un mensaje de usuario"):
        gemini_llm.to_gemini_contents([{"role": "assistant", "content": "x"}])
    with pytest.raises(ValueError):
        gemini_llm.to_gemini_contents([])


def test_gemini_usage_without_metadata() -> None:
    assert gemini_llm._usage(SimpleNamespace()) == {"input_tokens": 0, "output_tokens": 0}
    meta = SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=None)
    assert gemini_llm._usage(SimpleNamespace(usage_metadata=meta)) == {"input_tokens": 10, "output_tokens": 5}


def test_gemini_client_requires_key() -> None:
    pytest.importorskip("google.genai")
    llm = gemini_llm.GeminiLLM(_settings(gemini_api_key=None))
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm._get_client()


def test_gemini_cheap_config_uses_thinking_level_on_newer_models() -> None:
    pytest.importorskip("google.genai")
    llm = gemini_llm.GeminiLLM(_settings(briefer_gemini_model="gemini-3.8-flash"), cheap=True)
    config = llm._config("", None)
    assert config.thinking_config.thinking_level is not None
    assert config.system_instruction is None and config.response_mime_type is None


# ── Whisper API ───────────────────────────────────────────────────────────────────


def _wav(path: Path, frames: bytes, width: int = 2) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(width)
        wav.setframerate(8000)
        wav.writeframes(frames)
    return path


def test_is_silent_wav_edge_cases(tmp_path: Path) -> None:
    assert whisper_api.is_silent_wav(_wav(tmp_path / "vacio.wav", b"")) is True
    assert whisper_api.is_silent_wav(_wav(tmp_path / "8bit.wav", b"\x80" * 100, width=1)) is False
    loud = (b"\xff\x7f\x01\x80") * 400  # +32767 / -32767
    assert whisper_api.is_silent_wav(_wav(tmp_path / "voz.wav", loud)) is False
    (tmp_path / "x.mp3").write_bytes(b"ID3")
    assert whisper_api.is_silent_wav(tmp_path / "x.mp3") is False


def test_whisper_client_requires_key() -> None:
    pytest.importorskip("openai")
    stt = whisper_api.WhisperAPI(_settings(openai_api_key=None))
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        stt._get_client()


# ── Claude visión ─────────────────────────────────────────────────────────────────


def test_prepare_image_falls_back_to_jpeg_when_png_is_too_big(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.BytesIO()
    Image.frombytes("RGB", (300, 300), os.urandom(300 * 300 * 3)).save(buf, format="PNG")
    monkeypatch.setattr(claude_vision, "MAX_IMAGE_BYTES", 1000)  # ruido: el PNG no baja de 1 KB
    data, media_type = claude_vision.prepare_image(buf.getvalue())
    assert media_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff")


def test_prepare_image_without_pillow_sends_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    png = io.BytesIO()
    Image.new("RGB", (4, 4)).save(png, format="PNG")
    monkeypatch.setitem(sys.modules, "PIL", None)  # import -> ImportError
    assert claude_vision.prepare_image(png.getvalue()) == (png.getvalue(), "image/png")


def test_claude_vision_client_is_shared_and_warmup_is_noop_when_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr(claude_vision.common, "get_client", lambda settings: sentinel)
    vision = claude_vision.ClaudeVision(_settings(anthropic_api_key="sk-test-no-real"))
    assert vision._get_client() is sentinel and vision._get_client() is sentinel
    assert vision.warmup() == 0.0  # el cliente ya existe: no hay nada que calentar
