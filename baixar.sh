#!/usr/bin/env bash
# Baixa os vídeos combinados com os criadores (inclusive por acordo verbal).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/gtasix7.py" baixar "$@"
