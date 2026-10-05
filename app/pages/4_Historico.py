"""Página "Histórico": briefings guardados en ``data/outputs`` (carril C, usa ``storage``)."""

from __future__ import annotations

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import pending, render_briefing, show_disclaimer, sidebar_controls

from briefer import storage

st.set_page_config(page_title="Histórico · Market Briefer", layout="wide")
sidebar_controls()

st.title("Histórico de briefings")
show_disclaimer()

try:
    paths = storage.list_briefings()
except NotImplementedError as exc:
    pending(exc, "el listado de briefings guardados")
    paths = []

if paths:
    selected = st.selectbox("Briefing", paths, format_func=lambda p: p.parent.name)
    if st.button("Abrir"):
        try:
            briefing = storage.load_briefing(selected)
            st.session_state["briefing"] = briefing
            render_briefing(briefing)
        except NotImplementedError as exc:
            pending(exc, "la carga de briefings guardados")
        except Exception as exc:
            st.exception(exc)
else:
    st.write("Todavía no hay briefings guardados.")
