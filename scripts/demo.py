"""CLI de demostración: genera un briefing (con mocks o real) o hace una pregunta, sin UI.

Ejemplos::

    python scripts/demo.py --mock
    python scripts/demo.py --tickers SAN.MC AAPL --upload data/samples/resultados_ejemplo.pdf
    python scripts/demo.py --mock --question "¿Por qué sube el Santander?"

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
from briefer.schemas import DISCLAIMER_ES  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    s = get_settings()
    parser = argparse.ArgumentParser(description="Market Briefer — demo por línea de comandos")
    parser.add_argument("--tickers", nargs="+", default=s.default_tickers, help="Tickers (formato Yahoo)")
    parser.add_argument("--portfolio", type=Path, help="CSV de cartera (ver data/samples)")
    parser.add_argument("--upload", type=Path, nargs="*", default=[], help="PDF, imagen o audio")
    parser.add_argument("--video", action="store_true", help="Generar también el vídeo")
    parser.add_argument("--cover", action="store_true", help="Generar portada (texto a imagen)")
    parser.add_argument("--deliver", nargs="*", default=[], choices=["email", "telegram"])
    parser.add_argument("--mock", action="store_true", help="Forzar proveedores mock (sin red ni claves)")
    parser.add_argument("--question", help="En vez de un briefing, hacer una pregunta al Agente Q&A")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from briefer import pipeline
    from briefer.ingest.portfolio import load_portfolio_csv

    print(DISCLAIMER_ES, "\n")
    try:
        if args.question:
            answer = pipeline.answer_question(args.question, None, use_mock=args.mock)
            print(answer.answer_text)
            print("Audio:", answer.audio_path)
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

    # TODO: imprimir un resumen más rico (puntos clave, rutas de todos los ficheros).
    print("\n", briefing.analysis.headline)
    print("Audio:", briefing.audio.path if briefing.audio else "-")
    print("Métricas:", costs.summarize_metrics(briefing.metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
