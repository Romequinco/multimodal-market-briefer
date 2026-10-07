"""Consultas guiadas sobre datos guardados, sin llamadas a modelos de lenguaje."""

from __future__ import annotations

import re
import unicodedata

from briefer.agents.analyst import allowed_sources
from briefer.agents.guardrails import ADVICE_REMINDER_ES, asks_for_advice, looks_like_injection
from briefer.ingest.tickers import CATALOG
from briefer.schemas import Briefing, QAAnswer


def _normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c))


def _mentioned(question: str, tickers: set[str]) -> set[str]:
    out = set()
    for ticker in tickers:
        info = CATALOG.get(ticker, {})
        labels = [ticker, str(info.get("name", ticker)), *info.get("aliases", [])]
        for label in labels:
            if re.search(r"(?<!\w)" + re.escape(_normalize(str(label))) + r"(?!\w)", question):
                out.add(ticker)
                break
    return out


def _number(value: float) -> str:
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def answer(question: str, briefing: Briefing | None, history: list[dict] | None = None) -> QAAnswer:
    """Resumen, empresas por alias, precios, variaciones y comparaciones del briefing."""
    question = question.strip()
    if not question:
        raise ValueError("La pregunta está vacía.")

    def notice(text: str) -> QAAnswer:
        return QAAnswer(question=question, answer_text="Demo guiada: " + text, response_kind="demo_notice")

    if asks_for_advice(question) or re.search(r"\b(?:comprar|vender|invertir|recomiendas)\b", question, re.I):
        return notice(ADVICE_REMINDER_ES)
    if briefing is None:
        return notice("abre un briefing para consultar su resumen y fuentes.")
    if looks_like_injection(question):
        return notice("solo puedo mostrar contenido del briefing abierto.")

    q = _normalize(question)
    points = list(briefing.analysis.key_points)
    universe = set(briefing.context.tickers) | {t for point in points for t in point.tickers}
    universe |= {price.ticker for price in briefing.context.prices}
    mentioned = _mentioned(q, universe | set(CATALOG))
    followup = re.fullmatch(r"[¿?\s]*(?:y )?(?:por que|esta empresa|esa empresa|ella|su precio|su cotizacion)[¿?\s]*", q)
    if not mentioned and followup:
        for message in reversed(history or []):
            if message.get("role") == "user":
                mentioned = _mentioned(_normalize(str(message.get("content", ""))), universe)
                if mentioned:
                    break

    prefix = f"Demo guiada · datos del briefing del {briefing.analysis.date:%d/%m/%Y}.\n\n"
    prices = [p for p in briefing.context.prices if p.ticker in (mentioned or set(briefing.context.tickers))]
    wants_price = bool(re.search(r"\b(precio|cotiza|cotizacion|vale|variacion|porcentaje)\b", q))
    ranking = bool(re.search(
        r"\b(cual|quien|que valor|que accion|que empresa|que (ha )?(subido|bajado))\b.*\b(mas|mejor|peor)\b", q,
    ))
    if prices and (wants_price or ranking):
        if ranking:
            descending = not bool(re.search(r"\b(cayo|cae|bajo|baja|bajado|peor|perdio|perdido)\b", q))
            prices = sorted(prices, key=lambda p: p.change_pct, reverse=descending)[:1]
        rows = []
        for price in prices:
            name = str(CATALOG.get(price.ticker, {}).get("name", price.ticker))
            move = "sube" if price.change_pct > 0 else "cae" if price.change_pct < 0 else "no varía"
            rows.append(f"{name}: {_number(price.last)} {price.currency}; {move} "
                        f"un {_number(abs(price.change_pct))} % en la variación registrada.")
        return QAAnswer(question=question, answer_text=prefix + "\n\n".join(rows), response_kind="demo_excerpt")

    summary = not mentioned and bool(re.search(
        r"\b(resumen|mercado|puntos clave|fuentes|noticias|que (ha )?pasado|que paso|que pasa|que ocurrio)\b", q,
    ))
    point_title = q.split(":", 1)[-1].strip() if ":" in q else q.strip("¿? ")
    named_points = [point for point in points if _normalize(point.title) == point_title]
    if named_points:
        points = named_points
    elif mentioned:
        points = [point for point in points if mentioned & set(point.tickers)]
    elif not summary:
        stopwords = {"que", "por", "porque", "como", "del", "las", "los", "una", "con", "para", "sobre",
                     "este", "esta", "briefing", "pasado", "movido", "explicame", "hoy", "acciones",
                     "empresa", "dice", "hay", "tiene", "cual", "mas", "punto"}
        terms = {t for t in re.findall(r"\w+", q) if len(t) > 2 and t not in stopwords}
        points = [point for point in points if terms & set(re.findall(
            r"\w+", _normalize(point.title + " " + point.explanation),
        ))]
    if not points:
        return notice("no encuentro ese tema en el briefing. Puedes consultar el resumen, una empresa, "
                      "su precio o qué valor subió más. Para preguntas abiertas, usa el modo Real.")

    points = points[:6]
    valid = allowed_sources(briefing.context)
    sources = list(dict.fromkeys(s for point in points for s in point.sources if s in valid))
    if "fuentes" in q:
        content = "Las fuentes de los puntos del briefing están en el desplegable «Fuentes» de esta respuesta."
    else:
        content = "\n\n".join(f"**{point.title}**\n\n{point.explanation}" for point in points)
    return QAAnswer(question=question, answer_text=prefix + content, sources=sources, response_kind="demo_excerpt")
