"""Widgets comunes: disclaimer, avisos de "pendiente", barra lateral y reproductores.

Carril C. Solo presentación: recibe schemas (``Briefing``, ``QAAnswer``) y los pinta.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from briefer import costs
from briefer.providers import registry
from briefer.schemas import DISCLAIMER_ES, Briefing, QAAnswer

SENTIMENT_LABEL = {"positivo": "▲ positivo", "negativo": "▼ negativo", "neutral": "● neutral"}


def show_disclaimer() -> None:
    """Aviso MiFID II visible en todas las páginas."""
    st.caption(f"Aviso: {DISCLAIMER_ES}")


def pending(exc: BaseException, what: str) -> None:
    """Mensaje amable para funcionalidades aún no implementadas."""
    st.info(f"Pendiente: {what}. Detalle técnico: `{exc}`")


def sidebar_controls() -> bool:
    """Barra lateral con el modo mock y la configuración activa. Devuelve ``use_mock``."""
    with st.sidebar:
        use_mock = st.toggle(
            "Modo demo (mocks, sin red ni claves)",
            value=st.session_state.get("use_mock", True),
            help="Usa proveedores falsos y datos de ejemplo. Desactívalo para usar las APIs de .env.",
        )
        st.session_state["use_mock"] = use_mock
        with st.expander("Proveedores configurados"):
            try:
                for name, value in registry.describe_providers().items():
                    st.write(f"**{name}:** {value}")
            except Exception as exc:  # .env mal formado
                st.error(f"Configuración inválida: {exc}")
    return use_mock


def _exists(path: Path | None) -> bool:
    return path is not None and Path(path).exists()


def render_briefing(briefing: Briefing) -> None:
    """Pinta un briefing completo: titular, audio, puntos clave, gráficos, vídeo, métricas."""
    a = briefing.analysis
    st.subheader(a.headline)
    st.caption(f"{a.date:%d/%m/%Y} · Tono del mercado: {a.market_mood}")

    if briefing.cover_path and _exists(briefing.cover_path):
        st.image(str(briefing.cover_path))

    if briefing.audio and _exists(briefing.audio.path):
        st.audio(str(briefing.audio.path))

    tab_points, tab_transcript, tab_charts, tab_video, tab_metrics = st.tabs(
        ["Puntos clave", "Transcripción", "Gráficos", "Vídeo", "Costes y latencia"]
    )
    with tab_points:
        for kp in a.key_points:
            with st.container(border=True):
                st.markdown(f"**{kp.title}** — {SENTIMENT_LABEL.get(kp.sentiment, kp.sentiment)}")
                st.write(kp.explanation)
                if kp.tickers:
                    st.caption("Tickers: " + ", ".join(kp.tickers))
                if kp.sources:
                    st.caption("Fuentes: " + ", ".join(kp.sources))
    with tab_transcript:
        if briefing.transcript:
            st.text(briefing.transcript.text)
            if _exists(briefing.transcript.srt_path):
                st.download_button(
                    "Descargar subtítulos (.srt)",
                    Path(briefing.transcript.srt_path).read_bytes(),
                    file_name="podcast.srt",
                )
        else:
            st.write("Sin transcripción.")
    with tab_charts:
        images = [c for c in briefing.charts if _exists(c.path)]
        if images:
            cols = st.columns(2)
            for i, chart in enumerate(images):
                cols[i % 2].image(str(chart.path), caption=chart.ticker or chart.kind)
        else:
            st.write("Sin gráficos.")
    with tab_video:
        if briefing.video and _exists(briefing.video.path):
            st.video(str(briefing.video.path))
        else:
            st.write("No se generó vídeo para este briefing.")
    with tab_metrics:
        st.dataframe([m.model_dump() for m in briefing.metrics])
        st.write(costs.summarize_metrics(briefing.metrics))

    show_disclaimer()


def render_qa_answer(answer: QAAnswer) -> None:
    """Pinta la respuesta del Agente Q&A (texto, audio y fuentes)."""
    st.markdown(f"**Pregunta:** {answer.question}")
    st.markdown(answer.answer_text)
    if _exists(answer.audio_path):
        st.audio(str(answer.audio_path))
    if answer.sources:
        st.caption("Fuentes: " + ", ".join(answer.sources))
