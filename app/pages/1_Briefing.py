"""Página "Briefing": genera el briefing del día (carril C, llama a ``pipeline.run_briefing``).

Solo presentación: recoge tickers, cartera (de la sesión) y documentos, llama al pipeline con
un callback de progreso y pinta el resultado. Nunca instancia proveedores.
"""

from __future__ import annotations

from pathlib import Path

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import (
    demo_mode_banner,
    pending,
    render_briefing,
    show_disclaimer,
    show_error,
    sidebar_controls,
)

from briefer.config import get_settings
from briefer.ingest.tickers import TICKER_UNIVERSE

st.set_page_config(page_title="Briefing · Market Briefer", layout="wide")
use_mock = sidebar_controls()
settings = get_settings()

st.title("Briefing del día")
demo_mode_banner(use_mock)
show_disclaimer()

# ── Entradas ─────────────────────────────────────────────────────────────────────
portfolio = st.session_state.get("portfolio")
default_tickers = settings.default_tickers
options = sorted(set(TICKER_UNIVERSE) | set(default_tickers))
tickers = st.multiselect(
    "Tickers a seguir",
    options=options,
    default=[t for t in default_tickers if t in options],
    format_func=lambda t: f"{t} · {TICKER_UNIVERSE[t]['name']}" if t in TICKER_UNIVERSE else t,
)
if portfolio is not None:
    st.caption(
        f"Se incluirán también los {len(portfolio.positions)} valores de tu cartera «{portfolio.name}» "
        "(página «Mi cartera»)."
    )

UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "wav", "mp3", "m4a", "ogg", "webm"]
uploads = st.file_uploader(
    "Documentos opcionales: PDF de resultados, capturas de gráficos o notas de voz",
    type=UPLOAD_TYPES,
    accept_multiple_files=True,
    help="Los PDF se leen con extracción de texto + visión; las imágenes con visión; los audios "
    "se transcriben (voz a texto) y se añaden como contexto del análisis.",
)

col1, col2, col3 = st.columns(3)
make_video = col1.checkbox("Generar vídeo corto", value=False, help="Más lento")
make_cover = col2.checkbox("Generar portada con IA", value=False)
deliver = col3.multiselect("Enviar también por", ["email", "telegram"])

# ── Ejecución ────────────────────────────────────────────────────────────────────
if st.button("Generar briefing", type="primary", disabled=not tickers and portfolio is None):
    from briefer import pipeline

    upload_paths: list[Path] = []
    if uploads:
        upload_dir = settings.cache_path / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        for f in uploads:
            p = upload_dir / Path(f.name).name
            p.write_bytes(f.getvalue())
            upload_paths.append(p)

    with st.status("Generando briefing…", expanded=True) as status:
        try:
            briefing = pipeline.run_briefing(
                tickers,
                portfolio=portfolio,
                uploads=upload_paths,
                make_video=make_video,
                deliver=deliver,
                make_cover=make_cover,
                use_mock=use_mock,
                progress=st.write,
            )
            st.session_state["briefing"] = briefing
            status.update(label="Briefing listo", state="complete", expanded=False)
        except NotImplementedError as exc:
            status.update(label="Funcionalidad pendiente", state="error")
            pending(exc, "alguno de los pasos del pipeline aún no está implementado")
        except Exception as exc:  # error real: mostrar sin romper la app
            status.update(label="Error", state="error")
            show_error(exc, "el briefing")

# ── Resultado ────────────────────────────────────────────────────────────────────
if "briefing" in st.session_state:
    st.divider()
    render_briefing(st.session_state["briefing"], key="current")
