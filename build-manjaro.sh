#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")"
VERSION="$(python -c 'from relleno.portal import CLIENT_VERSION; print(CLIENT_VERSION)')"
: "${RELLENO_HIKCENTRAL_PASSWORDS:?Defina RELLENO_HIKCENTRAL_PASSWORDS con las claves separadas por |}"

python - <<'PY'
import os
from pathlib import Path
passwords = tuple(dict.fromkeys(value for value in os.environ['RELLENO_HIKCENTRAL_PASSWORDS'].split('|') if value))
Path('relleno/_managed_hikcentral.py').write_text('PASSWORDS = ' + repr(passwords) + '\n', encoding='utf-8')
PY
trap 'rm -f relleno/_managed_hikcentral.py' EXIT

python -m PyInstaller --noconfirm --clean --windowed --name RellenoCliente \
  --collect-all tzdata --collect-all playwright main.py

stage="dist/manjaro-package"
rm -rf "$stage"
mkdir -p "$stage"
cp -a dist/RellenoCliente "$stage/"
cp install-manjaro.sh "$stage/"
tar -C "$stage" -czf "dist/RellenoCliente-Manjaro-${VERSION}.tar.gz" .
sha256sum "dist/RellenoCliente-Manjaro-${VERSION}.tar.gz"
