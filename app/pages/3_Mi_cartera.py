"""Página "Mi cartera": carga la cartera desde CSV o desde una captura del broker (carril C/A).

La cartera vive solo en ``st.session_state["portfolio"]`` (RGPD: no se guarda en disco). La
lectura del CSV la hace ``briefer.ingest.portfolio.load_portfolio_csv``; la de la captura,
``briefer.pipeline.portfolio_from_screenshot`` (visión -> LLM barato; la UI no llama a
proveedores). La captura se lee en memoria (``bytes``), sin ficheros temporales.
"""

from __future__ import annotations

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer.config import get_settings
from briefer.logging_utils import get_logger
from components.brand import setup_page
from components.players import (
    handle_navigation,
    mode_badge,
    page_link,
    pending,
    portfolio_error_message,
    show_disclaimer,
    sidebar_mode,
)
from components.theme import apply_theme

log = get_logger("app.cartera")

setup_page("Mi cartera", ":material/account_balance_wallet:")
apply_theme()
handle_navigation()
mode = sidebar_mode()
settings = get_settings()

st.title("Mi cartera")
mode_badge(mode)
st.caption(
    "Privacidad (RGPD): la cartera se usa solo durante esta sesión para filtrar noticias; "
    "no se guarda en disco. Los tickers se usan para buscar noticias y precios, y los tickers con "
    "sus pesos se envían al modelo de IA para generar el análisis. Si usas una captura de tu broker, "
    "la imagen se envía al modelo de visión para leerla (no se guarda): recórtala para que solo se "
    "vean las posiciones, sin tu nombre ni números de cuenta."
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
IMAGE_ERROR_KEY = "_portfolio_image_error"
DISCARDED_KEY = "_portfolio_discarded"
IMAGE_HELP = (
    "Sube una captura (PNG o JPG) de la pantalla de **posiciones** de tu broker o banco, donde se vea "
    "el nombre o ticker de cada valor y sus títulos, importe o peso. Las filas que no se reconozcan se "
    "descartan y se avisa; para valores fuera de la lista de Briefly, usa el CSV con su ticker de Yahoo."
)


def _load(source, name: str) -> None:
    """Carga la cartera con el helper de ingest y la deja en la sesión (errores amables, sin traceback)."""
    from briefer.ingest.portfolio import load_portfolio_csv

    st.session_state.pop(ERROR_KEY, None)
    try:
        st.session_state["portfolio"] = load_portfolio_csv(source, name=name)
        st.session_state.pop(DISCARDED_KEY, None)  # avisos de una captura anterior: ya no aplican
        st.session_state.pop(IMAGE_ERROR_KEY, None)
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

def _load_image(image: bytes, name: str) -> None:
    """Lee la captura vía pipeline (visión -> LLM barato) y deja la cartera en la sesión."""
    st.session_state.pop(IMAGE_ERROR_KEY, None)
    st.session_state.pop(DISCARDED_KEY, None)
    from briefer.pipeline import portfolio_from_screenshot  # perezoso: solo al leer una captura

    stats: dict = {}
    try:
        with st.spinner("Leyendo la captura con el modelo de visión…"):
            portfolio, _metric = portfolio_from_screenshot(image, name=name, mode=mode, stats_out=stats)
        st.session_state["portfolio"] = portfolio
        st.session_state[DISCARDED_KEY] = list(stats.get("discarded") or [])
        if mode == "real":
            st.success(f"Cartera «{name}» leída de la captura: {len(portfolio.positions)} posiciones.")
        else:
            # Sin visión real, el mock devuelve siempre la cartera de la captura de ejemplo.
            st.info(f"Modo demo: se usa la cartera de la captura de ejemplo ({len(portfolio.positions)} "
                    "posiciones). Activa el modo real para leer tu propia captura.")
    except NotImplementedError as exc:
        pending(exc, "la lectura de carteras desde una captura")
    except ValueError as exc:
        log.info("Captura de cartera rechazada: %s", type(exc).__name__)  # sin contenido: dato personal
        st.session_state[IMAGE_ERROR_KEY] = portfolio_error_message(exc)
    except Exception as exc:  # noqa: BLE001 - nunca un traceback en la UI
        log.warning("Fallo al leer la captura de cartera: %s", type(exc).__name__)
        st.session_state[IMAGE_ERROR_KEY] = (
            "El servicio de IA no ha podido leer la captura ahora mismo. Inténtalo de nuevo en unos "
            "segundos o carga tu cartera con un CSV."
        )


st.markdown("**…o desde una captura de tu broker**")
image_sample = settings.samples_path / "cartera_ejemplo.png"
icol1, icol2 = st.columns([3, 1])
shot = icol1.file_uploader("Captura de tu broker (PNG/JPG)", type=["png", "jpg", "jpeg"], key="portfolio_shot")
read_shot = icol2.button("Leer captura", icon=":material/document_scanner:", disabled=shot is None)
use_shot_sample = icol2.button("Usar captura de ejemplo")
if shot is not None:
    icol1.image(shot.getvalue(), caption="Vista previa (no se guarda)", width=320)
if read_shot and shot is not None:
    _load_image(shot.getvalue(), "Mi cartera (captura)")
elif use_shot_sample:
    if image_sample.exists():
        _load_image(image_sample.read_bytes(), "Cartera de ejemplo (captura)")
    else:
        st.error("No se encuentra la captura de ejemplo en el servidor. Sube tu propia captura.")

if st.session_state.get(IMAGE_ERROR_KEY):
    st.error(f"No se pudo leer la captura: {st.session_state[IMAGE_ERROR_KEY]}", icon=":material/error:")
    if st.session_state.get("portfolio") is not None:
        st.caption("Se mantiene la cartera que tenías cargada.")
    with st.expander("Qué captura sirve", expanded=True):
        st.markdown(IMAGE_HELP)
if st.session_state.get(DISCARDED_KEY):
    lines = "\n".join(f"- {d['row']}: {d['reason']}" for d in st.session_state[DISCARDED_KEY])
    st.warning(f"Filas de la captura que no se han incluido:\n\n{lines}", icon=":material/warning:")

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
        st.session_state.pop(DISCARDED_KEY, None)
        st.rerun()
else:
    st.info("No hay cartera cargada. Sube un CSV con columnas `ticker` y `weight` (peso, 0-1) o "
            "`quantity` (nº de acciones), una captura de la pantalla de posiciones de tu broker, o prueba "
            "con la cartera de ejemplo.")

show_disclaimer()
