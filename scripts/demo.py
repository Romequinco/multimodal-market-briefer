"""CLI de demostración: genera un briefing (con mocks o real) o hace una pregunta, sin UI.

Ejemplos::

    python scripts/demo.py --mock
    python scripts/demo.py --mock --tickers santander AAPL --upload data/samples/resultados_ejemplo.pdf data/samples/grafico_ejemplo.png
    python scripts/demo.py --tickers SAN.MC AAPL --upload data/samples/resultados_ejemplo.pdf
    python scripts/demo.py --mock --question "¿Por qué sube el Santander?"

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from briefer import costs  # noqa: E402
from briefer.config import get_settings  # noqa: E402
from briefer.schemas import DISCLAIMER_ES, Briefing, StepMetric  # noqa: E402


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
    parser.add_argument("--mock", action="store_true", help="Forzar proveedores mock (sin red ni claves)")
    parser.add_argument("--question", help="En vez de un briefing, hacer una pregunta al Agente Q&A")
    return parser.parse_args(argv)


def print_metrics(metrics: list[StepMetric]) -> None:
    """Tabla de pasos: latencia, coste estimado y error (si lo hubo)."""
    print(f"\n{'Paso':<22} {'Proveedor':<14} {'Latencia':>9} {'Coste €':>9}  Estado")
    for m in metrics:
        status = "OK" if not m.error else f"ERROR: {m.error}"
        print(f"{m.step:<22} {m.provider[:14]:<14} {m.latency_s:>8.2f}s {m.est_cost_eur:>9.5f}  {status}")
    summary = costs.summarize_metrics(metrics)
    n_failed = sum(1 for m in metrics if m.error)
    print(
        f"Total: {summary.get('total_latency_s', 0.0):.2f} s · "
        f"{summary.get('total_cost_eur', 0.0):.4f} € (estimado) · {n_failed} paso(s) con error"
    )


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

    print(DISCLAIMER_ES, "\n")
    try:
        if args.question:
            answer = pipeline.answer_question(args.question, None, use_mock=args.mock)
            print("Pregunta:", answer.question)
            print("Respuesta:", answer.answer_text)
            print("Audio:", answer.audio_path or "-")
            print_metrics(answer.metrics)
            return 0

        portfolio = load_portfolio_csv(args.portfolio) if args.portfolio else None
        briefing = pipeline.run_briefing(
            args.tickers,
            portfolio=portfolio,
            uploads=args.upload,
            make_video=args.video,
            deliver=args.deliver,
            make_cover=args.cover,
            use_mock=args.mock,
            progress=lambda msg: print("·", msg),
        )
    except NotImplementedError as exc:
        print(f"Pendiente de implementar: {exc}")
        return 2

    print_briefing(briefing, get_settings().output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
