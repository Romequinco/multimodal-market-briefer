"""Piezas de la vista «Preguntar» (chat con el Agente Q&A): turnos, sugerencias, latencia y calentamiento.

Solo presentación: recibe ``QAAnswer``/``Briefing`` y los pinta; las llamadas a modelos pasan por
``briefer.pipeline`` (``answer_question``, ``speak_answer``, ``warmup``). La usa solo
``views/preguntar.py``.
"""

from __future__ import annotations

import re
import threading
from html import escape
from pathlib import Path
from urllib.parse import quote

import streamlit as st

from briefer import brand
from briefer.schemas import Briefing, NewsItem, QAAnswer

from .players import STEP_SHORT, _es, render_trace
from .theme import tech_label

#: Avatares del chat (iconos Material: sin imágenes que cargar).
USER_AVATAR = ":material/person:"
BOT_AVATAR = ":material/podcasts:"
VOICE_NOTE = "Respuesta leída con voz sintética generada por IA."
#: Objetivo de latencia de extremo a extremo de una respuesta (s).
LATENCY_TARGET_S = 10.0


@st.cache_resource(show_spinner=False)
def start_warmup(run_mode: str) -> bool:
    """Calienta clientes HTTP/modelos una vez por proceso y modo, en un hilo (no bloquea la página)."""
    from briefer import pipeline

    warm = getattr(pipeline, "warmup", None)
    if not callable(warm):
        return False

    def _run() -> None:
        try:
            try:
                warm(mode=run_mode)
            except TypeError:
                warm()
        except Exception:  # calentar es una optimización: nunca rompe la página
            pass

    threading.Thread(target=_run, name="briefer-warmup", daemon=True).start()
    return True


def suggestions(b: Briefing | None, *, demo: bool = False) -> list[str]:
    """Tres preguntas de ejemplo a partir del briefing (un clic y responde).

    La última, «¿Debería comprar acciones?», enseña el guardarraíl MiFID II (informa, no asesora).
    """
    out = ["¿Qué pasó en el mercado según este briefing?"]
    if b is not None:
        from briefer.ingest.tickers import TICKER_UNIVERSE

        tickers = [t for kp in b.analysis.key_points for t in kp.tickers] or list(b.context.tickers)
        if tickers:
            name = TICKER_UNIVERSE.get(tickers[0], {}).get("name", tickers[0])
            out.append(f"¿Qué dice este briefing sobre {name}?")
            if demo:
                out.append(f"¿Qué precio tiene {name} en este briefing?")
    out.append("¿Cuáles son las fuentes del briefing?")
    out.append("¿Cuál subió más?" if demo else "¿Debería comprar acciones?")
    return out


def welcome_text(b: Briefing | None) -> str:
    """Saludo inicial del asistente (conversación vacía)."""
    if b is None:
        return "Abre o genera un briefing en «Hoy» para consultar sus noticias y fuentes."
    tickers = ", ".join(b.context.tickers[:6])
    who = f": {tickers}" if tickers else ""
    return f"Hola. Tengo delante el briefing del {b.analysis.date:%d/%m/%Y}{who}. ¿Qué quieres saber?"


def latency_html(answer: QAAnswer) -> str:
    """Chip mono de latencia total (``✓ 6,0 s`` si cumple el objetivo); el desglose va en el ``title``."""
    if not answer.metrics:
        return ""
    total = sum(m.latency_s for m in answer.metrics)
    detail = " · ".join(
        f"{STEP_SHORT.get(m.step, m.step)} {_es(m.latency_s, 1, ' s')}" + (" (error)" if m.error else "")
        for m in answer.metrics
    )
    ok = total < LATENCY_TARGET_S
    tone = "ok" if ok else "amber"
    text = ("✓ " if ok else "⏱ ") + _es(total, 1, " s")
    return (f'<span class="mb-qa-lat mb-qa-lat--{tone}" title="Latencia total: {escape(detail)}">'
            f"{escape(text)}</span>")


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!<>|~$])")


def _md_escape(text: str) -> str:
    """Texto literal en Markdown: sin enlaces, énfasis, HTML ni LaTeX inyectados por la fuente."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(str(text).split()))


def _safe_url(url: str) -> str | None:
    """La URL solo si es http(s); codificada para no romper el ``(...)`` del enlace Markdown."""
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    return quote(url, safe=":/?#@!&'*+,;=%~-._[]")


def _source_md(source: str, news: dict[str, NewsItem]) -> str:
    """Markdown de una fuente: «[titular](url) · medio» si se conoce la noticia; todo escapado."""
    item = news.get(source)
    if item is not None:
        title, url, outlet = item.title, _safe_url(item.url), item.source
    else:
        title, url, outlet = source, _safe_url(source), ""
    text = _md_escape(title)
    link = f"[{text}]({url})" if url else text
    meta = f" · {_md_escape(outlet)}" if outlet else ""
    if item is not None:
        meta += f" · {item.published_at:%d/%m/%Y %H:%M}"
    return link + meta


def _sources_md(answer: QAAnswer, briefing: Briefing | None) -> str:
    news: dict[str, NewsItem] = {}
    if briefing is not None:
        for item in briefing.context.news:
            news[item.id] = item
            news[item.url] = item
    return " · ".join(_source_md(s, news) for s in answer.sources)


def render_user_turn(text: str, *, key: str, voice: bool = False, transcribed: bool = True) -> None:
    """Burbuja de la pregunta del usuario (``voice``: se marcó como transcrita de su voz).

    El contenedor con clave ``mb-qa-user-<key>`` permite al CSS distinguir la burbuja del usuario
    (Streamlit no marca el rol en el DOM cuando el avatar es un icono).
    """
    with st.chat_message("user", avatar=USER_AVATAR), st.container(key=f"mb-qa-user-{key}"):
        st.markdown(text.replace("$", "\\$") if text else "…")  # sin LaTeX accidental con «$»
        if voice:
            note = ("Transcrito de tu voz con IA (el audio ya se ha borrado)." if transcribed
                    else "Pregunta de voz de ejemplo; transcripción simulada.")
            st.caption(":material/mic: " + note)


def render_bot_text(text: str) -> None:
    """Burbuja simple del asistente (saludo, avisos)."""
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        st.markdown(text)


@st.dialog("Ejemplo completo de Preguntar", width="large")
def recorded_example() -> None:
    """Muestra una conversación preparada sin alterar el chat ni el briefing activo."""
    from briefer.qa_examples import load_qa_example

    try:
        example = load_qa_example()
    except (ValueError, OSError):
        example = None
    if example is None:
        st.info("El ejemplo completo no está incluido en esta copia del proyecto.")
        return
    st.caption(f"Ejemplo preparado · briefing del {example.briefing.analysis.date:%d/%m/%Y} · Santander y Apple")
    st.info("Así se presenta una conversación: respuesta, fuentes y voz. Estas respuestas están "
            "preparadas y los audios ya vienen incluidos; no necesitas claves ni conexión para escucharlos. "
            "En modo Real, la IA responde a tu pregunta con el briefing que tengas abierto.")
    for index, answer in enumerate(example.answers):
        render_user_turn(answer.question, key=f"example-{index}")
        with st.chat_message("assistant", avatar=BOT_AVATAR):
            render_answer_body(answer, example.briefing, key=f"example-{index}", trace=False)
            if answer.audio_path is None:
                st.caption("El audio de este ejemplo no está disponible en esta copia.")


def _request_audio(index: int) -> None:
    st.session_state["_qa_audio_request"] = index


def render_answer_body(answer: QAAnswer, briefing: Briefing | None, *, key: str, trace: bool = True,
                       voice: bool = False, audio_index: int | None = None) -> None:
    """Cuerpo de una respuesta: texto, audio con su aviso, fuentes, latencia y «Cómo se hizo».

    Se llama dentro de un ``st.chat_message`` del asistente. ``trace=False`` para la respuesta
    provisional (texto ya visible mientras se sintetiza la voz).
    """
    st.markdown(answer.answer_text)
    if any(m.model == "demo-qa" or (m.step == "agents.qa" and m.provider == "mock") for m in answer.metrics):
        st.caption("Respuesta de demo · contenido limitado al briefing, sin conversación libre con IA.")
    if answer.audio_path is not None and Path(answer.audio_path).exists():
        st.audio(str(answer.audio_path))
        st.caption(VOICE_NOTE)
    elif audio_index is not None and answer.response_kind != "demo_notice":
        from briefer import pipeline

        from .shell import current_mode

        offline = current_mode() == "mock"
        st.button("Escuchar respuesta", key=f"qa_listen_{key}", type="tertiary", icon=":material/volume_up:",
                  disabled=offline or not callable(getattr(pipeline, "speak_answer", None)),
                  help="La demo offline no genera voz." if offline else "Genera la voz de esta respuesta.",
                  on_click=_request_audio, args=(audio_index,))
    sources = _sources_md(answer, briefing) if answer.sources else ""
    lat = latency_html(answer)
    if sources or lat:
        with st.container(key=f"mb-qa-meta-{key}", horizontal=True, vertical_alignment="center", gap="small"):
            if lat:
                st.html(lat, width="content")
    if sources:
        news = {} if briefing is None else {s: item for item in briefing.context.news for s in (item.id, item.url)}
        with st.expander(f"Fuentes ({len(answer.sources)})", icon=":material/link:"):
            for source in answer.sources:
                st.markdown(_source_md(source, news))
    if trace and answer.metrics:
        with st.container(key=f"mb-qa-trace-{key}"):
            with st.expander("Cómo se hizo", icon=":material/account_tree:"):
                chain = (["Voz a texto"] if voice else []) + ["agente Q&A"] + (["texto a voz"] if answer.audio_path else [])
                text = " → ".join(chain)
                st.caption(text[:1].upper() + text[1:] + ": modelos encadenados, con su latencia y coste.")
                render_trace(answer, key=f"qa_trace_{key}")


def render_qa_turn(answer: QAAnswer, briefing: Briefing | None, *, key: str, voice: bool = False,
                   audio_index: int | None = None) -> None:
    """Un turno completo de la conversación: pregunta del usuario y respuesta del asistente."""
    transcribed = any(m.step == "qa.stt" and m.provider != "mock" for m in answer.metrics)
    render_user_turn(answer.question, key=key, voice=voice, transcribed=transcribed)
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        render_answer_body(answer, briefing, key=key, voice=voice, audio_index=audio_index)


_SCROLL_JS = """<script>/* mb-qa-scroll %s */
(() => {
  const go = () => {
    const conv = document.querySelector('.st-key-mb-qa-conv');
    if (!conv) return;
    const users = conv.querySelectorAll('[class*="st-key-mb-qa-user-"]');
    const msgs = conv.querySelectorAll('[data-testid="stChatMessage"]');
    if (!users.length || !msgs.length) return;
    const turn = users[users.length - 1].closest('[data-testid="stChatMessage"]') || users[users.length - 1];
    const last = msgs[msgs.length - 1];
    const bar = document.querySelector('.st-key-mb-topbar');
    const comp = document.querySelector('.st-key-mb-qa-composer');
    const minTop = (bar ? bar.getBoundingClientRect().bottom : 0) + 12;
    const maxBottom = (comp ? comp.getBoundingClientRect().top : window.innerHeight) - 12;
    let delta = 0;
    const lastBottom = last.getBoundingClientRect().bottom;
    if (lastBottom > maxBottom) delta = lastBottom - maxBottom;   /* que la barra fija no tape el final */
    const turnTop = turn.getBoundingClientRect().top;
    if (turnTop - delta < minTop) delta = turnTop - minTop;       /* ...sin esconder el inicio de la pregunta */
    if (Math.abs(delta) < 2) return;
    const main = document.querySelector('section.stMain');
    if (main && main.scrollHeight > main.clientHeight) main.scrollBy({top: delta});
    else window.scrollBy({top: delta});
  };
  requestAnimationFrame(() => setTimeout(go, 80));
  setTimeout(go, 450);
})();
</script>"""


def scroll_to_latest(nonce: str) -> None:
    """Desplaza la página para que el último turno (pregunta + respuesta) quede a la vista.

    Streamlit conserva el scroll entre ejecuciones, así que tras responder la respuesta nueva podía
    quedar debajo de la barra fija de entrada. ``nonce`` cambia en cada llamada para que el script se
    vuelva a montar (y a ejecutar). El contenedor va oculto por CSS (no ocupa sitio).
    """
    with st.container(key=f"mb-qa-scroll-{nonce}"):
        st.html(_SCROLL_JS % escape(nonce), unsafe_allow_javascript=True)


def page_title_html() -> str:
    """Título serif de la vista («Pregunta a Toro y Osa»)."""
    return (f'<h2 class="mb-qa-title">Pregunta a {escape(brand.SPEAKER_A_NAME)} y '
            f"{escape(brand.SPEAKER_B_NAME)}</h2>")


def context_html(b: Briefing) -> str:
    """Línea de contexto: «Sobre: <titular> · dd/mm/aaaa · id <corto>» (escapado; id completo en el ``title``)."""
    short = b.id.rsplit("-", 1)[-1][:8] if b.id else ""
    meta = f"· {b.analysis.date:%d/%m/%Y}" + (f" · id {short}" if short else "")
    return (f'<p class="mb-qa-ctx" title="Briefing {escape(b.id)}">Sobre: <b>{escape(b.analysis.headline)}</b> '
            f'{tech_label(meta, "muted")}</p>')


__all__ = [
    "BOT_AVATAR",
    "USER_AVATAR",
    "VOICE_NOTE",
    "context_html",
    "latency_html",
    "page_title_html",
    "render_answer_body",
    "render_bot_text",
    "render_qa_turn",
    "render_user_turn",
    "scroll_to_latest",
    "start_warmup",
    "suggestions",
    "welcome_text",
]
