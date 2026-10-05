"""Portada de la app Streamlit (carril C). Lanzar con: ``streamlit run app/main.py``.

Las páginas de ``app/pages/`` aparecen automáticamente en la barra lateral.

«Demo que nunca falla» (lo que ve el evaluador en los primeros 30 s), con el tema «Noticiero
nocturno» (``components.theme``):

1. Cinta de cotizaciones del briefing destacado y cabecera: nombre en serif, insignia «● en antena»,
   fecha de la sesión en mono, propuesta de valor en una línea e insignia del modo (real / demo).
2. El briefing de hoy **sin pulsar nada**: el último guardado (``data/outputs``) o, si no hay, el
   pregenerado real de ``data/samples/demo_briefing/`` (``storage.load_featured_briefing``, cacheado),
   con titular serif, reproductor, 3 puntos clave, «Preguntar sobre este briefing» (primario) y
   «Generar el tuyo».
3. Franja «Cómo se hizo» en mono (modelos, pasos, latencia y coste) y pestañas con el detalle.

Si no existe ningún briefing, lo explica y ofrece generar uno. El disclaimer va al pie, compacto.
"""

from __future__ import annotations

from html import escape

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
    briefing_tape,
    featured_briefing,
    handle_navigation,
    mode_badge,
    render_featured_briefing,
    show_disclaimer,
    sidebar_mode,
)
from components.theme import apply_theme, masthead

from briefer import storage
from briefer.logging_utils import error_text

st.set_page_config(page_title="Market Briefer", page_icon=":material/podcasts:", layout="wide")
apply_theme()
handle_navigation()
mode = sidebar_mode()

# ── Briefing de hoy (último guardado o pregenerado) ────────────────────────────────
load_error: str | None = None
try:
    featured = featured_briefing()
except Exception as exc:  # nunca romper la portada
    featured = None
    load_error = type(exc).__name__

# ── Cinta y cabecera ──────────────────────────────────────────────────────────────
if featured is not None:
    briefing_tape(featured[0])
masthead(featured[0].analysis.date if featured is not None else None, on_air=featured is not None)
st.markdown(f'<p class="mb-tagline">{escape(VALUE_PROPOSITION)}</p>', unsafe_allow_html=True)
mode_badge(mode)
if load_error:
    st.caption(f"No se pudo cargar el briefing guardado ({load_error}).")

if featured is not None:
    briefing, origin = featured
    st.session_state.setdefault("briefing", briefing)  # contexto por defecto para «Preguntar»
    try:
        render_featured_briefing(briefing, origin, key="home")
    except Exception as exc:  # p. ej. ficheros movidos a mano: se avisa sin traceback
        st.warning(f"El briefing guardado no se pudo mostrar completo ({error_text(exc)}).")
else:
    with st.container(key="mb-card-empty"):
        st.info(
            "Todavía no hay ningún briefing guardado ni el briefing de ejemplo "
            f"(`{storage.DEMO_BRIEFING_DIRNAME}/` en `data/samples/`). Genera el primero en la página "
            "**Briefing**: en modo demo tarda unos segundos y no necesita claves."
        )
        page_link(PAGE_BRIEFING, "Generar mi primer briefing", ":material/podcasts:")

# ── Acciones ──────────────────────────────────────────────────────────────────────
st.markdown("### ¿Qué más puedes hacer?")
ACTIONS = [
    (PAGE_BRIEFING, "Generar el tuyo", ":material/podcasts:",
     "Elige valores, añade un PDF de resultados, una captura de gráfico o una nota de voz."),
    (PAGE_ASK, "Preguntar por voz", ":material/mic:",
     "El Agente Q&A responde sobre el briefing, en texto y en audio."),
    (PAGE_PORTFOLIO, "Mi cartera", ":material/account_balance_wallet:",
     "Carga tu cartera (CSV) para filtrar las noticias. No se guarda en disco."),
    (PAGE_HISTORY, "Histórico", ":material/history:",
     "Briefings anteriores, con su audio, gráficos y traza."),
]
for i, (col, (page, label, icon, text)) in enumerate(zip(st.columns(4), ACTIONS)):
    with col, st.container(key=f"mb-card-action-{i}"):
        page_link(page, label, icon)
        st.caption(text)

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
