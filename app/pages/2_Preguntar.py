"""Página "Preguntar": Agente Q&A por voz o texto (carril C, llama a ``pipeline.answer_question``).

- **Contexto:** el briefing activo de la sesión (``st.session_state["briefing"]``: el de la portada, el
  recién generado o el abierto en el histórico). Si se llega aquí directamente, se usa el destacado
  de la portada. Al cambiar de briefing, la conversación empieza de cero (el historial de otro
  briefing confundiría al agente).
- **Respuesta en dos tiempos** (si el pipeline lo ofrece): primero el texto
  (``answer_question(..., speak=False)``) y después el audio (``pipeline.speak_answer``); así el texto
  aparece en ~2-5 s aunque la voz tarde más. Si ``speak_answer`` no existe, una sola llamada.
- **Calentamiento:** si existe ``pipeline.warmup``, se lanza una vez por proceso y modo en segundo
  plano al abrir la página (baja la latencia de la primera pregunta en frío).
- **RGPD:** el audio de la pregunta se guarda (nombre único, ``voice.save_audio_upload``) solo
  mientras se transcribe y se borra después.
- **Voz o texto:** al pulsar «Preguntar» se usa la entrada que el usuario tocó **la última**
  (``_qa_last_input``); tras cada pregunta los dos campos se vacían (clave nueva de widget), así
  que una grabación antigua nunca se reenvía al preguntar por texto.
- La respuesta muestra su traza «Cómo se hizo» (``QAAnswer.metrics``: voz a texto → agente → voz).
"""

from __future__ import annotations

import threading
from pathlib import Path

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import (
    featured_briefing,
    handle_navigation,
    mode_badge,
    pending,
    pick_question,
    render_qa_answer,
    show_disclaimer,
    show_error,
    sidebar_mode,
)

from briefer import pipeline
from briefer.config import get_settings
from briefer.schemas import Briefing, QAAnswer

st.set_page_config(page_title="Preguntar · Market Briefer", page_icon=":material/forum:", layout="wide")
handle_navigation()
mode = sidebar_mode()
settings = get_settings()

ANSWERS_KEY = "qa_answers"
HISTORY_KEY = "qa_history"
CONTEXT_KEY = "qa_context_id"
REQUEST_KEY = "_qa_request"
LAST_INPUT_KEY = "_qa_last_input"   # "audio" | "text": la entrada que se tocó la última
INPUT_GEN_KEY = "_qa_input_gen"     # generación de los widgets (cambia = campos vacíos)


@st.cache_resource(show_spinner=False)
def _start_warmup(run_mode: str) -> bool:
    """Calienta clientes HTTP/modelos una vez por proceso y modo, en un hilo (no bloquea la página)."""
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


_start_warmup(mode)

st.title("Pregunta sobre el briefing")
mode_badge(mode)

# ── Contexto ──────────────────────────────────────────────────────────────────────
briefing: Briefing | None = st.session_state.get("briefing")
if briefing is None:
    try:
        featured = featured_briefing()
    except Exception:
        featured = None
    if featured is not None:
        briefing = featured[0]
        st.session_state["briefing"] = briefing

if briefing is None:
    st.info("No hay ningún briefing cargado: el agente responderá sin el contexto del día. Genera uno en "
            "la página «Briefing» para preguntar sobre él.")
else:
    st.caption(f":material/description: Contexto: **{briefing.analysis.headline}** "
               f"(sesión del {briefing.analysis.date:%d/%m/%Y}, id `{briefing.id}`)")

context_id = briefing.id if briefing is not None else None
if st.session_state.get(CONTEXT_KEY) != context_id:
    st.session_state[CONTEXT_KEY] = context_id
    st.session_state[ANSWERS_KEY] = []
    st.session_state[HISTORY_KEY] = []

# ── Entrada ───────────────────────────────────────────────────────────────────────


def _suggestions(b: Briefing | None) -> list[str]:
    """Tres preguntas de ejemplo a partir del briefing (para la demo: un clic y responde)."""
    out = ["¿Qué ha pasado hoy en el mercado?"]
    if b is not None:
        from briefer.ingest.tickers import TICKER_UNIVERSE

        tickers = [t for kp in b.analysis.key_points for t in kp.tickers] or list(b.context.tickers)
        if tickers:
            name = TICKER_UNIVERSE.get(tickers[0], {}).get("name", tickers[0])
            out.append(f"¿Por qué se ha movido hoy {name}?")
    out.append("¿Debería comprar acciones?")  # muestra el guardarraíl MiFID (no asesora)
    return out


def _ask(question: str | None = None) -> None:
    """``on_click``: deja la pregunta pendiente (texto, sugerencia o audio grabado)."""
    st.session_state[REQUEST_KEY] = {"text": question}


def _touched(kind: str) -> None:
    st.session_state[LAST_INPUT_KEY] = kind


gen = int(st.session_state.get(INPUT_GEN_KEY, 0))
audio = st.audio_input("Graba tu pregunta", help="Se transcribe con voz a texto y se borra después.",
                       key=f"qa_audio_{gen}", on_change=_touched, args=("audio",))
text = st.text_input("…o escríbela", placeholder="¿Por qué ha subido hoy el Santander?",
                     key=f"qa_text_{gen}", on_change=_touched, args=("text",))
c1, c2 = st.columns([1, 3])
speak = c1.checkbox("Respuesta en audio", value=True)
c2.button("Preguntar", type="primary", disabled=audio is None and not text.strip(), on_click=_ask,
          icon=":material/send:")

st.caption("Prueba con:")
cols = st.columns(3)
for i, suggestion in enumerate(_suggestions(briefing)):
    cols[i].button(suggestion, key=f"suggest_{i}", on_click=_ask, args=(suggestion,), width="stretch")


def _answer(question: str | Path) -> QAAnswer:
    """Responde en dos tiempos si el pipeline lo permite (texto primero, audio después)."""
    history = st.session_state.get(HISTORY_KEY)
    two_step = speak and callable(getattr(pipeline, "speak_answer", None))
    with st.spinner("Pensando…"):
        answer = pipeline.answer_question(question, briefing, speak=speak and not two_step,
                                          history=history, mode=mode)
    if not two_step:
        return answer
    with st.container(border=True):  # el texto se ve ya, mientras se sintetiza la voz
        render_qa_answer(answer, briefing)
    with st.spinner("Poniendo voz a la respuesta…"):
        try:
            spoken = pipeline.speak_answer(answer, briefing, mode=mode)
        except TypeError:
            spoken = pipeline.speak_answer(answer)
        except Exception:  # el audio es opcional: se queda la respuesta en texto
            return answer
    if isinstance(spoken, QAAnswer):
        return spoken
    if isinstance(spoken, (str, Path)):
        return answer.model_copy(update={"audio_path": Path(spoken)})
    return answer


request = st.session_state.pop(REQUEST_KEY, None)
if request is not None:
    choice = pick_question(request.get("text"), text, audio is not None, st.session_state.get(LAST_INPUT_KEY))
    question: str | Path | None = None
    audio_tmp: Path | None = None
    if choice == "suggestion":
        question = request["text"]
    elif choice == "text":
        question = text.strip()
    elif choice == "audio":
        from briefer.ingest.voice import save_audio_upload

        try:
            audio_tmp = question = save_audio_upload(audio.getvalue(), settings.cache_path / "voice", ".wav")
        except ValueError as exc:  # grabación vacía
            st.warning(str(exc))
    if choice in ("text", "audio"):
        # Campos vacíos en la próxima recarga: la grabación ya enviada no se reenvía nunca.
        st.session_state[INPUT_GEN_KEY] = gen + 1
        st.session_state.pop(LAST_INPUT_KEY, None)
    if question is None:
        if choice != "audio":  # grabación vacía: ya avisado arriba
            st.warning("Escribe o graba una pregunta.")
    else:
        try:
            answer = _answer(question)
            st.session_state.setdefault(ANSWERS_KEY, []).insert(0, answer)
            st.session_state.setdefault(HISTORY_KEY, []).extend(
                [
                    {"role": "user", "content": answer.question},
                    {"role": "assistant", "content": answer.answer_text},
                ]
            )
            st.rerun()  # repinta la conversación con la respuesta definitiva arriba
        except NotImplementedError as exc:
            pending(exc, "la pregunta por voz (voz a texto)" if isinstance(question, Path)
                    else "el Agente Q&A")
        except ValueError as exc:
            st.warning(f"No se pudo entender la pregunta: {exc}")
        except Exception as exc:
            show_error(exc, "la respuesta")
        finally:
            if audio_tmp is not None:  # RGPD: la voz del usuario no se queda en disco
                audio_tmp.unlink(missing_ok=True)

# ── Conversación ──────────────────────────────────────────────────────────────────
answers = st.session_state.get(ANSWERS_KEY, [])
if answers:
    head, clear = st.columns([4, 1])
    head.markdown(f"#### Conversación ({len(answers)} pregunta{'s' if len(answers) != 1 else ''})")
    if clear.button("Borrar conversación", icon=":material/delete_sweep:"):
        st.session_state[ANSWERS_KEY] = []
        st.session_state[HISTORY_KEY] = []
        st.rerun()
    for previous in answers:
        with st.container(border=True):
            render_qa_answer(previous, briefing)

show_disclaimer()
