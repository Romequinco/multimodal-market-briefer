"""Diálogo «Nuevo briefing»: valores, cartera, documentos y opciones → ``pipeline.run_briefing``.

Interfaz pública (la usan las vistas):

- ``new_briefing_button(key=…)``: botón que abre el diálogo ``st.dialog("Nuevo briefing")``.
- ``new_briefing_form(key="nb")``: el cuerpo del diálogo (sin diálogo, para tests).

Solo presentación: la cartera se lee con ``briefer.ingest.portfolio.load_portfolio_csv`` (CSV) o
``briefer.pipeline.portfolio_from_screenshot`` (captura); el briefing con ``pipeline.run_briefing``
y el modo del chip de la barra superior (``shell.current_mode``). Nunca instancia proveedores.

Estado y reruns:

- La cartera vive solo en ``st.session_state["portfolio"]`` (RGPD, ADR-005: nunca a disco).
- «Generar» no lanza el pipeline en su callback: deja una **petición** (valores, opciones y
  subidas leídas del estado de los widgets) que el formulario consume una sola vez (``pop``). Mientras
  se genera, el formulario no se pinta (no hay doble clic posible); si falla, el error queda en el
  diálogo y el formulario vuelve debajo con lo que había (los widgets se pintan en esa misma
  ejecución, así que no pierden su valor).
- Las subidas se copian a una carpeta temporal propia de la ejecución que se borra **siempre**.
- Al terminar: ``set_active_briefing(b)``, ``st.session_state["_nb_done"] = b.id`` y ``st.rerun()``
  (cierra el diálogo; «Hoy» lo muestra).
"""

from __future__ import annotations

import html
import re
import shutil
import tempfile
from pathlib import Path

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer.config import get_settings
from briefer.ingest.tickers import TICKER_UNIVERSE
from briefer.logging_utils import get_logger
from components.players import (
    StatusProgress,
    pending,
    portfolio_error_message,
    set_active_briefing,
    show_error,
)

log = get_logger("app.nuevo")

DONE_KEY = "_nb_done"
PORTFOLIO_KEY = "portfolio"
LAST_TICKERS_KEY = "_nb_last_tickers"
#: Mensajes de la sección cartera (sobreviven a los reruns del diálogo): lista de ``(tipo, texto)``.
PF_MSGS_KEY = "_nb_pf_msgs"
PF_ERROR_KEY = "_nb_pf_error"  # (origen "csv"|"shot", texto)
PF_DISCARDED_KEY = "_nb_pf_discarded"
PF_UPLOAD_ID_KEY = "_nb_pf_upload_id"
PF_LAST_SRC_KEY = "_nb_pf_last_src"  # origen de la cartera cargada (el widget se pierde al cerrar el diálogo)

UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "wav", "mp3", "m4a", "ogg", "webm"]
_KIND_BY_EXT = {
    "pdf": ("PDF", "pdf"),
    **{ext: ("GRÁFICO", "img") for ext in ("png", "jpg", "jpeg", "webp")},
    **{ext: ("VOZ", "aud") for ext in ("wav", "mp3", "m4a", "ogg", "webm")},
}

PF_SOURCES = {"none": "Sin cartera", "csv": "CSV", "shot": "Captura del broker", "sample": "Ejemplo"}

SHORTCUTS = {
    "usual": "Mi selección habitual",
    "ibex": "Solo IBEX",
    "us": "Solo EE. UU.",
    "clear": "Vaciar",
}

FORMAT_HELP = (
    "Formato esperado: una fila de cabecera con `ticker` y `weight` (peso en tanto por uno, que sume 1, o en "
    "porcentaje, que sume 100) y/o `quantity` (nº de acciones). Separador: coma o punto y coma; decimales con punto "
    "o coma. "
    "Ejemplo:\n\n```\nticker,weight\nSAN.MC,0.6\nAAPL,0.4\n```"
)
IMAGE_HELP = (
    "Sube una captura (PNG o JPG) de la pantalla de **posiciones** de tu broker o banco, donde se vea "
    "el nombre o ticker de cada valor y sus títulos, importe o peso. Las filas que no se reconozcan se "
    "descartan y se avisa; para valores fuera de la lista de Briefly, usa el CSV con su ticker de Yahoo."
)
PRIVACY_NOTE = "Tu cartera solo vive en esta sesión: no se guarda en disco."
PRIVACY_DETAIL = (
    "Los tickers se usan para buscar noticias y precios, y los tickers con sus pesos se envían al modelo "
    "de IA para el análisis. Una captura se envía al modelo de visión para leerla (no se guarda): "
    "recórtala para que solo se vean las posiciones, sin tu nombre ni números de cuenta."
)


# ── Utilidades puras ──────────────────────────────────────────────────────────────


def ticker_label(ticker: str) -> str:
    """``"SAN.MC"`` → ``"Banco Santander · SAN.MC"``; texto libre tal cual."""
    info = TICKER_UNIVERSE.get(ticker)
    return f"{info['name']} · {ticker}" if info else str(ticker)


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md_escape(text) -> str:
    """Texto leído por IA (OCR) → Markdown inerte: sin enlaces, imágenes, HTML ni formato inyectable."""
    flat = " ".join(str(text).split())[:200]
    return _MD_SPECIAL.sub(r"\\\1", flat)


def doc_kind(name: str) -> tuple[str, str]:
    """Tipo detectado por extensión: ``("PDF"|"GRÁFICO"|"VOZ"|"DOC", clase CSS)``."""
    ext = Path(name).suffix.lower().lstrip(".")
    return _KIND_BY_EXT.get(ext, ("DOC", "doc"))


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary_text(n_values: int, n_docs: int, has_portfolio: bool) -> str:
    """Resumen del pie: ``"5 valores · 1 documento · cartera"``."""
    parts = [_plural(n_values, "valor", "valores"), _plural(n_docs, "documento", "documentos")]
    if has_portfolio:
        parts.append("cartera")
    return " · ".join(parts)


def _market(ticker: str) -> str:
    return "es" if ticker.upper().endswith(".MC") else "us"


def _shortcut_tickers(kind: str, defaults: list[str], universe: list[str]) -> list[str]:
    """Tickers de un atajo: los habituales del mercado pedido o, si no hay, los 5 primeros del universo."""
    if kind == "usual":
        return list(defaults)
    if kind == "clear":
        return []
    market = "es" if kind == "ibex" else "us"
    picked = [t for t in defaults if _market(t) == market]
    return picked or [t for t in universe if _market(t) == market][:5]


def _section(num: int, title: str, note: str | None = None) -> None:
    extra = f'<span class="mb-nb-opt">{html.escape(note)}</span>' if note else ""
    st.markdown(
        f'<div class="mb-nb-sec"><span class="mb-nb-num">{num}</span>'
        f'<span class="mb-nb-title">· {html.escape(title.upper())}</span>{extra}</div>',
        unsafe_allow_html=True,
    )


# ── Cartera ───────────────────────────────────────────────────────────────────────


def _pf_message(kind: str, text: str) -> None:
    st.session_state.setdefault(PF_MSGS_KEY, []).append((kind, text))


def _clear_pf_feedback() -> None:
    for k in (PF_MSGS_KEY, PF_ERROR_KEY, PF_DISCARDED_KEY):
        st.session_state.pop(k, None)


def _load_csv(source, name: str) -> None:
    """Carga un CSV de cartera (errores amables, sin traceback ni contenido en el log)."""
    from briefer.ingest.portfolio import load_portfolio_csv

    _clear_pf_feedback()
    try:
        portfolio = load_portfolio_csv(source, name=name)
    except NotImplementedError as exc:
        pending(exc, "la lectura de carteras CSV")
        return
    except Exception as exc:  # noqa: BLE001 - nunca un traceback en la UI
        log.info("CSV de cartera rechazado: %s", type(exc).__name__)  # sin contenido: dato personal
        st.session_state[PF_ERROR_KEY] = ("csv", portfolio_error_message(exc))
        return
    st.session_state[PORTFOLIO_KEY] = portfolio
    _pf_message("success", f"Cartera «{name}» cargada: {len(portfolio.positions)} posiciones.")


def _load_image(image: bytes, name: str, mode: str) -> None:
    """Lee la captura vía pipeline (visión → LLM barato), en memoria, y deja la cartera en la sesión."""
    from briefer.pipeline import portfolio_from_screenshot  # perezoso: solo al leer una captura

    _clear_pf_feedback()
    stats: dict = {}
    try:
        with st.spinner("Leyendo la captura con el modelo de visión…"):
            portfolio, _metric = portfolio_from_screenshot(image, name=name, mode=mode, stats_out=stats)
    except NotImplementedError as exc:
        pending(exc, "la lectura de carteras desde una captura")
        return
    except ValueError as exc:
        log.info("Captura de cartera rechazada: %s", type(exc).__name__)  # sin contenido: dato personal
        st.session_state[PF_ERROR_KEY] = ("shot", portfolio_error_message(exc))
        return
    except Exception as exc:  # noqa: BLE001 - nunca un traceback en la UI
        log.warning("Fallo al leer la captura de cartera: %s", type(exc).__name__)
        st.session_state[PF_ERROR_KEY] = (
            "shot",
            "El servicio de IA no ha podido leer la captura ahora mismo. Inténtalo de nuevo en unos "
            "segundos o carga tu cartera con un CSV.",
        )
        return
    st.session_state[PORTFOLIO_KEY] = portfolio
    st.session_state[PF_DISCARDED_KEY] = list(stats.get("discarded") or [])
    if stats.get("weight_note"):
        _pf_message("warning", str(stats["weight_note"]))
    if mode == "real":
        _pf_message("success", f"Cartera «{name}» leída de la captura: {len(portfolio.positions)} posiciones.")
    else:
        _pf_message("info", f"Modo demo: se usa la cartera de la captura de ejemplo ({len(portfolio.positions)} "
                            "posiciones). Activa el modo real para leer tu propia captura.")


def _forget_portfolio() -> None:
    st.session_state.pop(PORTFOLIO_KEY, None)
    st.session_state.pop(PF_UPLOAD_ID_KEY, None)
    st.session_state.pop(PF_LAST_SRC_KEY, None)
    _clear_pf_feedback()


def forget_portfolio(key: str = "nb") -> None:
    """Borra la cartera de la sesión y todo el estado de la sección cartera (p. ej. «Borrar mis datos»).

    Quita ``"portfolio"``, los avisos/errores/filas descartadas, el id de la última subida y el estado
    de los widgets de la sección (origen, CSV y captura subidos), así que el diálogo vuelve a
    «Sin cartera» la próxima vez que se abra. No toca disco: la cartera nunca se escribe en él.
    """
    _forget_portfolio()
    for suffix in ("_pf_src", "_pf_csv", "_pf_shot", "_pf_read", "_pf_shot_sample", "_pf_forget"):
        st.session_state.pop(f"{key}{suffix}", None)


def _on_source_change(key: str, sample_csv: Path) -> None:
    """``on_change`` del selector de origen: «Sin cartera» la quita; «Ejemplo» la carga al instante."""
    source = st.session_state.get(f"{key}_pf_src") or "none"
    st.session_state[PF_LAST_SRC_KEY] = source
    if source == "none":
        _forget_portfolio()
    elif source == "sample":
        if sample_csv.exists():
            _load_csv(sample_csv, "Cartera de ejemplo")
        else:
            _clear_pf_feedback()
            st.session_state[PF_ERROR_KEY] = (
                "csv", "No se encuentra la cartera de ejemplo en el servidor. Sube tu propio CSV.")
    else:
        st.session_state.pop(PF_ERROR_KEY, None)


def _on_forget(key: str) -> None:
    _forget_portfolio()
    st.session_state[f"{key}_pf_src"] = "none"


def portfolio_table_html(portfolio) -> str:
    """Tabla compacta ticker / peso (barra) / cantidad (función pura)."""
    total_w = sum(p.weight or 0.0 for p in portfolio.positions)
    rows = []
    for p in portfolio.positions:
        pct = 100 * p.weight / total_w if (p.weight is not None and total_w > 0) else None
        if pct is None:
            bar = "—"
        else:
            label = f"{pct:.1f}".replace(".", ",")
            bar = (f'<span class="mb-nb-bar"><i style="width:{min(pct, 100):.1f}%"></i></span>'
                   f'<span class="mb-nb-pct">{label} %</span>')
        qty = f"{p.quantity:g}".replace(".", ",") if p.quantity is not None else "—"
        rows.append(f"<tr><td class=\"mb-nb-tk\">{html.escape(p.ticker)}</td><td>{bar}</td>"
                    f"<td class=\"mb-nb-qty\">{qty}</td></tr>")
    return ('<table class="mb-nb-pftable"><thead><tr><th>Ticker</th><th>Peso</th><th>Cantidad</th></tr>'
            f"</thead><tbody>{''.join(rows)}</tbody></table>")


def _portfolio_section(key: str, mode: str, settings) -> None:
    sample_csv = settings.samples_path / "portfolio_ejemplo.csv"
    sample_shot = settings.samples_path / "cartera_ejemplo.png"
    portfolio = st.session_state.get(PORTFOLIO_KEY)
    src_key = f"{key}_pf_src"
    if src_key not in st.session_state:
        # Al reabrir el diálogo, el selector vuelve al origen de la cartera que sigue cargada.
        last = st.session_state.get(PF_LAST_SRC_KEY)
        st.session_state[src_key] = "none" if portfolio is None else (last if last in PF_SOURCES else "csv")

    st.segmented_control(
        "Origen de la cartera",
        options=list(PF_SOURCES),
        format_func=PF_SOURCES.get,
        key=src_key,
        required=True,
        label_visibility="collapsed",
        on_change=_on_source_change,
        args=(key, sample_csv),
    )
    source = st.session_state.get(src_key) or "none"

    if source == "csv":
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        uploaded = c1.file_uploader(
            "CSV con columnas ticker, weight y/o quantity", type=["csv"], key=f"{key}_pf_csv",
            help="Peso en tanto por uno (suma 1) o en porcentaje (suma 100), y/o nº de acciones. "
                 "Separador `,` o `;`.",
        )
        if sample_csv.exists():
            c2.download_button("Descargar plantilla", sample_csv.read_bytes(), file_name="portfolio_ejemplo.csv",
                               icon=":material/download:", key=f"{key}_pf_tpl", width="stretch")
        if uploaded is not None and st.session_state.get(PF_UPLOAD_ID_KEY) != uploaded.file_id:
            # Solo se procesa una vez por fichero subido (no en cada rerun del diálogo).
            st.session_state[PF_UPLOAD_ID_KEY] = uploaded.file_id
            _load_csv(uploaded, "Mi cartera")
        elif uploaded is None and (st.session_state.get(PF_ERROR_KEY) or ("",))[0] == "csv":
            st.session_state.pop(PF_ERROR_KEY, None)  # se quitó el fichero: el aviso ya no aplica
    elif source == "shot":
        shot = st.file_uploader(
            "Captura de la pantalla de posiciones de tu broker (PNG/JPG)", type=["png", "jpg", "jpeg"],
            key=f"{key}_pf_shot",
            help="Se lee en memoria con el modelo de visión y no se guarda.",
        )
        shot_ok = shot is not None
        if shot is not None:
            try:
                st.image(shot.getvalue(), caption="Vista previa (no se guarda)", width=220)
            except Exception as exc:  # noqa: BLE001 - imagen dañada o renombrada: aviso, no traceback
                log.info("Vista previa de la captura imposible: %s", type(exc).__name__)
                shot_ok = False
                st.warning("No se puede mostrar esta imagen: el fichero parece dañado o no es un PNG/JPG "
                           "de verdad. Prueba con otra captura.", icon=":material/broken_image:")
        b1, b2 = st.columns(2)
        read = b1.button("Leer captura", icon=":material/document_scanner:", disabled=not shot_ok,
                         key=f"{key}_pf_read", width="stretch")
        use_sample = b2.button("Usar captura de ejemplo", key=f"{key}_pf_shot_sample", width="stretch")
        if mode != "real":
            st.caption("En modo demo no se lee tu imagen: se usa la cartera de la captura de ejemplo. "
                       "Cambia a modo real (chip de arriba a la derecha) para leer tu propia captura.")
        if read and shot_ok:
            # En demo se usa la cartera de ejemplo: que el nombre no diga «Mi cartera».
            _load_image(shot.getvalue(),
                        "Mi cartera (captura)" if mode == "real" else "Cartera de ejemplo (captura)", mode)
        elif use_sample:
            if sample_shot.exists():
                _load_image(sample_shot.read_bytes(), "Cartera de ejemplo (captura)", mode)
            else:
                st.session_state[PF_ERROR_KEY] = (
                    "shot", "No se encuentra la captura de ejemplo en el servidor. Sube tu propia captura.")

    # Avisos (sobreviven a los reruns del diálogo hasta la siguiente carga).
    for kind, text in st.session_state.get(PF_MSGS_KEY, []):
        getattr(st, kind)(text, icon={"success": ":material/check_circle:", "warning": ":material/warning:",
                                      "info": ":material/info:"}.get(kind))
    error = st.session_state.get(PF_ERROR_KEY)
    portfolio = st.session_state.get(PORTFOLIO_KEY)
    if error:
        origin, text = error
        what = "leer la captura" if origin == "shot" else "cargar la cartera"
        st.error(f"No se pudo {what}: {text}", icon=":material/error:")
        if portfolio is not None:
            st.caption("Se mantiene la cartera que tenías cargada.")
        with st.expander("Qué captura sirve" if origin == "shot" else "Cómo debe ser el CSV", expanded=True):
            st.markdown(IMAGE_HELP if origin == "shot" else FORMAT_HELP)
    if st.session_state.get(PF_DISCARDED_KEY):
        lines = "\n".join(f"- {md_escape(d.get('row', ''))}: {md_escape(d.get('reason', ''))}"
                          for d in st.session_state[PF_DISCARDED_KEY])
        st.warning(f"Filas de la captura que no se han incluido:\n\n{lines}", icon=":material/warning:")

    if portfolio is not None:
        with st.container(key=f"{key}-pf-card"):
            h1, h2 = st.columns([3, 2], vertical_alignment="center")
            h1.markdown(f'<div class="mb-nb-pfname">{html.escape(portfolio.name)}'
                        f' <span>· {_plural(len(portfolio.positions), "posición", "posiciones")}</span></div>',
                        unsafe_allow_html=True)
            h2.button("Quitar cartera", icon=":material/delete:", key=f"{key}_pf_forget",
                      on_click=_on_forget, args=(key,), width="stretch")
            st.markdown(portfolio_table_html(portfolio), unsafe_allow_html=True)
    st.markdown(f'<div class="mb-nb-privacy">{html.escape(PRIVACY_NOTE)}</div>', unsafe_allow_html=True,
                help=PRIVACY_DETAIL)


# ── Petición y ejecución ──────────────────────────────────────────────────────────


def _on_shortcut(key: str, defaults: list[str], universe: list[str]) -> None:
    choice = st.session_state.get(f"{key}_short")
    if choice:
        st.session_state[f"{key}_tickers"] = _shortcut_tickers(choice, defaults, universe)
    st.session_state[f"{key}_short"] = None


def _on_generate(key: str, deliver: list[str], make_cover: bool, refresh_allowed: bool) -> None:
    """``on_click`` de «Generar»: deja la petición con lo que hay en los widgets (se consume una vez)."""
    ss = st.session_state
    tickers = list(ss.get(f"{key}_tickers") or [])
    ss[LAST_TICKERS_KEY] = tickers
    ss[f"{key}_request"] = {
        "tickers": tickers,
        "uploads": list(ss.get(f"{key}_docs") or []),
        "make_video": bool(ss.get(f"{key}_video")),
        "make_cover": make_cover and bool(ss.get(f"{key}_cover")),
        "deliver": deliver if ss.get(f"{key}_telegram") else [],
        "refresh": refresh_allowed and bool(ss.get(f"{key}_refresh")),
    }


def _save_uploads(files, settings) -> tuple[list[Path], Path | None]:
    """Copia las subidas a una carpeta temporal única de esta ejecución.

    Cada fichero va en su subcarpeta numerada (dos subidas con el mismo nombre no se pisan). Si una
    escritura falla a mitad, la carpeta se borra aquí mismo antes de propagar el error.
    """
    if not files:
        return [], None
    base = settings.cache_path / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="run_", dir=base))
    paths: list[Path] = []
    try:
        for i, f in enumerate(files, start=1):
            sub = folder / f"{i:02d}"  # subcarpeta por índice: se conserva el nombre original
            sub.mkdir()
            p = sub / (Path(f.name).name or "subida")
            p.write_bytes(f.getvalue())
            paths.append(p)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # RGPD: nada a medias en disco
        raise
    return paths, folder


def _run(request: dict, mode: str, settings) -> None:
    """Ejecuta el pipeline con ``st.status`` + barra. Éxito → ``st.rerun()``; error → mensaje y vuelve."""
    from briefer import pipeline

    upload_dir: Path | None = None
    briefing = None
    with st.container(key="nb-run"):
        st.caption(":material/hourglass_top: Generando… no cierres este diálogo hasta que termine." + (
            "" if mode == "mock" else " Con voces reales o en modo real tarda entre 30 s y 2 min.")
            + (" Se ignora la caché: noticias y precios recién descargados." if request["refresh"] else ""))
        bar = st.progress(0.0, text="Preparando…")
        try:
            upload_paths, upload_dir = _save_uploads(request["uploads"], settings)
            with st.status("Generando briefing…", expanded=True) as status:
                reporter = StatusProgress(status, bar)
                try:
                    briefing = pipeline.run_briefing(
                        request["tickers"],
                        portfolio=st.session_state.get(PORTFOLIO_KEY),
                        uploads=upload_paths,
                        make_video=request["make_video"],
                        deliver=request["deliver"],
                        make_cover=request["make_cover"],
                        mode=mode,
                        use_cache=not request["refresh"],
                        progress=reporter,
                    )
                    bar.progress(1.0, text="Briefing listo")
                    status.update(label="Briefing listo", state="complete", expanded=False)
                except NotImplementedError as exc:
                    status.update(label="Funcionalidad pendiente", state="error")
                    step = getattr(exc, "step", None)
                    pending(exc, f"el paso «{step}» del pipeline" if step else "alguno de los pasos del pipeline")
                except ValueError as exc:  # entrada no válida (sin tickers, canal desconocido…)
                    status.update(label="Revisa los datos de entrada", state="error")
                    show_error(exc, "el briefing")
                except Exception as exc:  # error real: el paso que falló, redactado y sin romper la app
                    step = getattr(exc, "step", None)
                    status.update(label=f"Error en el paso «{step}»" if step else "Error", state="error")
                    show_error((exc.__cause__ or exc) if step else exc,
                               f"el paso «{step}» del briefing" if step else "el briefing")
                    if mode != "mock":
                        st.info("Puedes reintentarlo en **Demo offline** (chip del modo, arriba a la derecha), "
                                "que no depende de la red ni de claves.")
        except OSError as exc:  # no se pudieron copiar las subidas
            show_error(exc, "la preparación de los documentos")
        finally:
            if upload_dir is not None:  # RGPD: los documentos subidos no se quedan en disco
                shutil.rmtree(upload_dir, ignore_errors=True)
    if briefing is not None:
        set_active_briefing(briefing)
        st.session_state[DONE_KEY] = briefing.id
        # Desde cualquier vista (p. ej. Archivo) se acaba en Hoy, que pinta el briefing activo.
        from components.shell import VIEW_HOY

        st.session_state["_goto"] = VIEW_HOY
        st.rerun()


# ── Formulario ────────────────────────────────────────────────────────────────────


def new_briefing_form(*, key: str = "nb") -> None:
    """Cuerpo del diálogo «Nuevo briefing» (se puede pintar sin diálogo, p. ej. en tests)."""
    from components.shell import current_mode

    mode = current_mode()
    settings = get_settings()

    # Un único hueco: al generar se vacía primero (si no, el formulario de la ejecución anterior
    # seguiría visible y pulsable, «caducado», mientras corre el pipeline) y se pinta el progreso.
    slot = st.empty()
    request = st.session_state.pop(f"{key}_request", None)
    if request is not None and (request["tickers"] or st.session_state.get(PORTFOLIO_KEY) is not None):
        slot.empty()
        with slot.container():
            _run(request, mode, settings)  # éxito → st.rerun() (no vuelve)
            st.divider()
        form_parent = st.container()  # error: el formulario vuelve debajo, con lo que había
    else:
        form_parent = slot.container()

    defaults = list(dict.fromkeys(settings.default_tickers))
    context = list(settings.context_tickers)
    universe = [t for t in TICKER_UNIVERSE if t not in set(context)]
    tickers_key = f"{key}_tickers"
    if tickers_key not in st.session_state:
        st.session_state[tickers_key] = list(st.session_state.get(LAST_TICKERS_KEY) or defaults)
    current = list(st.session_state.get(tickers_key) or [])
    options = list(dict.fromkeys([*universe, *defaults, *current]))

    with form_parent, st.container(key=f"{key}-form"):
        # 1 · Valores
        with st.container(key=f"{key}-sec1"):
            _section(1, "¿Qué quieres seguir?")
            tickers = st.multiselect(
                "Valores a seguir",
                options=options,
                format_func=ticker_label,
                key=tickers_key,
                accept_new_options=True,
                filter_mode="fuzzy",
                placeholder="Busca: Santander, Apple, NVDA…",
                label_visibility="collapsed",
                help="Puedes escribir cualquier ticker de Yahoo Finance o el nombre de la empresa "
                     "(se normaliza: «santander» → SAN.MC).",
            )
            st.pills(
                "Atajos", options=list(SHORTCUTS), format_func=SHORTCUTS.get, key=f"{key}_short",
                label_visibility="collapsed", on_change=_on_shortcut, args=(key, defaults, universe),
            )
            if context:
                st.caption("Siempre se incluyen como contexto los índices "
                           + ", ".join(str(TICKER_UNIVERSE.get(t, {}).get("name", t)) for t in context)
                           + " (precios y noticias generales de mercado).")
            portfolio = st.session_state.get(PORTFOLIO_KEY)
            extra: list[str] = []
            if portfolio is not None:
                chosen = {str(t).upper() for t in tickers}
                extra = [p.ticker for p in portfolio.positions if p.ticker not in chosen]
                if extra:
                    st.markdown(f'<div class="mb-nb-pfline">Se añadirán {_plural(len(extra), "valor", "valores")} '
                                f'de tu cartera: <b>{html.escape(", ".join(extra))}</b></div>',
                                unsafe_allow_html=True)
                else:
                    st.markdown('<div class="mb-nb-pfline">Todos los valores de tu cartera ya están en la '
                                'selección.</div>', unsafe_allow_html=True)

        # 2 · Cartera
        with st.container(key=f"{key}-sec2"):
            _section(2, "Tu cartera", "opcional")
            _portfolio_section(key, mode, settings)

        # 3 · Documentos
        with st.container(key=f"{key}-sec3"):
            _section(3, "Documentos", "opcional")
            docs = st.file_uploader(
                "PDF de resultados, capturas de gráficos o notas de voz",
                type=UPLOAD_TYPES,
                accept_multiple_files=True,
                key=f"{key}_docs",
                help="Detectamos el tipo por la extensión: los PDF se leen con extracción de texto + visión, "
                     "las imágenes de gráficos con visión y los audios se transcriben (voz a texto). Se añaden "
                     "como contexto del análisis y se borran al terminar. La captura de tu cartera va en el "
                     "paso 2, no aquí.",
            ) or []
            if docs:
                items = "".join(
                    f'<li><span class="mb-nb-ft mb-nb-ft--{cls}">{label}</span>'
                    f'<span class="mb-nb-fn">{html.escape(f.name)}</span></li>'
                    for f in docs for label, cls in [doc_kind(f.name)]
                )
                st.markdown(f'<ul class="mb-nb-files">{items}</ul>', unsafe_allow_html=True)

        # 4 · Opciones
        cover_ready = mode != "real" or settings.briefer_image_gen_provider != "none"
        telegram_ready = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        with st.container(key=f"{key}-sec4"):
            _section(4, "Opciones")
            o1, o2, o3 = st.columns(3)
            o1.toggle("Vídeo corto", key=f"{key}_video",
                      help="Vídeo vertical 9:16 con el podcast, los gráficos y subtítulos (unos segundos más).")
            o2.toggle("Portada con IA", key=f"{key}_cover", disabled=not cover_ready,
                      help="Ilustración generada por IA a partir del tono del día (no representa datos)."
                      if cover_ready else "Configura BRIEFER_IMAGE_GEN_PROVIDER (p. ej. local) en .env.")
            o3.toggle("Enviar por Telegram", key=f"{key}_telegram", disabled=not telegram_ready,
                      help="Resumen, audio, imagen y vídeo (si lo hay) a tu chat de Telegram."
                      if telegram_ready else "Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID "
                      "(scripts/telegram_setup.py).")
            if mode == "real":
                st.toggle("Refrescar datos (ignorar caché)", key=f"{key}_refresh",
                          help="Descarga de nuevo noticias y precios aunque ya estén en la caché del día.")
            st.caption("El briefing siempre queda disponible en la web.")

        # Pie
        no_input = not tickers and portfolio is None
        n_values = len({str(t).upper() for t in tickers}) + len(extra)
        with st.container(key=f"{key}-foot"):
            st.markdown(f'<div class="mb-nb-sum">{html.escape(summary_text(n_values, len(docs), portfolio is not None))}'
                        "</div>", unsafe_allow_html=True)
            st.button(
                "Generar briefing", type="primary", icon=":material/play_arrow:", key=f"{key}_generate",
                disabled=no_input, width="stretch",
                on_click=_on_generate, args=(key, ["telegram"] if telegram_ready else [], cover_ready, mode == "real"),
            )
            if no_input:
                st.caption("Elige al menos un valor o carga una cartera para generar el briefing.")


@st.dialog("Nuevo briefing", width="large")
def _new_briefing_dialog() -> None:
    new_briefing_form(key="nb")


def new_briefing_button(*, key: str, label: str = "Nuevo briefing", type: str = "primary",  # noqa: A002
                        width="content") -> None:
    """Botón que abre el diálogo «Nuevo briefing»."""
    if st.button(label, key=key, type=type, width=width, icon=":material/add:"):
        _new_briefing_dialog()
