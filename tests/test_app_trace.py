"""Traza «Cómo se hizo»: funciones puras de ``app/components/trace.py`` y ``render_trace`` con AppTest."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.trace import (  # noqa: E402
    COLORS,
    TRACE_COLORS,
    TRACE_LEGEND,
    build_edges,
    build_nodes,
    build_trace_dot,
    is_demo_run,
    node_label,
    step_status,
    trace_legend_text,
    trace_summary,
)

from briefer.schemas import StepMetric  # noqa: E402


def _m(step: str, provider: str, model: str = "-", latency: float = 0.1, cost: float = 0.0,
       error: str | None = None) -> StepMetric:
    return StepMetric(step=step, provider=provider, model=model, latency_s=latency, est_cost_eur=cost, error=error)


REAL_RUN = [
    _m("ingest.news", "yfinance+rss", latency=1.2),
    _m("ingest.tickers", "local"),
    _m("ingest.prices", "yfinance", latency=0.8),
    _m("ingest.chart", "anthropic", "claude-sonnet-5-5", 4.1, 0.004),
    _m("agents.analyst", "anthropic", "claude-sonnet-5-5", 12.3, 0.031),
    _m("agents.scriptwriter", "mock", "mock-llm", 0.01, 0.0, error="APIStatusError: 529 overloaded"),
    _m("media.podcast", "edge", "edge-tts", 17.4),
    _m("media.transcript", "local"),
    _m("media.charts", "matplotlib", latency=0.9),
    _m("media.video", "moviepy", latency=0.2, error="RuntimeError: ffmpeg falló"),
    _m("delivery.telegram", "telegram"),
    _m("storage.save", "local"),
]

DEMO_RUN = [
    _m("ingest.news", "samples"),
    _m("ingest.tickers", "local"),
    _m("ingest.prices", "synthetic"),
    _m("agents.analyst", "mock", "mock-llm"),
    _m("agents.scriptwriter", "mock", "mock-llm"),
    _m("media.podcast", "mock", "mock-tts"),
    _m("media.transcript", "local"),
    _m("media.charts", "matplotlib"),
    _m("storage.save", "local"),
]


def _steps_of_edges(metrics: list[StepMetric]) -> set[tuple[str, str]]:
    nodes = build_nodes(metrics)
    by_id = {n.node_id: n.metric.step for n in nodes}
    return {(by_id[a], by_id[b]) for a, b in build_edges(nodes)}


def test_demo_run_detection() -> None:
    assert is_demo_run(DEMO_RUN)
    assert not is_demo_run(REAL_RUN)
    assert not is_demo_run([])


def test_step_status_real_run() -> None:
    status = {n.metric.step: n.status for n in build_nodes(REAL_RUN)}
    assert status["agents.analyst"] == "real"
    assert status["media.podcast"] == "real"
    assert status["agents.scriptwriter"] == "fallback"   # mock + error = cayó a mock
    assert status["media.video"] == "error"              # opcional omitido
    assert status["ingest.tickers"] == "local"
    assert status["media.charts"] == "local"


def test_step_status_demo_run() -> None:
    assert {n.status for n in build_nodes(DEMO_RUN) if n.metric.provider == "mock"} == {"mock"}
    assert step_status(_m("media.cover", "mock", error="X: y"), demo_run=True) == "error"
    assert step_status(_m("ingest.chart", "mock"), demo_run=False) == "mock"  # configurado como mock


def test_edges_follow_the_pipeline_data_flow() -> None:
    edges = _steps_of_edges(REAL_RUN)
    for edge in [
        ("ingest.news", "ingest.tickers"),
        ("ingest.tickers", "agents.analyst"),
        ("ingest.prices", "agents.analyst"),
        ("ingest.chart", "agents.analyst"),
        ("agents.analyst", "agents.scriptwriter"),
        ("agents.scriptwriter", "media.podcast"),
        ("media.podcast", "media.transcript"),
        ("ingest.prices", "media.charts"),
        ("media.transcript", "media.video"),
        ("media.charts", "media.video"),
        ("media.video", "delivery.telegram"),
        ("delivery.telegram", "storage.save"),
    ]:
        assert edge in edges, edge
    # Aristas transitivas redundantes eliminadas (podcast -> vídeo ya pasa por la transcripción)
    assert ("media.podcast", "media.video") not in edges
    assert ("ingest.news", "agents.analyst") not in edges


def test_repeated_steps_get_unique_nodes() -> None:
    metrics = [_m("ingest.pdf", "anthropic", "claude"), _m("ingest.pdf", "anthropic", "claude"),
               _m("agents.analyst", "anthropic", "claude")]
    nodes = build_nodes(metrics)
    assert len({n.node_id for n in nodes}) == 3
    assert len(_steps_of_edges(metrics)) == 1  # ambos PDF -> analista (mismo par de pasos)
    assert len(build_edges(nodes)) == 2


def test_node_label_has_provider_model_latency_cost() -> None:
    node = build_nodes([_m("agents.analyst", "anthropic", "claude-sonnet-5-5", 12.345, 0.0312)])[0]
    label = node_label(node)
    assert "Agente Analista" in label
    assert "anthropic · claude-sonnet-5-5" in label
    assert "12.35 s" in label and "0.0312 €" in label


def test_dot_is_well_formed_and_marks_incidents() -> None:
    dot = build_trace_dot(REAL_RUN)
    assert dot.startswith("digraph briefing {") and dot.rstrip().endswith("}")
    assert dot.count("{") == dot.count("}")
    assert "cluster_agents" in dot and "cluster_media" in dot
    assert "CAÍDO A MOCK" in dot and "ERROR" in dot
    assert dot.count("->") == len(build_edges(build_nodes(REAL_RUN)))


def _node_attrs(dot: str) -> dict[str, str]:
    """``node_id`` -> atributos del nodo (texto entre corchetes) de las líneas de nodo del DOT."""
    return {m.group(1): m.group(2) for m in re.finditer(r"^\s*(n\d+) \[(.*)\];$", dot, re.MULTILINE)}


def test_dot_dark_theme_colors_by_status() -> None:
    dot = build_trace_dot(REAL_RUN)
    assert 'bgcolor="transparent"' in dot
    assert 'fontname="monospace"' in dot
    assert f'fontcolor="{TRACE_COLORS["text"]}"' in dot          # texto claro #D6DEE8
    assert f'fontcolor="{TRACE_COLORS["stage_label"]}"' in dot   # etiqueta ámbar de las etapas
    assert f'color="{TRACE_COLORS["border"]}"' in dot            # borde de los clusters
    assert 'edge [color="#888780"' in dot
    nodes = build_nodes(REAL_RUN)
    attrs = _node_attrs(dot)
    assert set(attrs) == {n.node_id for n in nodes}
    expected = {"real": "#5DCAA5", "fallback": "#EF9F27", "error": "#F09595", "local": "#888780"}
    for n in nodes:
        assert 'fillcolor="#1C2129"' in attrs[n.node_id]
        assert f'color="{expected[n.status]}"' in attrs[n.node_id], (n.metric.step, n.status)
    # Ningún color del tema claro anterior
    for old in ("#d8f3dc", "#ffe8cc", "#ffe3e3", "#e7f5ff", "Helvetica"):
        assert old not in dot


def test_dot_mock_nodes_are_grey_dashed() -> None:
    dot = build_trace_dot(DEMO_RUN)
    attrs = _node_attrs(dot)
    for n in build_nodes(DEMO_RUN):
        if n.status == "mock":
            assert 'color="#888780"' in attrs[n.node_id] and "dashed" in attrs[n.node_id]


def test_dot_structure_is_valid() -> None:
    """Validación estructural del DOT (con el paquete ``graphviz`` si está, si no con regex)."""
    dot = build_trace_dot(REAL_RUN)
    lines = [ln.strip() for ln in dot.splitlines()]
    assert lines[0] == "digraph briefing {" and lines[-1] == "}"
    depth = 0
    for ln in lines:
        depth += ln.count("{") - ln.count("}")
        assert depth >= 0
    assert depth == 0
    # Comillas equilibradas (sin contar las escapadas) en cada línea
    for ln in lines:
        assert ln.replace('\\"', "").count('"') % 2 == 0, ln
    ids = set(_node_attrs(dot))
    for a, b in re.findall(r"^\s*(n\d+) -> (n\d+);$", dot, re.MULTILINE):
        assert a in ids and b in ids
    try:
        import graphviz  # type: ignore[import-not-found]
    except ImportError:
        return
    assert graphviz.Source(dot).source == dot


def test_colors_and_legend_cover_every_status() -> None:
    statuses = {"real", "mock", "fallback", "error", "local"}
    assert set(COLORS) == statuses
    assert {s for s, _, _ in TRACE_LEGEND} == statuses
    text = trace_legend_text()
    assert "<" not in text and ">" not in text  # texto plano, sin HTML
    assert "verde" in text and "ámbar" in text and "rojo" in text and "gris" in text


def test_dot_escapes_quotes() -> None:
    dot = build_trace_dot([_m("agents.analyst", "x", 'mod"elo')])
    assert 'mod\\"elo' in dot


def test_trace_summary() -> None:
    summary = trace_summary(REAL_RUN)
    assert summary["steps"] == len(REAL_RUN)
    assert summary["ai_models"] == 3  # claude, mock-llm, edge-tts
    assert summary["fallbacks"] == 1 and summary["errors"] == 1
    assert summary["total_cost_eur"] == pytest.approx(0.035)


# ── render_trace con AppTest ───────────────────────────────────────────────────────


def _trace_app(app_dir: str) -> None:
    import sys

    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    import streamlit as st
    from components.players import render_trace

    render_trace(st.session_state["metrics"])


def _run_trace(metrics: list[StepMetric]):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_trace_app, args=(str(APP_DIR),), default_timeout=30)
    at.session_state["metrics"] = metrics
    return at.run()


def test_render_trace_apptest_real_run() -> None:
    at = _run_trace(REAL_RUN)
    assert not at.exception
    charts = at.get("graphviz_chart")
    assert len(charts) == 1
    assert "Agente Analista" in charts[0].proto.spec
    labels = [m.label for m in at.metric]
    assert labels == ["Modelos de IA", "Pasos", "Latencia (suma)", "Coste estimado"]
    assert at.metric[0].value == "3"
    assert len(at.dataframe) == 1
    assert any("caída(s) a mock" in c.value for c in at.caption)


def test_render_trace_apptest_empty() -> None:
    at = _run_trace([])
    assert not at.exception
    assert any("no tiene métricas" in i.value for i in at.info)
