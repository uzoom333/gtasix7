#!/usr/bin/env bash
# Uso: ./gtasix7.sh <video> <@criador> [legenda] [gancho] [corte]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/gtasix7.py" editar "$@"
