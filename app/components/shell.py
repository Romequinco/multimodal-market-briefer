"""Armazón común de la app (rediseño «Tres pestañas, cero sidebar»).

``app/main.py`` solo llama a :func:`run_app`, que:

1. Configura la página (título, favicon, ``layout="wide"``) e inyecta el tema (``theme.apply_theme``).
2. Registra las tres vistas con ``st.navigation(position="hidden")``: **Hoy** (``views/hoy.py``),
   **Preguntar** (``views/preguntar.py``) y **Archivo** (``views/archivo.py``).
3. Pinta la barra superior (:func:`topbar`): marca, las tres pestañas, el chip del modo (``st.popover``
   con el selector real / demo con voces / demo offline y el estado de los proveedores) y el menú ⚙
   («Quiénes somos» en un ``st.dialog`` y el acceso a privacidad).
4. Ejecuta la vista elegida y cierra con el pie (:func:`footer`): el aviso legal **una sola vez**.

No hay barra lateral. El modo se guarda en ``st.session_state["run_mode"]`` (y ``"use_mock"``); las
vistas lo leen con :func:`current_mode`.
"""

from __future__ import annotations

import hmac
from html import escape

import streamlit as st

from briefer import brand
from briefer.config import Settings, get_settings
from briefer.logging_utils import error_text

from .brand import mark_html, page_icon
from .players import (
    MODE_LABELS,
    default_demo_mode,
    disclaimer_note,
    handle_navigation,
    provider_badges,
    real_mode_available,
)
from .theme import apply_theme

# Rutas de las vistas (relativas a ``app/main.py``); también sirven para ``st.switch_page``.
VIEW_HOY = "views/hoy.py"
VIEW_ASK = "views/preguntar.py"
VIEW_ARCHIVE = "views/archivo.py"

#: (fichero, título, ``url_path``, icono) de cada pestaña, en orden.
VIEWS: tuple[tuple[str, str, str, str], ...] = (
    (VIEW_HOY, "Hoy", "hoy", ":material/podcasts:"),
    (VIEW_ASK, "Preguntar", "preguntar", ":material/forum:"),
    (VIEW_ARCHIVE, "Archivo", "archivo", ":material/inventory_2:"),
)

MODE_KEY = "run_mode"
_MODE_WIDGET = "mb_mode_choice"
#: Texto corto del chip del modo (barra superior).
MODE_CHIP: dict[str, str] = {
    "real": "Real",
    "demo_voices": "Demo · voces reales",
    "mock": "Demo offline",
}
#: Explicación de cada modo dentro del popover.
MODE_HELP: dict[str, str] = {
    "real": "APIs con las claves de `.env` (noticias, precios y modelos reales; ≈ 0,07 € por briefing).",
    "demo_voices": "Sin claves: noticias de ejemplo y modelos simulados, pero voces reales (edge-tts).",
    "mock": "Todo simulado y sin red (el audio es un silencio de prueba).",
}

ABOUT_ORIGIN = (
    f"<b>{escape(brand.BRAND_NAME)}</b> nació en un atasco de la M-30, cuando tres estudiantes de MIAX se "
    "dieron cuenta de que llegaban a casa sin saber qué había hecho su cartera. "
    "Nuestra misión: que lo sepas antes de quitarte los zapatos."
)
ABOUT_VALUES: tuple[tuple[str, str], ...] = (
    (brand.COMPLIANCE_MOTTO, "No damos consejos, ni siquiera de cocina."),
    ("Fuente o no ha pasado.", "Cada noticia lleva su enlace."),
    ("Cuatro minutos.", "Si tu cartera necesita más, el problema no es el podcast."),
    ("Voces sintéticas, y orgullosas de serlo.", "Nadie se ha quedado afónico grabando este programa."),
)
ABOUT_HOSTS: tuple[tuple[str, str, str, str], ...] = (
    (brand.SPEAKER_A_NAME, "Voz A", brand.SPEAKER_A_ROLE, ""),
    (brand.SPEAKER_B_NAME, "Voz B", brand.SPEAKER_B_ROLE, " mb-host__badge--b"),
)
ABOUT_TEAM = "Tres personas, seis modelos de IA, un toro y una osa."


# ── Modo de ejecución ──────────────────────────────────────────────────────────────


def current_mode() -> str:
    """Modo activo de la sesión (``"real"`` | ``"demo_voices"`` | ``"mock"``).

    Lo fija el chip de la barra superior; si una vista se ejecuta sola (p. ej. en ``AppTest``) y aún
    no hay modo, devuelve el demo por defecto (``players.default_demo_mode``).
    """
    mode = st.session_state.get(MODE_KEY)
    if mode in MODE_LABELS:
        return mode
    try:
        return default_demo_mode()
    except Exception:  # .env mal formado
        return "mock"


def mode_options(available: bool) -> list[str]:
    """Modos que se pueden elegir: el real solo si hay claves (``real_mode_available``)."""
    return (["real"] if available else []) + ["demo_voices", "mock"]


def _store_mode(mode: str) -> None:
    st.session_state[MODE_KEY] = mode
    st.session_state["use_mock"] = mode != "real"


# ── Contraseña del modo real (despliegue público) ─────────────────────────────────

_REAL_UNLOCKED_KEY = "_real_unlocked"
_REAL_ATTEMPTS_KEY = "_real_attempts"
#: Intentos fallidos por sesión antes de bloquear el formulario (frena el probar a ciegas).
MAX_REAL_ATTEMPTS = 5


def _real_password(settings: Settings | None = None) -> str:
    try:
        secret = (settings or get_settings()).briefer_real_mode_password
    except Exception:  # .env mal formado: sin contraseña configurada
        return ""
    return secret.get_secret_value().strip() if secret is not None else ""


def real_password_required(settings: Settings | None = None) -> bool:
    """``True`` si ``BRIEFER_REAL_MODE_PASSWORD`` tiene valor (el modo real pide contraseña)."""
    return bool(_real_password(settings))


def check_real_password(candidate: str, settings: Settings | None = None) -> bool:
    """Compara en tiempo constante con ``BRIEFER_REAL_MODE_PASSWORD`` (``False`` si no hay ninguna)."""
    expected = _real_password(settings)
    if not expected:
        return False
    return hmac.compare_digest(candidate.strip().encode("utf-8"), expected.encode("utf-8"))


def real_mode_locked() -> bool:
    """¿El modo real está bloqueado en esta sesión? (hay contraseña y aún no se ha introducido bien)."""
    return real_password_required() and not st.session_state.get(_REAL_UNLOCKED_KEY, False)


def _unlock_real() -> None:
    """Callback del formulario: comprueba la contraseña y desbloquea el modo real en la sesión."""
    attempts = int(st.session_state.get(_REAL_ATTEMPTS_KEY, 0))
    if attempts >= MAX_REAL_ATTEMPTS:
        return
    if check_real_password(str(st.session_state.get("mb_real_pwd", ""))):
        st.session_state[_REAL_UNLOCKED_KEY] = True
        st.session_state[_REAL_ATTEMPTS_KEY] = 0
    else:
        st.session_state[_REAL_ATTEMPTS_KEY] = attempts + 1
    st.session_state["mb_real_pwd"] = ""  # la contraseña no se queda en el campo


def _real_password_form() -> None:
    """Campo de contraseña dentro del popover del modo (mientras tanto se sigue en demo)."""
    attempts = int(st.session_state.get(_REAL_ATTEMPTS_KEY, 0))
    if attempts >= MAX_REAL_ATTEMPTS:
        st.error("Demasiados intentos. Recarga la página para volver a probar.")
        return
    st.caption("El modo real gasta con las claves de API: introduce la contraseña de esta instalación. "
               "Mientras tanto se sigue en modo demo.")
    st.text_input("Contraseña del modo real", type="password", key="mb_real_pwd")
    st.button("Desbloquear", key="mb_real_unlock", on_click=_unlock_real, type="primary")
    if attempts:
        st.caption(f":red[Contraseña incorrecta] ({attempts}/{MAX_REAL_ATTEMPTS}).")


def mode_popover() -> str:
    """Chip del modo en la barra superior (``st.popover``) con el selector y los proveedores.

    Es el **único** sitio de la app donde se elige y se ve el modo. Devuelve el modo activo.
    """
    try:
        available, why = real_mode_available()
    except Exception as exc:  # .env mal formado
        available, why = False, error_text(exc)
    options = mode_options(available)
    try:
        fallback = default_demo_mode()
    except Exception:  # .env mal formado: la barra no se rompe
        fallback = "mock"
    previous = st.session_state.get(MODE_KEY)
    if previous not in options:
        previous = fallback if previous != "real" else options[-2]
    # El valor del widget manda; si no existe (primera carga) se siembra con el modo de la sesión.
    if st.session_state.get(_MODE_WIDGET) not in options:
        st.session_state[_MODE_WIDGET] = previous
    locked = real_mode_locked()
    chosen = st.session_state[_MODE_WIDGET]
    mode = fallback if chosen == "real" and locked else chosen
    tone = "real" if mode == "real" else "demo"
    with st.container(key=f"mb-modechip-{tone}", width="content"):
        with st.popover(MODE_CHIP[mode], icon=":material/radio_button_checked:", width="content"), \
                st.container(key="mb-mode-pop", gap="small"):
            st.markdown("**Modo de funcionamiento**")
            chosen = st.radio(
                "Modo de funcionamiento",
                options,
                format_func=lambda m: MODE_LABELS[m],
                key=_MODE_WIDGET,
                label_visibility="collapsed",
            )
            st.caption(MODE_HELP[chosen])
            mode = chosen
            if chosen == "real" and real_mode_locked():
                mode = fallback
                _real_password_form()
            elif chosen == "real" and real_password_required():
                st.caption("Modo real desbloqueado en esta sesión.")
            if not available:
                st.caption(f"Modo real no disponible: {why}")
            st.markdown("**Proveedores de IA**")
            try:
                rows = []
                for badge in provider_badges():
                    color = {"real": "green", "mock": "orange", "off": "gray"}[badge.status]
                    rows.append(f"{badge.family}: :{color}[{badge.label}]")
                st.markdown("  \n".join(rows))
            except Exception as exc:  # .env mal formado
                st.error(f"Configuración inválida: {error_text(exc)}")
            if mode == "mock":
                st.caption("En la demo offline el pipeline usa mocks en todas las familias.")
            elif mode == "demo_voices":
                st.caption("En la demo sin claves todo es simulado salvo la voz (edge-tts real).")
    _store_mode(mode)
    return mode


# ── Quiénes somos (diálogo) ────────────────────────────────────────────────────────


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")


def host_html(name: str, voice: str, role: str, variant: str = "") -> str:
    """Tarjeta de un locutor: inicial, nombre, «voz sintética» y su papel (todo escapado)."""
    return (
        f'<div class="mb-host"><div class="mb-host__badge{variant}" aria-hidden="true">{escape(name[:1])}</div>'
        f'<div><p class="mb-host__name">{escape(name)}</p>'
        f'<p class="mb-host__voice">{escape(voice)} · sintética (IA)</p>'
        f'<p class="mb-host__role">{escape(_sentence(role))}</p></div></div>'
    )


def about_body() -> None:
    """Contenido de «Quiénes somos»: origen, valores, Toro y Osa (voces sintéticas) y equipo."""
    st.markdown(f'<p class="mb-tagline">{escape(brand.TAGLINE)}</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="mb-about">{ABOUT_ORIGIN}</p>', unsafe_allow_html=True)
    st.markdown("#### Lo que nos importa")
    items = "".join(f"<li><b>{escape(title)}</b> {escape(text)}</li>" for title, text in ABOUT_VALUES)
    st.markdown(f'<ul class="mb-values">{items}</ul>', unsafe_allow_html=True)
    st.markdown("#### Las voces del programa")
    st.caption("Un guiño a *bull & bear*: el toro empuja hacia arriba y la osa pone el «pero».")
    for i, (col, host) in enumerate(zip(st.columns(2), ABOUT_HOSTS, strict=True)):
        with col, st.container(key=f"mb-card-host-{i}"):
            st.html(host_html(*host))
    st.info(
        f"{brand.SPEAKER_A_NAME} y {brand.SPEAKER_B_NAME} son **voces sintéticas generadas por IA** "
        "(texto a voz), no personas reales. Los dos se ciñen a los hechos del análisis: tienen carácter, "
        "pero no opinan sobre qué comprar o vender.",
        icon=":material/record_voice_over:",
    )
    st.markdown("#### El equipo")
    st.markdown(f'<p class="mb-team">{escape(ABOUT_TEAM)}</p>', unsafe_allow_html=True)
    st.caption(f"{brand.BRAND_NAME} es la startup ficticia de una práctica del máster MIAX: "
               "un MVP, no un servicio real.")


@st.dialog("Quiénes somos", width="large")
def about_dialog() -> None:
    """«Quiénes somos» como diálogo (menú ⚙ de la barra superior)."""
    about_body()


# ── Barra superior y pie ───────────────────────────────────────────────────────────


def _brand_html() -> str:
    mark = mark_html(28)
    # Sin <a href>: un enlace HTML recargaría la página y perdería la sesión (modo, cartera, chat);
    # la navegación va por las pestañas (st.page_link).
    return (f'<span class="mb-brand" role="img" aria-label="{escape(brand.BRAND_NAME)}">'
            f'{mark}<span class="mb-brand__name">{escape(brand.BRAND_NAME.lower())}</span></span>')


def topbar(pages: dict[str, st.Page], active: str) -> str:
    """Barra superior: marca, pestañas Hoy · Preguntar · Archivo, chip del modo y menú ⚙.

    Args:
        pages: ``{fichero: st.Page}`` registrados en ``st.navigation``.
        active: fichero de la vista activa (``VIEW_*``), para resaltar su pestaña.

    Returns:
        El modo activo (``current_mode``).
    """
    with st.container(key="mb-topbar", horizontal=True, vertical_alignment="center", gap="small", wrap=False):
        st.html(_brand_html(), width="content")
        with st.container(key="mb-tabs", horizontal=True, vertical_alignment="center", gap=None,
                          width="content", wrap=False):
            for path, title, slug, icon in VIEWS:
                state = "on" if path == active else "off"
                with st.container(key=f"mb-tab-{slug}-{state}", width="content"):
                    st.page_link(pages[path], label=title, icon=icon)
        st.space("stretch")
        mode = mode_popover()
        with st.container(key="mb-menu", width="content"):
            with st.popover("", icon=":material/settings:", help="Menú", width="content"), \
                    st.container(key="mb-menu-pop", gap="small"):
                if st.button("Quiénes somos", icon=":material/groups:", type="tertiary", key="mb_menu_about"):
                    about_dialog()
                st.page_link(pages[VIEW_ARCHIVE], label="Privacidad y mis datos", icon=":material/shield_person:")
    return mode


def footer() -> None:
    """Pie común: aviso legal (MiFID II) una sola vez, voces sintéticas y lema de la marca."""
    with st.container(key="mb-footer"):
        st.divider()
        disclaimer_note()
        st.caption(f"{brand.COMPLIANCE_MOTTO} · Voces sintéticas generadas con IA, no son personas reales.")


def run_app() -> None:
    """Punto de entrada de ``app/main.py``: navegación, barra superior, vista y pie."""
    st.set_page_config(page_title=brand.BRAND_NAME, page_icon=page_icon(), layout="wide",
                       initial_sidebar_state="collapsed")
    apply_theme()
    pages = {path: st.Page(path, title=title, url_path=slug, icon=icon, default=(path == VIEW_HOY))
             for path, title, slug, icon in VIEWS}
    current = st.navigation(list(pages.values()), position="hidden")
    handle_navigation()
    active = next((p for p, page in pages.items() if page.url_path == current.url_path), VIEW_HOY)
    st.set_page_config(page_title=f"{current.title} · {brand.BRAND_NAME}")
    topbar(pages, active)
    current.run()
    footer()


__all__ = [
    "ABOUT_HOSTS",
    "ABOUT_VALUES",
    "MODE_CHIP",
    "VIEWS",
    "VIEW_ARCHIVE",
    "VIEW_ASK",
    "VIEW_HOY",
    "MAX_REAL_ATTEMPTS",
    "about_body",
    "check_real_password",
    "about_dialog",
    "current_mode",
    "footer",
    "host_html",
    "mode_options",
    "mode_popover",
    "real_mode_locked",
    "real_password_required",
    "run_app",
    "topbar",
]
