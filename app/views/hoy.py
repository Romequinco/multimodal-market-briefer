"""Vista «Hoy»: el briefing activo de la sesión (boceto A).

- Briefing mostrado: ``st.session_state["briefing"]`` si existe (recién generado, abierto desde Archivo
  o el que ya se estaba viendo); si no, el destacado (``players.featured_briefing``: último guardado
  real o el pregenerado), que queda como activo para «Preguntar».
- Cabecera: «TU BRIEFING» + «● en antena» + fecha, y el botón primario «Nuevo briefing» (diálogo de
  ``components.new_briefing``). Si lo mostrado no es el último o no es de hoy, etiqueta de origen y
  «Volver al último».
- El cuerpo lo pinta ``components.briefing_view.render_briefing_view`` (el único sitio que pinta
  briefings). El disclaimer lo pone el pie del armazón.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer import brand
from briefer.schemas import Briefing
from components.briefing_view import is_today, origin_pill_text, render_briefing_view
from components.players import ACTIVE_BRIEFING_KEY, featured_briefing, set_active_briefing, show_error
from components.theme import fmt_date, on_air_html

DONE_KEY = "_nb_done"          # lo deja ``new_briefing`` al terminar (id del briefing nuevo)
NEW_ID_KEY = "_hoy_new_id"     # id del último briefing generado en esta sesión (etiqueta «Recién generado»)
NEW_BRIEFING_KEY = "_hoy_new_briefing"  # ese briefing: «Volver al último» vuelve a él antes que al guardado


def _new_button(key: str) -> None:
    """«Nuevo briefing» (diálogo de ``components.new_briefing``); deshabilitado si aún no existe."""
    try:
        from components.new_briefing import new_briefing_button
    except ImportError:
        st.button("Nuevo briefing", key=key, type="primary", icon=":material/add:", disabled=True,
                  help="El formulario de nuevo briefing aún no está disponible.")
        return
    new_briefing_button(key=key)


def _featured() -> tuple[Briefing, str] | None:
    try:
        return featured_briefing()
    except Exception as exc:  # noqa: BLE001 - JSON corrupto u otra versión: Hoy no se rompe
        show_error(exc, "la carga del último briefing")
        return None


def _back_to_latest(briefing: Briefing) -> None:
    set_active_briefing(briefing)


def _origin(current: Briefing, featured: tuple[Briefing, str] | None) -> str:
    if st.session_state.get(NEW_ID_KEY) == current.id:
        return "nuevo"
    if featured is not None and featured[0].id == current.id:
        return featured[1]
    return "archivo"


def _latest(featured: tuple[Briefing, str] | None) -> Briefing | None:
    """Destino de «Volver al último»: el generado en esta sesión si lo hay; si no, el destacado."""
    new = st.session_state.get(NEW_BRIEFING_KEY)
    audio = getattr(new, "audio", None)
    gone = audio is not None and not Path(audio.path).exists()  # borrado desde Archivo
    if isinstance(new, Briefing) and new.id == st.session_state.get(NEW_ID_KEY) and not gone:
        return new
    return featured[0] if featured is not None else None


def _header(current: Briefing | None, origin: str | None, featured: tuple[Briefing, str] | None) -> None:
    with st.container(key="mb-hoy-head", horizontal=True, wrap=True, vertical_alignment="center", gap="small"):
        on_air = current is None or is_today(current)
        when = current.analysis.date if current is not None else None
        pills = ""
        text = origin_pill_text(current, origin) if current is not None else ""
        if text:
            pills += f'<span class="mb-hoy-origin">{escape(text)}</span>'
        portfolio = st.session_state.get("portfolio")
        positions = len(getattr(portfolio, "positions", None) or [])
        if positions:
            pills += (f'<span class="mb-hoy-origin mb-hoy-origin--pf">Cartera: {positions} '
                      f'{"posición" if positions == 1 else "posiciones"}</span>')
        st.html(
            '<div class="mb-hoy-sub"><span class="mb-hoy-label">Tu briefing</span>'
            f'{on_air_html(on_air)}<span class="mb-date">{escape(fmt_date(when))}</span>{pills}</div>'
            f'<p class="mb-hoy-pitch">{escape(brand.VALUE_PROPOSITION)} '
            f'<span>{escape(brand.TAGLINE)}.</span></p>',
            width="stretch",
        )
        latest = _latest(featured)
        if current is not None and latest is not None and latest.id != current.id:
            st.button("Volver al último", key="hoy_back", type="tertiary", icon=":material/history:",
                      on_click=_back_to_latest, args=(latest,))
        if current is not None:  # en el estado vacío el botón va dentro de la tarjeta (uno solo)
            _new_button("hoy_new")


def _empty_state() -> None:
    with st.container(key="mb-card-hoy-empty"):
        st.markdown("### Aún no hay ningún briefing")
        st.markdown(
            "Elige tus valores (o sube tu cartera) y Briefly prepara el cierre del día: noticias con su "
            "fuente, un podcast a dos voces sintéticas, gráficos y la transcripción. En el modo demo no "
            "hace falta ninguna clave."
        )
        _new_button("hoy_new_empty")


def render() -> None:
    done = st.session_state.pop(DONE_KEY, None)
    if done:
        st.session_state[NEW_ID_KEY] = done
        st.toast("Briefing listo", icon=":material/check_circle:")

    featured = _featured()
    current = st.session_state.get(ACTIVE_BRIEFING_KEY)
    if not isinstance(current, Briefing) and featured is not None:
        current = featured[0]  # también si la clave existe con None (setdefault no la tocaría)
        st.session_state[ACTIVE_BRIEFING_KEY] = current

    if not isinstance(current, Briefing):
        _header(None, None, None)
        _empty_state()
        return

    if current.id == st.session_state.get(NEW_ID_KEY):
        st.session_state[NEW_BRIEFING_KEY] = current
    origin = _origin(current, featured)
    _header(current, origin, featured)
    try:
        render_briefing_view(current, key="hoy")
    except Exception as exc:  # noqa: BLE001 - nunca romper la vista
        show_error(exc, "la presentación del briefing")


render()
