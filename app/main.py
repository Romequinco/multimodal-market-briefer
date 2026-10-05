"""Portada de la app Streamlit (carril C). Lanzar con: ``streamlit run app/main.py``.

Las páginas de ``app/pages/`` aparecen automáticamente en la barra lateral.
"""

from __future__ import annotations

import components  # noqa: F401  (añade src/ al sys.path)
from components import ROOT_DIR
import streamlit as st
from components.players import show_disclaimer, sidebar_controls

from briefer.schemas import DISCLAIMER_ES

st.set_page_config(page_title="Market Briefer", layout="wide")

sidebar_controls()

st.title("Market Briefer")
st.markdown(
    "#### Tu briefing de mercados en formato podcast, cada mañana\n"
    "Noticias filtradas por tu cartera, interpretadas por IA y contadas a **dos voces**, con "
    "transcripción, gráficos del día y vídeo corto. Sube un PDF de resultados o una captura de "
    "un gráfico, y pregunta por voz lo que no entiendas."
)

st.warning(f"**Aviso importante:** {DISCLAIMER_ES}")

st.markdown("### ¿Qué quieres hacer?")
col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/1_Briefing.py", label="Generar el briefing de hoy")
    st.caption("Elige tickers, añade documentos y escucha el podcast.")
    st.page_link("pages/2_Preguntar.py", label="Preguntar por voz o texto")
    st.caption("El Agente Q&A responde sobre el briefing, también en audio.")
with col2:
    st.page_link("pages/3_Mi_cartera.py", label="Mi cartera")
    st.caption("Carga tu cartera (CSV) para personalizar las noticias.")
    st.page_link("pages/4_Historico.py", label="Histórico")
    st.caption("Briefings anteriores guardados.")

with st.expander("¿Cómo funciona? (cadena de modelos)"):
    st.markdown(
        "1. **Entradas**: noticias de mercado, cartera, PDF de resultados, captura de gráfico, voz.\n"
        "2. **Procesado**: filtro por tickers · lectura de imagen (visión) · lectura de PDF · voz a texto.\n"
        "3. **Agentes IA**: Analista (interpreta) → Guionista (diálogo); Q&A (responde preguntas).\n"
        "4. **Salidas**: gráficos · podcast a 2 voces · transcripción · vídeo corto.\n"
        "5. **Entrega**: app web · email · Telegram."
    )
    diagram = ROOT_DIR / "docs" / "assets" / "arquitectura_mvp_podcast_financiero.png"
    if diagram.exists():
        st.image(str(diagram), caption="Arquitectura del MVP")

show_disclaimer()
