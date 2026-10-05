"""Página "Histórico": briefings guardados en ``data/outputs`` (carril C, usa ``storage``).

Lista los briefings (más reciente primero) con ``storage.briefing_summaries`` (lectura ligera, sin
validar el modelo completo, cacheada con ``st.cache_data`` y paginada), abre el elegido y lo deja
como briefing activo de la sesión para que «Preguntar» lo use como contexto. Un ``briefing.json``
corrupto aparece marcado en la lista («no disponible») en lugar de romper la página, y uno cuyo
audio ya no está en disco se marca «sin audio en disco».

RGPD (derecho de supresión): cada briefing se puede borrar (desplegable con confirmación) y la «Zona
de peligro» borra todos los datos generados (``storage.delete_user_data``: ``data/outputs`` y
``data/cache``; nunca ``data/samples``) tras marcar una casilla de confirmación.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer import storage
from briefer.config import get_settings
from briefer.logging_utils import error_text
from components.players import (
    ACTIVE_BRIEFING_KEY,
    handle_navigation,
    mode_badge,
    pending,
    render_briefing,
    set_active_briefing,
    show_disclaimer,
    show_error,
    sidebar_mode,
)
from components.theme import apply_theme

st.set_page_config(page_title="Histórico · Market Briefer", page_icon=":material/history:", layout="wide")
apply_theme()
handle_navigation()
mode = sidebar_mode()

st.title("Histórico de briefings")
mode_badge(mode)

PAGE_SIZE = 50
NOTICE_KEY = "_history_notice"


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
    """Etiqueta legible: fecha · titular · duración · marcas (no disponible / sin audio / demo)."""
    if summary.error:
        return f"⚠ {summary.id} · no disponible (no se puede leer)"
    parts = [_when(summary)]
    if summary.headline:
        parts.append(summary.headline if len(summary.headline) <= 70 else summary.headline[:69] + "…")
    if summary.duration_s:
        mins, secs = divmod(int(round(summary.duration_s)), 60)
        parts.append(f"{mins}:{secs:02d} min")
        if not summary.has_audio:
            parts.append("sin audio en disco")
    if summary.demo:
        parts.append("demo")
    return " · ".join(parts)


def _forget_session_briefing(briefing_id: str | None = None) -> None:
    """Quita de la sesión el briefing activo (todos, o solo si es ``briefing_id``)."""
    active = st.session_state.get(ACTIVE_BRIEFING_KEY)
    if briefing_id is None or getattr(active, "id", None) == briefing_id:
        st.session_state.pop(ACTIVE_BRIEFING_KEY, None)
        st.session_state.pop("qa_answers", None)
    st.session_state.pop("history_selected", None)


def _delete_one(briefing_id: str) -> None:
    """``on_click`` de «Borrar este briefing» (solo si se marcó la confirmación)."""
    if not st.session_state.get(f"_confirm_delete_{briefing_id}"):
        return
    try:
        removed = storage.delete_briefing(briefing_id)
    except Exception as exc:  # noqa: BLE001 - se muestra amable tras la recarga
        st.session_state[NOTICE_KEY] = ("error", f"No se pudo borrar el briefing: {error_text(exc, 200)}")
        return
    _forget_session_briefing(briefing_id)
    st.cache_data.clear()
    st.session_state[NOTICE_KEY] = (
        "success", "Briefing borrado." if removed else "Ese briefing ya no estaba en disco.")


def _delete_all(outputs: bool, cache: bool) -> None:
    """``on_click`` de «Borrar mis datos» (solo si se marcó la confirmación)."""
    if not st.session_state.get("_confirm_delete_all") or not (outputs or cache):
        return
    try:
        report = storage.delete_user_data(outputs=outputs, cache=cache)
    except Exception as exc:  # noqa: BLE001
        st.session_state[NOTICE_KEY] = ("error", f"No se pudieron borrar tus datos: {error_text(exc, 200)}")
        return
    _forget_session_briefing()
    for key in ("portfolio", "_portfolio_upload_id"):  # la cartera solo vive en la sesión: se olvida también
        st.session_state.pop(key, None)
    st.session_state["_confirm_delete_all"] = False
    st.cache_data.clear()
    msg = (f"Datos borrados: {report.briefings} briefing(s) y {report.total_files} fichero(s) "
           f"({report.cache_files} de caché). La cartera de esta sesión también se ha olvidado.")
    if report.failed:
        st.session_state[NOTICE_KEY] = ("warning", msg + f" No se pudieron borrar {len(report.failed)} "
                                        "elemento(s) en uso; vuelve a intentarlo en unos segundos.")
    else:
        st.session_state[NOTICE_KEY] = ("success", msg)


notice = st.session_state.pop(NOTICE_KEY, None)
if notice:
    {"success": st.success, "warning": st.warning, "error": st.error}[notice[0]](notice[1])

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
    with st.expander("Borrar este briefing", icon=":material/delete:"):
        st.caption("Se borra su carpeta en el servidor (audio, subtítulos, gráficos y JSON). No se puede deshacer.")
        confirm_one = st.checkbox("Sí, quiero borrar este briefing", key=f"_confirm_delete_{selected}")
        st.button("Borrar este briefing", key=f"delete_{selected}", disabled=not confirm_one,
                  on_click=_delete_one, args=(selected,), icon=":material/delete_forever:")
    if summary.error:
        st.warning("Este briefing no está disponible: su `briefing.json` está dañado o incompleto "
                   "y no se puede abrir. El resto del histórico sigue funcionando; puedes borrarlo arriba.")
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
            st.warning("Este briefing no está disponible: su `briefing.json` no cumple el formato esperado "
                       "(¿incompleto o de otra versión?). Elige otro de la lista.")
            show_error(exc, "la carga del briefing")
else:
    st.info("Todavía no hay briefings guardados. Genera uno en la página «Briefing»: aparecerá aquí con "
            "su audio, gráficos y traza.")

# ── Zona de peligro: borrar mis datos (RGPD, derecho de supresión) ────────────────────
st.divider()
with st.container(border=True, key="mb-danger"):
    st.subheader(":material/warning: Zona de peligro · Borrar mis datos", anchor=False)
    st.markdown(
        "Borra de este servidor **tus briefings generados** (audio, subtítulos, gráficos; carpeta de salidas) "
        "y **las cachés** (noticias y precios del día, subidas y notas de voz temporales). También olvida la "
        "cartera y el briefing activos de esta sesión. **No se puede deshacer.** El briefing de ejemplo de la "
        "portada no se toca."
    )
    c1, c2 = st.columns(2)
    del_outputs = c1.checkbox("Briefings generados", value=True, key="_delete_outputs")
    del_cache = c2.checkbox("Cachés y ficheros temporales", value=True, key="_delete_cache")
    confirm_all = st.checkbox("Entiendo que el borrado es definitivo", key="_confirm_delete_all")
    st.button(
        "Borrar mis datos", type="primary", icon=":material/delete_forever:", key="delete_all",
        disabled=not (confirm_all and (del_outputs or del_cache)),
        on_click=_delete_all, args=(del_outputs, del_cache),
        help="Requiere marcar la confirmación. Solo borra las carpetas de salidas y caché configuradas.",
    )

show_disclaimer()
