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
