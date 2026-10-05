"""Página "Mi cartera": carga la cartera desde CSV para personalizar el briefing (carril C/A).

La cartera vive solo en ``st.session_state["portfolio"]`` (RGPD: no se guarda en disco). La
lectura del CSV la hace ``briefer.ingest.portfolio.load_portfolio_csv``.
"""

from __future__ import annotations

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.theme import apply_theme
from components.players import (
    handle_navigation,
    mode_badge,
    page_link,
    pending,
    portfolio_error_message,
    show_disclaimer,
    sidebar_mode,
)

from briefer.config import get_settings
from briefer.logging_utils import get_logger

log = get_logger("app.cartera")

st.set_page_config(page_title="Mi cartera · Market Briefer", page_icon=":material/account_balance_wallet:",
                   layout="wide")
apply_theme()
handle_navigation()
mode = sidebar_mode()
settings = get_settings()

st.title("Mi cartera")
mode_badge(mode)
st.caption(
    "Privacidad (RGPD): la cartera se usa solo durante esta sesión para filtrar noticias; "
    "no se guarda en disco. Los tickers se usan para buscar noticias y precios, y los tickers con sus pesos se envían al modelo de IA para generar el análisis."
)

sample_path = settings.samples_path / "portfolio_ejemplo.csv"
col1, col2 = st.columns([3, 1])
uploaded = col1.file_uploader("CSV con columnas ticker, weight y/o quantity", type=["csv"])
use_sample = col2.button("Usar cartera de ejemplo")
if sample_path.exists():
    col2.download_button("Descargar plantilla", sample_path.read_bytes(), file_name="portfolio_ejemplo.csv")


FORMAT_HELP = (
    "Formato esperado: una fila de cabecera con `ticker` y `weight` (peso en tanto por uno, que sume 1, o en "
    "porcentaje, que sume 100) y/o `quantity` (nº de acciones). Separador `,` o `;`; decimales con punto o coma. "
    "Ejemplo:\n\n```\nticker,weight\nSAN.MC,0.6\nAAPL,0.4\n```"
)
ERROR_KEY = "_portfolio_error"


def _load(source, name: str) -> None:
    """Carga la cartera con el helper de ingest y la deja en la sesión (errores amables, sin traceback)."""
    from briefer.ingest.portfolio import load_portfolio_csv

    st.session_state.pop(ERROR_KEY, None)
    try:
        st.session_state["portfolio"] = load_portfolio_csv(source, name=name)
        st.success(f"Cartera «{name}» cargada.")
    except NotImplementedError as exc:
        pending(exc, "la lectura de carteras CSV")
    except Exception as exc:  # noqa: BLE001 - nunca un traceback en la UI
        log.info("CSV de cartera rechazado: %s", type(exc).__name__)  # sin contenido: es un dato personal
        st.session_state[ERROR_KEY] = portfolio_error_message(exc)


if use_sample:
    if sample_path.exists():
        _load(sample_path, "Cartera de ejemplo")
    else:
        st.error("No se encuentra la cartera de ejemplo en el servidor. Sube tu propio CSV.")
elif uploaded is not None and st.session_state.get("_portfolio_upload_id") != uploaded.file_id:
    # Solo se procesa una vez por fichero subido (no en cada recarga de la página).
    st.session_state["_portfolio_upload_id"] = uploaded.file_id
    _load(uploaded, "Mi cartera")
elif uploaded is None:
    st.session_state.pop(ERROR_KEY, None)  # se quitó el fichero: el aviso ya no aplica

if st.session_state.get(ERROR_KEY):
    st.error(f"No se pudo cargar la cartera: {st.session_state[ERROR_KEY]}", icon=":material/error:")
    if st.session_state.get("portfolio") is not None:
        st.caption("Se mantiene la cartera que tenías cargada.")
    with st.expander("Cómo debe ser el CSV", expanded=True):
        st.markdown(FORMAT_HELP)

portfolio = st.session_state.get("portfolio")
if portfolio is not None:
    st.subheader(portfolio.name)
    total_w = sum(p.weight or 0.0 for p in portfolio.positions)
    rows = [
        {
            "Ticker": p.ticker,
            "Peso (%)": round(100 * p.weight / total_w, 1) if (p.weight is not None and total_w > 0) else None,
            "Cantidad": p.quantity,
        }
        for p in portfolio.positions
    ]
    st.dataframe(
        rows,
        hide_index=True,
        column_config={
            "Peso (%)": st.column_config.ProgressColumn("Peso", format="%.1f %%", min_value=0.0, max_value=100.0),
        },
    )
    st.caption("La cartera se usará automáticamente en la página «Briefing» mientras dure la sesión.")
    c1, c2 = st.columns(2)
    page_link("pages/1_Briefing.py", "Generar el briefing de mi cartera", ":material/podcasts:", container=c1)
    if c2.button("Olvidar cartera", icon=":material/delete:"):
        st.session_state.pop("portfolio", None)
        st.session_state.pop("_portfolio_upload_id", None)
        st.rerun()
else:
    st.info("No hay cartera cargada. Sube un CSV con columnas `ticker` y `weight` (peso, 0-1) o "
            "`quantity` (nº de acciones), o prueba con la cartera de ejemplo.")

show_disclaimer()
