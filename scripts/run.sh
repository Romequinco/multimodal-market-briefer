#!/usr/bin/env bash
# Arranque en Linux/macOS: crea .venv, instala dependencias, prepara .env y lanza la app.
# Uso:  bash scripts/run.sh [--local]   (--local instala también los modelos locales)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON:-python3}"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creando entorno virtual en .venv ..."
  "$PYTHON_BIN" -m venv .venv
fi
PY=".venv/bin/python"

echo "Instalando dependencias ..."
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements.txt
if [ "${1:-}" = "--local" ]; then
  "$PY" -m pip install -r requirements-local.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creado .env a partir de .env.example: rellena tus claves (sin claves se usan mocks)."
fi

export PYTHONPATH="$ROOT/src"
echo "Lanzando Market Briefer en http://localhost:8501 ..."
exec "$PY" -m streamlit run app/main.py
