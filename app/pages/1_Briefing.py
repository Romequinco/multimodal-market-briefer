"""Página "Briefing": genera el briefing del día (carril C, llama a ``pipeline.run_briefing``).

Solo presentación: recoge tickers, cartera (de la sesión) y documentos, llama al pipeline con
un callback de progreso (``"(n/N) …"`` → ``st.status`` + barra) y pinta el resultado. Nunca
instancia proveedores: el modo (real / demo sin claves con voces reales / demo offline) se elige en
la barra lateral y se pasa como ``mode``. Los tickers por defecto salen de ``BRIEFER_DEFAULT_TICKERS``.
«Refrescar datos» genera ignorando la caché diaria de noticias y precios (``use_cache=False``).

Estado y reruns:

- Los botones no lanzan el pipeline directamente: un ``on_click`` deja una **petición** en la sesión
  y la página la consume una sola vez (``pop``). Mientras se genera, los botones salen deshabilitados
  (``_briefing_busy``), así que un doble clic no lanza dos briefings (ni cobra dos veces en modo real)
  y una recarga de la página no lo relanza.
- Las subidas se copian a una carpeta temporal **propia de esa ejecución** (dos sesiones con un
  fichero del mismo nombre no se pisan) que se borra al terminar.
- El resultado queda en ``st.session_state["briefing"]`` (contexto de «Preguntar»).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer.config import get_settings
from briefer.ingest.tickers import TICKER_UNIVERSE
from components.brand import setup_page
from components.players import (
    StatusProgress,
    briefing_tape,
    demo_mode_banner,
    featured_briefing,
    handle_navigation,
    pending,
    render_briefing,
    set_active_briefing,
    show_disclaimer,
    show_error,
    sidebar_mode,
)
from components.theme import apply_theme

setup_page("Briefing", ":material/podcasts:")
apply_theme()
handle_navigation()
mode = sidebar_mode()
use_mock = mode != "real"
settings = get_settings()

REQUEST_KEY = "_briefing_request"
BUSY_KEY = "_briefing_busy"


def _tape_briefing():
    """Briefing de la cinta: el activo de la sesión o, si no hay, el destacado de la portada."""
    if "briefing" in st.session_state:
        return st.session_state["briefing"]
    try:
        featured = featured_briefing()
    except Exception:
        return None
    return featured[0] if featured else None


briefing_tape(_tape_briefing())
st.title("Briefing del día")
demo_mode_banner(mode)

# ── Entradas ─────────────────────────────────────────────────────────────────────
portfolio = st.session_state.get("portfolio")
default_tickers = list(dict.fromkeys(settings.default_tickers))
context_tickers = set(settings.context_tickers)
options = sorted((set(TICKER_UNIVERSE) - context_tickers) | set(default_tickers))
tickers = st.multiselect(
    "Valores a seguir",
    options=options,
    default=default_tickers,
    format_func=lambda t: f"{TICKER_UNIVERSE[t]['name']} · {t}" if t in TICKER_UNIVERSE else t,
    accept_new_options=True,
    placeholder="Escribe un valor: «Santander», «AAPL», «REP.MC»…",
    help="Por defecto, los de `BRIEFER_DEFAULT_TICKERS` en `.env`. Puedes escribir otro ticker de Yahoo "
    "Finance o el nombre de la empresa (se normaliza: «santander» → SAN.MC).",
)
if context_tickers:
    st.caption(
        "Como referencia se añaden siempre los índices "
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
    "se transcriben (voz a texto) y se añaden como contexto del análisis. Se borran al terminar.",
)

#: Funciones que el pipeline aún no implementa: se enseñan desactivadas y «en desarrollo» para
#: que la demo nunca muestre avisos de fallo. Cuando se implementen, basta con pasar a ``False``.
IN_DEVELOPMENT = {"email": True}
#: Requisitos de configuración: sin ellos el control se desactiva con la explicación.
COVER_READY = mode != "real" or settings.briefer_image_gen_provider != "none"
TELEGRAM_READY = bool(settings.telegram_bot_token and settings.telegram_chat_id)
with st.expander("Opciones avanzadas: vídeo, portada y envíos"):
    col1, col2, col3 = st.columns(3)
    make_video = col1.checkbox("Generar vídeo corto", value=False,
                               help="Vídeo vertical 9:16 con el podcast, los gráficos y subtítulos (unos segundos más).")
    make_cover = col2.checkbox("Generar portada con IA", value=False, disabled=not COVER_READY,
                               help="Ilustración generada por IA a partir del tono del día (no representa datos)."
                               if COVER_READY else "Configura BRIEFER_IMAGE_GEN_PROVIDER (p. ej. gemini) en .env.")
    channels = [c for c in ("email", "telegram") if not IN_DEVELOPMENT.get(c) and (c != "telegram" or TELEGRAM_READY)]
    deliver = col3.multiselect("Enviar también por", channels, disabled=not channels,
                               help="Telegram: configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID "
                               "(scripts/telegram_setup.py). Email: en desarrollo.")
    st.caption("El email está en desarrollo; el briefing siempre queda disponible en la web.")
make_cover = bool(make_cover) and COVER_READY
deliver = [c for c in deliver if c in channels]

no_input = not tickers and portfolio is None
if no_input:
    st.caption("Elige al menos un valor o carga una cartera para generar el briefing.")

# ── Ejecución ────────────────────────────────────────────────────────────────────


def _request(refresh: bool) -> None:
    """``on_click``: deja la petición; la página la ejecuta una sola vez en esta recarga."""
    if not st.session_state.get(BUSY_KEY):
        st.session_state[REQUEST_KEY] = {"refresh": refresh}


request = st.session_state.pop(REQUEST_KEY, None)
busy = request is not None and not no_input
st.session_state[BUSY_KEY] = busy

buttons = st.empty()


def _render_buttons(disabled: bool) -> None:
    """Botones de generar/refrescar. Durante la generación se pintan deshabilitados (otra clave) y al
    terminar se sustituyen en el mismo hueco por los activos, sin esperar a otra recarga."""
    suffix = "_busy" if disabled else ""
    with buttons.container():
        b1, b2 = st.columns([1, 3])
        b1.button(
            "Generar briefing", type="primary", disabled=no_input or disabled, on_click=_request,
            args=(False,), icon=":material/play_arrow:", key=f"generate{suffix}",
        )
        b2.button(
            "Refrescar datos",
            disabled=no_input or mode != "real" or disabled,
            on_click=_request,
            args=(True,),
            key=f"refresh{suffix}",
            help="Genera el briefing descargando de nuevo noticias y precios (ignora la caché del día). "
            "Solo en modo real.",
        )


_render_buttons(busy)


def _save_uploads(files) -> tuple[list[Path], Path | None]:
    """Copia las subidas a una carpeta temporal única de esta ejecución."""
    if not files:
        return [], None
    base = settings.cache_path / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="run_", dir=base))
    paths: list[Path] = []
    for f in files:
        p = folder / (Path(f.name).name or "subida")
        p.write_bytes(f.getvalue())
        paths.append(p)
    return paths, folder


if request is not None and not no_input:
    from briefer import pipeline

    refresh = bool(request.get("refresh"))
    upload_paths, upload_dir = _save_uploads(uploads)
    st.caption(":material/hourglass_top: Generando… no cambies de página hasta que termine." + (
        "" if use_mock else " En modo real tarda entre 30 s y 2 min.")
        + (" Se ignora la caché: noticias y precios recién descargados." if refresh else ""))
    bar = st.progress(0.0, text="Preparando…")
    try:
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
                set_active_briefing(briefing)
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
                    st.info("Puedes reintentarlo en **demo offline** (barra lateral), que no depende de la "
                            "red ni de claves, o escuchar el briefing de ejemplo en la portada.")
    finally:
        st.session_state[BUSY_KEY] = False
        if upload_dir is not None:  # RGPD: los documentos subidos no se quedan en disco
            shutil.rmtree(upload_dir, ignore_errors=True)
    _render_buttons(False)  # listo (o con error): los botones vuelven a estar activos

# ── Resultado ────────────────────────────────────────────────────────────────────
if "briefing" in st.session_state:
    st.divider()
    render_briefing(st.session_state["briefing"], key="current")
else:
    st.info("Elige tus valores y pulsa **Generar briefing**. En modo demo tarda unos segundos; el "
            "resultado aparecerá aquí con el podcast, la transcripción, los gráficos y «Cómo se hizo».")

show_disclaimer()
