"""Mide la cadena de voz completa del Q&A: audio -> STT -> Agente Q&A -> TTS.

Reproduce lo que hace la vista «Preguntar» (``app/views/preguntar.py``):
``pipeline.warmup(mode=…)`` al cargar la vista, ``answer_question(Path, briefing, speak=False)``
(el texto se pinta en cuanto llega) y después ``speak_answer(answer, briefing)`` (la voz).

Uso::

    python scripts/measure_qa_voice.py                       # 3 procesos: frío + caliente cada uno
    python scripts/measure_qa_voice.py --runs 1              # una sola medición (más barato)
    python scripts/measure_qa_voice.py --mode mock           # sin red ni claves (comprueba el script)
    python scripts/measure_qa_voice.py --question "¿Qué tal Apple?" --question "¿Y el IBEX?"

Cómo mide:

1. Genera los audios de las preguntas con ``edge-tts`` (voz es-ES) en una carpeta temporal (con
   ``--mode mock``, WAV de silencio: el STT mock devuelve una pregunta fija).
2. Por cada ronda lanza un **proceso nuevo** (Python en frío, como un ``streamlit run`` recién
   arrancado) que: importa ``briefer.pipeline`` (medido), llama a ``pipeline.warmup`` (medido),
   responde la pregunta *i* (**frío**: primera pregunta del proceso) y después la pregunta *i+1*
   (**caliente**: clientes y conexiones ya abiertos).
3. Imprime por pregunta la latencia de cada paso (``qa.stt``, ``agents.qa``, ``qa.tts``), el tiempo
   hasta el texto, hasta el audio, el coste estimado (``costs.py``) y la mediana (p50) de la
   cadena en frío y en caliente.

Contexto: el briefing pregenerado (``storage.load_demo_briefing()``). Modo por defecto ``real``
(claves de ``.env``; ≈ 0,005-0,01 € por pregunta con Haiku 4.5 + ``gpt-4o-mini-transcribe``).
Los audios de respuesta van a ``BRIEFER_OUTPUT_DIR`` (``data/outputs/``, ignorado por git).
**Nunca imprime claves**: los errores pasan por ``logging_utils.error_text``.

Código de salida: 0 bien · 1 alguna pregunta falló · 2 no hay briefing pregenerado o no se
pudieron generar los audios.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_QUESTIONS = [
    "¿Por qué ha subido hoy Inditex?",
    "¿Qué ha pasado hoy con el Santander?",
    "¿Cómo ha cerrado hoy Apple?",
]
RESULT_TAG = "@@RESULTADO "
STEPS = ("qa.stt", "agents.qa", "qa.tts")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mide la cadena de voz del Q&A (audio -> STT -> Q&A -> TTS) en frío y en caliente."
    )
    parser.add_argument("--runs", type=int, default=3, help="Procesos nuevos a lanzar (cada uno: 1 frío + 1 caliente)")
    parser.add_argument("--mode", default="real", choices=["real", "mock", "demo_voices"], help="Modo del pipeline")
    parser.add_argument(
        "--question", action="append", default=None,
        help="Pregunta a sintetizar (repetible). Por defecto, tres preguntas sobre el pregenerado.",
    )
    parser.add_argument("--keep-audio", action="store_true", help="No borrar los audios de las preguntas")
    parser.add_argument("--json", action="store_true", help="Imprimir también los resultados en JSON")
    # Uso interno: el proceso hijo recibe la lista de audios y el modo.
    parser.add_argument("--_child", nargs="+", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


# ── Proceso hijo (frío) ───────────────────────────────────────────────────────────


def _chain(pipeline, briefing, audio: Path, mode: str) -> dict:
    """Una pregunta por voz como la UI: texto primero (speak=False) y voz después."""
    from briefer.logging_utils import error_text

    out: dict = {"audio": audio.name}
    t0 = time.perf_counter()
    try:
        answer = pipeline.answer_question(audio, briefing, speak=False, mode=mode)
        out["text_s"] = round(time.perf_counter() - t0, 3)
        answer = pipeline.speak_answer(answer, briefing, mode=mode)
        out["total_s"] = round(time.perf_counter() - t0, 3)
    except Exception as exc:  # se informa sin claves y se sigue con la siguiente
        out["error"] = error_text(exc)
        out["steps"] = {
            m.step: {"latency_s": m.latency_s, "cost_eur": m.est_cost_eur, "error": m.error}
            for m in getattr(exc, "metrics", []) or []
        }
        return out
    out["question"] = answer.question
    out["answer"] = answer.answer_text
    out["audio_ok"] = answer.audio_path is not None
    out["steps"] = {
        m.step: {"latency_s": m.latency_s, "cost_eur": m.est_cost_eur, "error": m.error, "detail": m.detail}
        for m in answer.metrics
    }
    out["cost_eur"] = round(sum(m.est_cost_eur for m in answer.metrics), 6)
    return out


def run_child(audios: list[str], mode: str) -> int:
    t = time.perf_counter()
    from briefer import pipeline, storage

    import_s = round(time.perf_counter() - t, 3)
    briefing = storage.load_demo_briefing()
    if briefing is None:
        print(RESULT_TAG + json.dumps({"fatal": "No hay briefing pregenerado (data/samples/demo_briefing)."}))
        return 2
    t = time.perf_counter()
    warm = pipeline.warmup(mode=mode)
    warmup_s = round(time.perf_counter() - t, 3)
    cold = _chain(pipeline, briefing, Path(audios[0]), mode)
    warm_runs = [_chain(pipeline, briefing, Path(a), mode) for a in audios[1:]]
    result = {"import_s": import_s, "warmup_s": warmup_s, "warmup": warm, "cold": cold, "warm": warm_runs}
    print(RESULT_TAG + json.dumps(result))  # ASCII: sin depender de la codificación de la consola
    return 0


# ── Proceso padre ─────────────────────────────────────────────────────────────────


def make_question_audios(questions: list[str], folder: Path, mode: str) -> list[Path]:
    """Audios de las preguntas: edge-tts (voz es-ES) o, en mock, WAV de silencio."""
    from briefer.config import get_settings

    paths: list[Path] = []
    if mode == "mock":
        from briefer.providers.mock import MockTTS

        tts = MockTTS()
        for i, q in enumerate(questions):
            paths.append(tts.synthesize(q, "mock", folder / f"pregunta_{i + 1}"))
        return paths
    from briefer.providers.tts.edge_tts_provider import EdgeTTS

    s = get_settings()
    tts = EdgeTTS(s)
    for i, q in enumerate(questions):
        paths.append(tts.synthesize(q, s.briefer_voice_a, folder / f"pregunta_{i + 1}"))
    return paths


def _p50(values: list[float], digits: int = 2) -> float | None:
    return round(statistics.median(values), digits) if values else None


def _fmt(value: float | None, unit: str = "s", digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f} {unit}"


def print_row(label: str, run: dict) -> None:
    steps = run.get("steps", {})
    cells = [_fmt(steps.get(s, {}).get("latency_s")) for s in STEPS]
    status = "OK" if "error" not in run else f"ERROR: {run['error']}"
    fell = [s for s, m in steps.items() if (m.get("error") or "").startswith("Fallback a ")]
    if fell:
        status = f"SUSTITUTO en {', '.join(fell)}"
    print(
        f"{label:<10} {cells[0]:>9} {cells[1]:>10} {cells[2]:>9} {_fmt(run.get('text_s')):>10} "
        f"{_fmt(run.get('total_s')):>10} {_fmt(run.get('cost_eur'), '€', 4):>10}  {status}"
    )
    if run.get("question"):
        print(f"{'':<10} P: {run['question']}")
        print(f"{'':<10} R: {run['answer'][:160]}{'…' if len(run.get('answer', '')) > 160 else ''}")
    detail = steps.get("agents.qa", {}).get("detail")
    if detail:
        print(f"{'':<10} traza Q&A: {detail}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # consola de Windows (cp1252): sin UnicodeEncodeError
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    if args._child:
        mode, *audios = args._child
        return run_child(audios, mode)

    from briefer.logging_utils import error_text

    questions = args.question or DEFAULT_QUESTIONS
    if len(questions) < 2:
        questions = questions * 2  # hace falta una para el frío y otra para el caliente
    runs = max(1, args.runs)
    tmp = Path(tempfile.mkdtemp(prefix="qa_voz_"))
    try:
        audios = make_question_audios(questions, tmp, args.mode)
    except Exception as exc:
        print(f"No se pudieron generar los audios de las preguntas: {error_text(exc)}")
        return 2
    print(f"Modo: {args.mode} · {runs} proceso(s) nuevo(s) · audios en {tmp}")

    results: list[dict] = []
    failed = False
    for i in range(runs):
        pair = [str(audios[i % len(audios)]), str(audios[(i + 1) % len(audios)])]
        t = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_child", args.mode, *pair],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
        )
        wall = round(time.perf_counter() - t, 2)
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_TAG)), None)
        if line is None:
            print(f"Ronda {i + 1}: el proceso hijo no devolvió resultado (código {proc.returncode}).")
            failed = True
            continue
        data = json.loads(line[len(RESULT_TAG):])
        if "fatal" in data:
            print(data["fatal"])
            return 2
        data["process_wall_s"] = wall
        results.append(data)

    print(
        f"\n{'Pregunta':<10} {'qa.stt':>9} {'agents.qa':>10} {'qa.tts':>9} "
        f"{'t. texto':>10} {'t. audio':>10} {'coste':>10}  Estado"
    )
    for i, r in enumerate(results, 1):
        print(
            f"— Proceso {i}: import pipeline {r['import_s']:.2f} s · warmup {r['warmup_s']:.2f} s "
            f"{ {k: v for k, v in (r.get('warmup') or {}).items()} } · pared {r['process_wall_s']:.1f} s"
        )
        print_row("frío", r["cold"])
        for w in r["warm"]:
            print_row("caliente", w)

    colds = [r["cold"] for r in results if "error" not in r["cold"]]
    warms = [w for r in results for w in r["warm"] if "error" not in w]
    failed = failed or len(colds) + len(warms) < sum(1 + len(r["warm"]) for r in results)
    print("\nResumen (p50 = mediana):")
    for label, group in (("frío", colds), ("caliente", warms)):
        print(
            f"  {label:<9} n={len(group)} · cadena completa (hasta el audio) p50 {_fmt(_p50([g['total_s'] for g in group]))} · "
            f"hasta el texto p50 {_fmt(_p50([g['text_s'] for g in group]))} · "
            + " · ".join(
                f"{s} p50 {_fmt(_p50([g['steps'][s]['latency_s'] for g in group if s in g['steps']]))}"
                for s in STEPS
            )
        )
    print(
        f"  warmup p50 {_fmt(_p50([r['warmup_s'] for r in results]))} · "
        f"import pipeline p50 {_fmt(_p50([r['import_s'] for r in results]))}"
    )
    all_runs = colds + warms
    total_cost = sum(g.get("cost_eur", 0.0) for g in all_runs)
    print(
        f"  coste total {total_cost:.4f} € (estimado, costs.py) · por pregunta p50 "
        f"{_fmt(_p50([g.get('cost_eur', 0.0) for g in all_runs], 5), '€', 4)}"
    )
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    if not args.keep_audio:
        for p in tmp.iterdir():
            p.unlink(missing_ok=True)
        tmp.rmdir()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
