"""Piezas comunes de la UI: disclaimer, avisos de "pendiente" y errores, estado de los proveedores,
progreso, puntos clave, traza «Cómo se hizo» y briefing activo.

Carril C. Solo presentación: recibe schemas (``Briefing``, ``QAAnswer``) y los pinta. No
instancia proveedores ni llama a modelos (eso es cosa de ``briefer.pipeline``); para saber qué
está configurado usa ``registry.describe_providers`` y ``Settings.has_secret`` (solo lectura).
El armazón (barra superior, chip del modo, pie) vive en ``components.shell`` y la vista de un
briefing en ``components.briefing_view``.

Estado de sesión (``st.session_state``) que comparten las vistas:

- ``"briefing"``: briefing activo (lo pinta «Hoy» y es el contexto de «Preguntar»). Lo fijan «Hoy»
  (el destacado, si no hay otro), «Nuevo briefing» al generar, «Archivo» al abrir y el botón
  «Preguntar sobre este briefing».
- ``"run_mode"`` / ``"use_mock"``: modo elegido en el chip de la barra superior.
- ``"_goto"``: navegación pendiente pedida desde un callback (``handle_navigation``).

Rendimiento: el briefing destacado se cachea con ``st.cache_data`` (``featured_briefing``).
"""

from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from streamlit.errors import StreamlitAPIException

from briefer import brand, storage
from briefer.config import Settings, get_settings
from briefer.logging_utils import error_text, redact_secrets
from briefer.providers import registry
from briefer.schemas import DISCLAIMER_ES, Briefing, ChartAsset, NewsItem, QAAnswer, StepMetric

from .theme import (
    keypoint_card,
    legend_html,
    tech_label,
    ticker_tape,
)
from .trace import (
    TRACE_LEGEND,
    build_trace_dot,
    fallback_tag,
    has_real_voices,
    is_demo_run,
    step_status,
    trace_summary,
)

SENTIMENT_LABEL = {"positivo": "▲ positivo", "negativo": "▼ negativo", "neutral": "● neutral"}
SENTIMENT_BADGE = {"positivo": "green", "negativo": "red", "neutral": "gray"}
SYNTHETIC_VOICE_NOTE = (
    "voces **sintéticas** generadas con IA, no son personas reales (lo dicen también el cierre del "
    "episodio y los metadatos del MP3, AI Act art. 50)"
)
# Modos de ejecución (``pipeline.RUN_MODES``) y su etiqueta en la barra lateral.
MODE_LABELS: dict[str, str] = {
    "real": "Real (APIs de .env)",
    "demo_voices": "Demo sin claves (voces reales)",
    "mock": "Demo offline (mock, sin red)",
}
CHART_KIND_LABEL = {
    "overview_bar": "Variación del día",
    "price_line": "Cotización",
    "portfolio_pie": "Reparto de la cartera",
}


def pending(exc: BaseException, what: str) -> None:
    """Mensaje amable para funcionalidades aún no implementadas (sin traceback)."""
    st.info(
        f"**Pendiente:** {what}. Esta parte todavía se está desarrollando; el resto de la app "
        f"sigue funcionando.\n\nDetalle técnico: `{redact_secrets(exc)}`"
    )


def portfolio_error_message(exc: BaseException) -> str:
    """Mensaje en español y sin traceback para un CSV de cartera que no se puede leer (función pura).

    Los ``ValueError`` de ``load_portfolio_csv`` ya traen un texto pensado para la UI (vacío, falta la
    columna, valor no numérico o negativo, pesos que no suman 1/100…); cualquier otro error se resume.
    """
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return ("Alguna fila del CSV tiene un ticker o un número que no es válido. Revisa que cada fila "
                "tenga un ticker y un peso o cantidad positivos.")
    if isinstance(exc, UnicodeError):
        return "No se puede leer el CSV: la codificación no es válida. Guárdalo como «CSV UTF-8»."
    if isinstance(exc, ValueError):
        text = " ".join(redact_secrets(exc).split())  # una línea, sin saltos ni tabuladores
        return text if len(text) <= 300 else text[:299] + "…"
    return ("El fichero no parece un CSV de cartera válido (¿es una hoja de Excel u otro formato?). "
            "Expórtalo como CSV e inténtalo de nuevo.")


def _debug_enabled() -> bool:
    try:
        return get_settings().briefer_log_level.upper() == "DEBUG"
    except Exception:
        return False


def show_error(exc: BaseException, what: str) -> None:
    """Error real mostrado de forma amigable y **redactado** (nunca claves ni tokens).

    El traceback completo (rutas del servidor) solo se muestra con ``BRIEFER_LOG_LEVEL=DEBUG``,
    también redactado; si no, basta el tipo y el mensaje.
    """
    st.error(f"No se pudo completar {what}: {error_text(exc, 400)}")
    if _debug_enabled():
        with st.expander("Detalle técnico (DEBUG)"):
            st.code(redact_secrets("".join(traceback.format_exception(exc))), language="text")


# Clave de .env que necesita cada proveedor real (``None`` = no necesita clave).
_PROVIDER_SECRETS: dict[str, dict[str, str | None]] = {
    "LLM": {"anthropic": "anthropic_api_key", "gemini": "gemini_api_key"},
    "Visión": {"claude": "anthropic_api_key"},
    "Voz a texto": {"whisper_api": "openai_api_key"},
    "Texto a voz": {"edge": None, "gemini": "gemini_api_key"},
    "Imagen": {},
    "Clasificador": {},
}


@dataclass(frozen=True)
class ProviderBadge:
    """Estado de una familia de proveedores para la barra lateral."""

    family: str
    configured: str      # valor de describe_providers («anthropic (claude-…)», «mock», «none»…)
    status: str          # "real" | "mock" | "off"
    reason: str = ""     # por qué está en mock (p. ej. «falta ANTHROPIC_API_KEY»)

    @property
    def label(self) -> str:
        """Texto corto de la insignia."""
        if self.status == "real":
            return f"real · {self.configured}"
        if self.status == "off":
            return "desactivado"
        return "MOCK" + (f" ({self.reason})" if self.reason else "")


def provider_badges(settings: Settings | None = None) -> list[ProviderBadge]:
    """Insignia por familia (real / MOCK (falta X) / desactivado), sin instanciar proveedores."""
    s = settings or get_settings()
    described = registry.describe_providers(s)
    badges: list[ProviderBadge] = []
    for family in _AI_PROVIDER_KEYS:
        value = str(described.get(family, "mock"))
        name = value.split(" ", 1)[0].strip().lower()
        if name == "none":
            badges.append(ProviderBadge(family, value, "off"))
            continue
        if name == "mock" or "mock" in value.lower() or "falta" in value.lower():
            reason = "configurado como mock" if name == "mock" else value
            badges.append(ProviderBadge(family, value, "mock", reason))
            continue
        secret = _PROVIDER_SECRETS.get(family, {}).get(name)
        if secret and not s.has_secret(secret):
            reason = f"falta {secret.upper()}" + ("" if s.briefer_fallback_to_mock else " · fallará")
            badges.append(ProviderBadge(family, value, "mock", reason))
        else:
            badges.append(ProviderBadge(family, value, "real"))
    return badges


def real_mode_available(settings: Settings | None = None) -> tuple[bool, str]:
    """¿Se puede usar el modo real? Exige al menos el LLM real con su clave.

    Returns:
        ``(disponible, motivo)``; el motivo explica qué falta cuando no lo está.
    """
    try:
        badges = {b.family: b for b in provider_badges(settings)}
    except Exception as exc:  # .env mal formado
        return False, f"configuración inválida: {error_text(exc)}"
    llm = badges.get("LLM")
    if llm is None or llm.status != "real":
        why = llm.reason if llm else "sin LLM"
        return False, (
            f"el LLM no tiene proveedor real ({why}). Configura `BRIEFER_LLM_PROVIDER` y su clave en `.env`."
        )
    return True, ""


def default_demo_mode(settings: Settings | None = None) -> str:
    """Modo demo por defecto: ``"demo_voices"`` (edge-tts real, sin claves) salvo que el TTS esté
    configurado **explícitamente** como ``mock`` (tests, CI, entornos sin red), que da ``"mock"``."""
    s = settings or get_settings()
    explicit_mock = "briefer_tts_provider" in s.model_fields_set and s.briefer_tts_provider == "mock"
    return "mock" if explicit_mock else "demo_voices"


def _as_mode(mode: str | bool) -> str:
    """Acepta el modo o el antiguo ``use_mock`` (bool)."""
    if isinstance(mode, bool):
        return "mock" if mode else "real"
    return mode


# Claves de ``registry.describe_providers`` que corresponden a proveedores de IA.
_AI_PROVIDER_KEYS = ("LLM", "Visión", "Voz a texto", "Texto a voz", "Imagen", "Clasificador")


def mock_providers(mode: str | bool) -> list[str]:
    """Nombres legibles de los proveedores de IA que irán en mock.

    En demo offline (o ``use_mock=True``) son todos; en la demo sin claves, todos menos «Texto a
    voz» (edge-tts real); en modo real, los configurados como ``mock`` en ``.env`` o sin la clave
    que necesitan (``provider_badges``, sin instanciar nada).
    """
    mode = _as_mode(mode)
    if mode == "mock":
        return list(_AI_PROVIDER_KEYS)
    if mode == "demo_voices":
        return [k for k in _AI_PROVIDER_KEYS if k != "Texto a voz"]
    try:
        return [b.family for b in provider_badges() if b.status == "mock"]
    except Exception:  # .env mal formado: lo avisa ya la barra lateral
        return []


def failed_steps(metrics: list[StepMetric]) -> list[StepMetric]:
    """Pasos que lanzaron una excepción (``StepMetric.error``, contrato v0.2)."""
    return [m for m in metrics if m.error]


def render_run_warnings(briefing: Briefing) -> None:
    """Avisos de pasos con incidencias: caídos a mock, omitidos por error y entregas fallidas."""
    demo = is_demo_run(briefing.metrics)
    fallbacks = [m for m in briefing.metrics if step_status(m, demo) == "fallback"]
    errors = [m for m in briefing.metrics if step_status(m, demo) == "error"]
    bad_deliveries = [d for d in briefing.deliveries if not d.ok]
    if fallbacks:
        lines = "\n".join(
            f"- `{m.step}` → {fallback_tag(m).lower()}: {redact_secrets(m.error) if m.error else 'proveedor real no disponible'}"
            for m in fallbacks
        )
        st.warning(
            f"**{len(fallbacks)} paso(s) cayeron a mock o a datos de ejemplo** (el proveedor real "
            f"falló y se usó un sustituto para no interrumpir el briefing; su contenido puede ser "
            f"simulado):\n{lines}"
        )
    if errors:
        lines = "\n".join(f"- `{m.step}` ({m.provider}): {redact_secrets(m.error)}" for m in errors)
        st.warning(f"**{len(errors)} paso(s) fallaron** y el briefing se generó sin ellos:\n{lines}")
    if bad_deliveries:
        lines = "\n".join(f"- {d.channel}: {redact_secrets(d.detail or 'error')}" for d in bad_deliveries)
        st.warning(f"**Entregas fallidas:**\n{lines}")
    if demo:
        voices = " Voces sintéticas reales (edge-tts)." if has_real_voices(briefing.metrics) else ""
        st.caption("Briefing de demostración: modelos simulados (mock) y datos de ejemplo ficticios." + voices)
    else:
        mocked = sorted({m.step for m in briefing.metrics if m.provider == "mock" and not m.error})
        if mocked:
            st.caption("Pasos con proveedor simulado (configurado como mock): " + ", ".join(mocked) + ".")


def _exists(path: Path | None) -> bool:
    return path is not None and Path(path).exists()


def _news_index(briefing: Briefing) -> dict[str, NewsItem]:
    index: dict[str, NewsItem] = {}
    for item in briefing.context.news:
        index[item.id] = item
        index[item.url] = item
    return index


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!<>|~$])")


def _md_escape(text: str) -> str:
    """Texto literal en Markdown: sin enlaces, énfasis, HTML ni LaTeX inyectados por la fuente."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(str(text).split()))


def _safe_url(url: str | None) -> str | None:
    """La URL solo si es http(s); codificada para no romper el ``(...)`` del enlace Markdown."""
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    return quote(url, safe=":/?#@!&'*+,;=%~-._[]")


def source_parts(source: str, news: dict[str, NewsItem]) -> tuple[str, str | None]:
    """``(texto, url)`` de una fuente para las tarjetas HTML (el escape lo hace ``theme``; url solo http/s)."""
    item = news.get(source)
    if item is not None:
        return f"{item.title} · {item.source}", _safe_url(item.url)
    return source, _safe_url(source)


def chart_caption(chart: ChartAsset) -> str:
    """Pie de figura legible para un gráfico."""
    label = CHART_KIND_LABEL.get(chart.kind, chart.kind)
    return f"{label} · {chart.ticker}" if chart.ticker else label


def _es(value: float, decimals: int, unit: str = "") -> str:
    """Número con coma decimal (formato español) y unidad, para las métricas de la UI."""
    return f"{value:.{decimals}f}".replace(".", ",") + unit


_STATUS_LABEL = {"fallback": "SUSTITUTO", "error": "ERROR"}


def render_metrics_table(metrics: list[StepMetric]) -> None:
    """Tabla de pasos con estado (OK / SUSTITUTO / ERROR) y el detalle de calidad (v0.3).

    «SUSTITUTO» = el proveedor real falló y el paso se completó con mock, ``data/samples``,
    precios sintéticos o guion de respaldo (``logging_utils.step_fell_back``); «ERROR» = el
    paso se omitió. «Detalle» = ``StepMetric.detail`` (grounding de cifras, reintentos…).
    """
    demo = is_demo_run(metrics)
    rows = [
        {
            "Paso": m.step,
            "Estado": _STATUS_LABEL.get(step_status(m, demo), "OK"),
            "Proveedor": m.provider,
            "Modelo": m.model,
            "Latencia (s)": round(m.latency_s, 3),
            "Coste est. (€)": round(m.est_cost_eur, 5),
            "Detalle": m.detail or "",
            "Error": m.error or "",
        }
        for m in metrics
    ]
    st.dataframe(rows, hide_index=True)
    n_failed = len(failed_steps(metrics))
    if n_failed:
        st.caption(f"{n_failed} paso(s) con incidencia (columnas «Estado» y «Error»).")
    details = [m for m in metrics if m.detail]
    if details:
        st.markdown("**Controles de calidad**")
        for m in details:
            st.caption(f"`{m.step}` · {m.detail}")


def render_trace(source: Briefing | QAAnswer | list[StepMetric], key: str = "trace") -> None:
    """Pestaña «Cómo se hizo»: grafo de la cadena de modelos con proveedor, latencia y coste.

    Acepta un ``Briefing``, un ``QAAnswer`` o directamente la lista de ``StepMetric``. El grafo
    se genera en DOT (``components.trace.build_trace_dot``) y lo dibuja ``st.graphviz_chart`` en el
    navegador. Debajo, la tabla de pasos para quien quiera los números exactos.
    """
    metrics = list(source.metrics) if isinstance(source, Briefing | QAAnswer) else list(source)
    if not metrics:
        st.info("Este resultado no tiene métricas registradas: no se puede reconstruir la traza.")
        return
    summary = trace_summary(metrics)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Modelos de IA", summary["ai_models"])
    c2.metric("Pasos", summary["steps"])
    c3.metric("Latencia (suma)", _es(summary['total_latency_s'], 1, " s"))
    c4.metric("Coste estimado", _es(summary['total_cost_eur'], 4, " €"))
    try:
        st.graphviz_chart(build_trace_dot(metrics))
    except Exception as exc:  # el grafo es secundario: nunca rompe la página
        st.caption(f"No se pudo dibujar el grafo ({error_text(exc)}); se muestra solo la tabla.")
    st.html(legend_html(TRACE_LEGEND))
    st.caption("La latencia es la suma de pasos (algunos se ejecutan en paralelo). Costes estimados "
               "con `costs.py`.")
    if summary["fallbacks"] or summary["errors"]:
        st.caption(
            tech_label(f"Incidencias: {summary['fallbacks']} caída(s) a mock", "warn") + " · "
            + tech_label(f"{summary['errors']} error(es)", "err" if summary["errors"] else "muted"),
            unsafe_allow_html=True,
        )
    render_metrics_table(metrics)


_PROGRESS_RE = re.compile(r"^\((\d+)/(\d+)\)\s*(.*)$")


def parse_progress(message: str) -> tuple[int, int, str] | None:
    """``"(3/6) Escribiendo el guion…"`` → ``(3, 6, "Escribiendo el guion…")``; otro formato → ``None``."""
    match = _PROGRESS_RE.match(str(message).strip())
    if not match:
        return None
    n, total, text = int(match.group(1)), int(match.group(2)), match.group(3)
    return n, max(total, 1), text


class StatusProgress:
    """Callback de progreso para ``pipeline.run_briefing`` que pinta en un ``st.status``.

    Cada mensaje ``"(n/N) …"`` actualiza la etiqueta del ``st.status``, una barra de progreso y
    deja una línea en el registro. Nunca lanza excepciones (el pipeline ya las ignora, pero así
    el registro queda limpio).
    """

    def __init__(self, status, bar=None) -> None:
        self.status = status
        self.bar = bar
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        try:
            self.messages.append(message)
            parsed = parse_progress(message)
            if parsed:
                n, total, text = parsed
                self.status.update(label=f"Paso {n} de {total}: {text}")
                if self.bar is not None:
                    self.bar.progress(min(1.0, n / total), text=message)
            st.write(message)
        except Exception:  # pragma: no cover - solo UI
            pass


# ── Briefing activo, portada y navegación ──────────────────────────────────────────

ACTIVE_BRIEFING_KEY = "briefing"
# Vistas registradas por ``components.shell`` (rutas relativas a ``app/main.py``).
PAGE_HOY = "views/hoy.py"
PAGE_ASK = "views/preguntar.py"
PAGE_HISTORY = "views/archivo.py"
#: Prefijo de los ficheros descargados (``briefly_<id>.mp3``).
_FILE_PREFIX = brand.BRAND_NAME.lower()


def set_active_briefing(briefing: Briefing) -> None:
    """Deja ``briefing`` como contexto de la sesión (lo usa «Preguntar»)."""
    st.session_state[ACTIVE_BRIEFING_KEY] = briefing


def ask_about(briefing: Briefing) -> None:
    """Callback de «Preguntar sobre este briefing»: lo fija como contexto y abre la página.

    Se usa como ``on_click`` (la navegación se pide en la siguiente ejecución con ``st.switch_page``,
    que no se puede llamar dentro de un callback).
    """
    set_active_briefing(briefing)
    st.session_state["_goto"] = PAGE_ASK


def handle_navigation() -> None:
    """Ejecuta la navegación pendiente que dejó un callback (``ask_about``).

    Si la página no se encuentra (p. ej. una página ejecutada sola en ``AppTest``), se queda donde
    está con un aviso en lugar de romper.
    """
    target = st.session_state.pop("_goto", None)
    if not target:
        return
    try:
        st.switch_page(target)
    except StreamlitAPIException:
        st.info("Abre la pestaña **Preguntar** en la barra superior: el briefing ya está seleccionado.")


def page_link(page: str, label: str, icon: str | None = None, container=None, width: str = "content") -> None:
    """``st.page_link`` tolerante: si la página no está registrada, muestra el texto sin enlace."""
    target = container or st
    try:
        target.page_link(page, label=label, icon=icon, width=width)
    except StreamlitAPIException:
        target.markdown(f"{label} (barra superior)")


def _featured_signature() -> tuple:
    """Huella barata de lo que decide la portada (último guardado + pregenerado) para la caché."""
    from briefer import storage

    s = get_settings()
    latest = storage.list_briefings(limit=1)
    demo_json = storage.demo_briefing_dir() / storage.BRIEFING_FILE

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    return (
        str(s.output_path), str(latest[0]) if latest else "", _mtime(latest[0]) if latest else 0.0,
        str(demo_json), _mtime(demo_json),
    )


@st.cache_data(show_spinner=False, max_entries=16)
def _featured_cached(signature: tuple) -> tuple[Briefing, str] | None:
    from briefer import storage

    return storage.load_featured_briefing()


def featured_briefing() -> tuple[Briefing, str] | None:
    """``storage.load_featured_briefing`` cacheado (se invalida al guardar un briefing nuevo)."""
    return _featured_cached(_featured_signature())


# ── Descargas y reproductor ────────────────────────────────────────────────────────


def disclaimer_note(text: str | None = None) -> None:
    """Disclaimer compacto (visible, sin ocupar la pantalla como un ``st.warning``), en mono gris."""
    body = escape(text or DISCLAIMER_ES)
    st.caption(f'<span class="mb-disclaimer"><b>Aviso:</b> {body}</span>', unsafe_allow_html=True)


def render_key_points(briefing: Briefing, max_points: int | None = None, *, compact: bool = False) -> None:
    """Puntos clave con impacto (▲/▼/●), valores y fuentes enlazadas."""
    a = briefing.analysis
    points = a.key_points[:max_points] if max_points else a.key_points
    if not points:
        st.write("Este briefing no tiene puntos clave.")
        return
    news = _news_index(briefing)
    impacts = {} if compact else news_impacts(briefing)
    for kp in points:
        sources = [] if compact else [source_parts(s, news) for s in kp.sources]
        tones = [source_impact(s, news, impacts) for s in kp.sources] if impacts else []
        keypoint_card(kp, sources, compact=compact, impacts=tones)


def news_impacts(briefing: Briefing) -> dict[str, dict]:
    """«Impacto de la noticia» (FinBERT) del briefing, de ``news_impact.json`` vía ``storage``.

    ``{}`` si no se calculó (``BRIEFER_FINBERT`` apagado) o si el fichero falta o está corrupto:
    la etiqueta es opcional y nunca rompe la página.
    """
    try:
        return storage.load_news_impact(briefing)
    except Exception:  # noqa: BLE001
        return {}


def source_impact(source: str, news: dict[str, NewsItem], impacts: dict[str, dict]) -> str | None:
    """Impacto (``positivo``/``negativo``/``neutral``) de la noticia citada como fuente, o ``None``."""
    item = news.get(source)
    row = impacts.get(item.id if item is not None else source)
    return str(row["impact"]) if row else None


def briefing_tape(briefing: Briefing | None) -> None:
    """Cinta de cotizaciones del briefing activo (índices de contexto con su nombre, en gris)."""
    if briefing is None or not briefing.context.prices:
        return
    try:
        indices = list(get_settings().context_tickers)
    except Exception:  # .env mal formado: lo avisa la barra lateral
        indices = []
    try:
        from briefer.ingest.tickers import TICKER_UNIVERSE
    except Exception:
        TICKER_UNIVERSE = {}
    names = {
        p.ticker: str(TICKER_UNIVERSE.get(p.ticker, {}).get("name", p.ticker))
        for p in briefing.context.prices
        if p.ticker.startswith("^") or p.ticker in indices
    }
    ticker_tape(briefing.context.prices, names, indices)


def trace_strip(briefing: Briefing) -> str:
    """Resumen de una línea de «Cómo se hizo» (modelos, pasos, latencia, coste)."""
    s = trace_summary(briefing.metrics)
    cost = f"{s['total_cost_eur']:.3f}".replace(".", ",")
    return (f"{s['ai_models']} modelos de IA encadenados · {s['steps']} pasos · "
            f"{s['total_latency_s']:.0f} s de proceso · {cost} € estimados")


def pick_question(suggestion: str | None, typed: str, has_audio: bool, last: str | None) -> str:
    """Qué entrada usar: ``"suggestion"``, ``"text"``, ``"audio"`` o ``""`` (nada).

    Una sugerencia pulsada manda. Si hay texto y audio a la vez, gana el que se tocó el último;
    si solo hay uno, ese.
    """
    if suggestion:
        return "suggestion"
    typed = typed.strip()
    if typed and has_audio:
        return "audio" if last == "audio" else "text"
    if typed:
        return "text"
    return "audio" if has_audio else ""


STEP_SHORT = {"qa.stt": "voz→texto", "agents.qa": "agente", "qa.tts": "texto→voz"}
