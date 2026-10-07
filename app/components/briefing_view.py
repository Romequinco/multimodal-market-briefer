"""Vista unificada de un briefing (rediseño «Hoy», boceto A).

Es el **único** sitio que pinta un briefing completo: la usan «Hoy» y «Archivo» (al abrir uno).

Estructura:

1. **Hero** (tarjeta ``mb-card-hero-<key>``): portada generada por IA a la izquierda (si existe) y, a la
   derecha, metadatos mono, titular serif, reproductor (``theme.player_card`` con ``st.audio`` real),
   Toro/Osa y la nota de voz sintética. Debajo, la cinta de cotizaciones del briefing.
2. Avisos compactos de pasos que cayeron a un sustituto (``players.render_run_warnings``).
3. Una fila de pestañas: Puntos clave · Transcripción · Gráficos · Vídeo (si hay) · Cómo se hizo.
4. Acciones: descargas (mp3 · .srt · .zip) y «Preguntar sobre este briefing».

El disclaimer no se repite aquí: lo pone el pie del armazón (``shell.footer``). Todo texto que entra en
HTML se escapa (titulares y fuentes vienen de noticias externas).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

from briefer import brand
from briefer.schemas import Briefing

from . import ROOT_DIR
from .players import (
    _FILE_PREFIX,
    SYNTHETIC_VOICE_NOTE,
    ask_about,
    briefing_tape,
    chart_caption,
    render_key_points,
    render_run_warnings,
    render_trace,
    trace_strip,
)
from .theme import fmt_duration, player_card
from .trace import is_demo_run

#: Etiqueta de cada origen (``origin`` de :func:`render_briefing_view`).
ORIGIN_LABELS: dict[str, str] = {
    "guardado": "Último guardado",
    "pregenerado": "Ejemplo pregenerado",
    "archivo": "Del archivo",
    "nuevo": "Recién generado",
}
AI_IMAGE_NOTE = "Imagen generada por IA"
#: Diagrama de la cadena de modelos (antigua portada «¿Cómo funciona?»).
ARCHITECTURE_DIAGRAM = ROOT_DIR / "docs" / "assets" / "arquitectura_mvp_podcast_financiero.png"
HOW_IT_WORKS = (
    "1. **Entradas**: noticias de mercado, cartera, PDF de resultados, captura de gráfico, voz.\n"
    "2. **Procesado**: filtro por valores · lectura de imagen (visión) · lectura de PDF · voz a texto.\n"
    "3. **Agentes IA**: Analista (interpreta, con control de cifras) → Guionista (diálogo); "
    "Q&A (responde preguntas).\n"
    "4. **Salidas**: gráficos · podcast a 2 voces sintéticas · transcripción y subtítulos.\n"
    "5. **Entrega**: app web y Telegram."
)
VOICE_NOTE = "Voces sintéticas generadas con IA, no son personas reales."


# ── Helpers puros (HTML escapado, testeables) ─────────────────────────────────────


def speaker_names() -> dict[str, str]:
    """``{"A": "Toro", "B": "Osa"}`` (configurable con ``BRIEFER_SPEAKER_*_NAME``)."""
    try:
        from briefer.config import get_settings

        s = get_settings()
        return {"A": s.briefer_speaker_a_name or brand.SPEAKER_A_NAME,
                "B": s.briefer_speaker_b_name or brand.SPEAKER_B_NAME}
    except Exception:  # .env mal formado: nombres de la marca
        return {"A": brand.SPEAKER_A_NAME, "B": brand.SPEAKER_B_NAME}


def _short_role(role: str) -> str:
    """``"el optimista: abre el episodio…"`` → ``"el optimista"``."""
    return role.split(":", 1)[0].strip()


def origin_label(briefing: Briefing, origin: str | None) -> str:
    """``"Del archivo · 05/10/2026"`` (vacío si ``origin`` es ``None`` o desconocido)."""
    label = ORIGIN_LABELS.get(origin or "")
    return f"{label} · {briefing.analysis.date:%d/%m/%Y}" if label else ""


def origin_pill_text(briefing: Briefing, origin: str | None) -> str:
    """Insignia de origen siempre visible en Hoy (pregenerado real/simulado, guardado, archivo…)."""
    demo = is_demo_run(briefing.metrics)
    if origin == "pregenerado":
        return "Ejemplo pregenerado · " + ("simulado" if demo else "datos y modelos reales")
    label = origin_label(briefing, origin)  # «Último guardado · 01/10/2026»
    if not label or origin == "archivo":
        return label
    return label + (" · demo" if demo else "")


def hero_meta(briefing: Briefing) -> list[str]:
    """Metadatos del hero: fecha · duración · 2 voces sintéticas · valores."""
    meta = [f"{briefing.analysis.date:%d/%m/%Y}"]
    if briefing.audio:
        meta.append(f"{fmt_duration(briefing.audio.duration_s)} min")
    meta.append("2 voces sintéticas")
    if briefing.context.tickers:
        meta.append(" · ".join(briefing.context.tickers))
    return meta


def hero_head_html(briefing: Briefing, origin: str | None = None) -> str:
    """Metadatos mono (+ etiqueta de origen) y titular serif grande del hero."""
    pill = origin_label(briefing, origin)
    pill_html = f'<span class="mb-hero__origin">{escape(pill)}</span>' if pill else ""
    items = hero_meta(briefing)
    tickers = " · ".join(briefing.context.tickers)
    # Los valores van en su propia línea (en pantallas medianas partían la fila con un «·» suelto)
    meta = "".join(
        f'<span class="mb-hero__tickers">{escape(m)}</span>' if tickers and i == len(items) - 1 and m == tickers
        else f"<span>{escape(m)}</span>"
        for i, m in enumerate(items)
    )
    mood = (briefing.analysis.market_mood or "").strip()
    mood_html = (f'<p class="mb-hero__mood"><span>Tono del mercado</span> {escape(mood)}</p>' if mood else "")
    return (f'<div class="mb-hero__meta">{pill_html}{meta}</div>'
            f'<h1 class="mb-hero__title">{escape(briefing.analysis.headline)}</h1>{mood_html}')


def voices_html(names: dict[str, str] | None = None) -> str:
    """Fila Toro/Osa con sus insignias T/O y la nota de voz sintética."""
    names = names or speaker_names()
    a, b = names["A"], names["B"]
    return (
        '<div class="mb-voices">'
        f'<span class="mb-badge mb-badge--a" aria-hidden="true">{escape(a[:1])}</span>'
        f'<span class="mb-badge mb-badge--b" aria-hidden="true">{escape(b[:1])}</span>'
        f'<span class="mb-voices__who"><b>{escape(a)}</b> {escape(_short_role(brand.SPEAKER_A_ROLE))}'
        f' &nbsp;·&nbsp; <b>{escape(b)}</b> {escape(_short_role(brand.SPEAKER_B_ROLE))}</span></div>'
        f'<p class="mb-voice-note">{escape(VOICE_NOTE)}</p>'
    )


def transcript_lines(briefing: Briefing) -> list[tuple[str, str, float | None]]:
    """Líneas del diálogo ``(locutor "A"/"B", texto, inicio en s o None)``.

    Texto del guion original (``script.lines``: cifras y tickers como se escriben); los tiempos salen
    de ``audio.segments`` si casan uno a uno. Sin guion, los segmentos del audio.
    """
    segments = list(briefing.audio.segments) if briefing.audio else []
    lines = list(briefing.script.lines)
    if lines:
        times: Sequence[float | None] = (
            [s.start_s for s in segments] if len(segments) == len(lines) else [None] * len(lines)
        )
        return [(ln.speaker, ln.text, t) for ln, t in zip(lines, times, strict=True)]
    return [(s.speaker, s.text, s.start_s) for s in segments]


def transcript_html(lines: Sequence[tuple[str, str, float | None]], names: dict[str, str] | None = None,
                    query: str = "") -> str:
    """Transcripción en estilo diálogo: insignia, nombre (+ minuto) y texto de cada intervención."""
    names = names or speaker_names()
    rows = []
    pattern = re.compile(re.escape(query.strip()), re.IGNORECASE) if query.strip() else None
    for speaker, text, start in lines:
        name = names.get(speaker, speaker)
        variant = "b" if speaker == "B" else "a"
        when = f"<span>{fmt_duration(start)}</span>" if start is not None else ""
        if pattern:
            parts, cursor = [], 0
            for match in pattern.finditer(text):
                parts.extend((escape(text[cursor:match.start()]), f"<mark>{escape(match.group())}</mark>"))
                cursor = match.end()
            parts.append(escape(text[cursor:]))
            body = "".join(parts)
        else:
            body = escape(text)
        rows.append(
            f'<div class="mb-line"><span class="mb-badge mb-badge--{variant}" aria-hidden="true">'
            f"{escape(name[:1])}</span><div><div class=\"mb-line__who\">{escape(name)} {when}</div>"
            f'<p class="mb-line__text">{body}</p></div></div>'
        )
    return '<div class="mb-transcript">' + "".join(rows) + "</div>"


def _exists(path: Path | None) -> bool:
    try:
        return path is not None and Path(path).exists()
    except OSError:
        return False


def is_today(briefing: Briefing, today: date | None = None) -> bool:
    return briefing.analysis.date == (today or date.today())


# ── Bloques que pintan ─────────────────────────────────────────────────────────────


def _hero(briefing: Briefing, key: str, origin: str | None) -> None:
    has_cover = _exists(briefing.cover_path)
    with st.container(key=f"mb-card-hero-{key}"):
        if has_cover:
            cover_col, body_col = st.columns([1.25, 2], gap=None)
            with cover_col, st.container(key=f"mb-hero-cover-{key}"):
                st.image(str(briefing.cover_path), caption=AI_IMAGE_NOTE, width="stretch")
        else:
            body_col = st.container()
        body_key = f"mb-hero-body-{key}" if has_cover else f"mb-hero-body-nocover-{key}"
        with body_col, st.container(key=body_key):
            st.html(hero_head_html(briefing, origin))
            _player(briefing, key)
            st.html(voices_html())
        with st.container(key=f"mb-hero-tape-{key}"):
            briefing_tape(briefing)


def _player(briefing: Briefing, key: str) -> None:
    audio = briefing.audio
    if audio and _exists(audio.path):
        meta = [f"{fmt_duration(audio.duration_s)} min"]
        if audio.segments:
            meta.append(f"{len(audio.segments)} intervenciones")
        player_card(Path(audio.path), key=f"hero-{key}", title=brand.episode_title(briefing.analysis.date),
                    meta=meta, seed=briefing.id)
    elif audio:
        st.info("El audio de este briefing ya no está en disco (¿se movió o borró la carpeta?). "
                "La transcripción y los gráficos siguen disponibles abajo.", icon=":material/music_off:")
    else:
        st.caption("Este briefing no tiene audio.")


def _warnings(briefing: Briefing, key: str) -> None:
    with st.container(key=f"mb-hoy-warn-{key}"):
        if briefing.metrics:
            try:
                st.caption(f":material/account_tree: **Cómo se hizo:** {trace_strip(briefing)}")
            except Exception:  # noqa: BLE001 - la franja es secundaria
                pass
        render_run_warnings(briefing)
        for d in briefing.deliveries:
            if d.channel != "web" and d.ok:  # las fallidas ya las avisa render_run_warnings
                st.caption(f":material/send: Enviado por {d.channel}: {d.detail or 'OK'}")


def transcript_text(briefing: Briefing) -> str:
    names = speaker_names()
    lines = transcript_lines(briefing)
    return "\n\n".join(f"{names.get(speaker, speaker)}: {text}" for speaker, text, _ in lines) if lines else (
        briefing.transcript.text if briefing.transcript else ""
    )


def _tab_transcript(briefing: Briefing, key: str) -> None:
    query = st.text_input("Buscar en la transcripción", key=f"{key}_transcript_search_{briefing.id}",
                          placeholder="Empresa, cifra o palabra…")
    lines = transcript_lines(briefing)
    if lines:
        if query.strip():
            count = sum(len(re.findall(re.escape(query.strip()), text, re.IGNORECASE)) for _, text, _ in lines)
            st.caption(f"{count} coincidencia(s)" if count else "No hay coincidencias con esa búsqueda.")
        st.html(transcript_html(lines, query=query))
        st.caption("Texto del guion original; el audio lee cifras y tickers en forma hablada. "
                   + VOICE_NOTE)
    elif briefing.transcript and briefing.transcript.text.strip():
        st.html(transcript_html([("", briefing.transcript.text, None)], query=query))
    else:
        st.write("Este briefing no tiene transcripción.")


def _tab_charts(briefing: Briefing, key: str) -> None:
    images = [c for c in briefing.charts if _exists(c.path)]
    if not images:
        st.write("Los gráficos de este briefing ya no están en disco." if briefing.charts
                 else "Este briefing no tiene gráficos.")
        return
    with st.container(key=f"mb-hoy-charts-{key}"):
        cols = st.columns(2, gap="medium")
        for i, chart in enumerate(images):
            with cols[i % 2], st.container(key=f"mb-card-chart-{key}-{i}"):
                st.image(str(chart.path), caption=chart_caption(chart), width="stretch")


def _tab_video(briefing: Briefing, key: str) -> None:
    with st.container(key=f"mb-hoy-video-{key}"):
        st.video(str(briefing.video.path))
        st.caption("Vídeo vertical con el podcast, los gráficos y subtítulos. " + VOICE_NOTE)


def _tab_trace(briefing: Briefing, key: str) -> None:
    with st.expander("¿Cómo funciona? (cadena de modelos)", icon=":material/schema:"):
        st.markdown(HOW_IT_WORKS)
        if _exists(ARCHITECTURE_DIAGRAM):
            st.image(str(ARCHITECTURE_DIAGRAM), caption="Arquitectura del MVP", width="stretch")
    render_trace(briefing, key=f"{key}_trace")


def _reader(path: Path):
    return lambda: Path(path).read_bytes()


def _actions(briefing: Briefing, key: str, ask_button: bool) -> None:
    """Descargas compactas en línea + «Preguntar sobre este briefing»."""
    with st.container(key=f"mb-hoy-actions-{key}", horizontal=True, wrap=True, gap="small",
                      vertical_alignment="center"):
        st.html('<span class="mb-hoy-label">Descargar</span>', width="content")
        audio = briefing.audio
        if audio and _exists(audio.path):
            path = Path(audio.path)
            ext = path.suffix.lstrip(".") or "mp3"
            st.download_button(
                f"Podcast .{ext}", _reader(path), file_name=f"{_FILE_PREFIX}_{briefing.id}{path.suffix}",
                mime="audio/mpeg" if ext.lower() == "mp3" else "audio/wav", key=f"{key}_dl_audio",
                on_click="ignore", icon=":material/download:",
            )
        if briefing.transcript and _exists(briefing.transcript.srt_path):
            st.download_button(
                "Subtítulos .srt", _reader(Path(briefing.transcript.srt_path)),
                file_name=f"{_FILE_PREFIX}_{briefing.id}.srt", mime="application/x-subrip",
                key=f"{key}_dl_srt", on_click="ignore", icon=":material/subtitles:",
            )
        text = transcript_text(briefing)
        if text:
            st.download_button("Transcripción .txt", text, file_name=f"{_FILE_PREFIX}_{briefing.id}.txt",
                               mime="text/plain; charset=utf-8", key=f"{key}_dl_text", on_click="ignore",
                               icon=":material/article:")
        from briefer import storage

        st.download_button(
            "Todo .zip", lambda: storage.export_briefing_zip(briefing),
            file_name=f"{_FILE_PREFIX}_{briefing.id}.zip", mime="application/zip", key=f"{key}_dl_zip",
            on_click="ignore", icon=":material/folder_zip:",
            help="Briefing autocontenido (JSON con rutas relativas, audio, SRT y gráficos): se puede "
            "abrir en otra máquina copiándolo a data/outputs/.",
        )
        if ask_button:
            st.space("stretch")
            st.button("Preguntar sobre este briefing", key=f"{key}_ask", icon=":material/forum:",
                      on_click=ask_about, args=(briefing,), type="primary")


def render_briefing_view(briefing: Briefing, *, key: str = "briefing", origin: str | None = None) -> None:
    """Pinta un briefing completo (interfaz estable para Hoy y Archivo).

    Args:
        briefing: el briefing a pintar.
        key: distingue los widgets si se pinta más de uno en la misma página.
        origin: ``None`` | ``"guardado"`` | ``"pregenerado"`` | ``"archivo"`` | ``"nuevo"``; solo
            cambia la etiqueta de origen que aparece junto a los metadatos.
    """
    _hero(briefing, key, origin)
    _warnings(briefing, key)

    video = briefing.video if briefing.video and _exists(briefing.video.path) else None
    names = ["Puntos clave", "Transcripción", "Gráficos"] + (["Vídeo"] if video else []) + ["Cómo se hizo"]
    with st.container(key=f"mb-hoy-tabs-{key}"):
        tabs = dict(zip(names, st.tabs(names), strict=True))
        with tabs["Puntos clave"]:
            render_key_points(briefing, ask_key=f"{key}_{briefing.id}")
        with tabs["Transcripción"]:
            _tab_transcript(briefing, key)
        with tabs["Gráficos"]:
            _tab_charts(briefing, key)
        if video:
            with tabs["Vídeo"]:
                _tab_video(briefing, key)
        with tabs["Cómo se hizo"]:
            _tab_trace(briefing, key)

    _actions(briefing, key, ask_button=True)
    from .new_briefing import repeat_briefing_button

    repeat_briefing_button(briefing, key=f"{key}_repeat")


__all__ = [
    "AI_IMAGE_NOTE",
    "ORIGIN_LABELS",
    "SYNTHETIC_VOICE_NOTE",
    "VOICE_NOTE",
    "hero_head_html",
    "hero_meta",
    "origin_pill_text",
    "is_today",
    "origin_label",
    "render_briefing_view",
    "speaker_names",
    "transcript_html",
    "transcript_lines",
    "voices_html",
]
