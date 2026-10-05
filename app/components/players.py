"""Widgets comunes: disclaimer, avisos de "pendiente", barra lateral y reproductores.

Carril C. Solo presentación: recibe schemas (``Briefing``, ``QAAnswer``) y los pinta. No
instancia proveedores ni llama a modelos (eso es cosa de ``briefer.pipeline``).
"""

from __future__ import annotations

import traceback
from pathlib import Path

import streamlit as st

from briefer import costs
from briefer.providers import registry
from briefer.schemas import DISCLAIMER_ES, Briefing, ChartAsset, NewsItem, QAAnswer, StepMetric

SENTIMENT_LABEL = {"positivo": "▲ positivo", "negativo": "▼ negativo", "neutral": "● neutral"}
SENTIMENT_BADGE = {"positivo": "blue", "negativo": "red", "neutral": "gray"}
SYNTHETIC_VOICE_NOTE = (
    "Las voces de este podcast son **sintéticas** (generadas con IA); no son personas reales."
)
CHART_KIND_LABEL = {
    "overview_bar": "Variación del día",
    "price_line": "Cotización",
    "portfolio_pie": "Reparto de la cartera",
}


def show_disclaimer() -> None:
    """Aviso MiFID II visible en todas las páginas."""
    st.caption(f"Aviso: {DISCLAIMER_ES}")


def pending(exc: BaseException, what: str) -> None:
    """Mensaje amable para funcionalidades aún no implementadas (sin traceback)."""
    st.info(
        f"**Pendiente:** {what}. Esta parte todavía se está desarrollando; el resto de la app "
        f"sigue funcionando.\n\nDetalle técnico: `{exc}`"
    )


def show_error(exc: BaseException, what: str) -> None:
    """Error real mostrado de forma amigable; el traceback queda plegado para depurar."""
    st.error(f"No se pudo completar {what}: {exc}")
    with st.expander("Detalle técnico"):
        st.code("".join(traceback.format_exception(exc)), language="text")


def sidebar_controls() -> bool:
    """Barra lateral con el modo mock y la configuración activa. Devuelve ``use_mock``."""
    with st.sidebar:
        use_mock = st.toggle(
            "Modo demo (mocks, sin red ni claves)",
            value=st.session_state.get("use_mock", True),
            help="Usa proveedores falsos y datos de ejemplo. Desactívalo para usar las APIs de .env.",
        )
        st.session_state["use_mock"] = use_mock
        if use_mock:
            st.caption("Modo demo activo: noticias de ejemplo, precios sintéticos y voces de prueba.")
        portfolio = st.session_state.get("portfolio")
        if portfolio is not None:
            st.caption(f"Cartera cargada: «{portfolio.name}» ({len(portfolio.positions)} posiciones)")
        with st.expander("Proveedores configurados"):
            try:
                for name, value in registry.describe_providers().items():
                    st.write(f"**{name}:** {value}")
            except Exception as exc:  # .env mal formado
                st.error(f"Configuración inválida: {exc}")
    return use_mock


# Claves de ``registry.describe_providers`` que corresponden a proveedores de IA.
_AI_PROVIDER_KEYS = ("LLM", "Visión", "Voz a texto", "Texto a voz", "Imagen", "Clasificador")


def mock_providers(use_mock: bool) -> list[str]:
    """Nombres legibles de los proveedores de IA que irán en mock.

    Con ``use_mock`` son todos (el pipeline fuerza mocks); si no, los configurados como
    ``mock`` en ``.env`` (vía ``registry.describe_providers``, sin instanciar nada).
    """
    if use_mock:
        return list(_AI_PROVIDER_KEYS)
    try:
        described = registry.describe_providers()
    except Exception:  # .env mal formado: lo avisa ya la barra lateral
        return []
    return [k for k in _AI_PROVIDER_KEYS if str(described.get(k, "")).split(" ", 1)[0] == "mock"]


def demo_mode_banner(use_mock: bool) -> None:
    """Insignia visible «MODO DEMO (mock)» y qué proveedores de IA están simulados."""
    mocked = mock_providers(use_mock)
    if use_mock:
        st.markdown(":orange-background[**MODO DEMO (mock)**] · sin red ni claves")
        st.caption(
            "Proveedores en mock: " + ", ".join(mocked) + ". Noticias de ejemplo y precios "
            "sintéticos: los contenidos son ficticios."
        )
    elif mocked:
        st.markdown(":orange-background[**MODO MIXTO**] · algunos proveedores son simulados")
        st.caption("Proveedores en mock (según `.env`): " + ", ".join(mocked) + ".")


def failed_steps(metrics: list[StepMetric]) -> list[StepMetric]:
    """Pasos que lanzaron una excepción (``StepMetric.error``, contrato v0.2)."""
    return [m for m in metrics if m.error]


def render_run_warnings(briefing: Briefing) -> None:
    """Aviso si algún paso opcional falló o alguna entrega quedó con ``ok=False``."""
    failed = failed_steps(briefing.metrics)
    bad_deliveries = [d for d in briefing.deliveries if not d.ok]
    if failed:
        lines = "\n".join(f"- `{m.step}` ({m.provider}): {m.error}" for m in failed)
        st.warning(
            f"**{len(failed)} paso(s) opcional(es) fallaron**; el briefing se generó sin ellos:\n{lines}"
        )
    if bad_deliveries:
        lines = "\n".join(f"- {d.channel}: {d.detail or 'error'}" for d in bad_deliveries)
        st.warning(f"**Entregas fallidas:**\n{lines}")
    used_mock = sorted({m.step.split(".", 1)[0] for m in briefing.metrics if m.provider == "mock"})
    if used_mock:
        st.caption("Este briefing usó proveedores simulados (mock) en: " + ", ".join(used_mock) + ".")


def _exists(path: Path | None) -> bool:
    return path is not None and Path(path).exists()


def _news_index(briefing: Briefing) -> dict[str, NewsItem]:
    index: dict[str, NewsItem] = {}
    for item in briefing.context.news:
        index[item.id] = item
        index[item.url] = item
    return index


def format_source(source: str, news: dict[str, NewsItem]) -> str:
    """Markdown de una fuente: enlace a la noticia si se conoce, si no el texto tal cual."""
    item = news.get(source)
    if item is not None:
        title = item.title.replace("[", "(").replace("]", ")")
        return f"[{title}]({item.url}) · {item.source}"
    if source.startswith(("http://", "https://")):
        return f"[{source}]({source})"
    return source


def chart_caption(chart: ChartAsset) -> str:
    """Pie de figura legible para un gráfico."""
    label = CHART_KIND_LABEL.get(chart.kind, chart.kind)
    return f"{label} · {chart.ticker}" if chart.ticker else label


def _fmt_duration(seconds: float) -> str:
    mins, secs = divmod(int(round(seconds)), 60)
    return f"{mins}:{secs:02d}"


def render_metrics(briefing: Briefing) -> None:
    """Tabla de latencia y coste estimado por paso, con totales."""
    if not briefing.metrics:
        st.write("Sin métricas registradas.")
        return
    summary = costs.summarize_metrics(briefing.metrics)
    c1, c2, c3 = st.columns(3)
    c1.metric("Pasos", int(summary.get("steps", len(briefing.metrics))))
    c2.metric("Latencia total", f"{summary.get('total_latency_s', 0.0):.2f} s")
    c3.metric("Coste estimado", f"{summary.get('total_cost_eur', 0.0):.4f} €")
    render_metrics_table(briefing.metrics)
    st.caption("Costes estimados con las tarifas de `costs.py` (no son facturas reales).")


def render_metrics_table(metrics: list[StepMetric]) -> None:
    """Tabla de pasos con estado (OK / error) a partir de ``StepMetric.error``."""
    rows = [
        {
            "Paso": m.step,
            "Estado": "OK" if not m.error else "ERROR",
            "Proveedor": m.provider,
            "Modelo": m.model,
            "Latencia (s)": round(m.latency_s, 3),
            "Coste est. (€)": round(m.est_cost_eur, 5),
            "Error": m.error or "",
        }
        for m in metrics
    ]
    st.dataframe(rows, hide_index=True)
    n_failed = len(failed_steps(metrics))
    if n_failed:
        st.caption(f"{n_failed} paso(s) con error (columna «Error»).")


def render_briefing(briefing: Briefing, key: str = "briefing") -> None:
    """Pinta un briefing completo: titular, audio, puntos clave, transcripción, gráficos, métricas.

    ``key`` distingue los widgets si se pinta más de un briefing en la misma página.
    """
    a = briefing.analysis
    st.subheader(a.headline)
    st.caption(f"{a.date:%d/%m/%Y} · Generado {briefing.created_at:%d/%m/%Y %H:%M} · id `{briefing.id}`")
    st.markdown(f"**Tono del mercado:** {a.market_mood}")
    render_run_warnings(briefing)

    if briefing.cover_path and _exists(briefing.cover_path):
        st.image(str(briefing.cover_path))

    # ── Podcast ──
    st.markdown("#### Podcast")
    if briefing.audio and _exists(briefing.audio.path):
        audio_path = Path(briefing.audio.path)
        st.audio(str(audio_path))
        st.caption(
            f"{briefing.script.title} · {_fmt_duration(briefing.audio.duration_s)} min · "
            f"{len(briefing.audio.segments)} intervenciones"
        )
        st.info(SYNTHETIC_VOICE_NOTE)
        st.download_button(
            "Descargar audio",
            audio_path.read_bytes(),
            file_name=f"market_briefer_{briefing.id}{audio_path.suffix}",
            key=f"{key}_dl_audio",
        )
    else:
        st.write("Este briefing no tiene audio disponible.")

    # ── Puntos clave ──
    st.markdown("#### Puntos clave")
    news = _news_index(briefing)
    if not a.key_points:
        st.write("Sin puntos clave.")
    for kp in a.key_points:
        with st.container(border=True):
            badge = SENTIMENT_BADGE.get(kp.sentiment, "gray")
            label = SENTIMENT_LABEL.get(kp.sentiment, kp.sentiment)
            st.markdown(f"**{kp.title}** — :{badge}[{label}]")
            st.write(kp.explanation)
            if kp.tickers:
                st.caption("Valores: " + ", ".join(kp.tickers))
            if kp.sources:
                st.markdown("Fuentes: " + " · ".join(format_source(s, news) for s in kp.sources))

    # ── Transcripción ──
    with st.expander("Transcripción del podcast"):
        if briefing.transcript:
            st.text(briefing.transcript.text)
            if _exists(briefing.transcript.srt_path):
                st.download_button(
                    "Descargar subtítulos (.srt)",
                    Path(briefing.transcript.srt_path).read_bytes(),
                    file_name=f"market_briefer_{briefing.id}.srt",
                    key=f"{key}_dl_srt",
                )
        else:
            st.write("Sin transcripción.")

    # ── Gráficos ──
    st.markdown("#### Gráficos del día")
    images = [c for c in briefing.charts if _exists(c.path)]
    if images:
        cols = st.columns(2)
        for i, chart in enumerate(images):
            cols[i % 2].image(str(chart.path), caption=chart_caption(chart))
    else:
        st.write("Sin gráficos.")

    if briefing.video and _exists(briefing.video.path):
        st.markdown("#### Vídeo")
        st.video(str(briefing.video.path))

    # ── Métricas y entrega ──
    with st.expander("Costes y latencia por paso"):
        render_metrics(briefing)
    for d in briefing.deliveries:
        if d.channel == "web" or not d.ok:  # las fallidas ya se avisan arriba (render_run_warnings)
            continue
        st.success(f"Entrega por {d.channel}: {d.detail or 'OK'}")

    st.warning(f"**Aviso:** {a.disclaimer or DISCLAIMER_ES}")


def render_qa_answer(answer: QAAnswer) -> None:
    """Pinta la respuesta del Agente Q&A (texto, audio y fuentes)."""
    st.markdown(f"**Pregunta:** {answer.question}")
    st.markdown(answer.answer_text)
    if _exists(answer.audio_path):
        st.audio(str(answer.audio_path))
        st.caption("Respuesta leída con voz sintética.")
    if answer.sources:
        st.caption("Fuentes: " + ", ".join(answer.sources))
    if answer.metrics:
        total = sum(m.latency_s for m in answer.metrics)
        detail = " · ".join(
            f"{m.step} {m.latency_s:.2f} s" + (" (error)" if m.error else "") for m in answer.metrics
        )
        st.caption(f"Latencia total: {total:.2f} s ({detail})")
