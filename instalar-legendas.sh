#!/usr/bin/env bash
# Instala a transcrição em ambiente isolado. O modelo baixa no primeiro uso.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${GTASIX7_PYTHON:-python3}"
"$PYTHON" -m venv "$DIR/.venv"
"$DIR/.venv/bin/python" -m pip install -r "$DIR/requirements-legendas.txt"
echo 'Legendas instaladas. O modelo Whisper baixa no primeiro vídeo com áudio.'
