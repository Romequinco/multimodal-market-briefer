"""Universo de tickers, normalización y filtrado de noticias por tickers/cartera.

Carril A. Entrada: ``list[NewsItem]`` + tickers del usuario. Salida: ``list[NewsItem]``
relevantes (las que mencionan alguno de los tickers o el nombre de la empresa).

Reglas de detección en texto (``extract_tickers``):
- Símbolo literal: solo en MAYÚSCULAS y como palabra completa (``SAN.MC``, ``AAPL``, ``$NVDA`` o la
  raíz sin sufijo ``SAN``). Así «San Sebastián» o «SANTANDER» no disparan ``SAN.MC``. Los
  símbolos de 1-2 letras (``F``, ``GM``) solo cuentan con ``$`` delante (``MIN_BARE_SYMBOL``).
- Alias/nombre de empresa: sin distinguir mayúsculas ni tildes, como palabra completa
  («telefonica» -> ``TEF.MC``). Los alias ambiguos en español (p. ej. «meta») no se usan sueltos.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from briefer.schemas import NewsItem

# Universo para la UI y la detección en texto (ticker de Yahoo Finance -> nombre y alias).
# Incluye los valores de la cartera y noticias de ejemplo, más algunos IBEX/EE. UU. habituales.
# TODO (D2+): ampliar a IBEX 35 completo o cargar desde un CSV en data/samples.
TICKER_UNIVERSE: dict[str, dict[str, list[str] | str]] = {
    # IBEX 35
    "SAN.MC": {"name": "Banco Santander", "aliases": ["Banco Santander", "Santander"]},
    "BBVA.MC": {"name": "BBVA", "aliases": ["BBVA", "Banco Bilbao Vizcaya"]},
    "CABK.MC": {"name": "CaixaBank", "aliases": ["CaixaBank", "Caixa Bank"]},
    "ITX.MC": {"name": "Inditex", "aliases": ["Inditex", "Zara"]},
    "IBE.MC": {"name": "Iberdrola", "aliases": ["Iberdrola"]},
    "TEF.MC": {"name": "Telefónica", "aliases": ["Telefónica", "Movistar"]},
    "REP.MC": {"name": "Repsol", "aliases": ["Repsol"]},
    "AENA.MC": {"name": "Aena", "aliases": ["Aena"]},
    "FER.MC": {"name": "Ferrovial", "aliases": ["Ferrovial"]},
    "AMS.MC": {"name": "Amadeus IT", "aliases": ["Amadeus IT", "Amadeus"]},
    # EE. UU.
    "AAPL": {"name": "Apple", "aliases": ["Apple", "iPhone"]},
    "MSFT": {"name": "Microsoft", "aliases": ["Microsoft"]},
    "NVDA": {"name": "NVIDIA", "aliases": ["NVIDIA"]},
    "AMZN": {"name": "Amazon", "aliases": ["Amazon"]},
    "GOOGL": {"name": "Alphabet", "aliases": ["Alphabet", "Google"]},
    "META": {"name": "Meta Platforms", "aliases": ["Meta Platforms", "Facebook"]},
    "TSLA": {"name": "Tesla", "aliases": ["Tesla"]},
    # Índices (contexto general de mercado)
    "^IBEX": {"name": "IBEX 35", "aliases": ["IBEX 35", "Ibex"]},
    "^GSPC": {"name": "S&P 500", "aliases": ["S&P 500", "S&P"]},
}

# Índices que se usan para completar un briefing con pocas noticias específicas.
MARKET_INDEX_TICKERS: tuple[str, ...] = ("^IBEX", "^GSPC")

#: Símbolos más cortos (``F``, ``T``, ``GM``…) solo se detectan con ``$`` delante (``$F``): sueltos
#: en mayúsculas dan falsos positivos («Fase V», «IA»).
MIN_BARE_SYMBOL = 3

# Delimitadores de "palabra" para alias y símbolos (más estrictos que \b, que falla con "&" o ".").
_LEFT = r"(?<![\w&.^$])"
_RIGHT = r"(?![\w&]|\.\w)"


def _fold(text: str) -> str:
    """Minúsculas y sin tildes (``"Telefónica"`` -> ``"telefonica"``)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _root(ticker: str) -> str:
    """Símbolo sin sufijo de mercado ni prefijo de índice (``"SAN.MC"`` -> ``"SAN"``)."""
    return ticker.lstrip("^").split(".", 1)[0]


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    """Índice ``clave plegada -> ticker`` con tickers, raíces, nombres y alias del universo."""
    index: dict[str, str] = {}
    for ticker, info in TICKER_UNIVERSE.items():
        keys = [ticker, _root(ticker), str(info["name"]), *list(info["aliases"])]
        for key in keys:
            index.setdefault(_fold(key), ticker)
    return index


def normalize_ticker(raw: str) -> str:
    """Normaliza la entrada del usuario a ticker de Yahoo (``"santander"`` -> ``"SAN.MC"``).

    Acepta el ticker exacto, la raíz sin sufijo (``"san"``), el nombre o un alias (sin
    distinguir mayúsculas ni tildes). Si no se reconoce, devuelve la entrada en mayúsculas y sin
    espacios (se asume que es un ticker válido de Yahoo fuera del universo).

    Raises:
        ValueError: si la entrada está vacía.
    """
    cleaned = " ".join(str(raw).split()).lstrip("$")
    if not cleaned:
        raise ValueError("Ticker vacío")
    found = _lookup().get(_fold(cleaned))
    if found:
        return found
    return cleaned.replace(" ", "").upper()


@lru_cache(maxsize=256)
def _patterns(ticker: str) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    """Regex de símbolo literal (sensible a mayúsculas) y de alias (sobre texto plegado)."""
    symbols = sorted({ticker, _root(ticker)}, key=len, reverse=True)
    bare = [re.escape(s) for s in symbols if len(s.lstrip("^")) >= MIN_BARE_SYMBOL]
    dollar_only = [re.escape(s) for s in symbols if len(s.lstrip("^")) < MIN_BARE_SYMBOL]
    options = []
    if bare:
        options.append(r"\$?(?:" + "|".join(bare) + ")")
    if dollar_only:
        options.append(r"\$(?:" + "|".join(dollar_only) + ")")
    literal = re.compile(_LEFT + "(?:" + "|".join(options) + ")" + _RIGHT)
    info = TICKER_UNIVERSE.get(ticker)
    if not info:
        return literal, None
    names = {_fold(str(info["name"])), *(_fold(a) for a in info["aliases"])}
    alias = re.compile(_LEFT + "(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + ")" + _RIGHT)
    return literal, alias


def extract_tickers(text: str, universe: list[str] | None = None) -> list[str]:
    """Tickers mencionados en ``text`` (por símbolo o por nombre/alias de la empresa).

    Args:
        text: texto libre (título + resumen de una noticia, transcripción…).
        universe: tickers candidatos; por defecto, los de ``TICKER_UNIVERSE``. Los tickers que no
            están en el universo solo se detectan por símbolo literal.

    Returns:
        Tickers encontrados, sin repetir, en el orden del universo.
    """
    if not text:
        return []
    candidates = [normalize_ticker(t) for t in universe] if universe else list(TICKER_UNIVERSE)
    folded = _fold(text)
    found: list[str] = []
    for ticker in dict.fromkeys(candidates):
        literal, alias = _patterns(ticker)
        if literal.search(text) or (alias is not None and alias.search(folded)):
            found.append(ticker)
    return found


def filter_by_tickers(
    news: list[NewsItem], tickers: list[str], min_items: int = 3
) -> list[NewsItem]:
    """Devuelve solo las noticias relevantes para ``tickers`` (y rellena ``NewsItem.tickers``).

    Cada noticia conserva sus tickers y suma los detectados en título + resumen. No muta la
    entrada (devuelve copias). Si quedan menos de ``min_items`` noticias, se completa con
    noticias generales de mercado (``MARKET_INDEX_TICKERS``). Se respeta el orden original.

    Si ``tickers`` está vacío, devuelve todas (briefing general de mercado).
    """
    wanted = {normalize_ticker(t) for t in tickers if str(t).strip()}
    enriched: list[NewsItem] = []
    for item in news:
        found = list(dict.fromkeys([*item.tickers, *extract_tickers(f"{item.title} {item.summary}")]))
        enriched.append(item.model_copy(update={"tickers": found}))
    if not wanted:
        return enriched

    keep = [bool(wanted & set(item.tickers)) for item in enriched]
    if sum(keep) < min_items:
        for i, item in enumerate(enriched):
            if sum(keep) >= min_items:
                break
            if not keep[i] and set(item.tickers) & set(MARKET_INDEX_TICKERS):
                keep[i] = True
    return [item for item, k in zip(enriched, keep, strict=True) if k]
