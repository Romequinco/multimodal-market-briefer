"""Utilidades comunes de los tests de la UI (AppTest, sin red). No es un módulo de tests.

La app (rediseño «Tres pestañas, cero sidebar») arranca en ``app/main.py`` → ``components.shell.run_app``
con tres vistas (``views/hoy.py``, ``views/preguntar.py``, ``views/archivo.py``). Las vistas se pueden
ejecutar solas con ``AppTest.from_file`` (el modo sale de ``shell.current_mode``: el demo por defecto)
y el cuerpo del diálogo «Nuevo briefing» con :func:`form_app` (``new_briefing_form`` sin diálogo:
``AppTest`` no reproduce los reruns parciales de un ``st.dialog``).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from briefer import pipeline, storage
from briefer.config import reset_settings_cache

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from streamlit.testing.v1 import AppTest  # noqa: E402

TIMEOUT = 60
MAIN = "main.py"
HOY = "views/hoy.py"
ASK = "views/preguntar.py"
ARCHIVE = "views/archivo.py"
FORM_KEY = "t"


def app(name: str) -> AppTest:
    """``AppTest`` de ``app/<name>`` (``main.py`` o una vista)."""
    return AppTest.from_file(str(APP_DIR / name), default_timeout=TIMEOUT)


def _form_script(app_dir: str, key: str) -> None:
    import sys

    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from components.new_briefing import new_briefing_form

    new_briefing_form(key=key)


def form_app(key: str = FORM_KEY) -> AppTest:
    """``AppTest`` del cuerpo del diálogo «Nuevo briefing» (``new_briefing_form(key=key)``)."""
    return AppTest.from_function(_form_script, args=(str(APP_DIR), key), default_timeout=TIMEOUT)


def texts(elements) -> str:
    return "\n".join(str(e.value) for e in elements)


def html(at: AppTest) -> str:
    return "\n".join(h.proto.body for h in at.get("html"))


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def disclaimers(at: AppTest) -> int:
    """Veces que aparece el aviso legal (``players.disclaimer_note``) en la página."""
    return sum("mb-disclaimer" in c.value for c in at.caption)


def copy_samples(tmp_path: Path) -> Path:
    """Copia ``data/samples`` (solo ficheros: sin el pregenerado) y apunta ``BRIEFER_SAMPLES_DIR`` ahí.

    El llamante debe fijar la variable con ``monkeypatch`` (ver :func:`use_samples`).
    """
    samples = tmp_path / "samples"
    samples.mkdir()
    for f in (ROOT / "data" / "samples").iterdir():
        if f.is_file():
            shutil.copy2(f, samples / f.name)
    return samples


def use_samples(monkeypatch, tmp_path: Path) -> Path:
    samples = copy_samples(tmp_path)
    monkeypatch.setenv("BRIEFER_SAMPLES_DIR", str(samples))
    reset_settings_cache()
    return samples


def make_demo(samples: Path) -> None:
    """Pregenerado mock en ``samples`` y ``data/outputs`` vacío (Hoy lo muestra como «pregenerado»)."""
    briefing = pipeline.run_briefing(["SAN.MC", "AAPL"], use_mock=True)
    storage.export_briefing(briefing, storage.demo_briefing_dir(samples))
    for path in storage.list_briefings():
        path.unlink()


def load_view(name: str) -> dict:
    """Funciones de una vista (``views/*.py``) sin ejecutarla: quita las llamadas de nivel superior
    (``render()``) y ejecuta el resto en un espacio de nombres propio (para probar sus helpers puros)."""
    import ast

    path = APP_DIR / name
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call))]
    namespace: dict = {"__name__": f"view_{path.stem}", "__file__": str(path)}
    exec(compile(tree, str(path), "exec"), namespace)  # noqa: S102 - código de la propia app
    return namespace


def clear_streamlit_caches() -> None:
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()
