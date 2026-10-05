#!/usr/bin/env bash
# Arranque en Linux/macOS: crea .venv, instala dependencias, prepara .env y lanza la app.
#
# Uso:  bash scripts/run.sh [--local] [--expose] [--port N] [--reinstall]
#   --local      instala tambien los modelos locales (requirements-local.txt, varios GB)
#   --expose     escucha en todas las interfaces (0.0.0.0): visible desde otros equipos de la red.
#                Por defecto solo localhost, para no exponer tus claves de API en la red de clase.
#   --port N     puerto de Streamlit (8501 por defecto)
#   --reinstall  fuerza pip install aunque los requirements no hayan cambiado
# Variable PYTHON: interprete a usar para crear el .venv (por defecto, el primero >= 3.11 que encuentre).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { echo; echo "ERROR: $*" >&2; exit 1; }

LOCAL=0; EXPOSE=0; PORT=8501; REINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --local) LOCAL=1 ;;
    --expose) EXPOSE=1 ;;
    --port) [ $# -ge 2 ] || fail "--port necesita un numero"; PORT="$2"; shift ;;
    --reinstall) REINSTALL=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) fail "Opcion desconocida: $1 (usa --help)" ;;
  esac
  shift
done

is_py311() { "$@" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; }

PY=".venv/bin/python"
if [ -x "$PY" ] && ! is_py311 "$PY"; then
  fail "El entorno .venv usa un Python anterior a 3.11. Borra la carpeta .venv y vuelve a ejecutar."
fi

if [ ! -x "$PY" ]; then
  SYS_PY=""
  for cand in ${PYTHON:-} python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && is_py311 "$cand"; then SYS_PY="$cand"; break; fi
  done
  [ -n "$SYS_PY" ] || fail "No encuentro Python 3.11 o superior. Instalalo (p. ej. 'sudo apt install python3.11 python3.11-venv' o 'brew install python@3.11') y vuelve a ejecutar."
  echo "Creando entorno virtual en .venv con: $SYS_PY ..."
  "$SYS_PY" -m venv .venv || fail "No se pudo crear .venv (en Debian/Ubuntu falta el paquete python3-venv?)."
fi

# Instala solo si cambian los requirements (asi se puede relanzar sin red el dia de la demo).
REQS="requirements.txt"
[ "$LOCAL" = 1 ] && REQS="$REQS requirements-local.txt"
HASH="$(cat $REQS | "$PY" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
STAMP=".venv/.deps-installed"
if [ "$REINSTALL" = 1 ] || [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$HASH" ]; then
  echo "Instalando dependencias (la primera vez tarda unos minutos) ..."
  "$PY" -m pip install --upgrade pip --quiet || fail "Fallo al actualizar pip (hay conexion a Internet?)."
  "$PY" -m pip install -r requirements.txt || fail "Fallo 'pip install -r requirements.txt'. Revisa el mensaje de arriba."
  if [ "$LOCAL" = 1 ]; then
    "$PY" -m pip install -r requirements-local.txt || fail "Fallo 'pip install -r requirements-local.txt'."
  fi
  echo "$HASH" > "$STAMP"
else
  echo "Dependencias ya instaladas (usa --reinstall para forzar)."
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creado .env a partir de .env.example."
  echo "  Sin claves de API la app funciona igual en modo demo (datos de ejemplo y mocks)."
  echo "  Para el modo real, rellena ANTHROPIC_API_KEY (y las demas que uses) en .env."
fi

export PYTHONPATH="$ROOT/src"
ADDRESS="localhost"
if [ "$EXPOSE" = 1 ]; then
  ADDRESS="0.0.0.0"
  echo "AVISO: --expose activo. Cualquiera en tu red podra usar la app (y tus claves de API)."
fi
echo "Lanzando Market Briefer en http://localhost:$PORT  (Ctrl+C para parar) ..."
exec "$PY" -m streamlit run app/main.py --server.address "$ADDRESS" --server.port "$PORT" --server.headless true
