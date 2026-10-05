"""Identidad de marca: una sola fuente para el nombre, el eslogan y los locutores.

La marca visible es **Briefly** (ver ``docs/08_identidad_marca.md``). El código interno sigue
llamándose ``briefer`` (paquete, variables ``BRIEFER_*``, repo): solo cambia lo que ve u oye el usuario.
App, guion, transcripción, gráficos, metadatos del audio y envíos leen de aquí en vez de repetir textos.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

#: Nombre de la marca y del programa (el podcast se llama igual).
BRAND_NAME = "Briefly"
#: Eslogan.
TAGLINE = "El cierre del día, mientras vuelves a casa"
#: Propuesta de valor en una línea (portada, README, pitch).
VALUE_PROPOSITION = "Lo que ha movido tu cartera hoy, contado a dos voces en unos cuatro minutos."
#: Edición actual: el resumen al cierre de la sesión (la de mañana queda como roadmap).
EDITION = "edición de noche"
#: Saludo de la edición de noche (apertura del guion).
GREETING = "Buenas noches"

#: Locutores por defecto: voz A (masculina) = Toro, voz B (femenina) = Osa (guiño a *bull & bear*).
#: Se pueden cambiar con ``BRIEFER_SPEAKER_A_NAME`` / ``BRIEFER_SPEAKER_B_NAME``.
SPEAKER_A_NAME = "Toro"
SPEAKER_B_NAME = "Osa"
#: Papel de cada locutor (prompt del Guionista y página «Quiénes somos»). Personalidad, nunca opinión:
#: los dos se ciñen a los hechos del análisis y ninguno recomienda comprar ni vender.
SPEAKER_A_ROLE = "el optimista: abre el episodio y se fija primero en lo que sube"
SPEAKER_B_ROLE = "la prudente: pone el contexto y los riesgos, y cierra con el aviso legal"

#: Lema de compliance como valor de marca.
COMPLIANCE_MOTTO = "Te contamos el mercado; tú decides."

#: Carpeta de los activos de marca (logo, icono, banner); se generan con ``scripts/generar_marca.py``.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "docs" / "assets" / "marca"


def episode_title(day: date) -> str:
    """Título del episodio: ``"Briefly · 05/10/2026"``."""
    return f"{BRAND_NAME} · {day:%d/%m/%Y}"


__all__ = [
    "ASSETS_DIR",
    "BRAND_NAME",
    "COMPLIANCE_MOTTO",
    "EDITION",
    "GREETING",
    "SPEAKER_A_NAME",
    "SPEAKER_A_ROLE",
    "SPEAKER_B_NAME",
    "SPEAKER_B_ROLE",
    "TAGLINE",
    "VALUE_PROPOSITION",
    "episode_title",
]
