"""Widgets comunes: disclaimer, avisos de "pendiente", barra lateral, progreso y reproductores.

Carril C. Solo presentación: recibe schemas (``Briefing``, ``QAAnswer``) y los pinta. No
instancia proveedores ni llama a modelos (eso es cosa de ``briefer.pipeline``); para saber qué
está configurado usa ``registry.describe_providers`` y ``Settings.has_secret`` (solo lectura).
"""

from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from briefer import costs
from briefer.config import Settings, get_settings
from briefer.providers import registry
from briefer.schemas import DISCLAIMER_ES, Briefing, ChartAsset, NewsItem, QAAnswer, StepMetric

from .trace import build_trace_dot, fallback_tag, has_real_voices, is_demo_run, step_status, trace_summary

SENTIMENT_LABEL = {"positivo": "▲ positivo", "negativo": "▼ negativo", "neutral": "● neutral"}
SENTIMENT_BADGE = {"positivo": "blue", "negativo": "red", "neutral": "gray"}
SYNTHETIC_VOICE_NOTE = (
    "Las voces de este podcast son **sintéticas** (generadas con IA); no son personas reales. "
    "El audio lo indica también al final del episodio y en sus metadatos (AI Act, art. 50)."
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
    """Aviso MiFID II visible en todas las páginas."""
    st.caption(f"Aviso: {DISCLAIMER_ES}")


def pending(exc: BaseException, what: str) -> None:
    """Mensaje amable para funcionalidades aún no implementadas (sin traceback)."""
    st.info(
        f"**Pendiente:** {what}. Esta parte todavía se está desarrollando; el resto de la app "
        f"sigue funcionando.\n\nDetalle técnico: `{exc}`"
    )


def show_error(exc: BaseException, what: str) -> None:
    """Error real mostrado de forma amigable; el traceback queda plegado para depurar."""
    st.error(f"No se pudo completar {what}: {exc}")
    with st.expander("Detalle técnico"):
        st.code("".join(traceback.format_exception(exc)), language="text")


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
        return False, f"configuración inválida: {exc}"
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
            st.markdown(":green-background[**MODO REAL**] · APIs de `.env`")
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
                st.markdown(":orange-background[**MODO DEMO**] · sin claves · voces reales (edge-tts)")
            else:
                st.markdown(":orange-background[**MODO DEMO**] · sin red ni claves")
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
                st.error(f"Configuración inválida: {exc}")
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
        st.markdown(":orange-background[**MODO DEMO (mock)**] · sin red ni claves")
        st.caption(
            "Proveedores en mock: " + ", ".join(mocked) + ". Noticias de ejemplo y precios "
            "sintéticos: los contenidos son ficticios."
        )
    elif mode == "demo_voices":
        st.markdown(":orange-background[**MODO DEMO SIN CLAVES**] · voces reales (edge-tts)")
        st.caption(
            "Proveedores en mock: " + ", ".join(mocked) + ". Noticias de ejemplo y precios "
            "sintéticos (contenidos ficticios), pero el podcast se lee con voces sintéticas reales "
            "de edge-tts (gratis, sin clave; necesita conexión)."
        )
    elif mocked:
        st.markdown(":orange-background[**MODO MIXTO**] · algunos proveedores son simulados")
        st.caption("Proveedores en mock (según `.env`): " + ", ".join(mocked) + ".")
    else:
        st.markdown(":green-background[**MODO REAL**] · noticias, precios y modelos reales")


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
            f"- `{m.step}` → {fallback_tag(m).lower()}: {m.error or 'proveedor real no disponible'}"
            for m in fallbacks
        )
        st.warning(
            f"**{len(fallbacks)} paso(s) cayeron a mock o a datos de ejemplo** (el proveedor real "
            f"falló y se usó un sustituto para no interrumpir el briefing; su contenido puede ser "
            f"simulado):\n{lines}"
        )
    if errors:
        lines = "\n".join(f"- `{m.step}` ({m.provider}): {m.error}" for m in errors)
        st.warning(f"**{len(errors)} paso(s) fallaron** y el briefing se generó sin ellos:\n{lines}")
    if bad_deliveries:
        lines = "\n".join(f"- {d.channel}: {d.detail or 'error'}" for d in bad_deliveries)
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


def chart_caption(chart: ChartAsset) -> str:
    """Pie de figura legible para un gráfico."""
    label = CHART_KIND_LABEL.get(chart.kind, chart.kind)
    return f"{label} · {chart.ticker}" if chart.ticker else label


def _fmt_duration(seconds: float) -> str:
    mins, secs = divmod(int(round(seconds)), 60)
    return f"{mins}:{secs:02d}"


def render_metrics(briefing: Briefing) -> None:
    """Tabla de latencia y coste estimado por paso, con totales."""
    if not briefing.metrics:
        st.write("Sin métricas registradas.")
        return
    summary = costs.summarize_metrics(briefing.metrics)
    c1, c2, c3 = st.columns(3)
    c1.metric("Pasos", int(summary.get("steps", len(briefing.metrics))))
    c2.metric("Latencia total", f"{summary.get('total_latency_s', 0.0):.2f} s")
    c3.metric("Coste estimado", f"{summary.get('total_cost_eur', 0.0):.4f} €")
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
    c3.metric("Latencia (suma)", f"{summary['total_latency_s']:.1f} s")
    c4.metric("Coste estimado", f"{summary['total_cost_eur']:.4f} €")
    try:
        st.graphviz_chart(build_trace_dot(metrics))
    except Exception as exc:  # el grafo es secundario: nunca rompe la página
        st.caption(f"No se pudo dibujar el grafo ({exc}); se muestra solo la tabla.")
    st.caption(
        "Verde: modelo real · gris: simulado (mock) · naranja: cayó a un sustituto (mock, datos de "
        "ejemplo o precios sintéticos) por un fallo · "
        "rojo: paso omitido por error · azul: procesado local sin IA. La latencia es la suma de "
        "pasos (algunos se ejecutan en paralelo). Costes estimados con `costs.py`."
    )
    if summary["fallbacks"] or summary["errors"]:
        st.caption(f"Incidencias: {summary['fallbacks']} caída(s) a mock · {summary['errors']} error(es).")
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


def render_downloads(briefing: Briefing, key: str = "briefing") -> None:
    """Botones de descarga del audio (mp3/wav) y de los subtítulos (.srt), si existen."""
    cols = st.columns(2)
    if briefing.audio and _exists(briefing.audio.path):
        audio_path = Path(briefing.audio.path)
        cols[0].download_button(
            f"Descargar audio ({audio_path.suffix.lstrip('.')})",
            audio_path.read_bytes(),
            file_name=f"market_briefer_{briefing.id}{audio_path.suffix}",
            mime="audio/mpeg" if audio_path.suffix.lower() == ".mp3" else "audio/wav",
            key=f"{key}_dl_audio",
        )
    if briefing.transcript and _exists(briefing.transcript.srt_path):
        cols[1].download_button(
            "Descargar subtítulos (.srt)",
            Path(briefing.transcript.srt_path).read_bytes(),
            file_name=f"market_briefer_{briefing.id}.srt",
            mime="application/x-subrip",
            key=f"{key}_dl_srt",
        )


def render_podcast_player(briefing: Briefing, key: str = "briefing", *, downloads: bool = True) -> None:
    """Reproductor del podcast con el aviso de voz sintética y, opcionalmente, las descargas."""
    if briefing.audio and _exists(briefing.audio.path):
        st.audio(str(Path(briefing.audio.path)))
        st.caption(
            f"{briefing.script.title} · {_fmt_duration(briefing.audio.duration_s)} min · "
            f"{len(briefing.audio.segments)} intervenciones"
        )
        st.info(SYNTHETIC_VOICE_NOTE)
        if downloads:
            render_downloads(briefing, key)
    else:
        st.write("Este briefing no tiene audio disponible.")


def render_briefing(briefing: Briefing, key: str = "briefing") -> None:
    """Pinta un briefing completo: titular, audio, puntos clave, transcripción, gráficos y traza.

    ``key`` distingue los widgets si se pinta más de un briefing en la misma página.
    """
    a = briefing.analysis
    st.subheader(a.headline)
    st.caption(f"{a.date:%d/%m/%Y} · Generado {briefing.created_at:%d/%m/%Y %H:%M} · id `{briefing.id}`")
    st.markdown(f"**Tono del mercado:** {a.market_mood}")
    render_run_warnings(briefing)

    if briefing.cover_path and _exists(briefing.cover_path):
        st.image(str(briefing.cover_path), caption="Imagen generada por IA")

    # ── Podcast ──
    st.markdown("#### Podcast")
    render_podcast_player(briefing, key)

    tab_points, tab_transcript, tab_charts, tab_trace = st.tabs(
        ["Puntos clave", "Transcripción", "Gráficos", "Cómo se hizo"]
    )

    # ── Puntos clave ──
    with tab_points:
        news = _news_index(briefing)
        if not a.key_points:
            st.write("Sin puntos clave.")
        for kp in a.key_points:
            with st.container(border=True):
                badge = SENTIMENT_BADGE.get(kp.sentiment, "gray")
                label = SENTIMENT_LABEL.get(kp.sentiment, kp.sentiment)
                st.markdown(f"**{kp.title}** — :{badge}[{label}]")
                st.write(kp.explanation)
                if kp.tickers:
                    st.caption("Valores: " + ", ".join(kp.tickers))
                if kp.sources:
                    st.markdown("Fuentes: " + " · ".join(format_source(s, news) for s in kp.sources))

    # ── Transcripción (texto original del guion, no el normalizado para la voz) ──
    with tab_transcript:
        if briefing.transcript:
            st.text(briefing.transcript.text)
            st.caption("Transcripción del guion original; el audio lee cifras y tickers en forma hablada.")
        else:
            st.write("Sin transcripción.")

    # ── Gráficos ──
    with tab_charts:
        images = [c for c in briefing.charts if _exists(c.path)]
        if images:
            cols = st.columns(2)
            for i, chart in enumerate(images):
                cols[i % 2].image(str(chart.path), caption=chart_caption(chart))
        else:
            st.write("Sin gráficos.")
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

    st.warning(f"**Aviso:** {a.disclaimer or DISCLAIMER_ES}")


def render_featured_briefing(briefing: Briefing, origin: str, key: str = "featured", max_points: int = 3) -> None:
    """Tarjeta compacta para la portada: titular, reproductor, 3 puntos clave y franja de traza."""
    a = briefing.analysis
    with st.container(border=True):
        tag = "Briefing pregenerado (ejemplo)" if origin == "pregenerado" else "Último briefing guardado"
        st.caption(f"{tag} · {a.date:%d/%m/%Y} · id `{briefing.id}`")
        st.subheader(a.headline)
        if briefing.cover_path and _exists(briefing.cover_path):
            st.image(str(briefing.cover_path), caption="Imagen generada por IA")
        render_podcast_player(briefing, key)
        for kp in a.key_points[:max_points]:
            badge = SENTIMENT_BADGE.get(kp.sentiment, "gray")
            tickers = f" · {', '.join(kp.tickers)}" if kp.tickers else ""
            st.markdown(f"- **{kp.title}** :{badge}[{SENTIMENT_LABEL.get(kp.sentiment, kp.sentiment)}]{tickers}")
        if briefing.metrics:
            summary = trace_summary(briefing.metrics)
            with st.expander(
                f"Cómo se hizo: {summary['ai_models']} modelos de IA · {summary['steps']} pasos · "
                f"{summary['total_latency_s']:.0f} s · {summary['total_cost_eur']:.3f} €"
            ):
                render_trace(briefing, key=f"{key}_trace")


def render_qa_answer(answer: QAAnswer) -> None:
    """Pinta la respuesta del Agente Q&A (texto, audio y fuentes)."""
    st.markdown(f"**Pregunta:** {answer.question}")
    st.markdown(answer.answer_text)
    if _exists(answer.audio_path):
        st.audio(str(answer.audio_path))
        st.caption("Respuesta leída con voz sintética generada por IA.")
    if answer.sources:
        st.caption("Fuentes: " + ", ".join(answer.sources))
    if answer.metrics:
        total = sum(m.latency_s for m in answer.metrics)
        detail = " · ".join(
            f"{m.step} {m.latency_s:.2f} s" + (" (error)" if m.error else "") for m in answer.metrics
        )
        st.caption(f"Latencia total: {total:.2f} s ({detail})")
        with st.expander("Cómo se hizo (voz → texto → respuesta → voz)"):
            render_trace(answer)
