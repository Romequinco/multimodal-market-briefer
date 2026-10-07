"""Vista «Archivo»: briefings guardados en ``data/outputs`` (carril C, usa ``storage``).

Solo **lista y abre**: «Abrir» deja el briefing como activo de la sesión (``set_active_briefing``) y
navega a **Hoy**, que es el único sitio que pinta briefings. La lista sale de
``storage.briefing_summaries`` (lectura ligera, sin validar el modelo completo), cacheada con
``st.cache_data`` y paginada de 50 en 50 («Cargar más antiguos»). Se filtra en memoria con un
buscador (titular, valor o fecha) y un control «Todos · Con audio · Demo». Un ``briefing.json``
corrupto aparece marcado («no disponible») en lugar de romper la vista, y uno cuyo audio ya no está en
disco se marca «sin audio».

RGPD (derecho de supresión): cada tarjeta tiene «Borrar» (popover con confirmación) y la sección
«Privacidad y datos» borra todos los datos generados (``storage.delete_user_data``: ``data/outputs``
y ``data/cache``; nunca ``data/samples``) tras marcar la confirmación; también olvida la cartera y el
briefing activos de la sesión (la cartera nunca se escribe en disco).
"""

from __future__ import annotations

import os
import unicodedata
from datetime import datetime
from html import escape
from pathlib import Path

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer import storage
from briefer.config import get_settings
from briefer.logging_utils import error_text
from components.players import ACTIVE_BRIEFING_KEY, pending, set_active_briefing, show_error
from components.shell import VIEW_HOY

PAGE_SIZE = 50
NOTICE_KEY = "_history_notice"
LIMIT_KEY = "_history_limit"
FILTERS = ("Todos", "Con audio", "Demo")
QA_KEYS = ("qa_answers", "qa_history", "qa_voice", "qa_context_id")
_WEEKDAYS = ("LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM")


# ── Datos ──────────────────────────────────────────────────────────────────────────


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


def _created(summary: storage.BriefingSummary) -> datetime | None:
    try:
        return datetime.fromisoformat(summary.created_at)
    except ValueError:
        try:
            return datetime.strptime(summary.id[:15], "%Y%m%d-%H%M%S")
        except ValueError:
            return None


def _when(summary: storage.BriefingSummary) -> str:
    """``MAR · 06/10/2026 · 16:00`` (o el id si no hay fecha legible)."""
    dt = _created(summary)
    if dt is None:
        return summary.id
    return f"{_WEEKDAYS[dt.weekday()]} · {dt:%d/%m/%Y · %H:%M}"


def _duration(summary: storage.BriefingSummary) -> str:
    if not summary.duration_s:
        return ""
    mins, secs = divmod(int(round(summary.duration_s)), 60)
    return f"{mins}:{secs:02d} min"


def _norm(text: str) -> str:
    """Minúsculas y sin tildes, para buscar «miércoles» o «IBERDROLA» igual."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _haystack(summary: storage.BriefingSummary) -> str:
    dt = _created(summary)
    dates = f"{dt:%d/%m/%Y %d-%m-%Y %Y-%m-%d %d/%m}" if dt else ""
    return _norm(" ".join([summary.id, summary.headline or "", " ".join(summary.tickers), _when(summary), dates]))


def filter_summaries(summaries: list[storage.BriefingSummary], query: str, kind: str | None
                     ) -> list[storage.BriefingSummary]:
    """Filtra en memoria por texto (todas las palabras) y por tipo (``FILTERS``)."""
    words = _norm(query or "").split()
    out = []
    for s in summaries:
        if kind == "Con audio" and (s.error or not s.has_audio):
            continue
        if kind == "Demo" and not s.demo:
            continue
        if words:
            hay = _haystack(s)
            if not all(w in hay for w in words):
                continue
        out.append(s)
    return out


# ── Callbacks (se ejecutan antes de la recarga; los avisos se muestran después) ─────


def _notice(kind: str, text: str) -> None:
    st.session_state[NOTICE_KEY] = (kind, text)


def _forget_session_briefing(briefing_id: str | None = None) -> None:
    """Quita de la sesión el briefing activo (todos, o solo si es ``briefing_id``)."""
    active = st.session_state.get(ACTIVE_BRIEFING_KEY)
    if briefing_id is None or getattr(active, "id", None) == briefing_id:
        st.session_state.pop(ACTIVE_BRIEFING_KEY, None)
        # Todo el estado del Q&A (respuestas visibles y memoria del agente), para que no quede contexto oculto
        for key in QA_KEYS:
            st.session_state.pop(key, None)


def _forget_portfolio() -> None:
    """Olvida la cartera de la sesión (y el estado del diálogo «Nuevo briefing» ligado a ella)."""
    try:
        from components.new_briefing import forget_portfolio
    except (ImportError, AttributeError):
        forget_portfolio = None
    if forget_portfolio is not None:
        try:
            forget_portfolio()
        except Exception:  # noqa: BLE001 - el respaldo de abajo deja la sesión limpia igualmente
            pass
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and (key.startswith(("_nb_pf_", "portfolio")) or key == "_portfolio_upload_id"):
            st.session_state.pop(key, None)


def _open(path: Path) -> None:
    """``on_click`` de «Abrir»: lo deja como briefing activo y navega a Hoy (que lo pinta)."""
    try:
        briefing = storage.load_briefing(path)
    except NotImplementedError as exc:
        _notice("warning", f"La carga de briefings guardados aún no está disponible: {error_text(exc, 200)}")
        return
    except FileNotFoundError:
        _summaries.clear()
        _notice("warning", "Ese briefing ya no existe en disco.")
        return
    except Exception as exc:  # noqa: BLE001 - JSON de otra versión o incompleto
        _notice("error", "Este briefing no está disponible: su `briefing.json` no cumple el formato esperado "
                f"(¿incompleto o de otra versión?). Detalle: {error_text(exc, 160)}")
        return
    set_active_briefing(briefing)
    st.session_state["_goto"] = VIEW_HOY


def _delete_one(briefing_id: str) -> None:
    """``on_click`` de «Borrar este briefing» (solo si se marcó la confirmación)."""
    if not st.session_state.get(f"_confirm_delete_{briefing_id}"):
        return
    try:
        removed = storage.delete_briefing(briefing_id)
    except Exception as exc:  # noqa: BLE001 - se muestra amable tras la recarga
        _notice("error", f"No se pudo borrar el briefing: {error_text(exc, 200)}")
        return
    _forget_session_briefing(briefing_id)
    st.session_state.pop(f"_confirm_delete_{briefing_id}", None)
    st.cache_data.clear()
    _notice("success", "Briefing borrado." if removed else "Ese briefing ya no estaba en disco.")


def _delete_all() -> None:
    """``on_click`` de «Borrar mis datos» (solo si se marcó la confirmación)."""
    outputs = bool(st.session_state.get("_delete_outputs"))
    cache = bool(st.session_state.get("_delete_cache"))
    if not st.session_state.get("_confirm_delete_all") or not (outputs or cache):
        return
    try:
        report = storage.delete_user_data(outputs=outputs, cache=cache)
    except Exception as exc:  # noqa: BLE001
        _notice("error", f"No se pudieron borrar tus datos: {error_text(exc, 200)}")
        return
    _forget_session_briefing()
    _forget_portfolio()  # la cartera solo vive en la sesión: se olvida también
    st.session_state["_confirm_delete_all"] = False
    st.session_state[LIMIT_KEY] = PAGE_SIZE
    st.cache_data.clear()
    msg = (f"Datos borrados: {report.briefings} briefing(s) y {report.total_files} fichero(s) "
           f"({report.cache_files} de caché). La cartera de esta sesión también se ha olvidado.")
    if report.failed:
        _notice("warning", msg + f" No se pudieron borrar {len(report.failed)} elemento(s) en uso; "
                "vuelve a intentarlo en unos segundos.")
    else:
        _notice("success", msg)


def _more() -> None:
    st.session_state[LIMIT_KEY] = st.session_state.get(LIMIT_KEY, PAGE_SIZE) + PAGE_SIZE


# ── Pintado ────────────────────────────────────────────────────────────────────────


def card_html(summary: storage.BriefingSummary, *, active: bool) -> str:
    """Cuerpo de la tarjeta: fecha · duración (· abierto), titular, valores y etiquetas (escapado)."""
    meta = [f"<span>{escape(_when(summary))}</span>"]
    if (dur := _duration(summary)):
        meta.append(f"<span>{escape(dur)}</span>")
    if active:
        meta.append('<span class="mb-arch__open">● abierto</span>')
    if summary.error:
        title = "Briefing no disponible"
    else:
        title = summary.headline or "Briefing sin titular"
    tags = []
    if summary.error:
        tags.append('<span class="mb-arch__tag mb-arch__tag--bad">No disponible</span>')
    elif not summary.has_audio:
        tags.append('<span class="mb-arch__tag mb-arch__tag--warn">Sin audio</span>')
    if summary.demo:
        tags.append('<span class="mb-arch__tag">Demo</span>')
    chips = "".join(f'<span class="mb-arch__tk">{escape(t)}</span>' for t in summary.tickers[:8])
    if len(summary.tickers) > 8:
        chips += f'<span class="mb-arch__tk">+{len(summary.tickers) - 8}</span>'
    note = ""
    if summary.error:
        note = ('<p class="mb-arch__note">Su <code>briefing.json</code> está dañado o incompleto y no se '
                "puede abrir. Puedes borrarlo.</p>")
    return (
        f'<div class="mb-arch"><div class="mb-arch__meta">{"".join(meta)}</div>'
        f'<h3 class="mb-arch__title">{escape(title)}</h3>'
        f'<div class="mb-arch__chips">{chips}{"".join(tags)}</div>{note}</div>'
    )


def _card(summary: storage.BriefingSummary, active_id: str | None) -> None:
    active = not summary.error and summary.id == active_id
    state = "on" if active else "off"
    # La clave lleva el id (no solo el índice): al borrar una tarjeta, el popover abierto no "salta" a la
    # tarjeta que ocupa su hueco.
    with st.container(key=f"mb-card-arch-{summary.id}-{state}"):
        st.html(card_html(summary, active=active))
        with st.container(key=f"mb-arch-act-{summary.id}", horizontal=True, gap="small", vertical_alignment="center"):
            if not summary.error:
                st.button("Abrir", key=f"arch_open_{summary.id}", type="primary", icon=":material/play_arrow:",
                          on_click=_open, args=(summary.path,), help="Ábrelo en Hoy para escucharlo y preguntar")
                from components.new_briefing import repeat_briefing_button

                repeat_briefing_button(summary.path, key=f"arch_repeat_{summary.id}")
            with st.popover("Borrar", icon=":material/delete:", width="content"):
                st.markdown("**¿Borrar este briefing?**")
                st.caption("Se borra su carpeta en el servidor (audio, subtítulos, gráficos y JSON). "
                           "No se puede deshacer.")
                confirm = st.checkbox("Sí, quiero borrarlo", key=f"_confirm_delete_{summary.id}")
                st.button("Borrar este briefing", key=f"delete_{summary.id}", disabled=not confirm,
                          on_click=_delete_one, args=(summary.id,), icon=":material/delete_forever:")


def _empty_state() -> None:
    with st.container(key="mb-card-arch-empty"):
        st.markdown("**Todavía no hay briefings guardados.**")
        st.caption("Genera uno: aparecerá aquí con su audio, gráficos y transcripción para volver a "
                   "escucharlo cuando quieras.")
        try:
            from components.new_briefing import new_briefing_button
        except ImportError:
            st.page_link(VIEW_HOY, label="Ir a Hoy", icon=":material/podcasts:")
        else:
            new_briefing_button(key="arch_new")


def _privacy() -> None:
    """«Privacidad y datos»: borrado RGPD de briefings y cachés, con confirmación."""
    with st.container(border=True, key="mb-danger"):
        st.markdown("**:material/shield_person: Privacidad y datos · Borrar mis datos**")
        st.markdown(
            "Borra de este servidor **tus briefings generados** (audio, subtítulos, gráficos y JSON) y **las "
            "cachés** (noticias y precios del día, subidas y notas de voz temporales). También olvida el "
            "briefing activo y la cartera de esta sesión. **No se puede deshacer.** El briefing de ejemplo "
            "no se toca."
        )
        st.caption("Tu cartera nunca se guarda en disco: solo vive en esta sesión y se olvida al cerrarla.")
        with st.container(horizontal=True, gap="medium", wrap=True):
            outputs = st.checkbox("Briefings generados", value=True, key="_delete_outputs")
            cache = st.checkbox("Cachés y ficheros temporales", value=True, key="_delete_cache")
        confirm = st.checkbox("Entiendo que el borrado es definitivo", key="_confirm_delete_all")
        st.button(
            "Borrar mis datos", type="primary", icon=":material/delete_forever:", key="delete_all",
            disabled=not (confirm and (outputs or cache)), on_click=_delete_all,
            help="Requiere marcar la confirmación. Solo borra las carpetas de salidas y caché configuradas.",
        )


def render() -> None:
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        {"success": st.success, "warning": st.warning, "error": st.error}[notice[0]](notice[1])

    limit = st.session_state.get(LIMIT_KEY, PAGE_SIZE)
    try:
        base = get_settings().output_path
        summaries = _summaries(_folder_signature(base, limit), limit)
    except NotImplementedError as exc:
        pending(exc, "el listado de briefings guardados")
        summaries = []
    except Exception as exc:  # noqa: BLE001
        show_error(exc, "el listado de briefings")
        summaries = []
    more = len(summaries) >= limit

    n = len(summaries)
    count = f"{n}+ briefings guardados" if more else (f"{n} briefing guardado" if n == 1
                                                       else f"{n} briefings guardados")
    with st.container(key="mb-arch-head", horizontal=True, vertical_alignment="bottom", wrap=True, gap="medium"):
        with st.container(key="mb-arch-title", width="stretch"):
            sub = f"{count} · Ábrelos para volver a escucharlos." if n else "Aquí se guardan los briefings que generes."
            st.html(f'<h2 class="mb-arch-h">Archivo</h2><p class="mb-arch-sub">{escape(sub)}</p>')
        if summaries:
            with st.container(key="mb-arch-tools", horizontal=True, vertical_alignment="center", wrap=True,
                              gap="small", width="content"):
                query = st.text_input("Buscar", key="arch_query", icon=":material/search:",
                                      placeholder="Buscar por titular, valor o fecha",
                                      label_visibility="collapsed")
                kind = st.segmented_control("Filtro", FILTERS, default="Todos", key="arch_filter",
                                            label_visibility="collapsed")

    if not summaries:
        _empty_state()
    else:
        shown = filter_summaries(summaries, query, kind)
        active_id = getattr(st.session_state.get(ACTIVE_BRIEFING_KEY), "id", None)
        if shown:
            with st.container(key="mb-arch-grid", horizontal=True, wrap=True, gap="small"):
                for summary in shown:
                    _card(summary, active_id)
        else:
            with st.container(key="mb-card-arch-none"):
                st.caption("No hay briefings que coincidan con la búsqueda o el filtro.")
        if more:
            st.button("Cargar más antiguos", key="arch_more", on_click=_more, icon=":material/expand_more:",
                      help=f"Carga {PAGE_SIZE} briefings más (la búsqueda solo mira los ya cargados).")

    st.space("medium")
    _privacy()


render()
