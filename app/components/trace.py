"""Traza «Cómo se hizo»: grafo de la cadena de modelos de un briefing (funciones puras).

Carril C. A partir de ``Briefing.metrics`` (``StepMetric``: paso, proveedor, modelo, latencia,
coste y error) construye un grafo en lenguaje DOT que ``st.graphviz_chart`` pinta en el
navegador (no hace falta el paquete ``graphviz`` de Python ni el binario ``dot``).

- Cada paso es un nodo con proveedor/modelo, latencia y coste estimado.
- Las aristas siguen el flujo de datos real del pipeline (``STEP_DEPENDENCIES``): noticias →
  filtro por tickers → Analista → Guionista → TTS → transcripción; precios → gráficos; subidas
  (PDF, gráfico, voz) → Analista; todo → vídeo / entrega → guardado.
- Colores: verde = proveedor real · gris = mock en un briefing de demo · naranja = paso que cayó
  a un sustituto (mock, ``data/samples``, precios sintéticos, guion de respaldo) en un briefing real
  · rojo = paso con error.
- ``StepMetric.detail`` (v0.3: grounding de cifras, reintentos, noticias filtradas…) se añade al
  nodo (recortado) y entero a la tabla.

Sin dependencias de Streamlit: se prueba en ``tests/test_app_trace.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase

from briefer.logging_utils import step_fell_back
from briefer.schemas import StepMetric

# Paso -> pasos de los que recibe datos (patrones fnmatch). Solo se dibujan si ambos existen.
STEP_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "ingest.tickers": ("ingest.news",),
    "agents.analyst": ("ingest.tickers", "ingest.prices", "ingest.pdf", "ingest.chart", "ingest.voice",
                       "ingest.upload"),
    "agents.scriptwriter": ("agents.analyst",),
    "media.podcast": ("agents.scriptwriter",),
    "media.transcript": ("media.podcast",),
    "media.verify": ("media.podcast",),
    "media.charts": ("ingest.prices",),
    "media.cover": ("agents.analyst",),
    "media.video": ("media.podcast", "media.transcript", "media.charts", "media.cover"),
    "delivery.*": ("media.podcast", "media.transcript", "media.charts", "media.video", "media.cover"),
    "storage.save": ("delivery.*", "media.*"),
    "agents.qa": ("qa.stt",),
    "qa.tts": ("agents.qa",),
}

# Grupos visuales (subgrafos) por prefijo del paso.
STAGES: tuple[tuple[str, str], ...] = (
    ("ingest", "Entradas y procesado"),
    ("qa", "Pregunta"),
    ("agents", "Agentes IA"),
    ("media", "Salidas multimodales"),
    ("delivery", "Entrega"),
    ("storage", "Persistencia"),
)

# Proveedores que no son modelos de IA (no cuentan como «modelo» en el resumen).
NON_AI_PROVIDERS = {"local", "matplotlib", "ffmpeg", "moviepy", "email", "samples", "synthetic", "yfinance", "yfinance+rss",
                    "rss", "disk", "storage", "smtp", "telegram", "web", "-", ""}

STEP_LABELS: dict[str, str] = {
    "ingest.news": "Noticias",
    "ingest.tickers": "Filtro por tickers",
    "ingest.prices": "Precios",
    "ingest.pdf": "Lectura de PDF",
    "ingest.chart": "Lectura de gráfico",
    "ingest.voice": "Nota de voz",
    "ingest.upload": "Subida",
    "agents.analyst": "Agente Analista",
    "agents.scriptwriter": "Agente Guionista",
    "agents.qa": "Agente Q&A",
    "media.podcast": "Podcast 2 voces (TTS)",
    "media.transcript": "Transcripción / SRT",
    "media.verify": "Verificación STT",
    "media.charts": "Gráficos",
    "media.cover": "Portada IA",
    "media.video": "Vídeo",
    "storage.save": "Guardado",
    "qa.stt": "Voz a texto",
    "qa.tts": "Respuesta hablada",
}

#: Longitud máxima de ``StepMetric.detail`` dentro de un nodo del grafo (la tabla lo muestra entero).
DETAIL_MAX_CHARS = 60

COLORS = {
    "real": ("#d8f3dc", "#2d6a4f"),
    "mock": ("#eeeeee", "#6c757d"),
    "fallback": ("#ffe8cc", "#d9480f"),
    "error": ("#ffe3e3", "#c92a2a"),
    "local": ("#e7f5ff", "#1c7ed6"),
}


@dataclass(frozen=True)
class TraceNode:
    """Un paso del briefing tal y como se dibuja en la traza."""

    node_id: str
    metric: StepMetric
    status: str  # "real" | "mock" | "fallback" | "error" | "local"


def is_ai_step(metric: StepMetric) -> bool:
    """True si el paso lo ejecuta un modelo de IA (real o mock), no una librería local."""
    return metric.provider not in NON_AI_PROVIDERS


#: Pasos de voz sintética: en la demo «sin claves» (``mode="demo_voices"``) son edge-tts real.
VOICE_STEPS = {"media.podcast", "qa.tts"}


def is_demo_run(metrics: Sequence[StepMetric]) -> bool:
    """True si todos los pasos de IA usaron mock (briefing de demo, mock esperado).

    La demo «sin claves» con voces reales (solo el TTS es real) también cuenta como demo.
    """
    ai = [m for m in metrics if is_ai_step(m) and not (m.step in VOICE_STEPS and m.provider != "mock")]
    return bool(ai) and all(m.provider == "mock" for m in ai)


def has_real_voices(metrics: Sequence[StepMetric]) -> bool:
    """True si el audio se sintetizó con un TTS real (edge-tts…) sin caer a mock."""
    return any(m.step in VOICE_STEPS and m.provider not in ("mock", *NON_AI_PROVIDERS) for m in metrics)


def step_status(metric: StepMetric, demo_run: bool) -> str:
    """Estado visual de un paso.

    - ``fallback``: el proveedor real falló y el paso se completó con un sustituto: mock, noticias
      de ``data/samples``, precios sintéticos o guion de respaldo (``logging_utils.step_fell_back``:
      ``error`` empieza por ``"Fallback a "``). También, por compatibilidad, ``provider == "mock"``
      con ``error`` en un briefing no-demo.
    - ``error``: el paso falló y se omitió (``error`` relleno, sin sustituto).
    - ``mock``: proveedor simulado sin incidencias (demo, o familia configurada como mock).
    - ``real`` (modelo de IA real) / ``local`` (librería sin IA: filtro, gráficos, guardado…).
    """
    if metric.error:
        if step_fell_back(metric):
            return "fallback"
        return "fallback" if metric.provider == "mock" and not demo_run else "error"
    if metric.provider == "mock":
        return "mock"
    return "real" if is_ai_step(metric) else "local"


def build_nodes(metrics: Iterable[StepMetric]) -> list[TraceNode]:
    """Nodos de la traza, uno por ``StepMetric`` (ids únicos aunque un paso se repita)."""
    items = list(metrics)
    demo = is_demo_run(items)
    nodes: list[TraceNode] = []
    for i, m in enumerate(items):
        nodes.append(TraceNode(node_id=f"n{i}", metric=m, status=step_status(m, demo)))
    return nodes


def _matches(step: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(step, p) for p in patterns)


def build_edges(nodes: Sequence[TraceNode]) -> list[tuple[str, str]]:
    """Aristas ``(origen, destino)`` según ``STEP_DEPENDENCIES`` entre los pasos presentes."""
    edges: list[tuple[str, str]] = []
    for target in nodes:
        deps = next((d for pat, d in STEP_DEPENDENCIES.items() if fnmatchcase(target.metric.step, pat)), ())
        if not deps:
            continue
        for source in nodes:
            if source is target or source.metric.step == target.metric.step:
                continue
            if _matches(source.metric.step, deps):
                edges.append((source.node_id, target.node_id))
    # «storage.save» depende de «media.*»: si hay entrega, basta con la arista desde la entrega.
    return _prune_transitive(nodes, edges)


def _prune_transitive(nodes: Sequence[TraceNode], edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Quita aristas redundantes A→C cuando ya existe un camino A→…→C (grafo más legible)."""
    succ: dict[str, set[str]] = {}
    for a, b in edges:
        succ.setdefault(a, set()).add(b)

    def reachable(start: str, goal: str, skip: tuple[str, str]) -> bool:
        stack, seen = [start], set()
        while stack:
            cur = stack.pop()
            for nxt in succ.get(cur, ()):
                if (cur, nxt) == skip or nxt in seen:
                    continue
                if nxt == goal:
                    return True
                seen.add(nxt)
                stack.append(nxt)
        return False

    return [e for e in edges if not reachable(e[0], e[1], skip=e)]


def _esc(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def node_label(node: TraceNode) -> str:
    """Etiqueta multilínea: nombre del paso, proveedor · modelo, latencia y coste."""
    m = node.metric
    title = STEP_LABELS.get(m.step, m.step)
    who = m.provider if m.model in ("", "-") else f"{m.provider} · {m.model}"
    lines = [title, who, f"{m.latency_s:.2f} s · {m.est_cost_eur:.4f} €"]
    if m.detail:
        lines.append(_short(m.detail))
    if node.status == "fallback":
        lines.append(fallback_tag(m))
    elif node.status == "error":
        lines.append("ERROR")
    return "\\n".join(_esc(x) for x in lines)


def _short(text: str, max_chars: int = DETAIL_MAX_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def fallback_tag(metric: StepMetric) -> str:
    """Etiqueta corta del sustituto usado: «CAÍDO A MOCK», «DATOS DE EJEMPLO», «PRECIOS SINTÉTICOS»…"""
    provider = metric.provider
    if provider == "samples":
        return "DATOS DE EJEMPLO (sustituto)"
    if provider == "synthetic":
        return "PRECIOS SINTÉTICOS (sustituto)"
    if provider == "local":
        return "GUION DE RESPALDO"
    return "CAÍDO A MOCK"


def build_trace_dot(metrics: Iterable[StepMetric], *, rankdir: str = "LR") -> str:
    """Grafo DOT de la cadena de modelos de un briefing (o de una pregunta Q&A)."""
    nodes = build_nodes(metrics)
    out = [
        "digraph briefing {",
        f'  rankdir="{rankdir}";',
        '  graph [fontname="Helvetica", fontsize=11, nodesep=0.25, ranksep=0.45];',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
        '  edge [color="#868e96", arrowsize=0.7];',
    ]
    for prefix, label in STAGES:
        members = [n for n in nodes if n.metric.step.split(".", 1)[0] == prefix]
        if not members:
            continue
        out.append(f"  subgraph cluster_{prefix} {{")
        out.append(f'    label="{_esc(label)}"; style="rounded,dashed"; color="#adb5bd";')
        for n in members:
            fill, border = COLORS[n.status]
            out.append(f'    {n.node_id} [label="{node_label(n)}", fillcolor="{fill}", color="{border}"];')
        out.append("  }")
    grouped = {p for p, _ in STAGES}
    for n in nodes:
        if n.metric.step.split(".", 1)[0] not in grouped:
            fill, border = COLORS[n.status]
            out.append(f'  {n.node_id} [label="{node_label(n)}", fillcolor="{fill}", color="{border}"];')
    for a, b in build_edges(nodes):
        out.append(f"  {a} -> {b};")
    out.append("}")
    return "\n".join(out)


def trace_summary(metrics: Iterable[StepMetric]) -> dict[str, float | int]:
    """Resumen para la franja «Cómo se hizo»: pasos, modelos de IA distintos, latencia y coste."""
    items = list(metrics)
    models = {(m.provider, m.model) for m in items if is_ai_step(m)}
    demo = is_demo_run(items)
    return {
        "steps": len(items),
        "ai_models": len(models),
        "total_latency_s": round(sum(m.latency_s for m in items), 2),
        "total_cost_eur": round(sum(m.est_cost_eur for m in items), 4),
        "fallbacks": sum(1 for m in items if step_status(m, demo) == "fallback"),
        "errors": sum(1 for m in items if step_status(m, demo) == "error"),
    }


__all__ = [
    "STEP_DEPENDENCIES",
    "TraceNode",
    "build_edges",
    "build_nodes",
    "build_trace_dot",
    "fallback_tag",
    "has_real_voices",
    "is_ai_step",
    "is_demo_run",
    "node_label",
    "step_status",
    "trace_summary",
]
