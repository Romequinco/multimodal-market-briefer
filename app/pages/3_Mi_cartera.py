"""Página "Mi cartera": carga la cartera desde CSV para personalizar el briefing (carril C/A).

La cartera vive solo en ``st.session_state["portfolio"]`` (RGPD: no se guarda en disco). La
lectura del CSV la hace ``briefer.ingest.portfolio.load_portfolio_csv``.
"""

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
    if st.button("Olvidar cartera"):
        st.session_state.pop("portfolio", None)
        st.rerun()
else:
    st.write("No hay cartera cargada.")
