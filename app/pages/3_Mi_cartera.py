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
    show_disclaimer,
    sidebar_mode,
)

from briefer.config import get_settings

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


def _load(source, name: str) -> None:
    """Carga la cartera con el helper de ingest y la deja en la sesión."""
    from briefer.ingest.portfolio import load_portfolio_csv

    try:
        st.session_state["portfolio"] = load_portfolio_csv(source, name=name)
        st.success(f"Cartera «{name}» cargada.")
    except NotImplementedError as exc:
        pending(exc, "la lectura de carteras CSV")
    except Exception as exc:
        st.error(f"No se pudo leer el CSV: {exc}")


if use_sample:
    if sample_path.exists():
        _load(sample_path, "Cartera de ejemplo")
    else:
        st.error(f"No se encuentra la cartera de ejemplo en {sample_path}.")
elif uploaded is not None and st.session_state.get("_portfolio_upload_id") != uploaded.file_id:
    # Solo se procesa una vez por fichero subido (no en cada recarga de la página).
    st.session_state["_portfolio_upload_id"] = uploaded.file_id
    _load(uploaded, "Mi cartera")

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
