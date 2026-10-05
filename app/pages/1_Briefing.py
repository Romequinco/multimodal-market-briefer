"""Página "Briefing": genera el briefing del día (carril C, llama a ``pipeline.run_briefing``).

Solo presentación: recoge tickers, cartera (de la sesión) y documentos, llama al pipeline con
un callback de progreso (``"(n/N) …"`` → ``st.status`` + barra) y pinta el resultado. Nunca
instancia proveedores: el modo (real / demo sin claves con voces reales / demo offline) se elige en
la barra lateral y se pasa como ``mode``. Los tickers por defecto salen de ``BRIEFER_DEFAULT_TICKERS``.
«Refrescar datos» genera ignorando la caché diaria de noticias y precios (``use_cache=False``).
"""

from __future__ import annotations

from pathlib import Path

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import (
    StatusProgress,
    demo_mode_banner,
    pending,
    render_briefing,
    show_disclaimer,
    show_error,
    sidebar_mode,
)

from briefer.config import get_settings
from briefer.ingest.tickers import TICKER_UNIVERSE

st.set_page_config(page_title="Briefing · Market Briefer", layout="wide")
mode = sidebar_mode()
use_mock = mode != "real"
settings = get_settings()

st.title("Briefing del día")
demo_mode_banner(mode)
show_disclaimer()

# ── Entradas ─────────────────────────────────────────────────────────────────────
portfolio = st.session_state.get("portfolio")
default_tickers = list(dict.fromkeys(settings.default_tickers))
context_tickers = set(settings.context_tickers)
options = sorted((set(TICKER_UNIVERSE) - context_tickers) | set(default_tickers))
tickers = st.multiselect(
    "Tickers a seguir",
    options=options,
    default=default_tickers,
    format_func=lambda t: f"{t} · {TICKER_UNIVERSE[t]['name']}" if t in TICKER_UNIVERSE else t,
    help="Por defecto, los de `BRIEFER_DEFAULT_TICKERS` en `.env`. Puedes añadir cualquiera del universo.",
)
if context_tickers:
    st.caption(
        "Siempre se añaden como contexto los índices "
        + ", ".join(str(TICKER_UNIVERSE.get(t, {}).get("name", t)) for t in settings.context_tickers)
        + " (precios y noticias generales de mercado)."
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

no_input = not tickers and portfolio is None
if no_input:
    st.caption("Elige al menos un ticker o carga una cartera para generar el briefing.")

# ── Ejecución ────────────────────────────────────────────────────────────────────
b1, b2 = st.columns([1, 3])
generate = b1.button("Generar briefing", type="primary", disabled=no_input)
refresh = b2.button(
    "Refrescar datos",
    disabled=no_input or mode != "real",
    help="Genera el briefing descargando de nuevo noticias y precios (ignora la caché del día). "
    "Solo en modo real.",
)
if generate or refresh:
    from briefer import pipeline

    upload_paths: list[Path] = []
    if uploads:
        upload_dir = settings.cache_path / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        for f in uploads:
            p = upload_dir / Path(f.name).name
            p.write_bytes(f.getvalue())
            upload_paths.append(p)

    st.caption("Generando… no cambies de página hasta que termine." + (
        "" if use_mock else " En modo real tarda entre 30 s y 2 min.")
        + (" Se ignora la caché: noticias y precios recién descargados." if refresh else ""))
    bar = st.progress(0.0, text="Preparando…")
    with st.status("Generando briefing…", expanded=True) as status:
        reporter = StatusProgress(status, bar)
        try:
            briefing = pipeline.run_briefing(
                tickers,
                portfolio=portfolio,
                uploads=upload_paths,
                make_video=make_video,
                deliver=deliver,
                make_cover=make_cover,
                mode=mode,
                use_cache=not refresh,
                progress=reporter,
            )
            st.session_state["briefing"] = briefing
            bar.progress(1.0, text="Briefing listo")
            status.update(label="Briefing listo", state="complete", expanded=False)
        except NotImplementedError as exc:
            status.update(label="Funcionalidad pendiente", state="error")
            step = getattr(exc, "step", None)
            pending(exc, f"el paso «{step}» del pipeline" if step else "alguno de los pasos del pipeline")
        except ValueError as exc:  # entrada no válida (sin tickers, canal desconocido…)
            status.update(label="Revisa los datos de entrada", state="error")
            st.error(f"No se pudo generar el briefing: {exc}")
        except Exception as exc:  # error real: mostrar el paso que falló sin romper la app
            step = getattr(exc, "step", None)
            status.update(label=f"Error en el paso «{step}»" if step else "Error", state="error")
            cause = exc.__cause__ or exc
            what = f"el paso «{step}» del briefing" if step else "el briefing"
            show_error(cause if step else exc, what)
            if mode != "mock":
                st.info("Puedes reintentarlo en **demo offline** (barra lateral), que no depende de la red ni de claves.")

# ── Resultado ────────────────────────────────────────────────────────────────────
if "briefing" in st.session_state:
    st.divider()
    render_briefing(st.session_state["briefing"], key="current")
