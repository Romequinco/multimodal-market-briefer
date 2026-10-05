"""Persistencia de briefings: ``data/outputs/<id>/briefing.json`` + ficheros generados.

Transversal (lo usa el pipeline y la página "Histórico"). Cada briefing vive en su carpeta
con el audio, SRT, gráficos, portada y vídeo; ``briefing.json`` es ``Briefing.model_dump_json``.
``data/outputs/`` está en ``.gitignore``.

Portabilidad: al guardar, las rutas de ficheros que están **dentro** de la carpeta del briefing
se escriben relativas a ella y con ``/`` (``charts/AAPL_price.png``), así la carpeta se puede
mover entre máquinas o montar en Docker. Al cargar se vuelven a resolver contra la carpeta en
la que está el JSON. Las rutas de fuera de la carpeta se guardan tal cual (absolutas).
Con esto, ``load_briefing(save_briefing(b)) == b`` cuando la carpeta no se ha movido.

Robustez (D2):

- Escrituras atómicas con temporal **único** por proceso e hilo (dos guardados simultáneos del
  mismo briefing no se pisan el ``.tmp``) y sin restos si la escritura falla.
- ``load_briefing`` acepta JSON con BOM (editado con el Bloc de notas) y briefings de **otra
  versión** del contrato: si la validación estricta falla solo por campos desconocidos (un
  ``briefing.json`` escrito por una versión más nueva), se descartan esos campos con un aviso en el
  log y se carga el resto. Un JSON corrupto o al que le falten campos obligatorios sigue fallando.
- ``list_briefings`` ordena por nombre de carpeta y solo comprueba en disco las ``limit`` primeras
  (rápido con cientos de briefings); ``briefing_summaries`` da filas ligeras para el histórico sin
  validar el modelo completo.
- ``export_briefing_zip`` empaqueta un briefing autocontenido (rutas relativas) en un ZIP portable.

Privacidad (RGPD): la cartera del usuario **no se persiste**. ``save_briefing`` y
``export_briefing`` escriben ``context.portfolio = null`` y omiten el gráfico ``portfolio_pie``
(pesos); los tickers de la cartera sí quedan en ``context.tickers`` (son el filtro del briefing).
El objeto en memoria no se toca: la sesión que lo generó sigue viendo su cartera.

Portada: ``latest_briefing`` / ``load_featured_briefing`` solo destacan briefings **reales**; uno
con algún paso simulado (``is_simulated_briefing``: mock, noticias de ejemplo, precios sintéticos o
guion de respaldo) se salta y, si no hay otro, se muestra el pregenerado.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
import types
import typing
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError

from briefer.logging_utils import get_logger
from briefer.schemas import Briefing

log = get_logger("storage")

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


def _write_json_atomic(target: Path, data: dict[str, Any]) -> Path:
    """Escribe ``data`` en ``target`` de forma atómica (temporal único + ``os.replace``)."""
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


#: Proveedores que indican contenido simulado (no real) en un ``StepMetric``.
SIMULATED_PROVIDERS = frozenset({"mock", "samples", "synthetic"})


def is_simulated_briefing(briefing: Briefing) -> bool:
    """``True`` si algún paso usó contenido simulado: proveedor ``mock``, noticias de
    ``data/samples``, precios sintéticos, guion de respaldo o cualquier caída a sustituto
    (``StepMetric.error`` que empieza por ``"Fallback a "``). Sin métricas -> ``False``.

    Criterio de la portada: solo se destaca un briefing 100 % real.
    """
    for m in briefing.metrics:
        if m.provider in SIMULATED_PROVIDERS or m.model == "fallback_script":
            return True
        if m.error and str(m.error).startswith("Fallback a "):
            return True
    return False


def _persistable(briefing: Briefing) -> Briefing:
    """Copia sin datos personales de la cartera (RGPD): ``context.portfolio=None`` y sin el gráfico
    ``portfolio_pie``. Los tickers de la cartera ya están en ``context.tickers``."""
    if briefing.context.portfolio is None and not any(c.kind == "portfolio_pie" for c in briefing.charts):
        return briefing
    return briefing.model_copy(
        update={
            "context": briefing.context.model_copy(update={"portfolio": None}),
            "charts": [c for c in briefing.charts if c.kind != "portfolio_pie"],
        }
    )


def save_briefing(briefing: Briefing, base_dir: Path | None = None) -> Path:
    """Guarda ``briefing.json`` en su carpeta y devuelve la ruta del JSON.

    Escritura atómica (fichero temporal + ``replace``) en UTF-8 con sangría 2. No modifica el
    objeto ``briefing`` recibido. La cartera no se persiste (``context.portfolio`` -> ``null`` y
    sin gráfico ``portfolio_pie``; ver el docstring del módulo).
    """
    folder = briefing_dir(briefing.id, base_dir)
    data = _map_paths(_persistable(briefing).model_dump(mode="json"), _to_relative(folder))
    return _write_json_atomic(folder / BRIEFING_FILE, data)


def _resolve_json_path(path_or_id: Path | str, base_dir: Path | None) -> Path:
    p = Path(path_or_id)
    if p.is_dir():
        return p / BRIEFING_FILE
    if p.suffix.lower() == ".json" or p.exists():
        return p
    return _base(base_dir) / _check_id(str(path_or_id)) / BRIEFING_FILE


def _model_types(annotation: Any) -> list[type[BaseModel]]:
    """Modelos Pydantic que aparecen en una anotación (``X``, ``X | None``, ``list[X]``…)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    origin = typing.get_origin(annotation)
    if origin is not None or isinstance(annotation, types.UnionType):
        for arg in typing.get_args(annotation):
            found += _model_types(arg)
    return found


def prune_unknown_fields(data: Any, model: type[BaseModel], dropped: list[str] | None = None,
                         prefix: str = "") -> Any:
    """Quita (recursivamente) las claves que ``model`` no conoce; anota sus rutas en ``dropped``.

    Sirve para leer un ``briefing.json`` escrito por una versión **más nueva** del contrato con
    modelos ``extra="forbid"``. No inventa campos que falten: eso sigue fallando al validar.
    """
    if not isinstance(data, dict):
        return data
    out: dict[str, Any] = {}
    for key, value in data.items():
        info = model.model_fields.get(key)
        if info is None:
            if dropped is not None:
                dropped.append(prefix + key)
            continue
        subs = _model_types(info.annotation)
        if subs and isinstance(value, dict):
            value = prune_unknown_fields(value, subs[0], dropped, f"{prefix}{key}.")
        elif subs and isinstance(value, list):
            value = [prune_unknown_fields(v, subs[0], dropped, f"{prefix}{key}[].") for v in value]
        out[key] = value
    return out


def _only_extra_errors(exc: ValidationError) -> bool:
    return all(err.get("type") == "extra_forbidden" for err in exc.errors())


def load_briefing(path_or_id: Path | str, base_dir: Path | None = None) -> Briefing:
    """Carga un briefing por ruta a ``briefing.json``, por su carpeta o por id.

    Las rutas relativas del JSON se resuelven contra la carpeta en la que está el fichero. Si el
    JSON trae campos que este contrato no conoce (escrito por una versión más nueva), se ignoran
    con un aviso en el log.

    Raises:
        FileNotFoundError: no existe. ``ValueError`` (JSON corrupto) /
        ``pydantic.ValidationError`` (faltan campos o tienen otro tipo).
    """
    path = _resolve_json_path(path_or_id, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"No existe el briefing: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))  # -sig: tolera el BOM de Windows
    if not isinstance(data, dict):
        raise ValueError(f"{path} no contiene un briefing (se esperaba un objeto JSON)")
    data = _map_paths(data, _to_absolute(path.parent))
    try:
        return Briefing.model_validate(data)
    except ValidationError as exc:
        if not _only_extra_errors(exc):
            raise
        dropped: list[str] = []
        briefing = Briefing.model_validate(prune_unknown_fields(data, Briefing, dropped))
        log.warning("%s: campos desconocidos ignorados (otra versión del contrato): %s",
                    path, ", ".join(sorted(set(dropped))))
        return briefing


def list_briefings(base_dir: Path | None = None, limit: int = 50) -> list[Path]:
    """Rutas a ``briefing.json`` ordenadas de más reciente a más antiguo.

    Los ids empiezan por ``YYYYMMDD-HHMMSS``, así que el orden alfabético inverso es el
    cronológico inverso. Si la carpeta base no existe devuelve ``[]``.
    """
    base = _base(base_dir)
    if not base.is_dir() or limit <= 0:
        return []
    try:
        names = sorted((e.name for e in os.scandir(base) if e.is_dir()), reverse=True)
    except OSError:
        return []
    paths: list[Path] = []
    for name in names:  # solo se comprueban en disco las carpetas necesarias
        candidate = base / name / BRIEFING_FILE
        if candidate.is_file():
            paths.append(candidate)
            if len(paths) >= limit:
                break
    return paths


@dataclass(frozen=True)
class BriefingSummary:
    """Fila ligera del histórico (sin validar el ``Briefing`` completo)."""

    path: Path
    id: str
    created_at: str = ""
    headline: str = ""
    tickers: list[str] = field(default_factory=list)
    duration_s: float | None = None
    has_audio: bool = False
    n_charts: int = 0
    demo: bool = False          # todos los pasos de IA en mock (briefing de demostración)
    error: str | None = None    # JSON ilegible: la fila se muestra marcada en lugar de romper la lista


def _summary_from(path: Path) -> BriefingSummary:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("no es un objeto JSON")
        audio = data.get("audio") or {}
        analysis = data.get("analysis") or {}
        context = data.get("context") or {}
        metrics = data.get("metrics") or []
        ai_steps = [m for m in metrics if isinstance(m, dict) and str(m.get("step", "")).startswith("agents.")]
        audio_path = audio.get("path")
        has_audio = bool(audio_path) and (path.parent / str(audio_path)).is_file() if audio_path else False
        return BriefingSummary(
            path=path,
            id=str(data.get("id") or path.parent.name),
            created_at=str(data.get("created_at") or ""),
            headline=str(analysis.get("headline") or ""),
            tickers=[str(t) for t in context.get("tickers") or []],
            duration_s=float(audio["duration_s"]) if audio.get("duration_s") is not None else None,
            has_audio=has_audio,
            n_charts=len(data.get("charts") or []),
            demo=bool(ai_steps) and all(m.get("provider") == "mock" for m in ai_steps),
        )
    except Exception as exc:  # noqa: BLE001 - una fila rota no debe tumbar el histórico
        return BriefingSummary(path=path, id=path.parent.name, error=f"{type(exc).__name__}: {exc}")


def briefing_summaries(base_dir: Path | None = None, limit: int = 50) -> list[BriefingSummary]:
    """Resumen de los ``limit`` briefings más recientes para listarlos deprisa.

    Lee cada JSON con ``json`` (sin Pydantic) y extrae id, fecha, titular, tickers, duración del
    audio y nº de gráficos. Un JSON corrupto aparece con ``error`` relleno en lugar de lanzar.
    """
    return [_summary_from(p) for p in list_briefings(base_dir, limit=limit)]


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


def latest_briefing(
    base_dir: Path | None = None, max_tries: int = 20, *, include_simulated: bool = False
) -> Briefing | None:
    """El briefing guardado más reciente que se pueda cargar, o ``None``.

    Salta JSON corruptos y, salvo ``include_simulated=True``, los briefings con pasos simulados
    (``is_simulated_briefing``: demo offline, demo sin claves, fallbacks). Mira como mucho los
    ``max_tries`` más recientes.
    """
    for path in list_briefings(base_dir, limit=max_tries):
        try:
            briefing = load_briefing(path)
        except Exception:  # un JSON a medias no debe tapar a los anteriores
            continue
        if include_simulated or not is_simulated_briefing(briefing):
            return briefing
    return None


def load_featured_briefing(
    base_dir: Path | None = None, samples_dir: Path | None = None
) -> tuple[Briefing, str] | None:
    """Briefing para la portada: el último guardado **real** y, si no hay, el pregenerado.

    Los briefings guardados con pasos simulados (``is_simulated_briefing``) no se destacan: un
    ensayo en «Demo offline» no puede tapar el pregenerado real.

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
    folder = Path(dest_dir).resolve()  # relativa -> absoluta: si no, las rutas del JSON no serían relativas a la carpeta
    folder.mkdir(parents=True, exist_ok=True)
    briefing = _persistable(briefing)  # RGPD: sin cartera ni gráfico de pesos
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
    return _write_json_atomic(folder / BRIEFING_FILE, data)


def export_briefing_zip(briefing: Briefing) -> bytes:
    """ZIP portable de un briefing: ``<id>/briefing.json`` (rutas relativas) + audio, SRT, gráficos…

    Usa ``export_briefing`` en una carpeta temporal que se borra al terminar (no deja restos). El ZIP
    se puede descomprimir en ``data/outputs/`` de otra máquina y abrirse en el histórico.
    """
    _check_id(briefing.id)
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="briefer_export_") as tmp:
        folder = Path(tmp) / briefing.id
        export_briefing(briefing, folder)
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file in sorted(folder.rglob("*")):
                if file.is_file():
                    zf.write(file, PurePosixPath(briefing.id, *file.relative_to(folder).parts).as_posix())
    return buffer.getvalue()


__all__ = [
    "BRIEFING_FILE",
    "BriefingSummary",
    "briefing_summaries",
    "export_briefing_zip",
    "prune_unknown_fields",
    "DEMO_BRIEFING_DIRNAME",
    "briefing_dir",
    "demo_briefing_dir",
    "export_briefing",
    "is_simulated_briefing",
    "latest_briefing",
    "list_briefings",
    "load_briefing",
    "load_demo_briefing",
    "load_featured_briefing",
    "save_briefing",
]
