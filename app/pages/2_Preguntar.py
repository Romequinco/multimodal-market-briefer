"""Página "Preguntar": Agente Q&A por voz o texto (carril C, llama a ``pipeline.answer_question``)."""

from __future__ import annotations

from datetime import datetime

import components  # noqa: F401  (añade src/ al sys.path)
import streamlit as st
from components.players import pending, render_qa_answer, show_disclaimer, show_error, sidebar_controls

from briefer.config import get_settings

st.set_page_config(page_title="Preguntar · Market Briefer", layout="wide")
use_mock = sidebar_controls()
settings = get_settings()

st.title("Pregunta sobre el briefing")
show_disclaimer()

briefing = st.session_state.get("briefing")
if briefing is None:
    st.info("Aún no has generado un briefing en esta sesión: el agente responderá sin contexto del día.")
else:
    st.caption(f"Contexto: «{briefing.analysis.headline}»")

audio = st.audio_input("Graba tu pregunta")
text = st.text_input("…o escríbela", placeholder="¿Por qué ha subido hoy el Santander?")
speak = st.checkbox("Responder también en audio", value=True)

if st.button("Preguntar", type="primary", disabled=audio is None and not text.strip()):
    from briefer import pipeline

    question: str | object = text.strip()
    if audio is not None:
        audio_dir = settings.cache_path / "voice"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"pregunta_{datetime.now():%Y%m%d_%H%M%S}.wav"
        audio_path.write_bytes(audio.getvalue())
        question = audio_path

    with st.spinner("Pensando…"):
        try:
            answer = pipeline.answer_question(
                question,
                briefing,
                speak=speak,
                history=st.session_state.get("qa_history"),
                use_mock=use_mock,
            )
            st.session_state.setdefault("qa_answers", []).insert(0, answer)
            st.session_state.setdefault("qa_history", []).extend(
                [
                    {"role": "user", "content": answer.question},
                    {"role": "assistant", "content": answer.answer_text},
                ]
            )
        except NotImplementedError as exc:
            pending(exc, "el Agente Q&A (voz → texto → respuesta → voz)")
        except Exception as exc:
            show_error(exc, "la respuesta")

for previous in st.session_state.get("qa_answers", []):
    with st.container(border=True):
        render_qa_answer(previous)
