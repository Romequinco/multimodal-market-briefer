"""Componentes reutilizables de la UI (carril C).

Al importarse, añade ``src/`` al ``sys.path`` para que ``import briefer`` funcione al lanzar
``streamlit run app/main.py`` sin instalar el paquete.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
_SRC = str(ROOT_DIR / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
