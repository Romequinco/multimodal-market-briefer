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

import csv
import re
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from briefer.schemas import NewsItem

# Universo para la UI y la detección en texto (ticker de Yahoo Finance -> nombre y alias).
# Incluye los valores de la cartera y noticias de ejemplo, más algunos IBEX/EE. UU. habituales.
# El buscador de la UI usa además el catálogo ampliado (``CATALOG``, ver abajo).
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

#: Catálogo ampliado para el **buscador** de la UI y para normalizar/nombrar lo que elige el usuario
#: (IBEX 35, grandes europeos, EE. UU., índices, materias primas, cripto y divisas), validado con
#: yfinance. Vive aparte de ``TICKER_UNIVERSE`` a propósito: el universo se usa para etiquetar *todas*
#: las noticias (``news``, ``speech``), y meter ahí cientos de nombres daría falsos positivos.
CATALOG_FILE = Path(__file__).with_name("tickers_catalogo.csv")
#: Mercado de cada ticker del catálogo (``IBEX``, ``EUROPA``, ``EEUU``, ``INDICE``…), para la UI.
CATALOG_MARKET: dict[str, str] = {}


def _load_catalog(path: Path = CATALOG_FILE) -> dict[str, dict[str, list[str] | str]]:
    """``TICKER_UNIVERSE`` + filas del CSV (las del universo conservan sus alias curados)."""
    catalog: dict[str, dict[str, list[str] | str]] = {t: dict(info) for t, info in TICKER_UNIVERSE.items()}
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                ticker = (row.get("ticker") or "").strip().upper()
                name = (row.get("name") or "").strip()
                if not ticker or not name:
                    continue
                CATALOG_MARKET.setdefault(ticker, (row.get("market") or "").strip().upper())
                if ticker in catalog:
                    continue
                aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
                catalog[ticker] = {"name": name, "aliases": aliases}
    except OSError:  # sin catálogo: solo el universo curado
        pass
    for ticker in MARKET_INDEX_TICKERS:
        CATALOG_MARKET.setdefault(ticker, "INDICE")
    return catalog


#: Universo curado + catálogo + lo que el usuario añade desde la búsqueda online (``register_ticker``).
CATALOG: dict[str, dict[str, list[str] | str]] = _load_catalog()

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
    """Índice ``clave plegada -> ticker`` con tickers, raíces, nombres y alias (universo primero)."""
    index: dict[str, str] = {}
    for ticker, info in [*TICKER_UNIVERSE.items(), *CATALOG.items()]:
        keys = [ticker, _root(ticker), str(info["name"]), *list(info["aliases"])]
        for key in keys:
            index.setdefault(_fold(key), ticker)
    return index


def ticker_info(ticker: str) -> dict[str, list[str] | str] | None:
    """``{name, aliases}`` del ticker en el universo o el catálogo; ``None`` si no se conoce."""
    return TICKER_UNIVERSE.get(ticker) or CATALOG.get(ticker)


def ticker_name(ticker: str) -> str:
    """Nombre de la empresa/activo (``"KO"`` -> ``"Coca-Cola"``); si no se conoce, el símbolo sin sufijo."""
    info = ticker_info(ticker)
    return str(info["name"]) if info else _root(ticker)


_CATALOG_LOCK = threading.Lock()


def register_ticker(ticker: str, name: str, market: str = "") -> str:
    """Añade al catálogo un ticker encontrado con la búsqueda online (nombre para noticias y la UI).

    Solo amplía el catálogo del proceso (no el ``TICKER_UNIVERSE`` que etiqueta todas las noticias) y
    nunca sobrescribe una entrada conocida. Devuelve el ticker normalizado (mayúsculas, sin espacios).
    """
    symbol = str(ticker).replace(" ", "").upper()
    clean_name = " ".join(str(name).split()) or _root(symbol)
    if not symbol:
        raise ValueError("Ticker vacío")
    with _CATALOG_LOCK:
        if symbol not in CATALOG:
            CATALOG[symbol] = {"name": clean_name, "aliases": []}
            if market:
                CATALOG_MARKET.setdefault(symbol, market.upper())
            _lookup.cache_clear()
            _patterns.cache_clear()
    return symbol


@dataclass(frozen=True)
class TickerMatch:
    """Resultado de búsqueda de un activo."""

    ticker: str
    name: str
    market: str = ""
    source: str = "catálogo"  # "catálogo" | "Yahoo Finance"


def search_catalog(query: str, limit: int = 12) -> list[TickerMatch]:
    """Busca en el catálogo por ticker, nombre o alias (sin tildes ni mayúsculas).

    Orden: ticker exacto, nombre/alias que empieza por la consulta, palabra que empieza por ella y,
    al final, coincidencia en cualquier parte.
    """
    q = _fold(" ".join(str(query).split()))
    if not q:
        return []
    scored: list[tuple[int, int, str]] = []
    for i, (ticker, info) in enumerate(CATALOG.items()):
        keys = [_fold(ticker), _fold(_root(ticker)), _fold(str(info["name"])), *(_fold(a) for a in info["aliases"])]
        if q in keys[:2]:
            rank = 0
        elif any(k.startswith(q) for k in keys):
            rank = 1
        elif any(w.startswith(q) for k in keys for w in re.split(r"[\s\-./&]+", k)):
            rank = 2
        elif any(q in k for k in keys):
            rank = 3
        else:
            continue
        scored.append((rank, i, ticker))
    scored.sort()
    return [TickerMatch(t, str(CATALOG[t]["name"]), CATALOG_MARKET.get(t, "")) for _, _, t in scored[:limit]]


#: Tipos de Yahoo que tienen sentido en un briefing (acciones, ETF, índices, cripto, divisas). Los futuros
#: quedan fuera (Yahoo devuelve futuros sobre acciones sueltas); oro, petróleo, etc. están en el catálogo.
_YAHOO_TYPES = {"EQUITY", "ETF", "INDEX", "CRYPTOCURRENCY", "CURRENCY", "MUTUALFUND"}


def search_online(query: str, limit: int = 8, timeout: float = 8.0) -> list[TickerMatch]:
    """Busca cualquier activo en Yahoo Finance (gratis, sin clave; necesita red).

    Raises:
        RuntimeError: si la búsqueda falla (sin red, Yahoo no responde…); mensaje apto para la UI.
    """
    q = " ".join(str(query).split())
    if not q:
        return []
    try:
        import yfinance as yf

        quotes = yf.Search(q, max_results=limit * 2, news_count=0, timeout=timeout).quotes or []
    except Exception as exc:  # noqa: BLE001 - red, cambios de la API de Yahoo…
        raise RuntimeError("No se pudo buscar en Yahoo Finance ahora mismo; prueba de nuevo.") from exc
    out: list[TickerMatch] = []
    for quote in quotes:
        symbol = str(quote.get("symbol") or "").strip().upper()
        kind = str(quote.get("quoteType") or "").upper()
        if not symbol or (kind and kind not in _YAHOO_TYPES):
            continue
        name = str(quote.get("shortname") or quote.get("longname") or symbol).strip()
        market = str(quote.get("exchDisp") or quote.get("exchange") or "").strip()
        out.append(TickerMatch(symbol, name, market, "Yahoo Finance"))
        if len(out) >= limit:
            break
    return out


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
    info = ticker_info(ticker)
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
