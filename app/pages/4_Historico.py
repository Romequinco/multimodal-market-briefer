"""Página "Histórico": briefings guardados en ``data/outputs`` (carril C, usa ``storage``).

Lista los ``briefing.json`` (más reciente primero), permite abrir uno y lo deja como briefing
activo de la sesión para que la página «Preguntar» lo use como contexto.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import pending, render_briefing, show_disclaimer, show_error, sidebar_controls

from briefer import storage

st.set_page_config(page_title="Histórico · Market Briefer", layout="wide")
sidebar_controls()

st.title("Histórico de briefings")
show_disclaimer()


def _label(path: Path) -> str:
    """Etiqueta legible a partir del id (``YYYYMMDD-HHMMSS-xxxxxx``)."""
    briefing_id = path.parent.name
    try:
        when = datetime.strptime(briefing_id[:15], "%Y%m%d-%H%M%S")
        return f"{when:%d/%m/%Y %H:%M:%S} · {briefing_id}"
    except ValueError:
        return briefing_id


try:
    paths = storage.list_briefings()
except NotImplementedError as exc:
    pending(exc, "el listado de briefings guardados")
    paths = []
except Exception as exc:
    show_error(exc, "el listado de briefings")
    paths = []

if paths:
    st.caption(f"{len(paths)} briefing(s) guardado(s), del más reciente al más antiguo.")
    selected = st.selectbox("Briefing", paths, format_func=_label)
    if st.button("Abrir", type="primary"):
        st.session_state["history_selected"] = str(selected)

    chosen = st.session_state.get("history_selected")
    if chosen:
        try:
            briefing = storage.load_briefing(Path(chosen))
            st.session_state["briefing"] = briefing  # contexto para «Preguntar»
            st.divider()
            render_briefing(briefing, key="history")
        except NotImplementedError as exc:
            pending(exc, "la carga de briefings guardados")
        except FileNotFoundError:
            st.warning("Ese briefing ya no existe en disco.")
            st.session_state.pop("history_selected", None)
        except Exception as exc:
            show_error(exc, "la carga del briefing")
else:
    st.write("Todavía no hay briefings guardados. Genera uno en la página «Briefing».")
