"""Agente Analista: interpreta el contexto de mercado del día.

Carril B. Entrada: ``MarketContext`` (noticias filtradas, precios, insights de PDF/gráfico/voz,
cartera opcional). Salida: ``Analysis`` (titular, puntos clave con tickers, sentimiento y
fuentes, tono del mercado y disclaimer). Prompt: ``prompts/analyst.md``.
Patrón de agente del notebook 9 (Agents): rol + contexto + salida estructurada.

No se confía ciegamente en el LLM: tras la llamada, ``postprocess_analysis`` fuerza la fecha
y el disclaimer, descarta tickers y fuentes que no existen en el contexto (anti-alucinación),
elimina frases con recomendaciones de compra/venta y limita el número de puntos clave.
"""

from __future__ import annotations

from briefer.agents import load_prompt
from briefer.agents.guardrails import strip_advice
from briefer.logging_utils import get_logger
from briefer.providers.base import LLMProvider
from briefer.schemas import DISCLAIMER_ES, Analysis, KeyPoint, MarketContext, NewsItem

log = get_logger("agents.analyst")

MAX_KEY_POINTS = 6
_NEWS_SUMMARY_CHARS = 600
_INSIGHT_SUMMARY_CHARS = 1_200
_INSIGHT_FIGURES = 12


def _ticker_names() -> dict[str, str]:
    """``{ticker: nombre}`` del universo conocido (carril A); vacío si no está disponible."""
    try:
        from briefer.ingest.tickers import TICKER_UNIVERSE

        return {t: str(info.get("name", t)) for t, info in TICKER_UNIVERSE.items()}
    except Exception:  # el universo es una ayuda, nunca debe romper el agente
        return {}


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _label(ticker: str, names: dict[str, str]) -> str:
    name = names.get(ticker)
    return f"{ticker} ({name})" if name and name != ticker else ticker


def _news_block(item: NewsItem, names: dict[str, str]) -> str:
    tickers = ", ".join(_label(t, names) for t in item.tickers) or "-"
    return (
        f"- id: {item.id}\n"
        f"  fuente: {item.source} · {item.published_at:%Y-%m-%d %H:%M}\n"
        f"  tickers: {tickers}\n"
        f"  titular: {_clip(item.title, 300)}\n"
        f"  resumen: {_clip(item.summary, _NEWS_SUMMARY_CHARS)}"
    )


def _prioritized_news(context: MarketContext) -> list[NewsItem]:
    """Noticias de la cartera/tickers del usuario primero, luego el resto (más recientes antes)."""
    focus = set(context.tickers)
    if context.portfolio:
        focus |= {p.ticker for p in context.portfolio.positions}
    ordered = sorted(context.news, key=lambda n: n.published_at, reverse=True)
    return [n for n in ordered if focus & set(n.tickers)] + [
        n for n in ordered if not focus & set(n.tickers)
    ]


def build_user_message(context: MarketContext, max_chars: int = 40_000) -> str:
    """Serializa el contexto en un mensaje compacto y trazable para el LLM.

    Secciones (en orden de prioridad al recortar): precios > cartera > noticias (las de los
    tickers del usuario primero) > documentos del usuario. Cada noticia lleva su ``id`` para
    que el LLM lo cite en ``KeyPoint.sources``; cada documento, su nombre. De la cartera solo
    se envían tickers y pesos (minimización de datos, RGPD). Si se supera ``max_chars`` se
    omiten bloques enteros (nunca se corta un bloque a la mitad) y se avisa al LLM.
    """
    names = _ticker_names()
    header = [
        f"# Contexto de mercado del {context.date:%d/%m/%Y}",
        "Tickers del usuario: " + (", ".join(_label(t, names) for t in context.tickers) or "-"),
    ]

    prices = ["## Precios (último · variación diaria)"]
    if context.prices:
        for p in context.prices:
            trend = ""
            if len(p.history) >= 2 and p.history[0][1]:
                first = p.history[0][1]
                trend = f" · {((p.last - first) / first) * 100:+.2f} % desde {p.history[0][0]:%d/%m}"
            prices.append(
                f"- {_label(p.ticker, names)}: {p.last:.2f} {p.currency} · {p.change_pct:+.2f} %{trend}"
            )
    else:
        prices.append("- (sin datos de precios)")

    portfolio: list[str] = []
    if context.portfolio and context.portfolio.positions:
        portfolio.append("## Cartera del usuario (solo tickers y pesos)")
        for pos in context.portfolio.positions:
            weight = f"{pos.weight * 100:.1f} %" if pos.weight is not None else "peso no indicado"
            portfolio.append(f"- {_label(pos.ticker, names)}: {weight}")

    blocks: list[str] = []
    news = _prioritized_news(context)
    if news:
        blocks.append("## Noticias (cita su `id` en `sources`)")
        blocks.extend(_news_block(n, names) for n in news)
    else:
        blocks.append("## Noticias\n- (no hay noticias relevantes hoy para estos tickers)")

    if context.insights:
        blocks.append("## Documentos del usuario (cita su nombre en `sources`)")
        for ins in context.insights:
            figures = list(ins.key_figures.items())[:_INSIGHT_FIGURES]
            fig_txt = "; ".join(f"{k}: {v}" for k, v in figures) or "-"
            blocks.append(
                f"- nombre: {ins.source_name} (tipo: {ins.source_type})\n"
                f"  resumen: {_clip(ins.summary, _INSIGHT_SUMMARY_CHARS)}\n"
                f"  cifras clave: {fig_txt}"
            )

    message = "\n".join(header + [""] + prices + ([""] + portfolio if portfolio else []))
    omitted = 0
    for block in blocks:
        if len(message) + len(block) + 2 > max_chars:
            omitted += 1
            continue
        message += "\n\n" + block if block.startswith("##") else "\n" + block
    if omitted:
        message += f"\n\n(Se han omitido {omitted} bloques por longitud.)"
    return message[:max_chars]


def allowed_sources(context: MarketContext) -> dict[str, str]:
    """Mapa de referencias válidas -> forma canónica (id de noticia o nombre de documento).

    Acepta el ``id`` o la ``url`` de cada noticia y el ``source_name`` de cada documento.
    """
    refs: dict[str, str] = {}
    for n in context.news:
        refs[n.id] = n.id
        refs[n.url] = n.id
    for ins in context.insights:
        refs[ins.source_name] = ins.source_name
    return {k.strip().lower(): v for k, v in refs.items() if k}


def allowed_tickers(context: MarketContext) -> set[str]:
    """Tickers que aparecen en el contexto (usuario, noticias, precios o cartera)."""
    tickers = {t.upper() for t in context.tickers}
    tickers |= {t.upper() for n in context.news for t in n.tickers}
    tickers |= {p.ticker.upper() for p in context.prices}
    if context.portfolio:
        tickers |= {p.ticker.upper() for p in context.portfolio.positions}
    return tickers


def _clean_ref(ref: str) -> str:
    return ref.strip().strip("[]()`'\"").strip().lower()


def postprocess_analysis(
    analysis: Analysis, context: MarketContext, max_points: int = MAX_KEY_POINTS
) -> Analysis:
    """Valida y sanea la salida del LLM contra el contexto (no confía en el modelo).

    - ``date`` = fecha del contexto y ``disclaimer`` = ``DISCLAIMER_ES`` siempre.
    - Tickers de cada ``KeyPoint`` que no estén en el contexto -> fuera.
    - ``sources`` que no correspondan a una noticia o documento real -> fuera (se aceptan
      id, URL o nombre de documento, y se normalizan al id/nombre canónico).
    - Frases con recomendaciones de compra/venta -> fuera (MiFID II).
    - Puntos sin título ni explicación -> fuera; como mucho ``max_points``.
    """
    valid_refs = allowed_sources(context)
    valid_tickers = allowed_tickers(context)
    points: list[KeyPoint] = []
    for kp in analysis.key_points:
        tickers = list(dict.fromkeys(t.strip().upper() for t in kp.tickers if t.strip()))
        dropped_t = [t for t in tickers if t not in valid_tickers]
        sources: list[str] = []
        dropped_s: list[str] = []
        for ref in kp.sources:
            canon = valid_refs.get(_clean_ref(ref))
            if canon is None:
                dropped_s.append(ref)
            elif canon not in sources:
                sources.append(canon)
        if dropped_t or dropped_s:
            log.warning(
                "Analista: descartados tickers %s y fuentes %s no presentes en el contexto",
                dropped_t,
                dropped_s,
            )
        explanation, changed = strip_advice(kp.explanation)
        title, changed_t = strip_advice(kp.title)
        if changed or changed_t:
            log.warning("Analista: eliminada una frase con recomendación de inversión")
        if not (title or "").strip() or not (explanation or "").strip():
            continue
        points.append(
            kp.model_copy(
                update={
                    "title": title.strip(),
                    "explanation": explanation.strip(),
                    "tickers": [t for t in tickers if t in valid_tickers],
                    "sources": sources,
                }
            )
        )
    if len(points) > max_points:
        log.info("Analista: recortando de %d a %d puntos clave", len(points), max_points)
        points = points[:max_points]

    headline, _ = strip_advice(analysis.headline)
    mood, _ = strip_advice(analysis.market_mood)
    return Analysis(
        date=context.date,
        headline=headline.strip() or f"Resumen de mercado del {context.date:%d/%m/%Y}",
        key_points=points,
        market_mood=mood.strip() or "Sin una tendencia clara.",
        disclaimer=DISCLAIMER_ES,
    )


def analyze(context: MarketContext, llm: LLMProvider, max_chars: int = 40_000) -> Analysis:
    """Ejecuta el Agente Analista y devuelve un ``Analysis`` validado y saneado.

    Args:
        context: contexto del día (de ``pipeline.run_briefing``).
        llm: proveedor LLM (inyectado; ``MockLLM`` en tests).
        max_chars: límite de longitud del mensaje de usuario.
    """
    system = load_prompt("analyst")
    user = build_user_message(context, max_chars=max_chars)
    result = llm.complete(system, [{"role": "user", "content": user}], response_model=Analysis)
    if not isinstance(result, Analysis):
        # Algunos proveedores podrían devolver dict/JSON; se valida aquí con el contrato.
        result = (
            Analysis.model_validate_json(result)
            if isinstance(result, str)
            else Analysis.model_validate(result)
        )
    analysis = postprocess_analysis(result, context)
    if not analysis.key_points:
        log.warning("Analista: ningún punto clave válido tras la post-validación")
    return analysis


__all__ = [
    "MAX_KEY_POINTS",
    "allowed_sources",
    "allowed_tickers",
    "analyze",
    "build_user_message",
    "postprocess_analysis",
]
