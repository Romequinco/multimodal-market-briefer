"""Estimación de costes de inferencia por proveedor/modelo (para StepMetric y viabilidad).

Carril B (transversal para docs de viabilidad). Las tarifas están en USD como las publican los
proveedores y se convierten a EUR con ``USD_TO_EUR``.

Estado de verificación (05-oct-2026):
- **Claude** (Sonnet 5.5: 2 $ / 10 $; Haiku 4.5: 1 $ / 5 $ por millón de tokens de entrada /
  salida): tabla de precios de la documentación oficial de la API de Anthropic (consultada el
  05-oct-2026, datos del 25-sep-2026). Los ids ``claude-sonnet-5-5`` y
  ``claude-haiku-4-5-20251001`` responden en la API (``scripts/smoke_real.py``).
- **Gemini, OpenAI, Whisper, ElevenLabs y tipo de cambio**: *estimación a verificar* en las
  páginas oficiales antes de la entrega (anotar la fecha en ``docs/04``).

El coste de una llamada LLM/visión se calcula con ``provider.last_usage``
(``{"input_tokens", "output_tokens"}`` y, si hubo caché de prompt,
``cache_read_input_tokens`` / ``cache_creation_input_tokens``):
``estimate_cost_eur(provider, model, **last_usage)``. Los tokens de razonamiento (Sonnet 5.5
adaptativo, Gemini *thinking*) se facturan como salida y ya vienen incluidos en
``output_tokens``. Las imágenes de visión se facturan como tokens de entrada y ya vienen en
``input_tokens`` de la respuesta (no hay que estimarlas aparte).

Qué cuenta en el coste de un paso (``pipeline._MeteredLLM`` / ``_MeteredVision``): **todas**
las llamadas que devuelven respuesta, incluidas las de reintento (JSON inválido, *grounding*,
reescritura del guion) y las que luego se descartan (rechazo, cortada por ``max_tokens``). Los
reintentos internos del SDK ante 429/5xx/red no se facturan (no hubo respuesta) y no se suman.

Caché de prompt (Anthropic): lectura 0,1x y escritura (5 min) 1,25x la tarifa de entrada.
"""

from __future__ import annotations

from collections.abc import Iterable

from briefer.schemas import StepMetric

# Estimación a verificar (≈ 0,86 €/$ en oct-2026).
USD_TO_EUR = 0.86

# USD por millón de tokens: (entrada, salida).
LLM_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # Anthropic — documentación oficial de precios (verificado 05-oct-2026)
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),  # también cubre claude-haiku-4-5-20251001 (prefijo)
    "claude-opus-5-5": (4.00, 20.00),
    # Google — estimación a verificar
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.8-flash": (0.50, 3.00),  # estimación a verificar: sin tarifa pública confirmada
    # OpenAI — estimación a verificar (LLM no implementado en el MVP)
    "gpt-4o-mini": (0.15, 0.60),
}

# USD por minuto de audio. Estimación a verificar.
STT_PRICES_USD_PER_MIN: dict[str, float] = {
    "whisper-1": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
}

# USD por 1.000 caracteres. edge-tts es gratuito (servicio no oficial, sin SLA); resto:
# estimación a verificar.
TTS_PRICES_USD_PER_1K_CHARS: dict[str, float] = {
    "edge": 0.0,
    "elevenlabs": 0.18,  # depende del plan; aprox.
    "openai-tts-1": 0.015,
}

# USD por imagen generada (solo modelos locales en el MVP).
IMAGE_GEN_PRICES_USD_PER_IMAGE: dict[str, float] = {
    "sdxl_turbo": 0.0,  # local
}

# Proveedores sin coste marginal: locales (se ignora electricidad/GPU), datos de ejemplo y mocks.
LOCAL_PROVIDERS = {
    "mock", "qwen_local", "whisper_local", "sdxl_turbo", "clip", "edge", "none",
    "local", "samples", "synthetic", "matplotlib", "moviepy", "-",
}


def estimate_tokens(text: str) -> int:
    """Aproximación grosera: ~4 caracteres por token (válida para estimar, no para facturar)."""
    return max(1, len(text) // 4) if text else 0


def estimate_image_tokens(width: int, height: int) -> int:
    """Tokens aproximados de una imagen en modelos de visión tipo Claude (~ ancho*alto/750)."""
    return max(1, (width * height) // 750)


def llm_price_usd_per_mtok(model: str) -> tuple[float, float] | None:
    """Tarifa ``(entrada, salida)`` en USD por millón de tokens; ``None`` si no se conoce.

    Admite ids con sufijo de fecha (``claude-haiku-4-5-20251001`` -> ``claude-haiku-4-5``)
    buscando el prefijo conocido más largo.
    """
    if model in LLM_PRICES_USD_PER_MTOK:
        return LLM_PRICES_USD_PER_MTOK[model]
    matches = [k for k in LLM_PRICES_USD_PER_MTOK if model.startswith(k)]
    return LLM_PRICES_USD_PER_MTOK[max(matches, key=len)] if matches else None


#: Multiplicadores de la tarifa de entrada para la caché de prompt de Anthropic
#: (documentación oficial de precios: lectura 0,1x; escritura con TTL de 5 min 1,25x).
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25


def estimate_llm_cost_eur(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Coste en EUR de una llamada LLM/visión. Modelo desconocido -> 0.0.

    ``input_tokens`` son los tokens de entrada sin caché; los de caché se facturan con
    ``CACHE_READ_MULTIPLIER`` / ``CACHE_WRITE_MULTIPLIER``.
    """
    price_in, price_out = llm_price_usd_per_mtok(model) or (0.0, 0.0)
    effective_in = (
        input_tokens
        + cache_read_input_tokens * CACHE_READ_MULTIPLIER
        + cache_creation_input_tokens * CACHE_WRITE_MULTIPLIER
    )
    usd = (effective_in * price_in + output_tokens * price_out) / 1_000_000
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


_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def estimate_cost_eur(provider: str, model: str, **usage: float) -> float:
    """Despachador genérico usado por el pipeline.

    ``usage`` admite: ``input_tokens``, ``output_tokens`` (LLM/visión, p. ej.
    ``**llm.last_usage``), ``duration_s`` (STT), ``n_chars`` (TTS), ``n_images`` (imagen).
    Proveedores locales, mocks y datos de ejemplo devuelven 0.0.
    """
    if provider in LOCAL_PROVIDERS:
        return 0.0
    if any(k in usage for k in _TOKEN_KEYS):
        return estimate_llm_cost_eur(model, **{k: int(usage.get(k, 0)) for k in _TOKEN_KEYS})
    if "duration_s" in usage:
        return estimate_stt_cost_eur(model, float(usage["duration_s"]))
    if "n_chars" in usage:
        return estimate_tts_cost_eur(provider, int(usage["n_chars"]))
    if "n_images" in usage:
        return estimate_image_cost_eur(provider, int(usage["n_images"]))
    return 0.0


def summarize_metrics(metrics: Iterable[StepMetric]) -> dict[str, float]:
    """Totales para la UI y el pitch: latencia total (s), coste total (EUR) y nº de pasos.

    ``total_latency_s`` es la **suma** de latencias de los pasos (los pasos en paralelo
    cuentan por separado: es mayor que el tiempo de pared).
    """
    items = list(metrics)
    return {
        "steps": float(len(items)),
        "total_latency_s": round(sum(m.latency_s for m in items), 3),
        "total_cost_eur": round(sum(m.est_cost_eur for m in items), 6),
    }


def cost_breakdown(metrics: Iterable[StepMetric]) -> list[tuple[str, float, float]]:
    """``[(paso, coste €, % del total)]`` de los pasos con coste > 0, de mayor a menor."""
    items = [(m.step, m.est_cost_eur) for m in metrics if m.est_cost_eur > 0]
    total = sum(c for _, c in items)
    items.sort(key=lambda x: x[1], reverse=True)
    return [(step, round(cost, 6), round(100 * cost / total, 1) if total else 0.0) for step, cost in items]


def format_cost_summary(metrics: Iterable[StepMetric], *, label: str = "briefing") -> str:
    """Resumen legible del coste, p. ej. para el log, el CLI o la UI::

        Coste estimado del briefing: 0,0652 € (≈ 0,0758 $) · agents.analyst 0,0248 € (38 %) · …

    Usa coma decimal (es-ES). Si todo es gratuito (mock, demo) lo dice.
    """
    items = list(metrics)
    total = sum(m.est_cost_eur for m in items)
    if total <= 0:
        return f"Coste estimado del {label}: 0 € (proveedores gratuitos, locales o mock)"
    def num(value: float) -> str:
        return f"{value:.4f}".replace(".", ",")

    parts = [f"{step} {num(cost)} € ({pct:.0f} %)" for step, cost, pct in cost_breakdown(items)]
    head = f"Coste estimado del {label}: {num(total)} € (≈ {num(total / USD_TO_EUR)} $)"
    return " · ".join([head, *parts])
