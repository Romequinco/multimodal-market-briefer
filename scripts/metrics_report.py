"""Informe de latencia y coste a partir de los briefings guardados (``Briefing.metrics``).

Lee los ``briefing.json`` de una o varias carpetas (por defecto ``BRIEFER_OUTPUT_DIR``, es decir
``data/outputs/``) y calcula, solo con lo que ya está en disco (sin red ni llamadas de pago):

- Nº de briefings por modo (``real`` / ``demo_voices`` / ``mock``). El modo no se guarda en el
  briefing: se deduce de sus ``StepMetric`` (ver ``infer_mode``). Las cifras de cabecera son solo de
  los ``real`` (``--mode`` para cambiarlo).
- Por briefing: pared aproximada, suma de pasos y coste total.
- Por paso: latencia y coste con p50 / p95, mínimo y máximo.
- Pasos caídos a sustituto (``logging_utils.step_fell_back``) y pasos con error.
- Q&A: ``QAAnswer.metrics`` **no se persiste** (en ``<id>/qa/`` solo queda el audio de la
  respuesta), así que solo se cuentan esos audios y no hay latencias del Q&A.

Método de los percentiles: **interpolación lineal** entre rangos (el ``percentile`` por defecto de
NumPy, «tipo 7»). Con N < 5 el p95 es casi el máximo y solo es orientativo.

Pared: el ``Briefing`` no la guarda. Se aproxima como ``created_at`` − hora del id
(``YYYYMMDD-HHMMSS``, se fija al empezar ``run_briefing``) + pasos posteriores a construir el
``Briefing`` (``delivery.*``, ``storage.save``). El id va truncado al segundo: error de 0 a +1 s.

Ejemplos::

    python scripts/metrics_report.py                         # data/outputs/, tabla legible
    python scripts/metrics_report.py --include-demo          # + data/samples/demo_briefing/
    python scripts/metrics_report.py --dir otra/carpeta --markdown
    python scripts/metrics_report.py --mode todos --json

Carpetas corruptas o sin ``briefing.json`` se saltan con un aviso por stderr. Un mismo id en dos
carpetas (p. ej. el pregenerado y su original) se cuenta una vez.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from briefer import storage  # noqa: E402
from briefer.logging_utils import step_failed, step_fell_back  # noqa: E402
from briefer.schemas import Briefing, StepMetric  # noqa: E402

MODES = ("real", "demo_voices", "mock")
UPLOAD_STEPS = ("ingest.pdf", "ingest.chart", "ingest.voice")
#: Pasos que se ejecutan después de construir el ``Briefing`` (``created_at``).
POST_BUILD_PREFIXES = ("delivery.", "storage.")
PERCENTILE_METHOD = "interpolación lineal (tipo 7, como numpy.percentile)"


# ── Cálculo ────────────────────────────────────────────────────────────────────────


def percentile(values: Sequence[float], q: float) -> float | None:
    """Percentil ``q`` (0-100) con interpolación lineal entre rangos; ``None`` si no hay datos."""
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def infer_mode(briefing: Briefing) -> str:
    """Modo de ejecución deducido de las métricas (``Briefing`` no lo guarda).

    - Algún paso caído a sustituto -> ``real`` (el fallback solo existe en modo real).
    - ``ingest.news`` con proveedor ``samples`` sin fallback, o (sin ese paso) todos los
      ``agents.*`` en ``mock`` -> modo offline: ``demo_voices`` si el podcast es ``edge``, si no ``mock``.
    - Resto -> ``real``.
    """
    metrics = briefing.metrics
    if any(step_fell_back(m) for m in metrics):
        return "real"
    by_step = {m.step: m for m in metrics}
    news = by_step.get("ingest.news")
    if news is not None:
        offline = news.provider == "samples"
    else:
        agents = [m for m in metrics if m.step.startswith("agents.")]
        offline = bool(agents) and all(m.provider == "mock" for m in agents)
    if not offline:
        return "real"
    podcast = by_step.get("media.podcast")
    return "demo_voices" if podcast is not None and podcast.provider == "edge" else "mock"


def estimate_wall_clock_s(briefing: Briefing) -> float | None:
    """Pared aproximada de ``run_briefing`` (ver docstring del módulo); ``None`` si no se puede."""
    try:
        start = datetime.strptime(briefing.id[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    created = briefing.created_at.replace(tzinfo=None)
    delta = (created - start).total_seconds()
    if delta < 0 or delta > 6 * 3600:  # id o fecha manipulados: mejor no inventar
        return None
    post = sum(m.latency_s for m in briefing.metrics if m.step.startswith(POST_BUILD_PREFIXES))
    return round(delta + post, 3)


def uploads_label(briefing: Briefing) -> str:
    """``"pdf+chart"``, ``"pdf"``… según las subidas procesadas, o ``"sin subidas"``."""
    kinds = [s.split(".", 1)[1] for s in UPLOAD_STEPS if any(m.step == s for m in briefing.metrics)]
    return "+".join(kinds) if kinds else "sin subidas"


@dataclass
class BriefingRow:
    id: str
    folder: str
    mode: str
    uploads: str
    wall_clock_s: float | None
    steps_sum_s: float
    cost_eur: float
    n_steps: int
    fallbacks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    qa_audio_files: int = 0


@dataclass
class Collection:
    rows: list[BriefingRow] = field(default_factory=list)
    briefings: dict[str, Briefing] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    qa_audio_orphans: int = 0  # audios de Q&A en carpetas sin briefing.json válido ni id conocido
    _orphan_qa: dict[str, int] = field(default_factory=dict)


def _count_qa_audio(folder: Path) -> int:
    qa = folder / "qa"
    if not qa.is_dir():
        return 0
    return sum(1 for p in qa.iterdir() if p.is_file() and p.suffix.lower() in {".mp3", ".wav"})


def _candidate_folders(directory: Path) -> list[Path]:
    """La propia carpeta si tiene ``briefing.json``; si no, sus subcarpetas (orden alfabético)."""
    if (directory / storage.BRIEFING_FILE).is_file():
        return [directory]
    try:
        return sorted(p for p in directory.iterdir() if p.is_dir())
    except OSError:
        return []


def collect(dirs: Iterable[Path]) -> Collection:
    """Carga todos los briefings de ``dirs``; salta (con aviso) carpetas corruptas o vacías."""
    col = Collection()
    for directory in dirs:
        directory = Path(directory)
        if not directory.is_dir():
            col.warnings.append(f"{directory}: no existe o no es una carpeta")
            continue
        for folder in _candidate_folders(directory):
            qa_files = _count_qa_audio(folder)
            json_path = folder / storage.BRIEFING_FILE
            if not json_path.is_file():
                col.warnings.append(f"{folder}: sin {storage.BRIEFING_FILE}, se salta")
                col._orphan_qa[folder.name] = col._orphan_qa.get(folder.name, 0) + qa_files
                continue
            try:
                briefing = storage.load_briefing(json_path)
            except Exception as exc:  # noqa: BLE001 - una carpeta rota no tumba el informe
                col.warnings.append(f"{folder}: no se puede cargar ({type(exc).__name__}), se salta")
                col._orphan_qa[folder.name] = col._orphan_qa.get(folder.name, 0) + qa_files
                continue
            if briefing.id in col.briefings:
                col.warnings.append(f"{folder}: id {briefing.id} repetido, se cuenta una vez")
                col._orphan_qa[briefing.id] = col._orphan_qa.get(briefing.id, 0) + qa_files
                continue
            metrics = briefing.metrics
            col.briefings[briefing.id] = briefing
            col.rows.append(BriefingRow(
                id=briefing.id,
                folder=str(folder),
                mode=infer_mode(briefing),
                uploads=uploads_label(briefing),
                wall_clock_s=estimate_wall_clock_s(briefing),
                steps_sum_s=round(sum(m.latency_s for m in metrics), 4),
                cost_eur=round(sum(m.est_cost_eur for m in metrics), 6),
                n_steps=len(metrics),
                fallbacks=[m.step for m in metrics if step_fell_back(m)],
                errors=[m.step for m in metrics if step_failed(m) and not step_fell_back(m)],
                qa_audio_files=qa_files,
            ))
    # Audios de Q&A de una carpeta sin JSON cuyo nombre es el id de un briefing cargado de otra
    # carpeta (p. ej. el original del pregenerado): se atribuyen a ese briefing.
    rows_by_id = {r.id: r for r in col.rows}
    for name, count in col._orphan_qa.items():
        if name in rows_by_id:
            rows_by_id[name].qa_audio_files += count
        else:
            col.qa_audio_orphans += count
    col.rows.sort(key=lambda r: r.id)
    return col


def _stats(values: Sequence[float]) -> dict[str, float | None]:
    vals = [float(v) for v in values]
    return {
        "n": len(vals),
        "p50": percentile(vals, 50),
        "p95": percentile(vals, 95),
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "mean": sum(vals) / len(vals) if vals else None,
    }


def build_report(col: Collection, mode: str = "real") -> dict[str, Any]:
    """Informe como dict (base de las tres salidas). ``mode``: uno de ``MODES`` o ``"todos"``."""
    selected = [r for r in col.rows if mode == "todos" or r.mode == mode]
    step_lat: dict[str, list[float]] = {}
    step_cost: dict[str, list[float]] = {}
    step_providers: dict[str, set[str]] = {}
    for row in selected:
        for m in col.briefings[row.id].metrics:
            step_lat.setdefault(m.step, []).append(m.latency_s)
            step_cost.setdefault(m.step, []).append(m.est_cost_eur)
            step_providers.setdefault(m.step, set()).add(f"{m.provider}/{m.model}" if m.model != "-" else m.provider)
    steps = [
        {
            "step": step,
            "providers": sorted(step_providers[step]),
            "latency_s": _stats(step_lat[step]),
            "cost_eur": {**_stats(step_cost[step]), "total": sum(step_cost[step])},
        }
        for step in step_lat
    ]
    walls = [r.wall_clock_s for r in selected if r.wall_clock_s is not None]
    by_uploads: dict[str, list[BriefingRow]] = {}
    for row in selected:
        by_uploads.setdefault(row.uploads, []).append(row)
    groups = [
        {
            "uploads": label,
            "n": len(rows),
            "wall_clock_s": _stats([r.wall_clock_s for r in rows if r.wall_clock_s is not None]),
            "steps_sum_s": _stats([r.steps_sum_s for r in rows]),
            "cost_eur": _stats([r.cost_eur for r in rows]),
        }
        for label, rows in sorted(by_uploads.items())
    ]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode_filter": mode,
        "percentile_method": PERCENTILE_METHOD,
        "wall_clock_method": "created_at - hora del id + delivery.*/storage.* (error 0 a +1 s)",
        "counts_by_mode": {m: sum(1 for r in col.rows if r.mode == m) for m in MODES},
        "n_selected": len(selected),
        "briefings": [r.__dict__ for r in selected],
        "totals": {
            "wall_clock_s": _stats(walls),
            "steps_sum_s": _stats([r.steps_sum_s for r in selected]),
            "cost_eur": {**_stats([r.cost_eur for r in selected]), "total": sum(r.cost_eur for r in selected)},
        },
        "by_uploads": groups,
        "steps": steps,
        "fallbacks": {
            "steps": sum(len(r.fallbacks) for r in selected),
            "briefings_with_fallback": sum(1 for r in selected if r.fallbacks),
            "by_step": _count(s for r in selected for s in r.fallbacks),
        },
        "errors": {
            "steps": sum(len(r.errors) for r in selected),
            "by_step": _count(s for r in selected for s in r.errors),
        },
        "qa": {
            "metrics_persisted": False,
            "audio_files": sum(r.qa_audio_files for r in selected),
            "audio_files_without_briefing": col.qa_audio_orphans,
            "note": "QAAnswer.metrics no se guarda en disco: sin latencias del Q&A en este informe.",
        },
        "warnings": list(col.warnings),
    }


def _count(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


# ── Formato ────────────────────────────────────────────────────────────────────────


def num(value: float | None, decimals: int = 1) -> str:
    """Número con coma decimal (es-ES), como ``costs.format_cost_summary``; ``—`` si falta."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}".replace(".", ",")


def _sec(value: float | None) -> str:
    return "—" if value is None else f"{num(value, 1)} s"


def _eur(value: float | None) -> str:
    return "—" if value is None else f"{num(value, 4)} €"


def _table(headers: list[str], rows: list[list[str]], markdown: bool) -> str:
    if markdown:
        lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(lines)
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    def fmt(cells: list[str]) -> str:
        return "  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(cells, widths)))
    return "\n".join([fmt(headers), "  ".join("-" * w for w in widths), *(fmt(r) for r in rows)])


def render_text(report: dict[str, Any], markdown: bool = False) -> str:
    """Informe legible (``markdown=False``) o tablas Markdown listas para ``docs/04``."""
    counts = report["counts_by_mode"]
    n = report["n_selected"]
    h = "### " if markdown else ""
    out: list[str] = []
    out.append(f"{h}Informe de métricas de briefings guardados ({report['generated_at'][:10]})")
    out.append("")
    out.append(
        f"Briefings encontrados: real {counts['real']} · demo_voices {counts['demo_voices']} · "
        f"mock {counts['mock']}. Filtro: **{report['mode_filter']}** (N = {n})."
        if markdown else
        f"Briefings encontrados: real {counts['real']} · demo_voices {counts['demo_voices']} · "
        f"mock {counts['mock']}. Filtro: {report['mode_filter']} (N = {n})."
    )
    out.append(f"Percentiles: {report['percentile_method']}."
               + (" Con N < 5 el p95 es solo orientativo." if n < 5 else ""))
    out.append(f"Pared aproximada: {report['wall_clock_method']}.")
    if n == 0:
        out.append("")
        out.append("No hay briefings de ese modo: nada que medir.")
        return "\n".join(out + _warnings(report, markdown))

    out += ["", f"{h}Por briefing", ""]
    out.append(_table(
        ["Briefing", "Modo", "Subidas", "Pared (aprox.)", "Suma de pasos", "Coste", "Fallbacks"],
        [[r["id"], r["mode"], r["uploads"], _sec(r["wall_clock_s"]), _sec(r["steps_sum_s"]),
          _eur(r["cost_eur"]), str(len(r["fallbacks"]))] for r in report["briefings"]],
        markdown,
    ))

    out += ["", f"{h}Totales por briefing (p50 · p95 · mín-máx)", ""]
    rows = []
    for label, key, fmt_ in (("Pared (aprox.)", "wall_clock_s", _sec), ("Suma de pasos", "steps_sum_s", _sec),
                             ("Coste", "cost_eur", _eur)):
        st = report["totals"][key]
        rows.append([label, str(st["n"]), fmt_(st["p50"]), fmt_(st["p95"]), f"{fmt_(st['min'])} - {fmt_(st['max'])}"])
    for g in report["by_uploads"]:
        for label, key, fmt_ in (("pared", "wall_clock_s", _sec), ("coste", "cost_eur", _eur)):
            st = g[key]
            rows.append([f"{g['uploads']} · {label}", str(st["n"]), fmt_(st["p50"]), fmt_(st["p95"]),
                         f"{fmt_(st['min'])} - {fmt_(st['max'])}"])
    out.append(_table(["Métrica", "N", "p50", "p95", "Rango"], rows, markdown))

    out += ["", f"{h}Por paso", ""]
    out.append(_table(
        ["Paso", "Proveedor/modelo", "N", "Latencia p50", "Latencia p95", "Latencia máx", "Coste p50", "Coste p95"],
        [[s["step"], ", ".join(s["providers"]), str(s["latency_s"]["n"]), _sec(s["latency_s"]["p50"]),
          _sec(s["latency_s"]["p95"]), _sec(s["latency_s"]["max"]), _eur(s["cost_eur"]["p50"]),
          _eur(s["cost_eur"]["p95"])] for s in report["steps"]],
        markdown,
    ))

    fb, err, qa = report["fallbacks"], report["errors"], report["qa"]
    out.append("")
    detail = ", ".join(f"{k} ×{v}" for k, v in fb["by_step"].items())
    out.append(f"Pasos caídos a sustituto (fallback): {fb['steps']} en {fb['briefings_with_fallback']} de {n} "
               f"briefings" + (f" ({detail})" if detail else "") + ".")
    if err["steps"]:
        out.append("Pasos con error sin sustituto: " + ", ".join(f"{k} ×{v}" for k, v in err["by_step"].items()) + ".")
    out.append(f"Q&A: {qa['note']} Audios de respuesta en qa/: {qa['audio_files']} en estos briefings"
               + (f" (+{qa['audio_files_without_briefing']} en carpetas sin briefing válido)"
                  if qa["audio_files_without_briefing"] else "") + ".")
    return "\n".join(out + _warnings(report, markdown))


def _warnings(report: dict[str, Any], markdown: bool) -> list[str]:
    if not report["warnings"] or markdown:
        return []
    return ["", "Avisos:", *(f"  - {w}" for w in report["warnings"])]


# ── CLI ────────────────────────────────────────────────────────────────────────────


def default_dirs() -> list[Path]:
    from briefer.config import get_settings

    return [get_settings().output_path]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Latencia y coste medidos a partir de los briefings guardados")
    parser.add_argument("--dir", type=Path, action="append", default=None,
                        help="Carpeta con briefings (repetible). Por defecto, BRIEFER_OUTPUT_DIR (data/outputs/)")
    parser.add_argument("--include-demo", action="store_true",
                        help="Añadir también el briefing pregenerado (data/samples/demo_briefing/)")
    parser.add_argument("--mode", choices=[*MODES, "todos"], default="real",
                        help="Modo de los briefings a medir (por defecto, solo los reales)")
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--markdown", action="store_true", help="Tablas Markdown para pegar en docs/04")
    out.add_argument("--json", action="store_true", help="Salida JSON para uso automático")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dirs = list(args.dir) if args.dir else default_dirs()
    if args.include_demo:
        dirs.append(storage.demo_briefing_dir())
    col = collect(dirs)
    for warning in col.warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    report = build_report(col, args.mode)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text(report, markdown=args.markdown))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
