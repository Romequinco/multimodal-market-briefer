"""Persistencia de briefings: ``data/outputs/<id>/briefing.json`` + ficheros generados.

Transversal (lo usa el pipeline y la página "Histórico"). Cada briefing vive en su carpeta
con el audio, SRT, gráficos, portada y vídeo; ``briefing.json`` es ``Briefing.model_dump_json``.
``data/outputs/`` está en ``.gitignore``.
"""

from __future__ import annotations

from pathlib import Path

from briefer.schemas import Briefing


def briefing_dir(briefing_id: str, base_dir: Path | None = None) -> Path:
    """Carpeta del briefing (la crea si no existe)."""
    # TODO: base = base_dir or get_settings().output_path; d = base / briefing_id;
    # d.mkdir(parents=True, exist_ok=True); return d. Validar que briefing_id no contiene
    # separadores de ruta ("..", "/", "\\") para evitar path traversal.
    raise NotImplementedError("briefing_dir: pendiente")


def save_briefing(briefing: Briefing, base_dir: Path | None = None) -> Path:
    """Guarda ``briefing.json`` en su carpeta y devuelve la ruta del JSON."""
    # TODO: rutas de assets relativas a la carpeta del briefing (portabilidad entre
    # máquinas/Docker); escribir en UTF-8 con indent=2; escritura atómica (tmp + replace).
    raise NotImplementedError("save_briefing: pendiente")


def load_briefing(path_or_id: Path | str, base_dir: Path | None = None) -> Briefing:
    """Carga un briefing por ruta a ``briefing.json`` o por id."""
    # TODO: Briefing.model_validate_json(path.read_text("utf-8")); resolver rutas relativas.
    raise NotImplementedError("load_briefing: pendiente")


def list_briefings(base_dir: Path | None = None, limit: int = 50) -> list[Path]:
    """Rutas a ``briefing.json`` ordenadas de más reciente a más antiguo."""
    # TODO: sorted(base.glob("*/briefing.json"), reverse=True)[:limit] (los ids empiezan
    # por fecha, así que el orden alfabético es cronológico).
    raise NotImplementedError("list_briefings: pendiente")
