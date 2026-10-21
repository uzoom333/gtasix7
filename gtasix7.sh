#!/usr/bin/env bash
# Uso: ./gtasix7.sh <video> <@criador> [legenda] [gancho] [corte]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${GTASIX7_PYTHON:-python3}"
if [[ -z "${GTASIX7_PYTHON:-}" && -x "$DIR/.venv/bin/python" ]]; then
  PYTHON="$DIR/.venv/bin/python"
fi
exec "$PYTHON" "$DIR/gtasix7.py" editar "$@"
