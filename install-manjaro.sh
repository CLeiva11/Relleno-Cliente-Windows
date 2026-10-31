#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
APP_SOURCE="$SOURCE_DIR/RellenoCliente"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/relleno-cliente/app"
BIN_DIR="$HOME/.local/bin"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

for command in secret-tool xdg-open; do
  command -v "$command" >/dev/null || {
    echo "Falta $command. Instale libsecret y xdg-utils antes de continuar." >&2
    exit 1
  }
done
if ! command -v chromium >/dev/null && ! command -v google-chrome-stable >/dev/null; then
  echo "Falta Chromium o Google Chrome para consultar HikCentral." >&2
  exit 1
fi
test -x "$APP_SOURCE/RellenoCliente" || {
  echo "El paquete no contiene RellenoCliente." >&2
  exit 1
}

pkill -f "$INSTALL_DIR/RellenoCliente.*--agent-worker" 2>/dev/null || true
mkdir -p "$(dirname "$INSTALL_DIR")" "$BIN_DIR" "$APPLICATIONS_DIR"
replacement="${INSTALL_DIR}.new"
rm -rf "$replacement"
cp -a "$APP_SOURCE" "$replacement"
rm -rf "$INSTALL_DIR"
mv "$replacement" "$INSTALL_DIR"

cat > "$BIN_DIR/relleno-cliente" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/RellenoCliente" "\$@"
EOF
chmod 755 "$BIN_DIR/relleno-cliente"

cat > "$APPLICATIONS_DIR/relleno-cliente.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Relleno Cliente
Comment=Comprobaciones de Personas y ANPR
Exec=$BIN_DIR/relleno-cliente
Terminal=false
Categories=Utility;
EOF

"$BIN_DIR/relleno-cliente" --resume-agent >/dev/null 2>&1 &
if [[ "${1:-}" != "--update" ]]; then
  "$BIN_DIR/relleno-cliente" >/dev/null 2>&1 &
fi
echo "Relleno Cliente quedó instalado para el usuario actual."
