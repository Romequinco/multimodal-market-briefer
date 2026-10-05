"""Costes del carril B (sin red): tarifas verificadas, caché de prompt, reintentos y resumen
legible del coste por briefing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from briefer import costs
from briefer.providers.llm import _anthropic_common as common
from briefer.schemas import StepMetric


def test_anthropic_prices_match_official_table() -> None:
    # Tabla oficial de precios de Anthropic (USD por millón de tokens, entrada / salida).
    assert costs.llm_price_usd_per_mtok("claude-sonnet-5-5") == (2.00, 10.00)
    assert costs.llm_price_usd_per_mtok("claude-haiku-4-5-20251001") == (1.00, 5.00)
    assert costs.llm_price_usd_per_mtok("claude-opus-5-5") == (4.00, 20.00)


def test_cache_tokens_are_priced_with_their_multipliers() -> None:
    base = costs.estimate_llm_cost_eur("claude-haiku-4-5", input_tokens=1_000_000)
    read = costs.estimate_llm_cost_eur("claude-haiku-4-5", cache_read_input_tokens=1_000_000)
    write = costs.estimate_llm_cost_eur("claude-haiku-4-5", cache_creation_input_tokens=1_000_000)
    assert read == pytest.approx(base * 0.10, rel=1e-3)
    assert write == pytest.approx(base * 1.25, rel=1e-3)
    assert costs.estimate_cost_eur("anthropic", "claude-haiku-4-5", cache_read_input_tokens=1_000_000) == read


def test_usage_dict_keeps_cache_tokens_apart() -> None:
    usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=900, cache_creation_input_tokens=0)
    out = common.usage_dict(SimpleNamespace(usage=usage))
    assert out == {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900}
    total = common.add_usage({"input_tokens": 1, "output_tokens": 1}, out)
    assert total == {"input_tokens": 101, "output_tokens": 21, "cache_read_input_tokens": 900}


def test_structured_retry_tokens_count(tmp_path) -> None:
    """El reintento por JSON inválido también se paga y cuenta (dos llamadas)."""
    from test_llm_providers import FakeAnthropicClient, _analysis_json, _resp

    from briefer.config import Settings
    from briefer.providers.llm.anthropic_llm import AnthropicLLM
    from briefer.schemas import Analysis

    s = Settings(_env_file=None, briefer_llm_provider="anthropic", anthropic_api_key="sk-test-no-real")
    llm = AnthropicLLM(s)
    llm._client = FakeAnthropicClient([_resp("{no es json", inp=1000, out=50), _resp(_analysis_json(), inp=1200, out=300)])
    llm.complete("s", [{"role": "user", "content": "x"}], response_model=Analysis)
    assert llm.last_usage == {"input_tokens": 2200, "output_tokens": 350}


def test_format_cost_summary_is_readable() -> None:
    metrics = [
        StepMetric(step="agents.analyst", provider="anthropic", model="m", latency_s=1, est_cost_eur=0.0248),
        StepMetric(step="ingest.chart", provider="anthropic", model="m", latency_s=1, est_cost_eur=0.017),
        StepMetric(step="media.podcast", provider="edge", model="-", latency_s=1, est_cost_eur=0.0),
    ]
    text = costs.format_cost_summary(metrics)
    assert text.startswith("Coste estimado del briefing: 0,0418 €")
    assert "agents.analyst 0,0248 € (59 %)" in text and "media.podcast" not in text
    assert costs.cost_breakdown(metrics)[0][0] == "agents.analyst"
    assert "0 €" in costs.format_cost_summary(metrics[2:])
