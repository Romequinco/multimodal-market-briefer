"""Prueba de humo REAL y barata de cada proveedor configurado en ``.env``.

Uso::

    python scripts/smoke_real.py                 # todo lo que tenga clave
    python scripts/smoke_real.py --only anthropic gemini
    python scripts/smoke_real.py --gemini-model gemini-3.8-flash

Imprime una línea por comprobación: ``OK`` / ``FAIL`` / ``SKIP`` / ``PEND`` (proveedor aún sin
implementar), latencia, tokens y coste estimado (``costs.py``). **Nunca imprime claves**: solo
si están presentes. Coste total esperado < 0,01 € (entradas mínimas; Haiku para el JSON).

Comprobaciones:
- ``anthropic.text``: Claude principal (``BRIEFER_LLM_MODEL``), texto libre.
- ``anthropic.structured``: Claude barato (``BRIEFER_LLM_MODEL_CHEAP``) con ``response_model``.
- ``anthropic.vision``: ``ClaudeVision`` sobre ``data/samples/grafico_ejemplo.png``.
- ``gemini.structured``: ``GeminiLLM`` con ``response_model``.
- ``tts`` / ``stt``: proveedores de los carriles C / A según ``.env`` (si están implementados);
  el STT transcribe el audio que acaba de generar el TTS (ida y vuelta).

Carril B. Las salidas (audio) van a ``BRIEFER_OUTPUT_DIR/smoke/``.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import BaseModel  # noqa: E402

from briefer import costs  # noqa: E402
from briefer.config import Settings, get_settings  # noqa: E402

SAMPLE_CHART = ROOT / "data" / "samples" / "grafico_ejemplo.png"


class _City(BaseModel):
    ciudad: str
    pais: str
    poblacion_aprox_millones: float


@dataclass
class Result:
    name: str
    status: str  # OK | FAIL | SKIP | PEND
    model: str = "-"
    latency_s: float = 0.0
    tokens: str = "-"
    cost_eur: float = 0.0
    detail: str = ""


def _clip(text: str, n: int = 110) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _run(name: str, model: str, fn: Callable[[], tuple[str, dict | None, float]]) -> Result:
    """Ejecuta una comprobación y mide latencia. ``fn`` -> (detalle, usage, coste extra)."""
    start = time.perf_counter()
    try:
        detail, usage, extra_cost = fn()
    except NotImplementedError as exc:
        return Result(name, "PEND", model, time.perf_counter() - start, detail=_clip(exc))
    except Exception as exc:  # noqa: BLE001 - se informa y se sigue con el resto
        return Result(name, "FAIL", model, time.perf_counter() - start, detail=_clip(f"{type(exc).__name__}: {exc}"))
    latency = time.perf_counter() - start
    tokens, cost = "-", extra_cost
    if usage:
        tokens = f"{usage.get('input_tokens', 0)}/{usage.get('output_tokens', 0)}"
        cost += costs.estimate_cost_eur(name.split(".")[0], model, **usage)
    return Result(name, "OK", model, latency, tokens, cost, _clip(detail))


def check_anthropic(s: Settings) -> list[Result]:
    if not s.has_secret("anthropic_api_key"):
        return [Result("anthropic", "SKIP", detail="Falta ANTHROPIC_API_KEY")]
    from briefer.providers.llm.anthropic_llm import AnthropicLLM
    from briefer.providers.vision.claude_vision import ClaudeVision

    main, cheap, vision = AnthropicLLM(s), AnthropicLLM(s, cheap=True), ClaudeVision(s)

    def text() -> tuple[str, dict, float]:
        out = main.complete("Responde en una sola frase corta en español.", [{"role": "user", "content": "¿Qué es el IBEX 35?"}])
        return str(out), main.last_usage, 0.0

    def structured() -> tuple[str, dict, float]:
        out = cheap.complete(
            "Extrae los datos pedidos.",
            [{"role": "user", "content": "Vivo en Sevilla (España), que tiene unos 0,7 millones de habitantes."}],
            response_model=_City,
        )
        return out.model_dump_json(), cheap.last_usage, 0.0

    def describe() -> tuple[str, dict, float]:
        out = vision.describe(SAMPLE_CHART.read_bytes(), "Describe este gráfico financiero en dos frases: tipo, tendencia y último valor.")
        return out, vision.last_usage, 0.0

    return [
        _run("anthropic.text", main.model, text),
        _run("anthropic.structured", cheap.model, structured),
        _run("anthropic.vision", vision.model, describe),
    ]


def check_gemini(s: Settings, model: str | None) -> list[Result]:
    if not s.has_secret("gemini_api_key"):
        return [Result("gemini", "SKIP", detail="Falta GEMINI_API_KEY")]
    from briefer.providers.llm.gemini_llm import GeminiLLM

    llm = GeminiLLM(s, cheap=True)
    if model:
        llm.model = model

    def structured() -> tuple[str, dict, float]:
        out = llm.complete(
            "Extrae los datos pedidos.",
            [{"role": "user", "content": "Vivo en Oporto (Portugal), con unos 0,23 millones de habitantes."}],
            response_model=_City,
        )
        return out.model_dump_json(), llm.last_usage, 0.0

    return [_run("gemini.structured", llm.model, structured)]


def check_tts_stt(s: Settings, out_dir: Path) -> list[Result]:
    """TTS y STT de los carriles C / A, si están configurados e implementados."""
    from briefer.providers import registry

    results: list[Result] = []
    audio: Path | None = None
    text = "Hola, esto es una prueba de Market Briefer."
    tts = registry.get_tts(s)
    if tts.provider_name == "mock":
        results.append(Result("tts", "SKIP", detail=f"TTS en mock (BRIEFER_TTS_PROVIDER={s.briefer_tts_provider})"))
    else:
        def synth() -> tuple[str, None, float]:
            nonlocal audio
            out_dir.mkdir(parents=True, exist_ok=True)
            audio = tts.synthesize(text, s.briefer_voice_a, out_dir / "smoke_tts")
            cost = costs.estimate_cost_eur(tts.provider_name, tts.model, n_chars=len(text))
            return f"{audio.name} ({audio.stat().st_size} bytes)", None, cost

        results.append(_run(f"tts.{tts.provider_name}", tts.model, synth))

    stt = registry.get_stt(s)
    if stt.provider_name == "mock":
        results.append(Result("stt", "SKIP", detail=f"STT en mock (BRIEFER_STT_PROVIDER={s.briefer_stt_provider})"))
    elif audio is None:
        results.append(Result(f"stt.{stt.provider_name}", "SKIP", stt.model, detail="Sin audio del TTS para transcribir"))
    else:
        def transcribe() -> tuple[str, None, float]:
            out = stt.transcribe(audio, s.briefer_language)  # type: ignore[arg-type]
            return out, None, costs.estimate_cost_eur(stt.provider_name, stt.model, duration_s=4.0)

        results.append(_run(f"stt.{stt.provider_name}", stt.model, transcribe))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba de humo real de los proveedores de .env")
    parser.add_argument("--only", nargs="*", choices=["anthropic", "gemini", "audio"], help="Limitar comprobaciones")
    parser.add_argument("--gemini-model", help="Modelo Gemini a probar (por defecto BRIEFER_GEMINI_MODEL)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # tildes legibles en la consola de Windows
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    s = get_settings()
    only = set(args.only or ["anthropic", "gemini", "audio"])

    print("Claves presentes:", ", ".join(
        f"{k.split('_')[0]}={'sí' if s.has_secret(k) else 'no'}"
        for k in ("anthropic_api_key", "gemini_api_key", "openai_api_key")
    ))
    results: list[Result] = []
    if "anthropic" in only:
        results += check_anthropic(s)
    if "gemini" in only:
        results += check_gemini(s, args.gemini_model)
    if "audio" in only:
        results += check_tts_stt(s, s.output_path / "smoke")

    print(f"\n{'comprobación':<22} {'estado':<5} {'modelo':<28} {'lat.(s)':>7} {'tok in/out':>11} {'coste €':>9}  detalle")
    for r in results:
        print(f"{r.name:<22} {r.status:<5} {r.model:<28} {r.latency_s:>7.2f} {r.tokens:>11} {r.cost_eur:>9.5f}  {r.detail}")
    total = sum(r.cost_eur for r in results)
    print(f"\nCoste total estimado: {total:.5f} € (tarifas de costs.py; ver docs/04)")
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
