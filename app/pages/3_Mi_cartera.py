"""Página "Mi cartera": carga la cartera desde CSV para personalizar el briefing (carril C/A)."""

from __future__ import annotations

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import pending, show_disclaimer, sidebar_controls

from briefer.config import get_settings

st.set_page_config(page_title="Mi cartera · Market Briefer", layout="wide")
sidebar_controls()
settings = get_settings()

st.title("Mi cartera")
show_disclaimer()
st.caption(
    "Privacidad (RGPD): la cartera se usa solo durante esta sesión para filtrar noticias; "
    "no se guarda en disco ni se comparte. Solo los tickers se envían a los proveedores de datos."
)

sample_path = settings.samples_path / "portfolio_ejemplo.csv"
col1, col2 = st.columns([3, 1])
uploaded = col1.file_uploader("CSV con columnas ticker, weight y/o quantity", type=["csv"])
use_sample = col2.button("Usar cartera de ejemplo")
if sample_path.exists():
    col2.download_button("Descargar plantilla", sample_path.read_bytes(), file_name="portfolio_ejemplo.csv")

source = uploaded if uploaded is not None else (sample_path if use_sample else None)
if source is not None:
    from briefer.ingest.portfolio import load_portfolio_csv

    try:
        name = "Cartera de ejemplo" if source is sample_path else "Mi cartera"
        st.session_state["portfolio"] = load_portfolio_csv(source, name=name)
        st.success("Cartera cargada.")
    except NotImplementedError as exc:
        pending(exc, "la lectura de carteras CSV")
    except Exception as exc:
        st.error(f"No se pudo leer el CSV: {exc}")

portfolio = st.session_state.get("portfolio")
if portfolio is not None:
    st.subheader(portfolio.name)
    st.dataframe([p.model_dump() for p in portfolio.positions])
    # TODO: gráfico de reparto (media.charts.make_portfolio_chart) y edición con st.data_editor.
    if st.button("Olvidar cartera"):
        del st.session_state["portfolio"]
        st.rerun()
else:
    st.write("No hay cartera cargada.")
