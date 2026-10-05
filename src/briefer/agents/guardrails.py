"""Guardarraíles de compliance (MiFID II) compartidos por los agentes.

Carril B. El prompt ya prohíbe recomendar, pero no se confía solo en el LLM: aquí se detectan
y eliminan frases que suenan a recomendación personalizada de compra/venta, y se detectan
preguntas del usuario que piden ese tipo de consejo (para recordarle el disclaimer).

Los patrones son deliberadamente conservadores: «la compra de una empresa» o «los inversores
venden» son hechos y NO se filtran; «deberías comprar» o «recomendamos vender» sí.
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


__all__ = ["ADVICE_REMINDER_ES", "asks_for_advice", "contains_advice", "strip_advice"]
