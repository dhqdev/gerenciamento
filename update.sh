#!/usr/bin/env bash
# VM//PANEL - atualiza para a ultima versao do GitHub
#
#   curl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/update.sh | sudo bash
set -euo pipefail
APP_DIR="/opt/vmpanel"
[ "$(id -u)" -eq 0 ] || { echo "Rode como root: curl ... | sudo bash" >&2; exit 1; }

if [ ! -d "$APP_DIR/.git" ]; then
  echo "> VM//PANEL nao esta instalado; rodando o instalador..."
  curl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/install.sh | bash
  exit
fi

# baixa o codigo novo primeiro, para usar a logica de atualizacao mais recente
branch="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"
VMPANEL_OLD_REV="$(git -C "$APP_DIR" rev-parse --short HEAD)"
export VMPANEL_OLD_REV
git -C "$APP_DIR" fetch --quiet origin "$branch"
git -C "$APP_DIR" reset --quiet --hard "origin/$branch"
chmod 0755 "$APP_DIR/bin/vmpanel"
exec "$APP_DIR/bin/vmpanel" update
