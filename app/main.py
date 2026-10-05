"""Portada de la app Streamlit (carril C). Lanzar con: ``streamlit run app/main.py``.

Las páginas de ``app/pages/`` aparecen automáticamente en la barra lateral.

«Demo que nunca falla»: al abrir, la portada enseña sin pulsar nada el último briefing guardado
(``data/outputs``) o, si no hay, el pregenerado versionado en ``data/samples/demo_briefing/``
(``storage.load_featured_briefing``). Si no existe ninguno, lo explica y ofrece generar uno.
"""

from __future__ import annotations

import components  # noqa: F401  (añade src/ al sys.path)
from components import ROOT_DIR
import streamlit as st
from components.players import render_featured_briefing, show_disclaimer, sidebar_controls

from briefer import storage
from briefer.schemas import DISCLAIMER_ES

st.set_page_config(page_title="Market Briefer", layout="wide")

sidebar_controls()

st.title("Market Briefer")
st.markdown(
    "#### Tu briefing de mercados en formato podcast, cada mañana\n"
    "Noticias filtradas por tu cartera, interpretadas por IA y contadas a **dos voces sintéticas**, "
    "con transcripción, gráficos del día y vídeo corto. Sube un PDF de resultados o una captura de "
    "un gráfico, y pregunta por voz lo que no entiendas."
)
st.caption(f"Aviso: {DISCLAIMER_ES}")

# ── Briefing de hoy (último guardado o pregenerado) ────────────────────────────────
st.markdown("### Briefing de hoy")
try:
    featured = storage.load_featured_briefing()
except Exception as exc:  # nunca romper la portada
    featured = None
    st.caption(f"No se pudo cargar el briefing guardado ({type(exc).__name__}).")

if featured is not None:
    briefing, origin = featured
    st.session_state.setdefault("briefing", briefing)  # contexto por defecto para «Preguntar»
    try:
        render_featured_briefing(briefing, origin, key="home")
    except Exception as exc:  # p. ej. ficheros movidos a mano: se avisa sin traceback
        st.warning(f"El briefing guardado no se pudo mostrar completo ({type(exc).__name__}: {exc}).")
else:
    with st.container(border=True):
        st.info(
            "Todavía no hay ningún briefing guardado ni el briefing de ejemplo "
            f"(`{storage.DEMO_BRIEFING_DIRNAME}/` en `data/samples/`). Genera el primero en la página "
            "**Briefing**: en modo demo tarda unos segundos y no necesita claves."
        )

# ── Acciones ──────────────────────────────────────────────────────────────────────
st.markdown("### ¿Qué quieres hacer?")
col1, col2, col3 = st.columns(3)
with col1:
    st.page_link("pages/1_Briefing.py", label="Generar el mío", icon=":material/podcasts:")
    st.caption("Elige tickers, añade PDF, capturas o notas de voz y escucha el podcast.")
with col2:
    st.page_link("pages/2_Preguntar.py", label="Preguntar por voz", icon=":material/mic:")
    st.caption("El Agente Q&A responde sobre el briefing, también en audio.")
with col3:
    st.page_link("pages/3_Mi_cartera.py", label="Mi cartera", icon=":material/account_balance_wallet:")
    st.caption("Carga tu cartera (CSV) para personalizar las noticias.")
st.page_link("pages/4_Historico.py", label="Histórico de briefings", icon=":material/history:")

with st.expander("¿Cómo funciona? (cadena de modelos)"):
    st.markdown(
        "1. **Entradas**: noticias de mercado, cartera, PDF de resultados, captura de gráfico, voz.\n"
        "2. **Procesado**: filtro por tickers · lectura de imagen (visión) · lectura de PDF · voz a texto.\n"
        "3. **Agentes IA**: Analista (interpreta) → Guionista (diálogo); Q&A (responde preguntas).\n"
        "4. **Salidas**: gráficos · podcast a 2 voces sintéticas · transcripción · vídeo corto.\n"
        "5. **Entrega**: app web · email · Telegram.\n\n"
        "Cada briefing incluye la pestaña **«Cómo se hizo»** con el grafo real de modelos, latencia y coste."
    )
    diagram = ROOT_DIR / "docs" / "assets" / "arquitectura_mvp_podcast_financiero.png"
    if diagram.exists():
        st.image(str(diagram), caption="Arquitectura del MVP")

show_disclaimer()
