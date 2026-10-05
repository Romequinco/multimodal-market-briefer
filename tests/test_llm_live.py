"""Tests **live** (red + claves reales, cuestan céntimos): excluidos por defecto.

Ejecutar a mano: ``python -m pytest -m live -q``. Cada test se salta si falta su clave.
Usan entradas mínimas y el modelo barato cuando es posible (< 0,01 € en total).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from briefer.config import ROOT_DIR, Settings

pytestmark = pytest.mark.live

SAMPLES_DIR = ROOT_DIR / "data" / "samples"


class Tiny(BaseModel):
    ciudad: str
    pais: str


def _settings(secret: str) -> Settings:
    s = Settings()  # lee .env (las claves); los proveedores se crean explícitamente
    if not s.has_secret(secret):
        pytest.skip(f"Falta {secret.upper()}")
    return s


def test_live_anthropic_text_and_structured() -> None:
    from briefer.providers.llm.anthropic_llm import AnthropicLLM

    llm = AnthropicLLM(_settings("anthropic_api_key"), cheap=True)
    text = llm.complete("Responde en una palabra.", [{"role": "user", "content": "Capital de Francia"}])
    assert "par" in str(text).lower()
    out = llm.complete(
        "Extrae los datos.", [{"role": "user", "content": "Vivo en Madrid, España."}], response_model=Tiny
    )
    assert isinstance(out, Tiny) and out.ciudad.lower() == "madrid"
    assert llm.last_usage["input_tokens"] > 0 and llm.last_usage["output_tokens"] > 0


def test_live_claude_vision() -> None:
    from briefer.providers.vision.claude_vision import ClaudeVision

    vision = ClaudeVision(_settings("anthropic_api_key"))
    text = vision.describe((SAMPLES_DIR / "grafico_ejemplo.png").read_bytes(), "¿Qué tipo de gráfico es? Una frase.")
    assert text and vision.last_usage["input_tokens"] > 0


def test_live_gemini_structured() -> None:
    from briefer.providers.llm.gemini_llm import GeminiLLM

    llm = GeminiLLM(_settings("gemini_api_key"), cheap=True)
    out = llm.complete(
        "Extrae los datos.", [{"role": "user", "content": "Vivo en Lisboa, Portugal."}], response_model=Tiny
    )
    assert isinstance(out, Tiny) and out.pais.lower() == "portugal"


def test_live_warmup_then_qa_text_under_10s(tmp_path) -> None:
    """Objetivo D2: con el cliente precalentado, la 1.ª pregunta del proceso responde en texto
    en < 10 s (Haiku, ~0,005 €). Sin audio: el TTS se mide en los tests de edge-tts."""
    import time

    from briefer import pipeline, storage
    from briefer.agents import guardrails

    s = _settings("anthropic_api_key").model_copy(
        update={"briefer_llm_provider": "anthropic", "briefer_output_dir": tmp_path}
    )
    timings = pipeline.warmup(s, mode="real")
    assert "llm" in timings  # models.retrieve respondió: clave e id del modelo válidos
    briefing = storage.load_demo_briefing()
    start = time.perf_counter()
    answer = pipeline.answer_question("¿Vendo mis Santander?", briefing, speak=False, mode="real", settings=s)
    assert time.perf_counter() - start < 10
    assert answer.metrics[-1].provider == "anthropic" and not answer.metrics[-1].error
    assert not guardrails.contains_advice(answer.answer_text)
    assert "asesor" in answer.answer_text.lower()


def test_live_whisper_roundtrip_with_edge_tts(tmp_path) -> None:
    """Ida y vuelta real: frase conocida -> edge-tts -> STT de OpenAI -> WER ≤ 0,2 (< 0,001 €)."""
    import re
    import unicodedata

    from briefer.providers.stt.whisper_api import WhisperAPI
    from briefer.providers.tts.edge_tts_provider import EdgeTTS

    s = _settings("openai_api_key")
    phrase = "¿Por qué ha caído hoy Inditex en el IBEX 35?"
    audio = EdgeTTS(s).synthesize(phrase, "es-ES-ElviraNeural", tmp_path / "pregunta")

    def words(t: str) -> list[str]:
        t = "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9 ]", " ", t).split()

    stt = WhisperAPI(s)
    out = stt.transcribe(audio, "es")
    ref, hyp = words(phrase), words(out)
    assert len(set(ref) - set(hyp)) <= 2, out  # ≈ WER ≤ 0,2 en 9 palabras
    assert stt.last_duration_s > 1
