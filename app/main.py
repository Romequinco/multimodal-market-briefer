"""Portada de la app Streamlit (carril C). Lanzar con: ``streamlit run app/main.py``.

Las páginas de ``app/pages/`` aparecen automáticamente en la barra lateral.

«Demo que nunca falla» (lo que ve el evaluador en los primeros 30 s):

1. Cabecera: nombre, propuesta de valor en una línea e insignia del modo (real / demo).
2. El briefing de hoy **sin pulsar nada**: el último guardado (``data/outputs``) o, si no hay, el
   pregenerado real de ``data/samples/demo_briefing/`` (``storage.load_featured_briefing``, cacheado),
   con el reproductor arriba, 3 puntos clave, «Preguntar sobre este briefing» y «Generar el tuyo».
3. Franja «Cómo se hizo» (modelos, pasos, latencia y coste) y pestañas con el detalle.

Si no existe ningún briefing, lo explica y ofrece generar uno. El disclaimer va al pie, compacto.
"""

from __future__ import annotations

import components  # noqa: F401  (añade src/ al sys.path)
from components import ROOT_DIR
import streamlit as st
from components.players import (
    page_link,
    PAGE_ASK,
    PAGE_BRIEFING,
    PAGE_HISTORY,
    PAGE_PORTFOLIO,
    VALUE_PROPOSITION,
    featured_briefing,
    handle_navigation,
    mode_badge,
    render_featured_briefing,
    show_disclaimer,
    sidebar_mode,
)

from briefer import storage
from briefer.logging_utils import error_text

st.set_page_config(page_title="Market Briefer", page_icon=":material/podcasts:", layout="wide")
handle_navigation()
mode = sidebar_mode()

# ── Cabecera ──────────────────────────────────────────────────────────────────────
st.title("Market Briefer")
st.markdown(f"#### {VALUE_PROPOSITION}")
mode_badge(mode)

# ── Briefing de hoy (último guardado o pregenerado) ────────────────────────────────
try:
    featured = featured_briefing()
except Exception as exc:  # nunca romper la portada
    featured = None
    st.caption(f"No se pudo cargar el briefing guardado ({type(exc).__name__}).")

if featured is not None:
    briefing, origin = featured
    st.session_state.setdefault("briefing", briefing)  # contexto por defecto para «Preguntar»
    try:
        render_featured_briefing(briefing, origin, key="home")
    except Exception as exc:  # p. ej. ficheros movidos a mano: se avisa sin traceback
        st.warning(f"El briefing guardado no se pudo mostrar completo ({error_text(exc)}).")
else:
    with st.container(border=True):
        st.info(
            "Todavía no hay ningún briefing guardado ni el briefing de ejemplo "
            f"(`{storage.DEMO_BRIEFING_DIRNAME}/` en `data/samples/`). Genera el primero en la página "
            "**Briefing**: en modo demo tarda unos segundos y no necesita claves."
        )
        page_link(PAGE_BRIEFING, "Generar mi primer briefing", ":material/podcasts:")

# ── Acciones ──────────────────────────────────────────────────────────────────────
st.markdown("### ¿Qué más puedes hacer?")
col1, col2, col3, col4 = st.columns(4)
with col1:
    page_link(PAGE_BRIEFING, "Generar el tuyo", ":material/podcasts:")
    st.caption("Elige valores, añade un PDF de resultados, una captura de gráfico o una nota de voz.")
with col2:
    page_link(PAGE_ASK, "Preguntar por voz", ":material/mic:")
    st.caption("El Agente Q&A responde sobre el briefing, en texto y en audio.")
with col3:
    page_link(PAGE_PORTFOLIO, "Mi cartera", ":material/account_balance_wallet:")
    st.caption("Carga tu cartera (CSV) para filtrar las noticias. No se guarda en disco.")
with col4:
    page_link(PAGE_HISTORY, "Histórico", ":material/history:")
    st.caption("Briefings anteriores, con su audio, gráficos y traza.")

with st.expander("¿Cómo funciona? (cadena de modelos)"):
    st.markdown(
        "1. **Entradas**: noticias de mercado, cartera, PDF de resultados, captura de gráfico, voz.\n"
        "2. **Procesado**: filtro por valores · lectura de imagen (visión) · lectura de PDF · voz a texto.\n"
        "3. **Agentes IA**: Analista (interpreta, con control de cifras) → Guionista (diálogo); "
        "Q&A (responde preguntas).\n"
        "4. **Salidas**: gráficos · podcast a 2 voces sintéticas · transcripción y subtítulos.\n"
        "5. **Entrega**: app web (email y Telegram en desarrollo).\n\n"
        "Cada briefing incluye la pestaña **«Cómo se hizo»** con el grafo real de modelos, latencia y coste."
    )
    diagram = ROOT_DIR / "docs" / "assets" / "arquitectura_mvp_podcast_financiero.png"
    if diagram.exists():
        st.image(str(diagram), caption="Arquitectura del MVP")

show_disclaimer()
