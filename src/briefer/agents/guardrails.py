"""Guardarraíles de compliance (MiFID II) compartidos por los agentes.

Carril B. El prompt ya prohíbe recomendar, pero no se confía solo en el LLM: aquí se detectan
y eliminan frases que suenan a recomendación personalizada de compra/venta, y se detectan
preguntas del usuario que piden ese tipo de consejo (para recordarle el disclaimer).

Los patrones son deliberadamente conservadores: «la compra de una empresa» o «los inversores
venden» son hechos y NO se filtran; «deberías comprar» o «recomendamos vender» sí.

Además, *grounding* de cifras (``untraceable_figures``): toda cifra que el Analista escriba
debe poder rastrearse hasta el contexto que recibió (precios, noticias, documentos); las que
no aparecen se consideran posiblemente inventadas.
"""

from __future__ import annotations

import re

_ACTIONS = r"(?:comprar|compres|compréis|vender|vendas|vendáis|mantener|deshacer(?:te|os)?|invertir|inviertas|entrar|salir|acumular|reforzar)"

# Frases de recomendación en la RESPUESTA del agente.
_ADVICE_PATTERNS = [
    re.compile(
        r"\b(?:te|os|le|les)?\s*(?:recomiend\w*|recomend\w*|aconsej\w*|sugier\w*|suger\w*)\b[^.!?]{0,60}?\b"
        + _ACTIONS
        + r"\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:deber[íi]as|deber[íi]ais|tendr[íi]as que|conviene|es buen momento para|es el momento de)\b"
        r"[^.!?]{0,40}?\b" + _ACTIONS + r"\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:señal|oportunidad) (?:clara )?de (?:compra|venta)\b", re.IGNORECASE),
    re.compile(r"\b(?:compra|vende|mantén|mantened)\s+(?:ya|ahora|sin dudar)\b", re.IGNORECASE),
]

# Preguntas del USUARIO que piden consejo personalizado.
_ADVICE_REQUEST_PATTERNS = [
    re.compile(r"\b(?:compro|vendo|invierto|meto|saco)\b", re.IGNORECASE),
    re.compile(r"\bdeber[íi]a\b[^?]{0,40}\b(?:comprar|vender|invertir|mantener|salir|entrar)\b", re.IGNORECASE),
    re.compile(r"\b(?:qué|que)\s+(?:me\s+)?(?:recomiendas|aconsejas|harías)\b", re.IGNORECASE),
    re.compile(r"\bcu[áa]nto\s+(?:dinero\s+)?(?:invierto|debo invertir|meto)\b", re.IGNORECASE),
    re.compile(r"\b(?:es|ser[íi]a)\s+(?:buen|un buen)\s+momento\s+(?:para|de)\s+(?:comprar|vender|invertir|entrar)\b", re.IGNORECASE),
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

ADVICE_REMINDER_ES = (
    "Recuerda que esto es información general, no asesoramiento financiero ni una "
    "recomendación personalizada de inversión."
)


_NEGATION_BEFORE = re.compile(r"\b(?:no|ni|nunca|jam[áa]s)\s*(?:te|os|le|les|se)?\s*$", re.IGNORECASE)


def contains_advice(text: str) -> bool:
    """``True`` si ``text`` contiene alguna frase que suena a recomendación de inversión.

    Las negaciones («no recomendamos comprar ni vender») no cuentan como recomendación.
    """
    for pattern in _ADVICE_PATTERNS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 20) : match.start()]
            if not _NEGATION_BEFORE.search(prefix):
                return True
    return False


def strip_advice(text: str) -> tuple[str, bool]:
    """Elimina las frases con recomendaciones de inversión.

    Returns:
        ``(texto_limpio, hubo_cambios)``. Si todas las frases eran recomendaciones, el texto
        queda vacío y es el llamante quien decide qué poner.
    """
    if not text or not contains_advice(text):
        return text, False
    kept = [s for s in _SENTENCE_SPLIT.split(text.strip()) if not contains_advice(s)]
    return " ".join(kept).strip(), True


def asks_for_advice(question: str) -> bool:
    """``True`` si la pregunta del usuario pide una recomendación personalizada."""
    return any(p.search(question) for p in _ADVICE_REQUEST_PATTERNS)


# ── Grounding de cifras ───────────────────────────────────────────────────────────

# Nombres de índices con número propio: no son cifras del día.
_INDEX_NAMES = re.compile(
    r"\b(?:IBEX|S&P|Euro\s*Stoxx|EuroStoxx|DAX|FTSE|Nasdaq|CAC|Nikkei|MSCI\s+World)\s*\d+\b",
    re.IGNORECASE,
)
# Cifra "suelta" en el texto: no pegada a letras (Q3, 3T, G7), ni a "/" (fechas 05/10/2026).
_FIGURE = re.compile(r"(?<![\w.,/])[-+−]?\d+(?:[.,]\d+)*(?![\w/])")
_REF_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _figure_values(token: str) -> list[tuple[float, int]]:
    """Interpretaciones posibles ``(valor, nº de decimales)`` de una cifra escrita.

    Contempla formato español (``1.245,5``) e inglés (``1,245.5``): ``"1.245"`` puede ser
    1245 o 1,245; ``"1,2"`` es 1,2.
    """
    t = token.lstrip("+-−")
    out: list[tuple[float, int]] = []
    if "." in t and "," in t:
        dec_sep = "." if t.rfind(".") > t.rfind(",") else ","
        thou_sep = "," if dec_sep == "." else "."
        integer, _, frac = t.replace(thou_sep, "").partition(dec_sep)
        out.append((float(f"{integer}.{frac}"), len(frac)))
        return out
    for sep in (".", ","):
        if sep in t:
            parts = t.split(sep)
            if len(parts) == 2:
                out.append((float(f"{parts[0]}.{parts[1]}"), len(parts[1])))
            if all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
                out.append((float("".join(parts)), 0))
            return out
    out.append((float(t), 0))
    return out


def extract_figures(text: str) -> list[str]:
    """Cifras relevantes de ``text`` (sin repetir, en orden de aparición).

    Se ignoran: años (1900-2100), enteros pequeños (< 10) que no sean porcentajes, números de
    nombres de índices («IBEX 35», «S&P 500») y cifras pegadas a letras o a «/».
    """
    clean = _INDEX_NAMES.sub(" ", text or "")
    figures: list[str] = []
    for match in _FIGURE.finditer(clean):
        token = match.group(0)
        digits = token.lstrip("+-−")
        is_int = digits.isdigit()
        followed_by_pct = clean[match.end() : match.end() + 3].lstrip().startswith(("%", "por ciento"))
        if is_int and 1900 <= int(digits) <= 2100 and not followed_by_pct:
            continue
        if is_int and int(digits) < 10 and not followed_by_pct:
            continue
        if digits not in figures:
            figures.append(digits)
    return figures


def untraceable_figures(text: str, reference: str) -> list[str]:
    """Cifras de ``text`` que no aparecen en ``reference`` (posibles invenciones del LLM).

    Una cifra es trazable si alguna cifra del contexto, en valor absoluto, coincide con ella
    al redondear a los decimales con que está escrita (``"1,2 %"`` casa con ``"+1.24 %"``;
    ``"1.245 millones"`` casa con ``"1.245 M€"``). El signo se ignora («cae un 1,2 %» frente a
    ``-1.20 %``). Las cifras derivadas (diferencias, sumas) no se consideran trazables.

    Returns:
        Lista de cifras tal como aparecen en ``text`` (sin signo), sin repetir.
    """
    ref_values = [v for tok in _REF_NUMBER.findall(reference or "") for v, _ in _figure_values(tok)]
    missing: list[str] = []
    for fig in extract_figures(text):
        candidates = _figure_values(fig)
        ok = any(
            abs(abs(r) - v) <= 0.5 * 10 ** (-d) + 1e-9 for v, d in candidates for r in ref_values
        )
        if not ok:
            missing.append(fig)
    return missing


def strip_figures(text: str, figures: list[str]) -> tuple[str, bool]:
    """Elimina de ``text`` las frases que contienen alguna de ``figures``.

    Returns:
        ``(texto_limpio, hubo_cambios)``.
    """
    if not text or not figures:
        return text, False
    targets = set(figures)
    kept = [s for s in _SENTENCE_SPLIT.split(text.strip()) if not targets & set(extract_figures(s))]
    cleaned = " ".join(kept).strip()
    return cleaned, cleaned != text.strip()


__all__ = [
    "ADVICE_REMINDER_ES",
    "asks_for_advice",
    "contains_advice",
    "extract_figures",
    "strip_advice",
    "strip_figures",
    "untraceable_figures",
]
