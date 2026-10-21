#!/usr/bin/env bash
# Baixa os vídeos combinados com os criadores (inclusive por acordo verbal).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${GTASIX7_PYTHON:-python3}"
if [[ -z "${GTASIX7_PYTHON:-}" && -x "$DIR/.venv/bin/python" ]]; then
  PYTHON="$DIR/.venv/bin/python"
fi
exec "$PYTHON" "$DIR/gtasix7.py" baixar "$@"
