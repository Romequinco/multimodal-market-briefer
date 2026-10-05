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


# ── Briefing destacado (portada de la app) ─────────────────────────────────────────

DEMO_BRIEFING_DIRNAME = "demo_briefing"


def demo_briefing_dir(samples_dir: Path | None = None) -> Path:
    """Carpeta del briefing pregenerado versionado: ``data/samples/demo_briefing/`` (no la crea)."""
    if samples_dir is None:
        from briefer.config import get_settings

        samples_dir = get_settings().samples_path
    return Path(samples_dir) / DEMO_BRIEFING_DIRNAME


def load_demo_briefing(samples_dir: Path | None = None) -> Briefing | None:
    """Carga el briefing pregenerado, o ``None`` si aún no existe (la UI muestra un aviso).

    Raises:
        ValueError / pydantic.ValidationError: si existe pero el JSON está corrupto o no cumple
            el contrato (mejor fallar alto que enseñar un briefing roto).
    """
    folder = demo_briefing_dir(samples_dir)
    if not (folder / BRIEFING_FILE).is_file():
        return None
    return load_briefing(folder)


def latest_briefing(base_dir: Path | None = None, max_tries: int = 5) -> Briefing | None:
    """El briefing guardado más reciente que se pueda cargar (salta JSON corruptos), o ``None``."""
    for path in list_briefings(base_dir, limit=max_tries):
        try:
            return load_briefing(path)
        except Exception:  # un JSON a medias no debe tapar a los anteriores
            continue
    return None


def load_featured_briefing(
    base_dir: Path | None = None, samples_dir: Path | None = None
) -> tuple[Briefing, str] | None:
    """Briefing para la portada: el último guardado y, si no hay, el pregenerado.

    Returns:
        ``(briefing, origen)`` con origen ``"guardado"`` o ``"pregenerado"``; ``None`` si no hay
        ninguno (la portada lo explica y ofrece generar uno).
    """
    latest = latest_briefing(base_dir)
    if latest is not None:
        return latest, "guardado"
    try:
        demo = load_demo_briefing(samples_dir)
    except Exception:
        demo = None
    return (demo, "pregenerado") if demo is not None else None


def _copy_into(src: Path | None, folder: Path, rel: str) -> Path | None:
    """Copia ``src`` a ``folder/rel`` si existe y devuelve la ruta nueva (``None`` si no existe)."""
    if src is None or not Path(src).is_file():
        return None
    import shutil

    dest = folder / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if Path(src).resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def export_briefing(briefing: Briefing, dest_dir: Path) -> Path:
    """Copia un briefing y sus ficheros a ``dest_dir`` (autocontenido) y escribe su JSON.

    Pensado para crear ``data/samples/demo_briefing/`` a partir de un briefing real:
    ``export_briefing(b, demo_briefing_dir())``. Copia audio, SRT, gráficos (``charts/``),
    portada y vídeo con nombres estables; las rutas del JSON quedan relativas. Los ficheros que no
    existan se quitan del briefing exportado (sin enlaces rotos). Devuelve la ruta del JSON.
    """
    folder = Path(dest_dir)
    folder.mkdir(parents=True, exist_ok=True)
    update: dict[str, Any] = {}
    if briefing.audio is not None:
        new = _copy_into(briefing.audio.path, folder, "podcast" + Path(briefing.audio.path).suffix)
        update["audio"] = briefing.audio.model_copy(update={"path": new}) if new else None
    if briefing.transcript is not None:
        srt = _copy_into(briefing.transcript.srt_path, folder, "podcast.srt")
        update["transcript"] = briefing.transcript.model_copy(update={"srt_path": srt})
    charts = []
    for chart in briefing.charts:
        new = _copy_into(chart.path, folder, f"charts/{Path(chart.path).name}")
        if new:
            charts.append(chart.model_copy(update={"path": new}))
    update["charts"] = charts
    update["cover_path"] = _copy_into(briefing.cover_path, folder,
                                      "cover" + Path(briefing.cover_path).suffix) if briefing.cover_path else None
    if briefing.video is not None:
        new = _copy_into(briefing.video.path, folder, "video" + Path(briefing.video.path).suffix)
        update["video"] = briefing.video.model_copy(update={"path": new}) if new else None
    exported = briefing.model_copy(update=update)
    data = _map_paths(exported.model_dump(mode="json"), _to_relative(folder))
    target = folder / BRIEFING_FILE
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


__all__ = [
    "BRIEFING_FILE",
    "DEMO_BRIEFING_DIRNAME",
    "briefing_dir",
    "demo_briefing_dir",
    "export_briefing",
    "latest_briefing",
    "list_briefings",
    "load_briefing",
    "load_demo_briefing",
    "load_featured_briefing",
    "save_briefing",
]
