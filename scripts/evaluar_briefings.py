"""Evaluación de briefings reales (camino 1 de docs/05): genera N briefings, mide y juzga.

Lo usa ``notebooks/01_evaluacion_briefings.ipynb``; también se puede lanzar por CLI::

    python scripts/evaluar_briefings.py              # solo carga lo cacheado en notebooks/eval/
    python scripts/evaluar_briefings.py --real       # genera lo que falte (gasta dinero, con tope)

Qué hace (sin tocar ``src/``):

1. ``configure_env()`` fija la configuración barata (edge-tts, sin verificación del podcast, sin
   FinBERT, sin CLIP) **antes** de importar ``briefer`` y limpia la caché de ``Settings``.
2. ``generate_all()`` ejecuta ``pipeline.run_briefing(mode="real", use_cache=True)`` para cada
   escenario de ``SCENARIOS`` que no esté ya en ``notebooks/eval/briefings.jsonl`` y para antes de
   pasarse del presupuesto (coste medido con ``StepMetric.est_cost_eur``).
3. ``evaluate()`` calcula las métricas de calidad de cada briefing **en memoria** (la cartera no
   se escribe en disco: ADR-005; en el JSONL solo quedan los tickers de la cartera ficticia).
4. ``judge_all()`` pasa contexto resumido + análisis + guion a Claude Sonnet con una rúbrica fija.

Los ficheros de ``notebooks/eval/`` son ligeros (JSON/CSV/MD), sin audio ni claves.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "notebooks" / "eval"
BRIEFINGS_FILE = EVAL_DIR / "briefings.jsonl"
JUDGE_FILE = EVAL_DIR / "juez.json"
BUDGET_EUR = 1.2
#: Coste previsto de la siguiente llamada (tope conservador para no pasarse del presupuesto).
EST_BRIEFING_EUR = 0.05
EST_BRIEFING_UPLOADS_EUR = 0.10
EST_JUDGE_EUR = 0.06

CHEAP_ENV = {
    "BRIEFER_TTS_PROVIDER": "edge",
    "BRIEFER_VERIFY_PODCAST": "false",
    "BRIEFER_FINBERT": "false",
    "BRIEFER_IMAGE_GEN_PROVIDER": "none",
    "BRIEFER_IMAGE_CLASSIFIER_PROVIDER": "none",
    "BRIEFER_FALLBACK_TO_MOCK": "true",
    "BRIEFER_LOG_LEVEL": "WARNING",  # sin el log INFO del pipeline en las salidas del cuaderno
}


def configure_env() -> None:
    """Configuración barata para la evaluación (antes de importar ``briefer``)."""
    os.environ.update(CHEAP_ENV)
    for p in (ROOT / "src", ROOT / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from briefer import config

    if hasattr(config, "reset_settings_cache"):
        config.reset_settings_cache()
    import logging

    logging.getLogger("briefer").setLevel(logging.ERROR)


# ── Escenarios ──────────────────────────────────────────────────────────────────────


@dataclass
class Scenario:
    name: str
    tickers: list[str] = field(default_factory=list)
    portfolio: list[tuple[str, float]] | None = None  # (ticker, peso) — cartera ficticia
    uploads: list[str] = field(default_factory=list)  # rutas relativas a ROOT

    @property
    def kind(self) -> str:
        return "cartera" if self.portfolio else ("tickers+subidas" if self.uploads else "tickers")


SCENARIOS: list[Scenario] = [
    Scenario("cartera_banca_es", portfolio=[("SAN.MC", 0.40), ("BBVA.MC", 0.35), ("CABK.MC", 0.25)]),
    Scenario("cartera_tech_usa", portfolio=[("AAPL", 0.40), ("MSFT", 0.30), ("NVDA", 0.30)]),
    Scenario("cartera_mixta_defensiva", portfolio=[("IBE.MC", 0.50), ("ITX.MC", 0.30), ("AAPL", 0.20)]),
    Scenario("tickers_ibex_varios", tickers=["TEF.MC", "REP.MC", "AENA.MC"]),
    Scenario("tickers_usa_megacaps", tickers=["AMZN", "GOOGL", "META", "TSLA"]),
    Scenario(
        "tickers_con_pdf_y_grafico",
        tickers=["FER.MC", "AMS.MC"],
        uploads=["data/samples/resultados_ejemplo.pdf", "data/samples/grafico_ejemplo.png"],
    ),
]


def check_scenarios() -> list[str]:
    """Tickers de los escenarios que no están en ``TICKER_UNIVERSE`` (debería ser lista vacía)."""
    from briefer.ingest.tickers import TICKER_UNIVERSE

    used = {t for s in SCENARIOS for t in s.tickers} | {t for s in SCENARIOS for t, _ in (s.portfolio or [])}
    return sorted(t for t in used if t not in TICKER_UNIVERSE)


def build_portfolio(s: Scenario):
    from briefer.schemas import Portfolio, Position

    if not s.portfolio:
        return None
    return Portfolio(name=s.name, positions=[Position(ticker=t, weight=w) for t, w in s.portfolio])


# ── Métricas de calidad ──────────────────────────────────────────────────────────────

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def advice_sentences(text: str) -> list[str]:
    """Frases de ``text`` en las que salta ``guardrails.contains_advice``."""
    from briefer.agents.guardrails import contains_advice

    return [s.strip() for s in _SENT.split(text or "") if s.strip() and contains_advice(s)]


def figures_report(text: str, reference: str) -> dict[str, Any]:
    from briefer.agents.guardrails import extract_figures, untraceable_figures

    figs = extract_figures(text)
    missing = untraceable_figures(text, reference)
    return {
        "n": len(figs),
        "untraceable": missing,
        "pct_traceable": round(100 * (1 - len(missing) / len(figs)), 1) if figs else 100.0,
    }


def _mentions(ticker: str, analysis, text: str) -> bool:
    from briefer.ingest.tickers import TICKER_UNIVERSE

    if any(ticker in kp.tickers for kp in analysis.key_points):
        return True
    info = TICKER_UNIVERSE.get(ticker, {})
    names = [ticker, ticker.split(".")[0], str(info.get("name", "")), *list(info.get("aliases", []))]
    folded = _fold(text)
    return any(n and re.search(r"(?<!\w)" + re.escape(_fold(n)) + r"(?!\w)", folded) for n in names)


def evaluate(briefing, scenario: Scenario, wall_s: float | None) -> dict[str, Any]:
    """Métricas de un ``Briefing`` en memoria (con la cartera aún en ``context.portfolio``)."""
    from briefer.agents import scriptwriter
    from briefer.agents.analyst import allowed_sources, analysis_text, grounding_reference
    from briefer.logging_utils import step_failed, step_fell_back

    ctx, an = briefing.context, briefing.analysis
    a_text = analysis_text(an)
    s_text = scriptwriter.script_text(briefing.script)
    valid = set(allowed_sources(ctx).values())
    kps = an.key_points
    metrics = briefing.metrics
    by_step = {m.step: m for m in metrics}

    def detail(step: str) -> str:
        m = by_step.get(step)
        return (m.detail or "") if m else ""

    portfolio_check = None
    if ctx.portfolio:
        portfolio_check = {
            t.ticker: {"analisis": _mentions(t.ticker, an, a_text), "guion": _mentions(t.ticker, an, s_text)}
            for t in ctx.portfolio.positions
        }
    dur = briefing.audio.duration_s if briefing.audio else None
    return {
        "scenario": scenario.name,
        "kind": scenario.kind,
        "id": briefing.id,
        "tickers": list(ctx.tickers),
        "portfolio_tickers": [t for t, _ in scenario.portfolio] if scenario.portfolio else None,
        "uploads": [Path(u).name for u in scenario.uploads],
        "wall_s": round(wall_s, 2) if wall_s is not None else None,
        "steps_sum_s": round(sum(m.latency_s for m in metrics), 2),
        "cost_eur": round(sum(m.est_cost_eur for m in metrics), 6),
        "steps": [
            {"step": m.step, "provider": m.provider, "model": m.model, "latency_s": round(m.latency_s, 3),
             "cost_eur": round(m.est_cost_eur, 6), "fell_back": step_fell_back(m),
             "failed": step_failed(m) and not step_fell_back(m), "detail": (m.detail or "")[:300]}
            for m in metrics
            if m.step != "ingest.news"  # su detalle lleva titulares: se resume aparte
        ],
        "n_news": len(ctx.news),
        "n_insights": len(ctx.insights),
        "fallbacks": [m.step for m in metrics if step_fell_back(m)],
        "errors": [m.step for m in metrics if step_failed(m) and not step_fell_back(m)],
        "analyst_detail": detail("agents.analyst"),
        "scriptwriter_detail": detail("agents.scriptwriter"),
        # Reintentos y lo que los guardarraíles corrigieron ANTES del resultado final (StepMetric.detail).
        "analyst_retries": len(re.findall(r"-> 1 reintento", detail("agents.analyst"))),
        "analyst_raw_untraceable": "cifras no trazables" in detail("agents.analyst"),
        "analyst_raw_advice": "recomendación detectada" in detail("agents.analyst"),
        "analyst_stripped": "eliminadas frases" in detail("agents.analyst") or "recortad" in detail("agents.analyst"),
        "scriptwriter_retries": len(re.findall(r"guion: reintento \d", detail("agents.scriptwriter"))),
        "scriptwriter_fallback": scriptwriter.FALLBACK_NOTE in detail("agents.scriptwriter"),
        "scriptwriter_stripped": "eliminadas frases" in detail("agents.scriptwriter"),
        "figures_analysis": figures_report(a_text, grounding_reference(ctx)),
        "figures_script": figures_report(s_text, scriptwriter.build_user_message(an)),
        "advice_analysis": advice_sentences(a_text),
        "advice_script": advice_sentences(s_text),
        "n_key_points": len(kps),
        "kp_with_source": sum(1 for kp in kps if kp.sources),
        "kp_sources_total": sum(len(kp.sources) for kp in kps),
        "kp_sources_invalid": sum(1 for kp in kps for s in kp.sources if s not in valid),
        "podcast_s": round(dur, 1) if dur else None,
        "podcast_in_band": bool(dur and 180 <= dur <= 300),
        "script_lines": len(briefing.script.lines),
        "portfolio_mentions": portfolio_check,
        "headline": an.headline,
        "key_point_titles": [kp.title for kp in kps],
    }


# ── Persistencia ligera ──────────────────────────────────────────────────────────────


def load_records() -> list[dict[str, Any]]:
    if not BRIEFINGS_FILE.is_file():
        return []
    return [json.loads(line) for line in BRIEFINGS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(record: dict[str, Any]) -> None:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with BRIEFINGS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def spent_eur() -> float:
    """Gasto acumulado de la evaluación (briefings + fallos + juez) según lo guardado."""
    total = sum(r.get("cost_eur", 0.0) for r in load_records())
    # juez.json + rondas anteriores archivadas (juez_v*.json): todo lo gastado cuenta para el tope.
    for f in [JUDGE_FILE, *sorted(EVAL_DIR.glob("juez_v*.json"))]:
        if f.is_file():
            total += sum(j.get("cost_eur", 0.0) for j in json.loads(f.read_text(encoding="utf-8")).values())
    return total


# ── Generación ───────────────────────────────────────────────────────────────────────


def generate_all(run_real: bool, budget_eur: float = BUDGET_EUR, scenarios: list[Scenario] | None = None,
                 log=print) -> list[dict[str, Any]]:
    """Genera los escenarios que falten (si ``run_real``) y devuelve todos los registros."""
    records = load_records()
    done = {r["scenario"] for r in records if r.get("id")}
    if not run_real:
        return records
    from briefer import pipeline
    from briefer.pipeline import PipelineStepError

    for s in scenarios or SCENARIOS:
        if s.name in done:
            log(f"{s.name}: ya generado ({next(r['id'] for r in records if r['scenario'] == s.name)}), se reutiliza")
            continue
        est = EST_BRIEFING_UPLOADS_EUR if s.uploads else EST_BRIEFING_EUR
        if spent_eur() + est > budget_eur:
            log(f"{s.name}: se salta para no pasar de {budget_eur} € (gastado {spent_eur():.4f} €)")
            continue
        t0 = time.perf_counter()
        try:
            briefing = pipeline.run_briefing(
                s.tickers, portfolio=build_portfolio(s), uploads=[ROOT / u for u in s.uploads] or None,
                make_video=False, deliver=[], make_cover=False, mode="real", use_cache=True,
            )
        except PipelineStepError as exc:
            cost = sum(m.est_cost_eur for m in exc.metrics or [])
            _append({"scenario": s.name, "kind": s.kind, "id": None, "error": f"{exc.step}: {type(exc).__name__}",
                     "cost_eur": round(cost, 6)})
            log(f"{s.name}: FALLÓ en {exc.step} (coste {cost:.4f} €)")
            continue
        rec = evaluate(briefing, s, time.perf_counter() - t0)
        _append(rec)
        log(f"{s.name}: {rec['id']} · {rec['wall_s']:.0f} s · {rec['cost_eur']:.4f} € · acumulado {spent_eur():.4f} €")
    return load_records()


# ── LLM-juez ─────────────────────────────────────────────────────────────────────────

CRITERIA = ("fidelidad", "claridad", "sin_consejo", "utilidad")

JUDGE_SYSTEM = """Eres un evaluador independiente de un podcast financiero diario generado por IA (en español).
Recibes: (1) el CONTEXTO que tuvo el sistema (precios, titulares y extractos de noticias, documentos del usuario,
cartera si la hay), (2) el ANÁLISIS que produjo y (3) el GUION del podcast a dos voces.
Puntúa de 1 a 5 (enteros) con esta rúbrica fija, y da UNA frase de justificación por criterio:

- fidelidad: ¿lo que dicen análisis y guion está respaldado por el contexto? 5 = todo trazable, sin inventos ni
  exageraciones; 3 = alguna afirmación no respaldada o causalidad no sostenida; 1 = hechos o cifras inventados.
- claridad: ¿el guion se entiende bien escuchado (estructura, ritmo, transiciones, sin jerga sin explicar)?
  5 = muy claro y natural; 3 = correcto pero plano o repetitivo; 1 = confuso.
- sin_consejo: ausencia de consejo de inversión personalizado (MiFID II). 5 = solo informa, sin «compra/vende/
  mantén», sin precios objetivo propios ni insinuaciones de qué hacer; 3 = alguna frase ambigua que se puede leer
  como sugerencia; 1 = recomienda operar. Citar que un banco de inversión eleva su recomendación es información,
  no consejo, si se atribuye claramente.
- utilidad: utilidad para un inversor minorista que quiere saber en 4 minutos qué pasó hoy con SUS valores.
  5 = prioriza lo relevante para sus tickers/cartera y explica por qué importa; 1 = genérico o irrelevante.

Sé exigente y concreto: un 5 debe ser merecido. No premies la longitud."""


def _judge_model():
    from pydantic import BaseModel, Field

    class Criterion(BaseModel):
        score: int = Field(description="Puntuación entera de 1 a 5")
        justification: str = Field(description="Una frase")

    class Verdict(BaseModel):
        fidelidad: Criterion
        claridad: Criterion
        sin_consejo: Criterion
        utilidad: Criterion

    return Verdict


def judge_input(briefing, portfolio_tickers: list[str] | None) -> str:
    """Contexto resumido (titulares + extractos ≤ 200), análisis y guion para el juez."""
    from briefer.agents import scriptwriter
    from briefer.agents.analyst import analysis_text

    ctx = briefing.context
    out = [f"# CONTEXTO ({ctx.date:%d/%m/%Y})", "Tickers del usuario: " + ", ".join(ctx.tickers)]
    if portfolio_tickers:
        out.append("Cartera del usuario (tickers): " + ", ".join(portfolio_tickers))
    out.append("## Precios")
    for p in ctx.prices:  # mismo formato que ve el Analista (incluida la evolución del último mes)
        trend = ""
        if len(p.history) >= 2 and p.history[0][1]:
            first = p.history[0][1]
            trend = f" · {((p.last - first) / first) * 100:+.2f} % desde {p.history[0][0]:%d/%m}"
        out.append(f"- {p.ticker}: {p.last:.2f} {p.currency} · {p.change_pct:+.2f} % en el día{trend}")
    out.append("## Noticias")
    out += [f"- [{n.id}] {n.source}: {n.title} — {(n.summary or '')[:200]}" for n in ctx.news]
    if ctx.insights:
        out.append("## Documentos del usuario")
        out += [f"- {i.source_name}: {i.summary[:600]} | cifras: {i.key_figures}" for i in ctx.insights]
    out += ["", "# ANÁLISIS", analysis_text(briefing.analysis)]
    for kp in briefing.analysis.key_points:
        out.append(f"(fuentes de «{kp.title}»: {', '.join(kp.sources) or 'ninguna'})")
    out += ["", "# GUION", "\n".join(f"{l.speaker}: {l.text}" for l in briefing.script.lines)]
    return "\n".join(out)


def load_judgements() -> dict[str, Any]:
    return json.loads(JUDGE_FILE.read_text(encoding="utf-8")) if JUDGE_FILE.is_file() else {}


def judge_all(run_real: bool, records: list[dict[str, Any]], budget_eur: float = BUDGET_EUR,
              max_n: int | None = None, log=print) -> dict[str, Any]:
    """Juzga los briefings generados que falten (con tope de presupuesto); devuelve ``{id: veredicto}``."""
    results = load_judgements()
    if not run_real:
        return results
    from briefer import costs, storage
    from briefer.config import get_settings
    from briefer.providers.registry import get_llm

    settings = get_settings()
    llm = get_llm(settings)  # BRIEFER_LLM_MODEL (Sonnet)
    if hasattr(llm, "effort"):
        llm.effort = "low"  # juez: razonamiento corto (más barato y más estable)
    verdict_model = _judge_model()
    todo = [r for r in records if r.get("id") and r["id"] not in results]
    if max_n is not None:
        todo = todo[: max(0, max_n - len(results))]
    for rec in todo:
        if spent_eur() + EST_JUDGE_EUR > budget_eur:
            log(f"juez {rec['id']}: se salta por presupuesto")
            continue
        path = settings.output_path / rec["id"] / storage.BRIEFING_FILE
        briefing = storage.load_briefing(path)
        t0 = time.perf_counter()
        verdict = llm.complete(JUDGE_SYSTEM, [{"role": "user", "content": judge_input(briefing, rec.get("portfolio_tickers"))}],
                               response_model=verdict_model)
        cost = costs.estimate_cost_eur(llm.provider_name, getattr(llm, "model", ""), **llm.last_usage)
        data = verdict.model_dump()
        for c in CRITERIA:
            data[c]["score"] = max(1, min(5, int(data[c]["score"])))
        results[rec["id"]] = {"scenario": rec["scenario"], "model": getattr(llm, "model", "?"),
                              "provider": llm.provider_name, "latency_s": round(time.perf_counter() - t0, 2),
                              "cost_eur": round(cost, 6), **data}
        JUDGE_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"juez {rec['scenario']}: " + " · ".join(f"{c} {data[c]['score']}" for c in CRITERIA) + f" · {cost:.4f} €")
    return results


# ── Agregados ────────────────────────────────────────────────────────────────────────


def metrics_report_for(records: list[dict[str, Any]]) -> dict[str, Any]:
    """``scripts/metrics_report.build_report`` sobre las carpetas de estos briefings (solo disco)."""
    import metrics_report as mr
    from briefer.config import get_settings

    out = get_settings().output_path
    col = mr.collect([out / r["id"] for r in records if r.get("id")])
    return mr.build_report(col, "real")


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--real", action="store_true", help="Generar/juzgar lo que falte (gasta dinero)")
    p.add_argument("--budget", type=float, default=BUDGET_EUR)
    args = p.parse_args(argv)
    configure_env()
    missing = check_scenarios()
    if missing:
        print("Tickers fuera de TICKER_UNIVERSE:", missing)
    recs = generate_all(args.real, args.budget)
    judge_all(args.real, recs, args.budget)
    print(f"Briefings: {sum(1 for r in recs if r.get('id'))} · gasto acumulado {spent_eur():.4f} €")
    return 0


if __name__ == "__main__":
    sys.exit(main())
