"""Vista «Preguntar»: chat por voz o texto con el Agente Q&A (llama a ``pipeline.answer_question``).

- **Contexto:** el briefing activo de la sesión (``st.session_state["briefing"]``: el de Hoy, el recién
  generado o el abierto en Archivo). Si se llega aquí directamente, se usa el destacado de la portada.
  Al cambiar de briefing, la conversación empieza de cero (el historial de otro briefing confundiría
  al agente).
- **Una sola barra de entrada:** ``st.chat_input(accept_audio=True)``: el usuario escribe **o** graba;
  el valor solo llega en la ejecución siguiente al envío, así que una grabación ya enviada nunca se
  reenvía. Las sugerencias (``st.pills``) van encima de la barra.
- **Respuesta en dos tiempos** (si el pipeline lo ofrece): primero el texto
  (``answer_question(..., speak=False)``) y después el audio (``pipeline.speak_answer``); así el texto
  aparece en ~2-5 s aunque la voz tarde más. Si ``speak_answer`` no existe, una sola llamada.
- **Calentamiento:** ``pipeline.warmup`` se lanza una vez por proceso y modo en segundo plano.
- **RGPD:** el audio de la pregunta se guarda (nombre único, ``voice.save_audio_upload``) solo mientras
  se transcribe y se borra después.
- Cada respuesta lleva su latencia y su traza «Cómo se hizo» (``QAAnswer.metrics``).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

import components  # noqa: F401  (añade src/ al sys.path)
from briefer import pipeline
from briefer.config import get_settings
from briefer.logging_utils import error_text
from briefer.schemas import Briefing, QAAnswer
from components import qa_view
from components.players import featured_briefing, page_link, pending, pick_question, show_error
from components.shell import VIEW_ARCHIVE, VIEW_HOY, current_mode

ANSWERS_KEY = "qa_answers"          # list[QAAnswer], la más reciente primero
HISTORY_KEY = "qa_history"          # memoria del agente: [{"role", "content"}, …]
VOICE_KEY = "qa_voice"              # list[bool] alineada con ANSWERS_KEY: ¿pregunta por voz?
CONTEXT_KEY = "qa_context_id"
REQUEST_KEY = "_qa_request"         # sugerencia pulsada (la deja el callback de las pills)
SUGGEST_KEY = "qa_suggest"
SPEAK_KEY = "qa_speak"
SCROLL_KEY = "_qa_scroll"           # tras responder: llevar el último turno a la vista

mode = current_mode()
settings = get_settings()
qa_view.start_warmup(mode)

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

context_id = briefing.id if briefing is not None else None
if st.session_state.get(CONTEXT_KEY) != context_id:
    st.session_state[CONTEXT_KEY] = context_id
    st.session_state[ANSWERS_KEY] = []
    st.session_state[HISTORY_KEY] = []
    st.session_state[VOICE_KEY] = []


def _suggest() -> None:
    """``on_change`` de las sugerencias: deja la pregunta pendiente y desmarca la pill."""
    choice = st.session_state.get(SUGGEST_KEY)
    if choice:
        st.session_state[REQUEST_KEY] = {"text": choice}
    st.session_state[SUGGEST_KEY] = None


def _clear() -> None:
    st.session_state[ANSWERS_KEY] = []
    st.session_state[HISTORY_KEY] = []
    st.session_state[VOICE_KEY] = []


def _answer(question: str | Path, speak: bool) -> QAAnswer:
    """Responde en dos tiempos si el pipeline lo permite (texto primero, audio después).

    Se llama dentro del ``st.chat_message`` del asistente: el texto provisional se pinta en el chat
    mientras se sintetiza la voz.
    """
    history = st.session_state.get(HISTORY_KEY)
    two_step = speak and callable(getattr(pipeline, "speak_answer", None))
    with st.spinner("Pensando…"):
        answer = pipeline.answer_question(question, briefing, speak=speak and not two_step,
                                          history=history, mode=mode)
    if not two_step:
        return answer
    with st.container(key="mb-qa-pending"):  # el texto se ve ya, mientras se sintetiza la voz
        qa_view.render_answer_body(answer, briefing, key="pending", trace=False)
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


answers: list[QAAnswer] = st.session_state.get(ANSWERS_KEY, [])
voices: list[bool] = st.session_state.get(VOICE_KEY, [])

with st.container(key="mb-qa"):
    # ── Cabecera ──
    st.html(qa_view.page_title_html())
    if briefing is not None:
        with st.container(key="mb-qa-context", horizontal=True, vertical_alignment="center", gap="small"):
            st.html(qa_view.context_html(briefing), width="content")
            page_link(VIEW_ARCHIVE, "Cambiar", ":material/swap_horiz:")
    else:
        with st.container(key="mb-qa-empty"):
            st.info("No hay ningún briefing cargado: el agente responderá sin el contexto del día. "
                    "Abre o genera uno en «Hoy» para preguntar sobre él.", icon=":material/info:")
            page_link(VIEW_HOY, "Ir a Hoy", ":material/podcasts:")

    # ── Conversación (en orden cronológico) ──
    conversation = st.container(key="mb-qa-conv")
    with conversation:
        if not answers:
            qa_view.render_bot_text(qa_view.welcome_text(briefing))
        n = len(answers)
        for i, previous in enumerate(reversed(answers)):
            voice = voices[n - 1 - i] if n - 1 - i < len(voices) else False
            qa_view.render_qa_turn(previous, briefing, key=str(i), voice=voice)

    # ── Barra de entrada: sugerencias, chat (texto o voz) y herramientas ──
    with st.container(key="mb-qa-composer"):
        compact = "on" if answers else "off"
        asked = {str(a.question).strip() for a in answers}
        pending = [q for q in qa_view.suggestions(briefing) if q not in asked]  # sin repetir lo ya preguntado
        if pending:
            with st.container(key=f"mb-qa-sugs-{compact}"):
                st.pills("Prueba con:", pending, key=SUGGEST_KEY, on_change=_suggest,
                         label_visibility="visible" if not answers else "collapsed")
        prompt = st.chat_input("Escribe o graba tu pregunta…", accept_audio=True, key="qa_chat")
        with st.container(key="mb-qa-tools", horizontal=True, vertical_alignment="center", gap="small",
                          wrap=False):
            speak = st.toggle("Respuesta en audio", value=True, key=SPEAK_KEY)
            st.space("stretch")
            st.button("Borrar conversación", type="tertiary", icon=":material/delete_sweep:",
                      key="qa_clear", on_click=_clear, disabled=not answers)

if st.session_state.pop(SCROLL_KEY, False) and answers:
    qa_view.scroll_to_latest(f"a{len(answers)}")  # la respuesta nueva, a la vista

# ── Pregunta pendiente (sugerencia o envío del chat) ──────────────────────────────
request = st.session_state.pop(REQUEST_KEY, None)
typed, recording = "", None
if prompt is not None:
    if isinstance(prompt, str):
        typed = prompt
    else:  # ChatInputValue: .text y .audio (UploadedFile audio/wav o None)
        typed = getattr(prompt, "text", "") or ""
        recording = getattr(prompt, "audio", None)
choice = ""
if request is not None or prompt is not None:
    # En la barra única, si llega una grabación es lo último que hizo el usuario.
    choice = pick_question(request.get("text") if request else None, typed, recording is not None, "audio")

if choice:
    question: str | Path | None = None
    audio_tmp: Path | None = None
    with conversation:
        user_slot = st.empty()
        if choice == "suggestion":
            question = request["text"]
        elif choice == "text":
            question = typed.strip()
        elif choice == "audio":
            from briefer.ingest.voice import save_audio_upload

            try:
                audio_tmp = question = save_audio_upload(recording.getvalue(), settings.cache_path / "voice",
                                                         ".wav")
            except ValueError as exc:  # grabación vacía
                st.warning(f"No se pudo usar la grabación ({error_text(exc)}).")
        if question is not None:
            with user_slot.container():
                qa_view.render_user_turn(
                    "Transcribiendo tu pregunta…" if isinstance(question, Path) else str(question),
                    key="pending", voice=isinstance(question, Path),
                )
            qa_view.scroll_to_latest(f"p{len(answers)}")  # la pregunta enviada y el «Pensando…», a la vista
            with st.chat_message("assistant", avatar=qa_view.BOT_AVATAR):
                try:
                    answer = _answer(question, speak)
                    st.session_state.setdefault(ANSWERS_KEY, []).insert(0, answer)
                    st.session_state.setdefault(VOICE_KEY, []).insert(0, isinstance(question, Path))
                    st.session_state.setdefault(HISTORY_KEY, []).extend(
                        [
                            {"role": "user", "content": answer.question},
                            {"role": "assistant", "content": answer.answer_text},
                        ]
                    )
                    ok = True
                except NotImplementedError as exc:
                    ok = False
                    pending(exc, "la pregunta por voz (voz a texto)" if isinstance(question, Path)
                            else "el Agente Q&A")
                except ValueError as exc:
                    ok = False
                    st.warning(f"No se pudo entender la pregunta ({error_text(exc)}).")
                except Exception as exc:
                    ok = False
                    show_error(exc, "la respuesta")
                finally:
                    if audio_tmp is not None:  # RGPD: la voz del usuario no se queda en disco
                        audio_tmp.unlink(missing_ok=True)
            if ok:
                st.session_state[SCROLL_KEY] = True
                st.rerun()  # repinta la conversación con la respuesta definitiva
