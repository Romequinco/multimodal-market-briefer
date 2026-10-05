"""Carga de la cartera del usuario desde CSV.

Carril A. Entrada: CSV con columnas ``ticker`` y ``weight`` y/o ``quantity`` (ver
``data/samples/portfolio_ejemplo.csv``). Salida: ``Portfolio``.

RGPD: la cartera es un dato personal/financiero. Se procesa en memoria durante la sesión;
no se guarda en disco ni se envía a terceros salvo los tickers necesarios para el briefing
(TODO: documentar en docs/04 y pedir consentimiento explícito si se persiste).
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from briefer.schemas import Portfolio


def load_portfolio_csv(source: Path | BinaryIO | str, name: str = "Mi cartera") -> Portfolio:
    """Lee un CSV (ruta o fichero subido por Streamlit) y devuelve un ``Portfolio`` validado."""
    # TODO:
    # 1. pandas.read_csv(source, sep=None, engine="python") para aceptar "," y ";".
    # 2. Normalizar cabeceras (minúsculas, sin espacios); aceptar sinónimos
    #    (symbol/ticker, peso/weight, cantidad/quantity).
    # 3. Pesos en % (suman ~100) -> dividir entre 100; validar que suman ~1 (tolerancia 2 %).
    # 4. Position(ticker=normalize_ticker(...), weight=..., quantity=...).
    # Casos borde: decimales con coma ("12,5"), filas vacías, tickers duplicados (sumar),
    # CSV sin columna ticker -> ValueError con mensaje para la UI.
    raise NotImplementedError("load_portfolio_csv: pendiente (carril A)")


def portfolio_tickers(portfolio: Portfolio) -> list[str]:
    """Tickers únicos de la cartera, ordenados por peso descendente."""
    # TODO: ordenar por weight (None al final) y quitar duplicados conservando orden.
    raise NotImplementedError("portfolio_tickers: pendiente (carril A)")
