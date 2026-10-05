"""Tema visual «Noticiero nocturno» de la UI (carril C, solo presentación).

Base oscura de terminal, titulares serif de periódico y acento naranja «en antena». Los colores base
y las fuentes viven en ``.streamlit/config.toml`` (tema ``dark``); aquí se inyecta el CSS propio que
Streamlit no cubre (cinta de cotizaciones, cabecera, reproductor, tarjetas de puntos clave, etiquetas
técnicas en mono) y se ofrecen helpers que generan ese HTML.

Reglas:

- ``apply_theme()`` se llama al principio de cada página; es idempotente dentro de una ejecución
  (una segunda llamada en la misma recarga no vuelve a inyectar el CSS).
- Selectores estables: ``[data-testid=...]`` de Streamlit y las clases ``st-key-<key>`` que Streamlit
  añade a los contenedores con ``key`` (nunca clases hash de emotion).
- **Todo texto que entra en HTML se escapa** (``html.escape``): titulares, fuentes y tickers vienen
  de noticias externas. Solo se enlazan URL ``http(s)``.
- El CSS es decorativo: si no se aplica, la app sigue siendo usable (y los tests ``AppTest`` no
  dependen de él). Los helpers que devuelven ``str`` (``*_html``) son funciones puras y testeables.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

# ── Paleta (tokens fijos del diseño) ──────────────────────────────────────────────────
TOKENS: dict[str, str] = {
    "bg": "#12151B",
    "bg-sidebar": "#0E1116",
    "surface": "#1C2129",
    "surface-2": "#232A34",
    "border": "#2A313B",
    "text": "#D6DEE8",
    "text-strong": "#FFFFFF",
    "text-muted": "#888780",
    "accent": "#D85A30",
    "accent-soft": "#F0997B",
    "up": "#5DCAA5",
    "down": "#F09595",
    "amber": "#EF9F27",
}
FONT_SERIF = "'Source Serif 4', Georgia, 'Times New Roman', serif"
FONT_SANS = "Inter, 'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_MONO = "'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace"

SENTIMENT_CLASS = {"positivo": "up", "negativo": "down", "neutral": "flat"}
SENTIMENT_TEXT = {"positivo": "▲ positivo", "negativo": "▼ negativo", "neutral": "● neutral"}
TECH_TONES = ("amber", "ok", "warn", "err", "muted", "accent")
_WEEKDAYS = ("LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM")

_FONTS_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600"
    "&family=JetBrains+Mono:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap');"
)

_CSS = """
:root {
  --mb-bg: %(bg)s; --mb-bg-sidebar: %(bg-sidebar)s; --mb-surface: %(surface)s;
  --mb-surface-2: %(surface-2)s; --mb-border: %(border)s; --mb-text: %(text)s;
  --mb-text-strong: %(text-strong)s; --mb-muted: %(text-muted)s; --mb-accent: %(accent)s;
  --mb-accent-soft: %(accent-soft)s; --mb-up: %(up)s; --mb-down: %(down)s; --mb-amber: %(amber)s;
  --mb-serif: %(serif)s; --mb-sans: %(sans)s; --mb-mono: %(mono)s;
}
[data-testid="stApp"] { background: var(--mb-bg); color: var(--mb-text); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: var(--mb-bg-sidebar); border-right: 1px solid var(--mb-border); }
[data-testid="stMainBlockContainer"] { padding-top: 2.2rem; }

/* Titulares: serif de periódico */
[data-testid="stHeading"] h1, [data-testid="stHeading"] h2, [data-testid="stHeading"] h3,
[data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4 {
  font-family: var(--mb-serif); font-weight: 600; color: var(--mb-text-strong); letter-spacing: -0.01em;
}
[data-testid="stCaptionContainer"] { color: var(--mb-muted); }

/* Botones: primario sólido accent; secundario con borde */
[data-testid="stBaseButton-primary"] { background: var(--mb-accent); border-color: var(--mb-accent); color: #fff; }
[data-testid="stBaseButton-primary"]:hover { background: #c24f29; border-color: #c24f29; color: #fff; }
[data-testid="stBaseButton-secondary"] { background: transparent; border: 1px solid var(--mb-border); color: var(--mb-text); }
[data-testid="stBaseButton-secondary"]:hover { border-color: var(--mb-accent-soft); color: var(--mb-text-strong); }
button:focus-visible, a:focus-visible, [role="tab"]:focus-visible, summary:focus-visible,
input:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--mb-accent-soft) !important; outline-offset: 2px;
}

/* Pestañas, desplegables, métricas */
[data-testid="stTab"][aria-selected="true"] p { color: var(--mb-accent-soft); }
[data-testid="stExpander"] details { background: var(--mb-surface); border: 1px solid var(--mb-border); }
[data-testid="stMetric"] { background: var(--mb-surface); border: 1px solid var(--mb-border); border-radius: 8px; padding: .6rem .8rem; }
[data-testid="stMetricLabel"] p { font-family: var(--mb-mono); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--mb-amber); }
[data-testid="stMetricValue"] { font-family: var(--mb-mono); font-size: 1.35rem; color: var(--mb-text-strong); }
[data-testid="stGraphVizChart"] { background: transparent; }
[data-testid="stAudio"], [data-testid="stAudio"] audio { width: 100%%; color-scheme: dark; }
[data-testid="stPageLink-NavLink"] { border-radius: 8px; }
[data-testid="stMultiSelect"] [data-baseweb="tag"] { background: var(--mb-surface-2); color: var(--mb-text);
  border: 1px solid var(--mb-border); font-family: var(--mb-mono); font-size: 12.5px; }

/* Contenedores con key: tarjetas surface */
[class*="st-key-mb-card"], [class*="st-key-mb-player"] {
  background: var(--mb-surface); border: 1px solid var(--mb-border); border-radius: 10px; padding: 1rem 1.1rem;
}
[class*="st-key-mb-cta"] [data-testid="stPageLink-NavLink"] {
  border: 1px solid var(--mb-border); justify-content: center; padding: .38rem .9rem; min-height: 2.5rem;
}
[class*="st-key-mb-cta"] [data-testid="stPageLink-NavLink"]:hover { border-color: var(--mb-accent-soft); background: var(--mb-surface-2); }

/* Cinta de cotizaciones */
.mb-tape { display: flex; gap: 1.4rem; align-items: center; overflow-x: auto; white-space: nowrap;
  font-family: var(--mb-mono); font-size: 12px; color: var(--mb-text); padding: .45rem .75rem;
  background: var(--mb-bg-sidebar); border-top: 1px solid var(--mb-border); border-bottom: 1px solid var(--mb-border);
  scrollbar-width: thin; }
.mb-tape__label { color: var(--mb-amber); letter-spacing: .08em; }
.mb-tape__item b { color: var(--mb-text-strong); font-weight: 500; margin-right: .35rem; }
.mb-tape__last { color: var(--mb-muted); margin-right: .35rem; }
.mb-up { color: var(--mb-up); } .mb-down { color: var(--mb-down); } .mb-flat { color: var(--mb-muted); }
.mb-tape__item.mb-idx b, .mb-tape__item.mb-idx .mb-up, .mb-tape__item.mb-idx .mb-down { color: var(--mb-muted); }

/* Cabecera */
.st-key-mb-masthead h1 { font-family: var(--mb-serif); font-size: 2.1rem; padding: 0; }
.mb-mast { display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; }
.mb-onair { font-family: var(--mb-mono); font-size: 12px; text-transform: lowercase; color: var(--mb-accent-soft);
  border: 1px solid var(--mb-accent); border-radius: 999px; padding: .15rem .6rem; }
.mb-onair__dot { color: var(--mb-accent); animation: mb-pulse 2s ease-in-out infinite; }
.mb-onair--off { color: var(--mb-muted); border-color: var(--mb-border); }
.mb-onair--off .mb-onair__dot { color: var(--mb-muted); animation: none; }
.mb-date { font-family: var(--mb-mono); font-size: 12px; color: var(--mb-muted); letter-spacing: .06em; }
.mb-tagline { font-family: var(--mb-serif); font-weight: 400; font-size: 1.15rem; color: var(--mb-text); margin: 0 0 .4rem; }
@keyframes mb-pulse { 0%%, 100%% { opacity: 1; } 50%% { opacity: .35; } }

/* Titular y metadatos */
.mb-headline { font-family: var(--mb-serif); font-weight: 600; font-size: clamp(1.5rem, 1.1rem + 1.4vw, 2.1rem);
  line-height: 1.2; color: var(--mb-text-strong); margin: .2rem 0 .35rem; padding: 0; }
.mb-meta { font-family: var(--mb-mono); font-size: 12px; color: var(--mb-muted); margin: 0; }

/* Píldoras de modo / origen */
.mb-pill { display: inline-block; font-family: var(--mb-mono); font-size: 11.5px; text-transform: uppercase;
  letter-spacing: .05em; border: 1px solid var(--mb-border); border-radius: 4px; padding: .12rem .5rem; color: var(--mb-muted); }
.mb-pill--ok { color: var(--mb-up); border-color: var(--mb-up); }
.mb-pill--amber { color: var(--mb-amber); border-color: var(--mb-amber); }
.mb-pill--accent { color: var(--mb-accent-soft); border-color: var(--mb-accent); }
.mb-mode-note { font-family: var(--mb-mono); font-size: 11.5px; color: var(--mb-muted); }

/* Reproductor */
.mb-player { display: flex; align-items: center; gap: 1rem; }
.mb-player__disc { flex: none; width: 46px; height: 46px; border-radius: 50%%; background: var(--mb-accent);
  display: flex; align-items: center; justify-content: center; }
.mb-player__body { flex: 1; min-width: 0; }
.mb-eq { display: flex; align-items: flex-end; gap: 3px; height: 18px; }
.mb-eq span { width: 4px; background: #fff; border-radius: 1px; }
.mb-eq span:nth-child(1) { height: 55%%; } .mb-eq span:nth-child(2) { height: 100%%; } .mb-eq span:nth-child(3) { height: 70%%; }
.mb-player__title { font-family: var(--mb-serif); font-weight: 600; color: var(--mb-text-strong); font-size: 1.05rem; margin: 0; }
.mb-wave { display: flex; align-items: center; gap: 2px; height: 28px; margin-top: .35rem; overflow: hidden; }
.mb-wave span { flex: 1 1 0; min-width: 2px; max-width: 5px; border-radius: 1px; background: var(--mb-border); }
.mb-wave span.on { background: var(--mb-accent-soft); }

/* Puntos clave */
.mb-kp { background: var(--mb-surface); border: 1px solid var(--mb-border); border-left: 3px solid var(--mb-muted);
  border-radius: 0 8px 8px 0; padding: .75rem 1rem; margin: 0 0 .1rem; }
.mb-kp--up { border-left-color: var(--mb-up); } .mb-kp--down { border-left-color: var(--mb-down); }
.mb-kp__head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: .5rem; }
.mb-kp__title { font-family: var(--mb-serif); font-weight: 600; font-size: 18px; color: var(--mb-text-strong); margin: 0; padding: 0; line-height: 1.3; }
.mb-kp__sent { font-family: var(--mb-mono); font-size: 12px; }
.mb-kp__text { margin: .4rem 0 0; color: var(--mb-text); font-size: 15px; line-height: 1.5; }
.mb-kp__meta { font-family: var(--mb-mono); font-size: 12px; color: var(--mb-muted); margin-top: .4rem; }
.mb-kp__src { font-size: 13px; color: var(--mb-muted); margin-top: .3rem; }
.mb-kp__src a { color: var(--mb-accent-soft); text-decoration: underline; text-underline-offset: 2px; }

/* Etiquetas técnicas (tono terminal) */
.mb-tech { font-family: var(--mb-mono); font-size: 12px; letter-spacing: .03em; }
.mb-tech--amber { color: var(--mb-amber); } .mb-tech--ok { color: var(--mb-up); } .mb-tech--warn { color: var(--mb-amber); }
.mb-tech--err { color: var(--mb-down); } .mb-tech--muted { color: var(--mb-muted); } .mb-tech--accent { color: var(--mb-accent-soft); }
.mb-strip { font-family: var(--mb-mono); font-size: 12px; color: var(--mb-text); }
.mb-legend { font-family: var(--mb-mono); font-size: 11.5px; color: var(--mb-muted); display: flex; flex-wrap: wrap; gap: .3rem 1rem; }
.mb-legend i { display: inline-block; width: 10px; height: 10px; border: 2px solid; border-radius: 2px; margin-right: .35rem; vertical-align: -1px; }
.mb-disclaimer { font-family: var(--mb-mono); font-size: 11.5px; color: var(--mb-muted); }

@media (prefers-reduced-motion: reduce) {
  .mb-onair__dot { animation: none; }
  * { scroll-behavior: auto !important; }
}
[data-testid="stSidebarNav"] li:first-child a p { font-size: 0; line-height: 1.4rem; }
[data-testid="stSidebarNav"] li:first-child a p::after { content: "Portada"; font-size: 0.875rem; }
@media (max-width: 640px) {
  .mb-tape { gap: 1rem; }
  .st-key-mb-masthead h1 { font-size: 1.7rem; }
}
"""


def theme_css() -> str:
    """CSS completo del tema (función pura, útil en tests)."""
    values = dict(TOKENS, serif=FONT_SERIF, sans=FONT_SANS, mono=FONT_MONO)
    return _FONTS_IMPORT + (_CSS % values)


def apply_theme() -> bool:
    """Inyecta el CSS del tema una sola vez por ejecución de la página.

    Idempotente: Streamlit renueva ``ctx.cursors`` (un dict) al empezar cada recarga, así que se
    marca el contexto con ese objeto; una segunda llamada en la misma recarga no hace nada.

    Returns:
        ``True`` si ha inyectado el CSS en esta llamada.
    """
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

        ctx = get_script_run_ctx(suppress_warning=True)
    except Exception:  # API interna: si cambia, se inyecta igualmente
        ctx = None
    marker = getattr(ctx, "cursors", None) if ctx is not None else None
    if marker is not None and getattr(ctx, "_mb_theme_marker", None) is marker:
        return False
    st.html(f"<style>{theme_css()}</style>")
    if marker is not None:
        try:
            setattr(ctx, "_mb_theme_marker", marker)
        except Exception:
            pass
    return True


# ── Utilidades de formato ──────────────────────────────────────────────────────────


def _e(value: Any) -> str:
    """Escapa cualquier valor para HTML (texto y atributos)."""
    return escape(str(value), quote=True)


def _fmt_num(value: float, decimals: int = 2) -> str:
    """Formato español: 1.234,56."""
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_pct(value: float) -> str:
    return ("+" if value > 0 else "") + _fmt_num(value) + " %"


def _safe_url(url: str | None) -> str | None:
    if url and str(url).strip().lower().startswith(("http://", "https://")):
        return str(url).strip()
    return None


def fmt_date(value: date | datetime | str | None) -> str:
    """``LUN · 05/10/2026`` (mono en la cabecera)."""
    if value is None:
        value = date.today()
    if isinstance(value, str):
        return value
    return f"{_WEEKDAYS[value.weekday()]} · {value:%d/%m/%Y}"


def fmt_duration(seconds: float) -> str:
    mins, secs = divmod(int(round(seconds or 0)), 60)
    return f"{mins}:{secs:02d}"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ── Helpers HTML (puros) ───────────────────────────────────────────────────────────


def ticker_tape_html(
    prices: Iterable[Any], names: dict[str, str] | None = None, indices: Iterable[str] = ()
) -> str:
    """Cinta mono de cotizaciones: ``TICKER último ▲ +1,20 %``; índices (``^…``) en gris.

    ``prices``: objetos o dicts con ``ticker``, ``last`` y ``change_pct`` (``PriceSnapshot``).
    Nunca usa el color como única señal: cada variación lleva ▲/▼/● y signo.
    """
    idx = set(indices)
    names = names or {}
    items: list[str] = []
    for p in prices:
        ticker = str(_get(p, "ticker", "") or "")
        if not ticker:
            continue
        try:
            change = float(_get(p, "change_pct", 0.0) or 0.0)
            last = float(_get(p, "last", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        tone = "up" if change > 0 else "down" if change < 0 else "flat"
        arrow = {"up": "▲", "down": "▼", "flat": "●"}[tone]
        is_index = ticker.startswith("^") or ticker in idx
        label = names.get(ticker, ticker)
        items.append(
            f'<span class="mb-tape__item{" mb-idx" if is_index else ""}">'
            f"<b>{_e(label)}</b><span class=\"mb-tape__last\">{_e(_fmt_num(last))}</span>"
            f'<span class="mb-{tone}">{arrow} {_e(_fmt_pct(change))}</span></span>'
        )
    if not items:
        return ""
    return (
        '<div class="mb-tape" role="region" aria-label="Cotizaciones de la sesión" tabindex="0">'
        '<span class="mb-tape__label">COTIZACIONES</span>' + "".join(items) + "</div>"
    )


def on_air_html(on_air: bool = True) -> str:
    if on_air:
        return '<span class="mb-onair"><span class="mb-onair__dot" aria-hidden="true">●</span> en antena</span>'
    return ('<span class="mb-onair mb-onair--off"><span class="mb-onair__dot" aria-hidden="true">●</span>'
            " fuera de antena</span>")


def masthead_meta_html(when: date | datetime | str | None, on_air: bool = True) -> str:
    return f'<div class="mb-mast">{on_air_html(on_air)}<span class="mb-date">{_e(fmt_date(when))}</span></div>'


def headline_html(text: str, meta: str | Sequence[str] | None = None, *, level: int = 2) -> str:
    """Titular serif grande + línea de metadatos mono (``05/10/2026 · 5:27 · 2 voces sintéticas``)."""
    level = min(max(int(level), 1), 4)
    out = f'<h{level} class="mb-headline">{_e(text)}</h{level}>'
    if meta:
        parts = [meta] if isinstance(meta, str) else [m for m in meta if m]
        out += f'<p class="mb-meta">{_e(" · ".join(str(m) for m in parts))}</p>'
    return f"<div>{out}</div>"


def tech_label(text: str, tone: str = "amber") -> str:
    """Etiqueta técnica en mono (ámbar por defecto; ``ok``/``warn``/``err``/``muted``/``accent``)."""
    tone = tone if tone in TECH_TONES else "amber"
    return f'<span class="mb-tech mb-tech--{tone}">{_e(text)}</span>'


def pill_html(text: str, tone: str = "muted") -> str:
    tone = tone if tone in ("ok", "amber", "accent", "muted") else "muted"
    return f'<span class="mb-pill mb-pill--{tone}">{_e(text)}</span>'


def wave_html(seed: str = "", bars: int = 56, played: float = 0.38) -> str:
    """Onda decorativa (determinista a partir de ``seed``); ``aria-hidden``."""
    digest = hashlib.sha256(str(seed).encode("utf-8")).digest()
    spans = []
    for i in range(bars):
        b = digest[i % len(digest)] ^ (i * 37 & 0xFF)
        envelope = 0.55 + 0.45 * abs(((i % 14) - 7) / 7)  # ligera ondulación
        height = int(18 + (b / 255) * 82 * envelope)
        cls = ' class="on"' if i < bars * played else ""
        spans.append(f'<span{cls} style="height:{min(height, 100)}%"></span>')
    return '<div class="mb-wave" aria-hidden="true">' + "".join(spans) + "</div>"


#: Icono del disco dibujado con CSS (st.html sanea los SVG en línea): tres barras de ecualizador.
_DISC_ICON = '<span class="mb-eq"><span></span><span></span><span></span></span>'


def player_header_html(title: str, meta: str | Sequence[str] | None = None, seed: str = "") -> str:
    """Cabecera del reproductor: disco accent (decorativo, no es un control), título, metadatos y onda.

    El control real de reproducción es el ``st.audio`` que ``player_card`` pinta debajo.
    """
    parts = [meta] if isinstance(meta, str) else [m for m in (meta or []) if m]
    meta_html = f'<p class="mb-meta">{_e(" · ".join(str(m) for m in parts))}</p>' if parts else ""
    return (
        f'<div class="mb-player"><div class="mb-player__disc" aria-hidden="true">{_DISC_ICON}</div>'
        f'<div class="mb-player__body"><p class="mb-player__title">{_e(title)}</p>{meta_html}'
        f"{wave_html(seed)}</div></div>"
    )


def keypoint_card_html(
    kp: Any, sources: Sequence[tuple[str, str | None]] = (), *, compact: bool = False
) -> str:
    """Tarjeta de un punto clave con borde izquierdo por sentimiento.

    Args:
        kp: ``KeyPoint`` (o dict con ``title``, ``explanation``, ``tickers``, ``sentiment``).
        sources: ``(texto, url)`` ya resueltos; solo se enlazan URL ``http(s)``.
        compact: sin explicación ni fuentes (portada).
    """
    sentiment = str(_get(kp, "sentiment", "neutral") or "neutral")
    tone = SENTIMENT_CLASS.get(sentiment, "flat")
    label = SENTIMENT_TEXT.get(sentiment, sentiment)
    tickers = [str(t) for t in (_get(kp, "tickers", []) or [])]
    side = {"up": "up", "down": "down"}.get(tone, "flat")
    out = [
        f'<article class="mb-kp mb-kp--{side}"><div class="mb-kp__head">'
        f'<h3 class="mb-kp__title">{_e(_get(kp, "title", ""))}</h3>'
        f'<span class="mb-kp__sent mb-{tone}">{_e(label)}</span></div>'
    ]
    explanation = str(_get(kp, "explanation", "") or "")
    if explanation and not compact:
        out.append(f'<p class="mb-kp__text">{_e(explanation)}</p>')
    if tickers:
        out.append(f'<div class="mb-kp__meta">Valores: {_e(", ".join(tickers))}</div>')
    if sources and not compact:
        links = []
        for text, url in sources:
            safe = _safe_url(url)
            if safe:
                links.append(f'<a href="{_e(safe)}" target="_blank" rel="noopener noreferrer">{_e(text)}</a>')
            else:
                links.append(_e(text))
        out.append(f'<div class="mb-kp__src">Fuentes: {" · ".join(links)}</div>')
    out.append("</article>")
    return "".join(out)


def legend_html(entries: Iterable[tuple[str, str, str]]) -> str:
    """Leyenda mono ``(estado, color, descripción)`` con muestra de color (el texto ya dice el estado)."""
    items = "".join(
        f'<span><i style="border-color:{_e(color)}"></i>{_e(desc)}</span>' for _, color, desc in entries
    )
    return f'<div class="mb-legend">{items}</div>'


# ── Helpers que pintan ─────────────────────────────────────────────────────────────


def ticker_tape(prices: Iterable[Any], names: dict[str, str] | None = None, indices: Iterable[str] = ()) -> None:
    """Pinta la cinta de cotizaciones (nada si no hay precios)."""
    body = ticker_tape_html(prices, names, indices)
    if body:
        st.html(body)


def masthead(when: date | datetime | str | None = None, on_air: bool = True, title: str = "Market Briefer") -> None:
    """Cabecera: nombre en serif (``st.title``) + insignia «● en antena» + fecha mono."""
    with st.container(key="mb-masthead", horizontal=True, vertical_alignment="center", gap="medium"):
        st.title(title, anchor=False, width="content")
        st.html(masthead_meta_html(when, on_air), width="content")


def headline(text: str, meta: str | Sequence[str] | None = None) -> None:
    st.html(headline_html(text, meta))


def player_card(
    audio_path: str | Path, *, key: str, title: str = "Episodio de hoy",
    meta: str | Sequence[str] | None = None, seed: str = "",
) -> None:
    """Tarjeta del reproductor: cabecera decorativa + ``st.audio`` real dentro de la tarjeta."""
    with st.container(key=f"mb-player-{key}"):
        st.html(player_header_html(title, meta, seed or str(audio_path)))
        st.audio(str(audio_path))


def keypoint_card(kp: Any, sources: Sequence[tuple[str, str | None]] = (), *, compact: bool = False) -> None:
    st.html(keypoint_card_html(kp, sources, compact=compact))
