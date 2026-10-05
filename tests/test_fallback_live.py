"""Fallback **real** (``live``, excluido por defecto): un proveedor núcleo falla de verdad.

Ejecutar a mano: ``python -m pytest -m live tests/test_fallback_live.py -q``.

Se fuerza un fallo real del LLM con una ``ANTHROPIC_API_KEY`` **inválida** (sobrescrita en
memoria; la del ``.env`` no se toca): la API responde 401 y, con
``BRIEFER_FALLBACK_TO_MOCK=true``, el pipeline debe completar el briefing con ``MockLLM``,
marcando el sustituto en el ``StepMetric`` (``step_fell_back`` / ``error = "Fallback a …"``) y
sin que ningún error, detalle ni log lleve claves.

Coste ≈ 0 €: la llamada con clave inválida no se factura; noticias y precios reales (gratis,
caché diaria de ``data/cache`` si existe); TTS y visión mock. Necesita red.
"""

from __future__ import annotations

import logging

import pytest
from pydantic import SecretStr

from briefer.config import ROOT_DIR, Settings
from briefer.logging_utils import FALLBACK_PREFIX, step_fell_back

pytestmark = pytest.mark.live

#: Clave inválida con forma de clave real (los patrones de ``redact_secrets`` la reconocen).
INVALID_KEY = "sk-ant-api03-" + "x" * 40 + "-INVALIDA"


def _real_secrets() -> list[str]:
    """Valores de las claves reales de ``.env`` (para comprobar que no se filtran)."""
    s = Settings()
    out = []
    for name in type(s).model_fields:
        value = getattr(s, name, None)
        if isinstance(value, SecretStr) and len(value.get_secret_value()) >= 8:
            out.append(value.get_secret_value())
    return out


def _broken_settings(tmp_path) -> Settings:
    return Settings().model_copy(
        update={
            "anthropic_api_key": SecretStr(INVALID_KEY),
            "briefer_llm_provider": "anthropic",
            "briefer_vision_provider": "mock",
            "briefer_stt_provider": "mock",
            "briefer_tts_provider": "mock",
            "briefer_image_gen_provider": "none",
            "briefer_fallback_to_mock": True,
            "briefer_output_dir": tmp_path / "outputs",
            "briefer_cache_dir": ROOT_DIR / "data" / "cache",
        }
    )


def _assert_no_secrets(texts: list[str]) -> None:
    secrets = [INVALID_KEY, *_real_secrets()]
    for text in texts:
        for secret in secrets:
            assert secret not in text, "un secreto aparece en un error, detalle o log"


def test_live_invalid_anthropic_key_falls_back_to_mock(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    from briefer import pipeline
    from briefer.providers.llm import _anthropic_common as common

    common.reset_clients()  # sin clientes de otra clave en el caché del proceso
    s = _broken_settings(tmp_path)
    caplog.set_level(logging.INFO)
    try:
        briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], mode="real", settings=s)
    finally:
        common.reset_clients()

    by_step = {m.step: m for m in briefing.metrics}
    analyst_m, writer_m = by_step["agents.analyst"], by_step["agents.scriptwriter"]
    # Analista: excepción del proveedor -> MockLLM.
    assert step_fell_back(analyst_m) and analyst_m.provider == "mock", analyst_m.error
    assert analyst_m.error.startswith(f"{FALLBACK_PREFIX}mock tras AuthenticationError")
    # Guionista: absorbe el error y usa su guion de respaldo determinista (también marcado).
    assert step_fell_back(writer_m), writer_m.error
    assert (writer_m.provider, writer_m.model) in {("mock", "mock-llm"), ("local", "fallback_script")}
    assert "AuthenticationError" in writer_m.error
    # El resto del briefing sale completo con lo real (noticias/precios) y los mocks pedidos.
    assert not by_step["ingest.news"].error or step_fell_back(by_step["ingest.news"])
    assert briefing.analysis.headline and briefing.script.lines and briefing.audio is not None
    texts = [str(m.error or "") + " " + str(m.detail or "") for m in briefing.metrics]
    texts += [r.getMessage() for r in caplog.records]
    _assert_no_secrets(texts)


def test_live_invalid_anthropic_key_qa_falls_back(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    from briefer import pipeline, storage
    from briefer.providers.llm import _anthropic_common as common

    common.reset_clients()
    s = _broken_settings(tmp_path)
    caplog.set_level(logging.INFO)
    try:
        answer = pipeline.answer_question(
            "¿Qué ha pasado hoy con el Santander?", storage.load_demo_briefing(),
            speak=False, mode="real", settings=s,
        )
    finally:
        common.reset_clients()
    qa_metric = answer.metrics[-1]
    assert qa_metric.step == "agents.qa" and step_fell_back(qa_metric), qa_metric.error
    assert answer.answer_text
    _assert_no_secrets([str(qa_metric.error), *(r.getMessage() for r in caplog.records)])
