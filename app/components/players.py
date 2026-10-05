"""Widgets comunes: disclaimer, avisos de "pendiente", barra lateral, progreso y reproductores.

Carril C. Solo presentación: recibe schemas (``Briefing``, ``QAAnswer``) y los pinta. No
instancia proveedores ni llama a modelos (eso es cosa de ``briefer.pipeline``); para saber qué
está configurado usa ``registry.describe_providers`` y ``Settings.has_secret`` (solo lectura).

Estado de sesión (``st.session_state``) que comparten las páginas:

- ``"briefing"``: briefing activo (contexto de «Preguntar»). Lo fijan la portada (si no hay otro),
  «Briefing» al generar, «Histórico» al abrir y el botón «Preguntar sobre este briefing».
- ``"run_mode"`` / ``"use_mock"``: modo elegido en la barra lateral.
- ``"_goto"``: navegación pendiente pedida desde un callback (``handle_navigation``).

Rendimiento: la portada se cachea con ``st.cache_data`` (``featured_briefing``) y las descargas
leen el fichero solo al pulsar (``data`` perezoso), no en cada recarga.
"""

from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from html import escape
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

from briefer import brand, costs, storage
from briefer.config import Settings, get_settings
from briefer.logging_utils import error_text, redact_secrets
from briefer.providers import registry
from briefer.schemas import DISCLAIMER_ES, Briefing, ChartAsset, NewsItem, QAAnswer, StepMetric

from .theme import (
    fmt_duration,
    headline,
    keypoint_card,
    legend_html,
    pill_html,
    player_card,
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


def show_disclaimer() -> None:
    """Aviso MiFID II visible en todas las páginas (compacto, al pie, mono gris)."""
    st.divider()
    disclaimer_note()


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
    "LLM": {"anthropic": "anthropic_api_key", "gemini": "gemini_api_key", "openai": "openai_api_key"},
    "Visión": {"claude": "anthropic_api_key", "qwen_local": None},
    "Voz a texto": {"whisper_api": "openai_api_key", "whisper_local": None},
    "Texto a voz": {"edge": None, "elevenlabs": "elevenlabs_api_key"},
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


def sidebar_mode() -> str:
    """Barra lateral: modo de ejecución, insignias de proveedores y cartera. Devuelve el modo.

    - Interruptor «Modo real»: solo se puede activar si hay claves (``real_mode_available``); si
      no, queda bloqueado con el motivo.
    - En demo, selector entre **«Demo sin claves (voces reales)»** (datos de ejemplo + modelos
      simulados + edge-tts real, que no necesita clave) y **«Demo offline»** (todo mock, sin red).

    El modo se recuerda en la sesión (``st.session_state["run_mode"]`` y ``["use_mock"]``).
    """
    with st.sidebar:
        available, why = real_mode_available()
        previous = st.session_state.get("run_mode")
        want_real = st.toggle(
            "Modo real (APIs de .env)",
            value=available and previous == "real",
            disabled=not available,
            help="Desactivado = modo demo: noticias de ejemplo, precios sintéticos y modelos simulados "
            "(sin claves). Activado = proveedores configurados en .env.",
        )
        if want_real and available:
            mode = "real"
            st.markdown(mode_line("MODO REAL", "APIs de .env", "ok"), unsafe_allow_html=True)
        else:
            demo_options = ["demo_voices", "mock"]
            default = previous if previous in demo_options else default_demo_mode()
            mode = st.radio(
                "Tipo de demo",
                demo_options,
                index=demo_options.index(default),
                format_func=lambda m: MODE_LABELS[m],
                help="Voces reales: el podcast se lee con edge-tts (gratis, sin clave; necesita red). "
                "Offline: todo simulado, sin red (el audio es un silencio de prueba).",
            )
            if mode == "demo_voices":
                st.markdown(mode_line("MODO DEMO", "sin claves · voces reales (edge-tts)", "amber"),
                            unsafe_allow_html=True)
            else:
                st.markdown(mode_line("MODO DEMO", "sin red ni claves", "amber"), unsafe_allow_html=True)
            if not available:
                st.caption(f"Modo real no disponible: {why}")
        st.session_state["run_mode"] = mode
        st.session_state["use_mock"] = mode != "real"
        portfolio = st.session_state.get("portfolio")
        if portfolio is not None:
            st.caption(f"Cartera cargada: «{portfolio.name}» ({len(portfolio.positions)} posiciones)")
        with st.expander("Proveedores de IA", expanded=False):
            try:
                for badge in provider_badges():
                    color = {"real": "green", "mock": "orange", "off": "gray"}[badge.status]
                    st.markdown(f"**{badge.family}:** :{color}[{badge.label}]")
                if mode == "mock":
                    st.caption("En modo demo offline el pipeline usa mocks en todas las familias.")
                elif mode == "demo_voices":
                    st.caption("En la demo sin claves todo es simulado salvo la voz (edge-tts real).")
            except Exception as exc:  # .env mal formado
                st.error(f"Configuración inválida: {error_text(exc)}")
        st.caption("Voces sintéticas generadas por IA · no es asesoramiento financiero.")
    return mode


def sidebar_controls() -> bool:
    """Compatibilidad: pinta la barra lateral (``sidebar_mode``) y devuelve ``use_mock``
    (``True`` en cualquier modo demo)."""
    return sidebar_mode() != "real"


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


def demo_mode_banner(mode: str | bool) -> None:
    """Insignia visible del modo activo (DEMO / MIXTO / REAL) y qué proveedores están simulados.

    Acepta el modo (``"real"``, ``"mock"``, ``"demo_voices"``) o el antiguo ``use_mock`` (bool).
    """
    mode = _as_mode(mode)
    mocked = mock_providers(mode)
    if mode == "mock":
        st.markdown(mode_line("MODO DEMO (mock)", "sin red ni claves", "amber"), unsafe_allow_html=True)
        st.caption(
            "Proveedores en mock: " + ", ".join(mocked) + ". Noticias de ejemplo y precios "
            "sintéticos: los contenidos son ficticios."
        )
    elif mode == "demo_voices":
        st.markdown(mode_line("MODO DEMO SIN CLAVES", "voces reales (edge-tts)", "amber"),
                    unsafe_allow_html=True)
        st.caption(
            "Proveedores en mock: " + ", ".join(mocked) + ". Noticias de ejemplo y precios "
            "sintéticos (contenidos ficticios), pero el podcast se lee con voces sintéticas reales "
            "de edge-tts (gratis, sin clave; necesita conexión)."
        )
    elif mocked:
        st.markdown(mode_line("MODO MIXTO", "algunos proveedores son simulados", "amber"),
                    unsafe_allow_html=True)
        st.caption("Proveedores en mock (según `.env`): " + ", ".join(mocked) + ".")
    else:
        st.markdown(mode_line("MODO REAL", "noticias, precios y modelos reales", "ok"),
                    unsafe_allow_html=True)


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


def format_source(source: str, news: dict[str, NewsItem]) -> str:
    """Markdown de una fuente: enlace a la noticia si se conoce, si no el texto tal cual."""
    item = news.get(source)
    if item is not None:
        title = item.title.replace("[", "(").replace("]", ")")
        return f"[{title}]({item.url}) · {item.source}"
    if source.startswith(("http://", "https://")):
        return f"[{source}]({source})"
    return source


def source_parts(source: str, news: dict[str, NewsItem]) -> tuple[str, str | None]:
    """``(texto, url)`` de una fuente para las tarjetas HTML (el escape lo hace ``theme``)."""
    item = news.get(source)
    if item is not None:
        return f"{item.title} · {item.source}", item.url
    if source.startswith(("http://", "https://")):
        return source, source
    return source, None


def chart_caption(chart: ChartAsset) -> str:
    """Pie de figura legible para un gráfico."""
    label = CHART_KIND_LABEL.get(chart.kind, chart.kind)
    return f"{label} · {chart.ticker}" if chart.ticker else label


def _fmt_duration(seconds: float) -> str:
    mins, secs = divmod(int(round(seconds)), 60)
    return f"{mins}:{secs:02d}"


def _es(value: float, decimals: int, unit: str = "") -> str:
    """Número con coma decimal (formato español) y unidad, para las métricas de la UI."""
    return f"{value:.{decimals}f}".replace(".", ",") + unit


def render_metrics(briefing: Briefing) -> None:
    """Tabla de latencia y coste estimado por paso, con totales."""
    if not briefing.metrics:
        st.write("Sin métricas registradas.")
        return
    summary = costs.summarize_metrics(briefing.metrics)
    c1, c2, c3 = st.columns(3)
    c1.metric("Pasos", int(summary.get("steps", len(briefing.metrics))))
    c2.metric("Latencia total", _es(summary.get('total_latency_s', 0.0), 2, " s"))
    c3.metric("Coste estimado", _es(summary.get('total_cost_eur', 0.0), 4, " €"))
    render_metrics_table(briefing.metrics)
    st.caption("Costes estimados con las tarifas de `costs.py` (no son facturas reales).")


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
        st.caption(f"No se pudo dibujar el grafo ({exc}); se muestra solo la tabla.")
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
PAGE_BRIEFING = "pages/1_Briefing.py"
PAGE_ASK = "pages/2_Preguntar.py"
PAGE_PORTFOLIO = "pages/3_Mi_cartera.py"
PAGE_HISTORY = "pages/4_Historico.py"
PAGE_ABOUT = "pages/5_Quienes_somos.py"
#: Propuesta de valor y eslogan: fuente única en ``briefer.brand``.
VALUE_PROPOSITION = brand.VALUE_PROPOSITION
TAGLINE = brand.TAGLINE
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
        st.info("Abre la página **Preguntar** en el menú lateral: el briefing ya está seleccionado.")


def page_link(page: str, label: str, icon: str | None = None, container=None, width: str = "content") -> None:
    """``st.page_link`` tolerante: si la página no está registrada, muestra el texto sin enlace."""
    target = container or st
    try:
        target.page_link(page, label=label, icon=icon, width=width)
    except StreamlitAPIException:
        target.markdown(f"{label} (menú lateral)")


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


def mode_badge(mode: str) -> None:
    """Insignia compacta del modo activo (cabecera de las páginas)."""
    if mode == "real":
        body = pill_html("Modo real", "ok")
    elif mode == "demo_voices":
        body = pill_html("Demo sin claves · voces reales", "amber")
    else:
        body = pill_html("Demo offline · todo simulado", "amber")
    st.markdown(body, unsafe_allow_html=True)


def origin_badge(briefing: Briefing, origin: str) -> None:
    """Insignia del origen del briefing destacado (pregenerado real, guardado, demo…)."""
    demo = is_demo_run(briefing.metrics)
    if origin == "pregenerado":
        label = "Briefing de ejemplo pregenerado" + (" (simulado)" if demo else " con datos y modelos reales")
    else:
        label = "Último briefing guardado" + (" (demo)" if demo else "")
    st.markdown(pill_html(label, "muted" if demo else "accent"), unsafe_allow_html=True)


# ── Descargas y reproductor ────────────────────────────────────────────────────────


def _reader(path: Path):
    """Lectura perezosa para ``st.download_button``: el fichero solo se lee al pulsar."""
    return lambda: Path(path).read_bytes()


def render_downloads(briefing: Briefing, key: str = "briefing", *, zip_export: bool = True) -> None:
    """Botones de descarga: audio, subtítulos (.srt) y el briefing completo en ZIP portable.

    Los datos se generan al pulsar (``data`` perezoso) y la descarga no relanza la página
    (``on_click="ignore"``): en cada recarga no se leen ni comprimen megas de audio.
    """
    cols = st.columns(3)
    if briefing.audio and _exists(briefing.audio.path):
        audio_path = Path(briefing.audio.path)
        cols[0].download_button(
            f"Descargar audio ({audio_path.suffix.lstrip('.')})",
            _reader(audio_path),
            file_name=f"{_FILE_PREFIX}_{briefing.id}{audio_path.suffix}",
            mime="audio/mpeg" if audio_path.suffix.lower() == ".mp3" else "audio/wav",
            key=f"{key}_dl_audio",
            on_click="ignore",
            icon=":material/download:",
        )
    if briefing.transcript and _exists(briefing.transcript.srt_path):
        cols[1].download_button(
            "Descargar subtítulos (.srt)",
            _reader(Path(briefing.transcript.srt_path)),
            file_name=f"{_FILE_PREFIX}_{briefing.id}.srt",
            mime="application/x-subrip",
            key=f"{key}_dl_srt",
            on_click="ignore",
            icon=":material/subtitles:",
        )
    if zip_export:
        from briefer import storage

        cols[2].download_button(
            "Descargar todo (.zip)",
            lambda: storage.export_briefing_zip(briefing),
            file_name=f"{_FILE_PREFIX}_{briefing.id}.zip",
            mime="application/zip",
            key=f"{key}_dl_zip",
            on_click="ignore",
            icon=":material/folder_zip:",
            help="Briefing autocontenido (JSON con rutas relativas, audio, SRT y gráficos): se puede "
            "abrir en otra máquina copiándolo a data/outputs/.",
        )


def render_podcast_player(briefing: Briefing, key: str = "briefing", *, downloads: bool = True) -> None:
    """Reproductor del podcast con el aviso de voz sintética y, opcionalmente, las descargas."""
    if briefing.audio and _exists(briefing.audio.path):
        a = briefing.analysis
        player_card(
            Path(briefing.audio.path),
            key=key,
            title="Podcast del día",
            meta=[f"{a.date:%d/%m/%Y}", f"{fmt_duration(briefing.audio.duration_s)} min",
                  "2 voces sintéticas"],
            seed=briefing.id,
        )
        st.caption(
            f":material/graphic_eq: {_fmt_duration(briefing.audio.duration_s)} min · "
            f"{len(briefing.audio.segments)} intervenciones · {SYNTHETIC_VOICE_NOTE}"
        )
        if downloads:
            render_downloads(briefing, key)
    elif briefing.audio:
        st.info("El audio de este briefing ya no está en disco (¿se movió o borró la carpeta?). "
                "La transcripción y los gráficos siguen disponibles abajo.")
    else:
        st.info("Este briefing no tiene audio.")


def disclaimer_note(text: str | None = None) -> None:
    """Disclaimer compacto (visible, sin ocupar la pantalla como un ``st.warning``), en mono gris."""
    body = escape(text or DISCLAIMER_ES)
    st.caption(f'<span class="mb-disclaimer"><b>Aviso:</b> {body}</span>', unsafe_allow_html=True)


def mode_line(label: str, note: str, tone: str) -> str:
    """Insignia de modo en mono (``MODO DEMO`` / ``MODO REAL``) + nota; HTML escapado."""
    return f'{pill_html(label, tone)} <span class="mb-mode-note">· {escape(note)}</span>'


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


def render_briefing(briefing: Briefing, key: str = "briefing", *, ask_button: bool = True) -> None:
    """Pinta un briefing completo: titular, audio, puntos clave, transcripción, gráficos y traza.

    ``key`` distingue los widgets si se pinta más de un briefing en la misma página.
    ``ask_button``: botón «Preguntar sobre este briefing» (lo deja como contexto y abre Preguntar).
    """
    a = briefing.analysis
    headline(a.headline, [f"Sesión del {a.date:%d/%m/%Y}",
                          f"generado el {briefing.created_at:%d/%m/%Y a las %H:%M}", f"id {briefing.id}"])
    st.markdown(f"**Tono del mercado:** {a.market_mood}")
    render_run_warnings(briefing)

    if briefing.cover_path and _exists(briefing.cover_path):
        st.image(str(briefing.cover_path), caption="Imagen generada por IA")

    # ── Podcast ──
    render_podcast_player(briefing, key)
    if ask_button:
        st.button("Preguntar sobre este briefing", key=f"{key}_ask", icon=":material/forum:",
                  on_click=ask_about, args=(briefing,), type="primary")

    tab_points, tab_transcript, tab_charts, tab_trace = st.tabs(
        ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]
    )

    # ── Puntos clave ──
    with tab_points:
        render_key_points(briefing)

    # ── Transcripción (texto original del guion, no el normalizado para la voz) ──
    with tab_transcript:
        if briefing.transcript and briefing.transcript.text.strip():
            st.text(briefing.transcript.text)
            st.caption("Transcripción del guion original; el audio lee cifras y tickers en forma hablada.")
        else:
            st.write("Este briefing no tiene transcripción.")

    # ── Gráficos ──
    with tab_charts:
        images = [c for c in briefing.charts if _exists(c.path)]
        if images:
            cols = st.columns(2)
            for i, chart in enumerate(images):
                cols[i % 2].image(str(chart.path), caption=chart_caption(chart))
        elif briefing.charts:
            st.write("Los gráficos de este briefing ya no están en disco.")
        else:
            st.write("Este briefing no tiene gráficos.")
        if briefing.video and _exists(briefing.video.path):
            st.markdown("##### Vídeo")
            st.video(str(briefing.video.path))

    # ── Cómo se hizo: cadena de modelos, latencia y coste ──
    with tab_trace:
        render_trace(briefing, key=f"{key}_trace")

    for d in briefing.deliveries:
        if d.channel == "web" or not d.ok:  # las fallidas ya se avisan arriba (render_run_warnings)
            continue
        st.success(f"Entrega por {d.channel}: {d.detail or 'OK'}")

    disclaimer_note(a.disclaimer)


def render_featured_briefing(
    briefing: Briefing, origin: str, key: str = "featured", max_points: int = 3
) -> None:
    """Portada: tarjeta con origen, titular, reproductor arriba, 3 puntos clave y botones de acción.

    Debajo, las pestañas completas (puntos, transcripción, gráficos y «Cómo se hizo») con una franja
    de resumen de la traza siempre visible.
    """
    a = briefing.analysis
    origin_badge(briefing, origin)
    meta = [f"{a.date:%d/%m/%Y}"]
    if briefing.audio:
        meta.append(f"{fmt_duration(briefing.audio.duration_s)} min")
    meta += ["2 voces sintéticas", "valores: " + (", ".join(briefing.context.tickers) or "—")]
    headline(a.headline, meta)
    if briefing.cover_path and _exists(briefing.cover_path):
        st.image(str(briefing.cover_path), caption="Imagen generada por IA")
    render_podcast_player(briefing, key, downloads=False)
    render_key_points(briefing, max_points, compact=True)
    with st.container(key=f"mb-cta-{key}"):
        c1, c2 = st.columns(2)
        c1.button("Preguntar sobre este briefing", key=f"{key}_ask", icon=":material/forum:",
                  on_click=ask_about, args=(briefing,), width="stretch", type="primary")
        page_link(PAGE_BRIEFING, "Generar el tuyo", ":material/podcasts:", container=c2, width="stretch")
    if briefing.metrics:
        st.caption(f'{tech_label("Cómo se hizo:")} <span class="mb-strip">{escape(trace_strip(briefing))}'
                   "</span> " + tech_label("(detalle en la pestaña «Cómo se hizo»)", "muted"),
                   unsafe_allow_html=True)

    tab_points, tab_transcript, tab_charts, tab_trace = st.tabs(
        ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]
    )
    with tab_points:
        render_key_points(briefing)
    with tab_transcript:
        if briefing.transcript and briefing.transcript.text.strip():
            st.text(briefing.transcript.text)
        else:
            st.write("Este briefing no tiene transcripción.")
    with tab_charts:
        images = [c for c in briefing.charts if _exists(c.path)]
        if images:
            cols = st.columns(2)
            for i, chart in enumerate(images):
                cols[i % 2].image(str(chart.path), caption=chart_caption(chart))
        else:
            st.write("Este briefing no tiene gráficos.")
    with tab_trace:
        render_trace(briefing, key=f"{key}_trace")
    render_downloads(briefing, key)


def render_qa_answer(answer: QAAnswer, briefing: Briefing | None = None) -> None:
    """Pinta la respuesta del Agente Q&A (texto, audio, fuentes enlazadas y latencia medida)."""
    st.markdown(f"**Pregunta:** {answer.question}")
    st.markdown(answer.answer_text)
    if _exists(answer.audio_path):
        st.audio(str(answer.audio_path))
        st.caption("Respuesta leída con voz sintética generada por IA.")
    if answer.sources:
        news = _news_index(briefing) if briefing is not None else {}
        st.caption("Fuentes: " + " · ".join(format_source(s, news) for s in answer.sources))
    if answer.metrics:
        total = sum(m.latency_s for m in answer.metrics)
        detail = " · ".join(
            f"{STEP_SHORT.get(m.step, m.step)} {_es(m.latency_s, 1, ' s')}" + (" (error)" if m.error else "")
            for m in answer.metrics
        )
        target = " ✓ < 10 s" if total < 10 else ""
        st.caption(tech_label(f"Latencia total {_es(total, 1, ' s')}{target}", "ok" if total < 10 else "amber")
                   + " " + tech_label(f"({detail})", "muted"), unsafe_allow_html=True)
        with st.expander("Cómo se hizo (voz → texto → respuesta → voz)"):
            render_trace(answer)


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
