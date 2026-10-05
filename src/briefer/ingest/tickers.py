"""Universo de tickers, normalización y filtrado de noticias por tickers/cartera.

Carril A. Entrada: ``list[NewsItem]`` + tickers del usuario. Salida: ``list[NewsItem]``
relevantes (las que mencionan alguno de los tickers o el nombre de la empresa).
"""

from __future__ import annotations

from briefer.schemas import NewsItem

# Universo mínimo para la UI (ticker de Yahoo Finance -> nombre y alias para buscar en texto).
# TODO: ampliar (IBEX 35 completo) o cargar desde CSV en data/samples.
TICKER_UNIVERSE: dict[str, dict[str, list[str] | str]] = {
    "SAN.MC": {"name": "Banco Santander", "aliases": ["Santander"]},
    "BBVA.MC": {"name": "BBVA", "aliases": ["BBVA"]},
    "ITX.MC": {"name": "Inditex", "aliases": ["Inditex", "Zara"]},
    "IBE.MC": {"name": "Iberdrola", "aliases": ["Iberdrola"]},
    "TEF.MC": {"name": "Telefónica", "aliases": ["Telefónica", "Telefonica"]},
    "REP.MC": {"name": "Repsol", "aliases": ["Repsol"]},
    "AAPL": {"name": "Apple", "aliases": ["Apple", "iPhone"]},
    "MSFT": {"name": "Microsoft", "aliases": ["Microsoft"]},
    "NVDA": {"name": "NVIDIA", "aliases": ["Nvidia", "NVIDIA"]},
    "AMZN": {"name": "Amazon", "aliases": ["Amazon"]},
    "^IBEX": {"name": "IBEX 35", "aliases": ["Ibex", "IBEX 35"]},
    "^GSPC": {"name": "S&P 500", "aliases": ["S&P 500", "S&P"]},
}


def normalize_ticker(raw: str) -> str:
    """Normaliza la entrada del usuario a ticker de Yahoo (``"santander"`` -> ``"SAN.MC"``)."""
    # TODO: strip + upper; si coincide con un ticker del universo, devolverlo; si coincide
    # (sin mayúsculas/tildes) con name o aliases, devolver su ticker; si no, devolver raw.upper().
    raise NotImplementedError("normalize_ticker: pendiente (carril A)")


def extract_tickers(text: str, universe: list[str] | None = None) -> list[str]:
    """Tickers mencionados en ``text`` (por símbolo o por nombre/alias de la empresa)."""
    # TODO: regex con límites de palabra (\b) sobre símbolo sin sufijo (SAN) y alias;
    # ignorar mayúsculas y tildes (unicodedata.normalize); evitar falsos positivos con
    # símbolos cortos que son palabras comunes (p. ej. "REP", "ITX" vale, "SAN" con cuidado).
    raise NotImplementedError("extract_tickers: pendiente (carril A)")


def filter_by_tickers(news: list[NewsItem], tickers: list[str]) -> list[NewsItem]:
    """Devuelve solo las noticias relevantes para ``tickers`` (y rellena ``NewsItem.tickers``).

    Si ``tickers`` está vacío, devuelve todas (briefing general de mercado).
    """
    # TODO:
    # 1. Para cada noticia: found = set(item.tickers) | set(extract_tickers(title + summary)).
    # 2. Conservar si found ∩ tickers no está vacío; actualizar item.tickers (copia, no mutar
    #    la entrada: item.model_copy(update=...)).
    # 3. Si quedan muy pocas (< 3), completar con noticias generales de mercado (^IBEX, ^GSPC).
    raise NotImplementedError("filter_by_tickers: pendiente (carril A)")
