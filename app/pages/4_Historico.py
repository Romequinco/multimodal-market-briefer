"""Página "Histórico": briefings guardados en ``data/outputs`` (carril C, usa ``storage``).

Lista los briefings (más reciente primero) con ``storage.briefing_summaries`` (lectura ligera, sin
validar el modelo completo, cacheada con ``st.cache_data`` y paginada), abre el elegido y lo deja
como briefing activo de la sesión para que «Preguntar» lo use como contexto. Un ``briefing.json``
corrupto aparece marcado en la lista en lugar de romper la página.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import (
    handle_navigation,
    mode_badge,
    pending,
    render_briefing,
    set_active_briefing,
    show_disclaimer,
    show_error,
    sidebar_mode,
)

from briefer import storage
from briefer.config import get_settings

st.set_page_config(page_title="Histórico · Market Briefer", page_icon=":material/history:", layout="wide")
handle_navigation()
mode = sidebar_mode()

st.title("Histórico de briefings")
mode_badge(mode)

PAGE_SIZE = 50


def _folder_signature(base: Path, limit: int) -> tuple:
    """Huella barata del listado (nombres y fechas de modificación de las carpetas más recientes)."""
    try:
        entries = sorted((e for e in os.scandir(base) if e.is_dir()), key=lambda e: e.name, reverse=True)
    except OSError:
        return (str(base),)
    return (str(base), limit, tuple((e.name, e.stat().st_mtime) for e in entries[: limit + 1]))


@st.cache_data(show_spinner=False, max_entries=8)
def _summaries(signature: tuple, limit: int) -> list[storage.BriefingSummary]:
    return storage.briefing_summaries(limit=limit)


def _when(summary: storage.BriefingSummary) -> str:
    try:
        return f"{datetime.fromisoformat(summary.created_at):%d/%m/%Y %H:%M}"
    except ValueError:
        try:
            return f"{datetime.strptime(summary.id[:15], '%Y%m%d-%H%M%S'):%d/%m/%Y %H:%M}"
        except ValueError:
            return summary.id


def _label(summary: storage.BriefingSummary) -> str:
    """Etiqueta legible: fecha · titular · duración · marcas."""
    if summary.error:
        return f"⚠ {summary.id} · no se puede leer"
    parts = [_when(summary)]
    if summary.headline:
        parts.append(summary.headline if len(summary.headline) <= 70 else summary.headline[:69] + "…")
    if summary.duration_s:
        mins, secs = divmod(int(round(summary.duration_s)), 60)
        parts.append(f"{mins}:{secs:02d} min")
    if summary.demo:
        parts.append("demo")
    return " · ".join(parts)


limit = st.session_state.get("_history_limit", PAGE_SIZE)
try:
    base = get_settings().output_path
    summaries = _summaries(_folder_signature(base, limit), limit)
except NotImplementedError as exc:
    pending(exc, "el listado de briefings guardados")
    summaries = []
except Exception as exc:
    show_error(exc, "el listado de briefings")
    summaries = []

if summaries:
    st.caption(f"{len(summaries)} briefing(s) más recientes, del más nuevo al más antiguo.")
    ids = [s.id for s in summaries]
    by_id = {s.id: s for s in summaries}
    chosen_id = st.session_state.get("history_selected")
    index = ids.index(chosen_id) if chosen_id in ids else 0
    selected = st.selectbox("Briefing", ids, index=index, format_func=lambda i: _label(by_id[i]))
    if len(summaries) >= limit and st.button("Cargar más antiguos"):
        st.session_state["_history_limit"] = limit + PAGE_SIZE
        st.rerun()
    st.session_state["history_selected"] = selected
    summary = by_id[selected]
    if summary.error:
        st.warning(f"Este briefing no se puede abrir: su `briefing.json` está dañado ({summary.error}).")
    else:
        try:
            briefing = storage.load_briefing(summary.path)
            set_active_briefing(briefing)  # contexto para «Preguntar»
            st.divider()
            render_briefing(briefing, key="history")
        except NotImplementedError as exc:
            pending(exc, "la carga de briefings guardados")
        except FileNotFoundError:
            st.warning("Ese briefing ya no existe en disco.")
            st.session_state.pop("history_selected", None)
            _summaries.clear()
        except Exception as exc:
            show_error(exc, "la carga del briefing")
else:
    st.info("Todavía no hay briefings guardados. Genera uno en la página «Briefing»: aparecerá aquí con "
            "su audio, gráficos y traza.")

show_disclaimer()
