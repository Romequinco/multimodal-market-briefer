"""Carga de la cartera del usuario desde CSV.

Carril A. Entrada: CSV con columnas ``ticker`` y ``weight`` y/o ``quantity`` (ver
``data/samples/portfolio_ejemplo.csv``). Salida: ``Portfolio``.

Formatos aceptados: separador ``,``, ``;``, tabulador o ``|``; decimales con punto o coma
(``12,5``); pesos en tanto por uno (suman ~1) o en porcentaje (suman ~100, también ``"20 %"``);
cabeceras en inglés o español (``symbol``/``ticker``/``valor``, ``peso``/``weight``,
``cantidad``/``quantity``/``acciones``). Las columnas extra (p. ej. ``name``) se ignoran.

RGPD: la cartera es un dato personal/financiero. Se procesa en memoria durante la sesión;
no se guarda en disco ni se envía a terceros salvo los tickers necesarios para el briefing
(TODO: documentar en docs/04 y pedir consentimiento explícito si se persiste).
"""

from __future__ import annotations

import csv
import io
import unicodedata
from pathlib import Path
from typing import BinaryIO

from briefer.ingest.tickers import normalize_ticker
from briefer.schemas import Portfolio, Position

# Tolerancia para la suma de pesos (en tanto por uno).
WEIGHT_TOLERANCE = 0.02

_COLUMN_ALIASES: dict[str, set[str]] = {
    "ticker": {"ticker", "tickers", "symbol", "simbolo", "valor", "codigo", "isin_ticker"},
    "weight": {"weight", "weights", "peso", "pesos", "ponderacion", "porcentaje", "pct", "%", "weight_pct"},
    "quantity": {"quantity", "qty", "cantidad", "acciones", "titulos", "shares", "unidades"},
}


def _norm_header(header: str) -> str:
    folded = unicodedata.normalize("NFKD", header or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return folded.strip().strip('"').lower().replace(" ", "_")


def _read_text(source: Path | BinaryIO | str) -> str:
    """Texto del CSV desde una ruta, un fichero binario/texto (p. ej. ``UploadedFile``) o un str.

    Un ``str`` con saltos de línea se interpreta como el contenido del CSV; si no, como ruta.
    """
    if isinstance(source, Path):
        raw: bytes | str = source.read_bytes()
    elif isinstance(source, str):
        raw = source if ("\n" in source or "\r" in source) else Path(source).read_bytes()
    elif hasattr(source, "read"):
        if hasattr(source, "seek"):
            source.seek(0)
        raw = source.read()
    else:
        raise TypeError(f"Fuente de cartera no soportada: {type(source).__name__}")
    if isinstance(raw, bytes):
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("No se puede leer el CSV: codificación no reconocida (usa UTF-8)")
    return raw.lstrip(chr(0xFEFF))  # BOM de Excel


def _parse_number(value: str | None, column: str, row_no: int) -> float | None:
    """``"12,5"``, ``"12.5"``, ``"20 %"``, ``"1.234,5"`` -> float; vacío -> ``None``."""
    text = (value or "").strip().replace("%", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:  # 1.234,5 (es) o 1,234.5 (en)
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"Fila {row_no}: valor no numérico en '{column}': {value!r}") from None
    if number < 0:
        raise ValueError(f"Fila {row_no}: '{column}' no puede ser negativo ({value!r})")
    return number


def load_portfolio_csv(source: Path | BinaryIO | str, name: str = "Mi cartera") -> Portfolio:
    """Lee un CSV (ruta o fichero subido por Streamlit) y devuelve un ``Portfolio`` validado.

    - Tickers normalizados con ``normalize_ticker`` (``"santander"`` -> ``"SAN.MC"``).
    - Tickers duplicados se fusionan sumando peso y cantidad.
    - Pesos en porcentaje (suman ~100) se pasan a tanto por uno; si hay pesos, deben sumar ~1
      (tolerancia ``WEIGHT_TOLERANCE``).

    Raises:
        ValueError: con un mensaje apto para la UI si el CSV está vacío, falta la columna de
            ticker, no hay ni pesos ni cantidades, hay valores no numéricos/negativos o los pesos
            no suman ~1 (ni ~100).
    """
    text = _read_text(source)
    if not text.strip():
        raise ValueError("El CSV de cartera está vacío")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        raise ValueError("El CSV de cartera está vacío")

    headers = [_norm_header(h) for h in rows[0]]
    columns: dict[str, int] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for i, h in enumerate(headers):
            if h in aliases:
                columns[canonical] = i
                break
    if "ticker" not in columns:
        raise ValueError(
            "El CSV necesita una columna 'ticker' (o 'symbol'/'valor'). Columnas encontradas: "
            + ", ".join(rows[0])
        )
    if "weight" not in columns and "quantity" not in columns:
        raise ValueError("El CSV necesita una columna 'weight' (peso) y/o 'quantity' (cantidad)")

    merged: dict[str, dict[str, float | None]] = {}
    for row_no, row in enumerate(rows[1:], start=2):
        cells = row + [""] * (len(headers) - len(row))
        raw_ticker = cells[columns["ticker"]].strip()
        if not raw_ticker:
            continue
        ticker = normalize_ticker(raw_ticker)
        weight = _parse_number(cells[columns["weight"]], "weight", row_no) if "weight" in columns else None
        quantity = _parse_number(cells[columns["quantity"]], "quantity", row_no) if "quantity" in columns else None
        acc = merged.setdefault(ticker, {"weight": None, "quantity": None})
        for key, value in (("weight", weight), ("quantity", quantity)):
            if value is not None:
                acc[key] = (acc[key] or 0.0) + value
    if not merged:
        raise ValueError("El CSV de cartera no tiene ninguna posición con ticker")

    weights = [v["weight"] for v in merged.values() if v["weight"] is not None]
    if weights:
        total = sum(weights)
        if abs(total - 100) <= 100 * WEIGHT_TOLERANCE:
            for v in merged.values():
                if v["weight"] is not None:
                    v["weight"] = v["weight"] / 100
            total /= 100
        if abs(total - 1) > WEIGHT_TOLERANCE:
            raise ValueError(
                f"Los pesos de la cartera suman {total:.4g}; deben sumar 1 (o 100 si son porcentajes)"
            )

    positions = [Position(ticker=t, weight=v["weight"], quantity=v["quantity"]) for t, v in merged.items()]
    return Portfolio(name=name, positions=positions)


def portfolio_tickers(portfolio: Portfolio) -> list[str]:
    """Tickers únicos de la cartera, ordenados por peso descendente (sin peso, al final)."""
    ordered = sorted(
        portfolio.positions,
        key=lambda p: (p.weight is None, -(p.weight or 0.0)),
    )
    return list(dict.fromkeys(p.ticker for p in ordered))
