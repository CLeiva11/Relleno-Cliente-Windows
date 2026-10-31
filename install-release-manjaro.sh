#!/usr/bin/env bash
set -euo pipefail

VERSION="${RELLENO_CLIENT_VERSION:-0.4.36}"
TAG="manjaro-v${VERSION}"
REPOSITORY="CLeiva11/Relleno-Cliente-Windows"
BASE_URL="https://github.com/${REPOSITORY}/releases/download/${TAG}"
PACKAGE="RellenoCliente-Manjaro-${VERSION}.tar.gz"
CHECKSUMS="SHA256SUMS-Manjaro.txt"

if ! command -v pacman >/dev/null 2>&1; then
  echo "Este instalador está preparado para Manjaro/Arch Linux." >&2
  exit 1
fi

missing=()
for command in curl secret-tool xdg-open; do
  command -v "$command" >/dev/null 2>&1 || missing+=("$command")
done
if ! command -v chromium >/dev/null 2>&1 && ! command -v google-chrome-stable >/dev/null 2>&1; then
  missing+=("chromium")
fi

if ((${#missing[@]})); then
  echo "Instalando dependencias del sistema..."
  sudo pacman -S --needed --noconfirm curl chromium libsecret xdg-utils tk
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "Descargando Relleno Cliente ${VERSION}..."
curl --fail --location --retry 3 --output "$workdir/$PACKAGE" "$BASE_URL/$PACKAGE"
curl --fail --location --retry 3 --output "$workdir/$CHECKSUMS" "$BASE_URL/$CHECKSUMS"

(
  cd "$workdir"
  sha256sum --check "$CHECKSUMS"
  mkdir package
  tar -xzf "$PACKAGE" -C package
  ./package/install-manjaro.sh
)

echo "Instalación terminada. Puede abrir Relleno Cliente desde el menú de aplicaciones."
