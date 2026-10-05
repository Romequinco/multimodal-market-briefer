"""Caché diaria en disco para las entradas que requieren red (noticias y precios).

Carril A. Objetivo: que una segunda ejecución el mismo día (demo, reintentos, varias pruebas
desde la UI) no vuelva a llamar a Yahoo/Google News. Cada entrada es un JSON en
``settings.cache_path`` (``BRIEFER_CACHE_DIR``, por defecto ``data/cache/``) con nombre
``<fuente>_<clave>_<YYYYMMDD>.json``; la fecha (local) forma parte de la clave, así que al día
siguiente la entrada deja de usarse sola. Las entradas de días anteriores se pueden borrar con
``purge_old``.

La caché es «best effort»: un fichero corrupto o un error de escritura solo generan un aviso
en el log; nunca rompen la ingesta.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from briefer.config import get_settings
from briefer.logging_utils import get_logger

log = get_logger("ingest.cache")

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def cache_dir() -> Path:
    """Directorio de caché (``settings.cache_path``); se crea si no existe."""
    path = get_settings().cache_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(*parts: object) -> str:
    """Clave corta y estable a partir de varias partes (hash md5 de 12 caracteres)."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def cache_file(source: str, key: str, day: date | None = None) -> Path:
    """Ruta del fichero de caché para ``source`` + ``key`` + día (por defecto, hoy)."""
    day = day or date.today()
    name = f"{_SAFE.sub('_', source)}_{_SAFE.sub('_', key)}_{day:%Y%m%d}.json"
    return cache_dir() / name


def read_cache(source: str, key: str, day: date | None = None) -> Any | None:
    """Contenido JSON cacheado o ``None`` si no existe o está dañado."""
    path = cache_file(source, key, day)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Caché ilegible (%s): %s; se ignora", path.name, exc)
        return None


def write_cache(source: str, key: str, data: Any, day: date | None = None) -> None:
    """Guarda ``data`` (serializable a JSON) de forma atómica; los errores solo se registran."""
    try:
        path = cache_file(source, key, day)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("No se pudo escribir la caché %s/%s: %s", source, key, exc)


def purge_old(keep_days: int = 1) -> int:
    """Borra entradas de caché de más de ``keep_days`` días. Devuelve cuántas se borraron."""
    today = date.today()
    removed = 0
    for path in cache_dir().glob("*_*.json"):
        match = re.search(r"_(\d{8})\.json$", path.name)
        if not match:
            continue
        try:
            day = date(int(match[1][:4]), int(match[1][4:6]), int(match[1][6:]))
        except ValueError:
            continue
        if (today - day).days >= keep_days:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed
