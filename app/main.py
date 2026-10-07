"""Briefly · app Streamlit (carril C). Lanzar con: ``streamlit run app/main.py``.

Rediseño «Tres pestañas, cero sidebar»: este fichero solo arranca el armazón común
(``components.shell.run_app``), que registra las tres vistas de ``app/views/`` con ``st.navigation``,
pinta la barra superior (Hoy · Preguntar · Archivo, chip del modo y menú ⚙), ejecuta la vista activa
y cierra con el aviso legal.

- **Hoy** (``views/hoy.py``): el briefing de hoy sin pulsar nada y «＋ Nuevo briefing» (un diálogo
  con valores, cartera, documentos y opciones).
- **Preguntar** (``views/preguntar.py``): chat por voz o texto con Toro y Osa sobre el briefing.
- **Archivo** (``views/archivo.py``): briefings anteriores y borrado de datos (RGPD).
"""

from __future__ import annotations

import components  # noqa: F401  (añade src/ al sys.path)
from components.shell import run_app

run_app()
