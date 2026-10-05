"""Estimación de costes de inferencia por proveedor/modelo (para StepMetric y viabilidad).

Carril B (transversal para docs de viabilidad). Las tarifas son **aproximadas** y están en
USD como las publican los proveedores; se convierten a EUR con ``USD_TO_EUR``.

TODO: verificar todas las tarifas en las páginas oficiales de precios antes de la entrega
(Anthropic, OpenAI, Google, ElevenLabs) y anotar la fecha de consulta en
``docs/04_viabilidad_costes_latencia_compliance.md``.
"""

from __future__ import annotations

from collections.abc import Iterable

from briefer.schemas import StepMetric

# TODO: verificar tipo de cambio (aprox.).
USD_TO_EUR = 0.86

# USD por millón de tokens: (entrada, salida). TODO: verificar cada valor.
LLM_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (3.00, 15.00),  # TODO: verificar (aprox. gama Sonnet)
    "claude-haiku-4-5-20251001": (1.00, 5.00),  # TODO: verificar
    "gemini-2.5-flash": (0.30, 2.50),  # TODO: verificar
    "gpt-4o-mini": (0.15, 0.60),  # TODO: verificar
}

# USD por minuto de audio. TODO: verificar.
STT_PRICES_USD_PER_MIN: dict[str, float] = {
    "whisper-1": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
}

# USD por 1.000 caracteres. edge-tts es gratuito (servicio no oficial, sin SLA). TODO: verificar.
TTS_PRICES_USD_PER_1K_CHARS: dict[str, float] = {
    "edge": 0.0,
    "elevenlabs": 0.18,  # depende del plan; aprox.
    "openai-tts-1": 0.015,
}

# USD por imagen generada. TODO: verificar si se usa una API de imagen.
IMAGE_GEN_PRICES_USD_PER_IMAGE: dict[str, float] = {
    "sdxl_turbo": 0.0,  # local
}

# Proveedores que corren en local: coste marginal 0 (se ignora electricidad/GPU).
LOCAL_PROVIDERS = {"mock", "qwen_local", "whisper_local", "sdxl_turbo", "clip", "edge", "none"}


def estimate_tokens(text: str) -> int:
    """Aproximación grosera: ~4 caracteres por token (válida para estimar, no para facturar)."""
    return max(1, len(text) // 4) if text else 0


def estimate_image_tokens(width: int, height: int) -> int:
    """Tokens aproximados de una imagen en modelos de visión tipo Claude (~ ancho*alto/750)."""
    return max(1, (width * height) // 750)


def estimate_llm_cost_eur(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
    """Coste en EUR de una llamada LLM/visión. Modelo desconocido -> 0.0."""
    price_in, price_out = LLM_PRICES_USD_PER_MTOK.get(model, (0.0, 0.0))
    usd = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    return round(usd * USD_TO_EUR, 6)


def estimate_stt_cost_eur(model: str, duration_s: float) -> float:
    """Coste en EUR de transcribir ``duration_s`` segundos."""
    usd = STT_PRICES_USD_PER_MIN.get(model, 0.0) * (duration_s / 60)
    return round(usd * USD_TO_EUR, 6)


def estimate_tts_cost_eur(provider: str, n_chars: int) -> float:
    """Coste en EUR de sintetizar ``n_chars`` caracteres."""
    usd = TTS_PRICES_USD_PER_1K_CHARS.get(provider, 0.0) * (n_chars / 1000)
    return round(usd * USD_TO_EUR, 6)


def estimate_image_cost_eur(provider: str, n_images: int = 1) -> float:
    """Coste en EUR de generar ``n_images`` imágenes."""
    return round(IMAGE_GEN_PRICES_USD_PER_IMAGE.get(provider, 0.0) * n_images * USD_TO_EUR, 6)


def estimate_cost_eur(provider: str, model: str, **usage: float) -> float:
    """Despachador genérico usado por el pipeline.

    ``usage`` admite: ``input_tokens``, ``output_tokens`` (LLM/visión), ``duration_s`` (STT),
    ``n_chars`` (TTS), ``n_images`` (imagen). Proveedores locales devuelven 0.0.
    """
    if provider in LOCAL_PROVIDERS:
        return 0.0
    if "input_tokens" in usage or "output_tokens" in usage:
        return estimate_llm_cost_eur(
            model, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        )
    if "duration_s" in usage:
        return estimate_stt_cost_eur(model, float(usage["duration_s"]))
    if "n_chars" in usage:
        return estimate_tts_cost_eur(provider, int(usage["n_chars"]))
    if "n_images" in usage:
        return estimate_image_cost_eur(provider, int(usage["n_images"]))
    return 0.0


def summarize_metrics(metrics: Iterable[StepMetric]) -> dict[str, float]:
    """Totales para la UI y el pitch: latencia total (s), coste total (EUR) y nº de pasos."""
    items = list(metrics)
    return {
        "steps": float(len(items)),
        "total_latency_s": round(sum(m.latency_s for m in items), 3),
        "total_cost_eur": round(sum(m.est_cost_eur for m in items), 6),
    }
