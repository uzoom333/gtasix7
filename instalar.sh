#!/usr/bin/env bash
# Instala FFmpeg, Python 3, fontconfig, Montserrat e yt-dlp.
set -euo pipefail
if command -v dnf >/dev/null; then
  sudo dnf install -y ffmpeg-free python3 python3-pip fontconfig julietaula-montserrat-fonts curl
elif command -v apt-get >/dev/null; then
  sudo apt-get update
  sudo apt-get install -y ffmpeg python3 python3-venv fontconfig fonts-montserrat curl
elif command -v brew >/dev/null; then
  brew install ffmpeg python fontconfig
  brew install --cask font-montserrat
else
  echo 'Instale: ffmpeg, Python 3, fontconfig, Montserrat e yt-dlp.' >&2
  exit 1
fi
mkdir -p "$HOME/.local/bin"
TMP="$(mktemp "$HOME/.local/bin/yt-dlp.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
curl --fail --show-error --location --retry 3 \
  -o "$TMP" https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp
chmod +x "$TMP"
mv "$TMP" "$HOME/.local/bin/yt-dlp"
if [[ ! -e "$(dirname "$0")/fila.txt" ]]; then
  cp "$(dirname "$0")/fila.exemplo.txt" "$(dirname "$0")/fila.txt"
fi
printf 'Instalação concluída. Inclua %s/.local/bin no PATH.\n' "$HOME"
"$(dirname "$0")/instalar-legendas.sh"
