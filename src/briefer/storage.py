"""Persistencia de briefings: ``data/outputs/<id>/briefing.json`` + ficheros generados.

Transversal (lo usa el pipeline y la página "Histórico"). Cada briefing vive en su carpeta
con el audio, SRT, gráficos, portada y vídeo; ``briefing.json`` es ``Briefing.model_dump_json``.
``data/outputs/`` está en ``.gitignore``.

Portabilidad: al guardar, las rutas de ficheros que están **dentro** de la carpeta del briefing
se escriben relativas a ella y con ``/`` (``charts/AAPL_price.png``), así la carpeta se puede
mover entre máquinas o montar en Docker. Al cargar se vuelven a resolver contra la carpeta en
la que está el JSON. Las rutas de fuera de la carpeta se guardan tal cual (absolutas).
Con esto, ``load_briefing(save_briefing(b)) == b`` cuando la carpeta no se ha movido.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from briefer.schemas import Briefing

BRIEFING_FILE = "briefing.json"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _base(base_dir: Path | None) -> Path:
    if base_dir is not None:
        return Path(base_dir)
    from briefer.config import get_settings

    return get_settings().output_path


def _check_id(briefing_id: str) -> str:
    """Rechaza ids con separadores o ``..`` (evita escribir fuera de ``data/outputs``)."""
    if not briefing_id or not _ID_RE.match(briefing_id) or ".." in briefing_id:
        raise ValueError(f"Id de briefing no válido: {briefing_id!r}")
    return briefing_id


def briefing_dir(briefing_id: str, base_dir: Path | None = None) -> Path:
    """Carpeta del briefing (la crea si no existe)."""
    d = _base(base_dir) / _check_id(briefing_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Rutas relativas <-> absolutas ──────────────────────────────────────────────────

# Campos de ``Briefing.model_dump(mode="json")`` que son rutas a ficheros.
_PathFn = Callable[[str], str]


def _map_paths(data: dict[str, Any], fn: _PathFn) -> dict[str, Any]:
    """Aplica ``fn`` a todas las rutas de ficheros del dict serializado (in situ)."""
    for key in ("audio", "video"):
        if data.get(key) and data[key].get("path"):
            data[key]["path"] = fn(data[key]["path"])
    if data.get("transcript") and data["transcript"].get("srt_path"):
        data["transcript"]["srt_path"] = fn(data["transcript"]["srt_path"])
    for chart in data.get("charts") or []:
        if chart.get("path"):
            chart["path"] = fn(chart["path"])
    if data.get("cover_path"):
        data["cover_path"] = fn(data["cover_path"])
    return data


def _to_relative(folder: Path) -> _PathFn:
    root = folder.resolve()

    def fn(value: str) -> str:
        p = Path(value)
        if not p.is_absolute():
            return PurePosixPath(*p.parts).as_posix()
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            return value  # fuera de la carpeta del briefing: se deja absoluta
        return PurePosixPath(*rel.parts).as_posix()

    return fn


def _to_absolute(folder: Path) -> _PathFn:
    def fn(value: str) -> str:
        p = Path(value)
        return str(p if p.is_absolute() else folder.joinpath(*PurePosixPath(value).parts))

    return fn


# ── API ────────────────────────────────────────────────────────────────────────────


def save_briefing(briefing: Briefing, base_dir: Path | None = None) -> Path:
    """Guarda ``briefing.json`` en su carpeta y devuelve la ruta del JSON.

    Escritura atómica (fichero temporal + ``replace``) en UTF-8 con sangría 2. No modifica el
    objeto ``briefing`` recibido.
    """
    folder = briefing_dir(briefing.id, base_dir)
    data = _map_paths(briefing.model_dump(mode="json"), _to_relative(folder))
    target = folder / BRIEFING_FILE
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def _resolve_json_path(path_or_id: Path | str, base_dir: Path | None) -> Path:
    p = Path(path_or_id)
    if p.is_dir():
        return p / BRIEFING_FILE
    if p.suffix.lower() == ".json" or p.exists():
        return p
    return _base(base_dir) / _check_id(str(path_or_id)) / BRIEFING_FILE


def load_briefing(path_or_id: Path | str, base_dir: Path | None = None) -> Briefing:
    """Carga un briefing por ruta a ``briefing.json``, por su carpeta o por id.

    Las rutas relativas del JSON se resuelven contra la carpeta en la que está el fichero.
    """
    path = _resolve_json_path(path_or_id, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"No existe el briefing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Briefing.model_validate(_map_paths(data, _to_absolute(path.parent)))


def list_briefings(base_dir: Path | None = None, limit: int = 50) -> list[Path]:
    """Rutas a ``briefing.json`` ordenadas de más reciente a más antiguo.

    Los ids empiezan por ``YYYYMMDD-HHMMSS``, así que el orden alfabético inverso es el
    cronológico inverso. Si la carpeta base no existe devuelve ``[]``.
    """
    base = _base(base_dir)
    if not base.is_dir():
        return []
    paths = [p for p in base.glob(f"*/{BRIEFING_FILE}") if p.is_file()]
    return sorted(paths, key=lambda p: p.parent.name, reverse=True)[: max(0, limit)]


__all__ = ["BRIEFING_FILE", "briefing_dir", "list_briefings", "load_briefing", "save_briefing"]
