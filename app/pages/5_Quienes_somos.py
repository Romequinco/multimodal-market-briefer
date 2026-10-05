"""Página «Quiénes somos» (carril C): la startup ficticia detrás del MVP, en tono de broma.

Texto de ``docs/08_identidad_marca.md`` (origen, misión, valores y equipo) y presentación de los dos
locutores, Toro y Osa, con su papel (``briefer.brand``). Deja claro que **las dos voces son sintéticas**
(IA) y, como todas las páginas, termina con el aviso legal.
"""

from __future__ import annotations

from html import escape

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer import brand
from components.brand import mark_html, setup_page
from components.players import PAGE_BRIEFING, handle_navigation, page_link, show_disclaimer, sidebar_mode
from components.theme import apply_theme

setup_page("Quiénes somos", ":material/groups:")
apply_theme()
handle_navigation()
sidebar_mode()

ORIGIN = (
    f"<b>{escape(brand.BRAND_NAME)}</b> nació en un atasco de la M-30, cuando tres estudiantes de MIAX se "
    "dieron cuenta de que llegaban a casa sin saber qué había hecho su cartera. "
    "Nuestra misión: que lo sepas antes de quitarte los zapatos."
)
VALUES: tuple[tuple[str, str], ...] = (
    (brand.COMPLIANCE_MOTTO, "No damos consejos, ni siquiera de cocina."),
    ("Fuente o no ha pasado.", "Cada noticia lleva su enlace."),
    ("Cuatro minutos.", "Si tu cartera necesita más, el problema no es el podcast."),
    ("Voces sintéticas, y orgullosas de serlo.", "Nadie se ha quedado afónico grabando este programa."),
)
HOSTS: tuple[tuple[str, str, str, str], ...] = (
    (brand.SPEAKER_A_NAME, "Voz A", brand.SPEAKER_A_ROLE, ""),
    (brand.SPEAKER_B_NAME, "Voz B", brand.SPEAKER_B_ROLE, " mb-host__badge--b"),
)
TEAM = "Tres personas, seis modelos de IA, un toro y una osa."


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


with st.container(key="mb-about-head", horizontal=True, vertical_alignment="center", gap="medium"):
    mark = mark_html()
    if mark:
        st.html(mark, width="content")
    st.title("Quiénes somos", anchor=False, width="content")
st.markdown(f'<p class="mb-tagline">{escape(brand.TAGLINE)}</p>', unsafe_allow_html=True)

st.markdown(f'<p class="mb-about">{ORIGIN}</p>', unsafe_allow_html=True)

st.markdown("### Lo que nos importa")
items = "".join(f"<li><b>{escape(title)}</b> {escape(text)}</li>" for title, text in VALUES)
st.markdown(f'<ul class="mb-values">{items}</ul>', unsafe_allow_html=True)

st.markdown("### Las voces del programa")
st.caption("Un guiño a *bull & bear*: el toro empuja hacia arriba y la osa pone el «pero».")
for i, (col, host) in enumerate(zip(st.columns(2), HOSTS, strict=True)):
    with col, st.container(key=f"mb-card-host-{i}"):
        st.html(host_html(*host))

st.info(
    f"{brand.SPEAKER_A_NAME} y {brand.SPEAKER_B_NAME} son **voces sintéticas generadas por IA** "
    "(texto a voz), no personas reales. Los dos se ciñen a los hechos del análisis: tienen carácter, "
    "pero no opinan sobre qué comprar o vender.",
    icon=":material/record_voice_over:",
)

st.markdown("### El equipo")
st.markdown(f'<p class="mb-team">{escape(TEAM)}</p>', unsafe_allow_html=True)
st.caption(f"{brand.BRAND_NAME} es la startup ficticia de una práctica del máster MIAX: un MVP, no un servicio real.")
page_link(PAGE_BRIEFING, "Escuchar el briefing de hoy", ":material/podcasts:")

show_disclaimer()
