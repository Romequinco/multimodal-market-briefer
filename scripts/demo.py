"""CLI de demostración: genera un briefing (con mocks o real) o hace una pregunta, sin UI.

Ejemplos::

    python scripts/demo.py --mock
    python scripts/demo.py --demo-voices          # sin claves, pero con voces reales (edge-tts)
    python scripts/demo.py --refresh              # real, ignorando la caché diaria de noticias/precios
    python scripts/demo.py --mock --tickers santander AAPL \
        --upload data/samples/resultados_ejemplo.pdf data/samples/grafico_ejemplo.png
    python scripts/demo.py --tickers SAN.MC AAPL --upload data/samples/resultados_ejemplo.pdf
    python scripts/demo.py --mock --question "¿Por qué sube el Santander?"
    python scripts/demo.py --question "¿Qué dice el PDF?" --briefing pregenerado --warmup

Códigos de salida: 0 bien · 1 falló un paso núcleo (se indica cuál y lo ya gastado) ·
2 entrada inválida o paso pendiente de implementar · 3 con ``--strict``, algún paso usó un
sustituto (mock, ``data/samples``…) · 130 interrumpido. Nunca imprime claves.

Los ficheros de ``data/samples/`` (PDF de resultados y captura de gráfico) son ficticios y se
regeneran con ``python data/samples/generar_muestras.py``. Las salidas van a
``BRIEFER_OUTPUT_DIR`` (por defecto ``data/outputs/<id>/``). Los tickers admiten el nombre de la
empresa («santander», «telefonica»): se normalizan con ``ingest.tickers.normalize_ticker``.

Carril B (orquestación). Útil para medir latencias/costes para el pitch y para depurar el
pipeline sin Streamlit.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from briefer import costs
from briefer.config import get_settings
from briefer.logging_utils import step_fell_back
from briefer.schemas import DISCLAIMER_ES, Briefing, StepMetric


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    s = get_settings()
    parser = argparse.ArgumentParser(description="Market Briefer — demo por línea de comandos")
    parser.add_argument(
        "--tickers", nargs="+", default=s.default_tickers, help="Tickers (formato Yahoo o nombre de empresa)"
    )
    parser.add_argument("--portfolio", type=Path, help="CSV de cartera (ver data/samples)")
    parser.add_argument("--upload", type=Path, nargs="*", default=[], help="PDF, imagen o audio")
    parser.add_argument("--video", action="store_true", help="Generar también el vídeo")
    parser.add_argument("--cover", action="store_true", help="Generar portada (texto a imagen)")
    parser.add_argument("--deliver", nargs="*", default=[], choices=["email", "telegram"])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--mock", action="store_true", help="Forzar proveedores mock (sin red ni claves)")
    modes.add_argument(
        "--demo-voices",
        action="store_true",
        help="Demo sin claves con voces reales: datos de ejemplo + LLM mock + edge-tts (necesita red)",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Ignorar la caché diaria de noticias y precios (modo real)"
    )
    parser.add_argument("--question", help="En vez de un briefing, hacer una pregunta al Agente Q&A")
    parser.add_argument(
        "--briefing",
        default="auto",
        help="Contexto de --question: 'auto' (último guardado o pregenerado), 'pregenerado', "
        "'ninguno' o el id / ruta de un briefing.json",
    )
    parser.add_argument(
        "--warmup", action="store_true", help="Con --question: precalentar clientes antes (pipeline.warmup)"
    )
    parser.add_argument(
        "--strict", action="store_true", help="Salir con código 3 si algún paso usó un sustituto (mock…)"
    )
    return parser.parse_args(argv)


def load_question_briefing(spec: str) -> Briefing | None:
    """Briefing de contexto para ``--question`` según ``--briefing``."""
    from briefer import storage

    key = spec.strip().lower()
    if key in ("ninguno", "none", ""):
        return None
    if key == "auto":
        featured = storage.load_featured_briefing()
        return featured[0] if featured else None
    if key == "pregenerado":
        return storage.load_demo_briefing()
    return storage.load_briefing(spec)


def print_metrics(metrics: list[StepMetric]) -> None:
    """Tabla de pasos: latencia, coste estimado y error (si lo hubo)."""
    print(f"\n{'Paso':<22} {'Proveedor':<14} {'Latencia':>9} {'Coste €':>9}  Estado")
    for m in metrics:
        status = "OK" if not m.error else (
            f"SUSTITUTO: {m.error}" if step_fell_back(m) else f"ERROR: {m.error}"
        )
        if m.detail:
            status += f" · {m.detail}"
        print(f"{m.step:<22} {m.provider[:14]:<14} {m.latency_s:>8.2f}s {m.est_cost_eur:>9.5f}  {status}")
    summary = costs.summarize_metrics(metrics)
    n_failed = sum(1 for m in metrics if m.error)
    print(
        f"Total: {summary.get('total_latency_s', 0.0):.2f} s (suma de pasos) · "
        f"{summary.get('total_cost_eur', 0.0):.4f} € (estimado) · {n_failed} paso(s) con error"
    )
    print(costs.format_cost_summary(metrics, label="proceso"))


def print_briefing(briefing: Briefing, output_dir: Path) -> None:
    """Resumen legible del briefing generado."""
    print("\n" + "=" * 72)
    print("Titular:", briefing.analysis.headline)
    print("Tickers:", ", ".join(briefing.context.tickers))
    print(f"Puntos clave: {len(briefing.analysis.key_points)}")
    for kp in briefing.analysis.key_points:
        print(f"  - [{kp.sentiment}] {kp.title}")
    if briefing.context.insights:
        print(f"Documentos del usuario: {len(briefing.context.insights)}")
        for ins in briefing.context.insights:
            print(f"  - {ins.source_type}: {ins.source_name} · {len(ins.key_figures)} cifras clave")
    print(f"Guion: «{briefing.script.title}» · {len(briefing.script.lines)} líneas")
    if briefing.audio:
        print(f"Audio: {briefing.audio.duration_s:.1f} s · {briefing.audio.path}")
    else:
        print("Audio: -")
    if briefing.transcript and briefing.transcript.srt_path:
        print("Subtítulos:", briefing.transcript.srt_path)
    print(f"Gráficos: {len(briefing.charts)}")
    if briefing.video:
        print("Vídeo:", briefing.video.path)
    for d in briefing.deliveries:
        print(f"Entrega {d.channel}: {'OK' if d.ok else 'FALLO'} · {d.detail}")
    print("Salida:", output_dir / briefing.id)
    print_metrics(briefing.metrics)


def main(argv: list[str] | None = None) -> int:
    # Consolas Windows con códigos de página antiguos: que «€», «·» o «≈» no rompan la salida.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    from briefer import pipeline
    from briefer.ingest.portfolio import load_portfolio_csv

    mode = "mock" if args.mock else "demo_voices" if args.demo_voices else "real"
    print(DISCLAIMER_ES, "\n")
    print(f"Modo: {mode}" + (" (datos de ejemplo, sin coste)" if mode != "real" else " (llamadas reales: cuestan dinero)"))
    started = time.perf_counter()
    try:
        if args.question:
            context = load_question_briefing(args.briefing)
            print("Contexto:", f"briefing {context.id}" if context else "ninguno (el agente lo dirá)")
            if args.warmup:
                timings = pipeline.warmup(mode=mode)
                print(f"Precalentado en {timings.get('total', 0.0):.2f} s: {timings}")
            t0 = time.perf_counter()
            answer = pipeline.answer_question(args.question, context, mode=mode, speak=False)
            text_s = time.perf_counter() - t0
            print("Pregunta:", answer.question)
            print(f"Respuesta ({text_s:.2f} s):", answer.answer_text)
            if answer.sources:
                print("Fuentes:", ", ".join(answer.sources))
            answer = pipeline.speak_answer(answer, context, mode=mode)
            print(f"Audio ({time.perf_counter() - t0:.2f} s desde la pregunta):", answer.audio_path or "-")
            print_metrics(answer.metrics)
            return _exit_code(answer.metrics, args.strict)

        portfolio = load_portfolio_csv(args.portfolio) if args.portfolio else None
        briefing = pipeline.run_briefing(
            args.tickers,
            portfolio=portfolio,
            uploads=args.upload,
            make_video=args.video,
            deliver=args.deliver,
            make_cover=args.cover,
            mode=mode,
            use_cache=not args.refresh,
            progress=lambda msg: print("·", msg),
        )
    except NotImplementedError as exc:
        print(f"\nPendiente de implementar: {exc}", file=sys.stderr)
        return 2
    except pipeline.PipelineStepError as exc:
        cause = exc.__cause__
        print(f"\nERROR: falló el paso núcleo «{exc.step}»", file=sys.stderr)
        if cause is not None:
            print(f"Causa: {type(cause).__name__}: {cause}", file=sys.stderr)
        if exc.metrics:
            print_metrics(exc.metrics)
        print(
            "Sugerencias: revisa la red y las claves de .env (python scripts/smoke_real.py), "
            "activa BRIEFER_FALLBACK_TO_MOCK=true o prueba con --mock.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, FileNotFoundError) as exc:
        print(f"\nEntrada no válida: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130

    print_briefing(briefing, get_settings().output_path)
    print(f"Tiempo de pared: {time.perf_counter() - started:.1f} s")
    return _exit_code(briefing.metrics, args.strict)


def _exit_code(metrics: list[StepMetric], strict: bool) -> int:
    """0, o 3 si ``strict`` y algún paso usó un sustituto (avisa siempre)."""
    fell_back = [m.step for m in metrics if step_fell_back(m)]
    if fell_back:
        print(f"AVISO: pasos completados con sustituto (no reales): {', '.join(fell_back)}", file=sys.stderr)
    return 3 if strict and fell_back else 0


if __name__ == "__main__":
    raise SystemExit(main())
