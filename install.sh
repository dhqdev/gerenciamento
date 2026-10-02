#!/usr/bin/env bash
# VM//PANEL - instalador
#
#   curl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/install.sh | sudo bash
#
# Variaveis opcionais (instalacao sem perguntas):
#   VMPANEL_DOMAIN, VMPANEL_EMAIL, VMPANEL_USER, VMPANEL_PASSWORD, VMPANEL_2FA=s|n,
#   VMPANEL_DOCKER=s|n, VMPANEL_REPO, VMPANEL_BRANCH
set -euo pipefail

REPO="${VMPANEL_REPO:-https://github.com/dhqdev/gerenciamento.git}"
BRANCH="${VMPANEL_BRANCH:-}"
APP_DIR="/opt/vmpanel"

G=$'\033[1;32m'; R=$'\033[1;31m'; N=$'\033[0m'
say() { printf '%s>%s %s\n' "$G" "$N" "$*"; }
die() { printf '%sx %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Rode como root:  curl -fsSL .../install.sh | sudo bash"
command -v systemctl >/dev/null 2>&1 || die "Este instalador precisa de systemd."

printf '%s' "$G"
cat <<'ART'
 __   ____  __    __  __  ___  _   _  _ ___ _
 \ \ / /  \/  |  / / / / | _ \/_\ | \| | __| |
  \ V /| |\/| | / / / /  |  _/ _ \| .` | _|| |__
   \_/ |_|  |_|/_/ /_/   |_|/_/ \_\_|\_|___|____|
        INSTALADOR // monitoramento retro de VM
ART
printf '%s\n' "$N"

say "Instalando dependencias do sistema (git, python3, curl, qrencode)..."
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
  # VM recem-criada costuma estar com o apt ocupado (unattended-upgrades): espera ate 10 min
  apt-get -o DPkg::Lock::Timeout=600 update -qq || say "Aviso: 'apt-get update' teve erros; continuando..."
  apt-get -o DPkg::Lock::Timeout=600 install -y -qq git python3 curl ca-certificates iproute2 procps >/dev/null \
    || die "Falha ao instalar dependencias (veja: sudo apt-get install git python3 curl)"
  apt-get -o DPkg::Lock::Timeout=600 install -y -qq qrencode >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q git python3 curl ca-certificates iproute procps-ng >/dev/null
  dnf install -y -q qrencode >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y -q git python3 curl ca-certificates iproute procps-ng >/dev/null
else
  die "Distribuicao nao suportada (precisa de apt ou dnf)."
fi

python3 - <<'PY' || die "Precisa de Python 3.7 ou superior."
import sys
sys.exit(0 if sys.version_info >= (3, 7) else 1)
PY

if [ -d "$APP_DIR/.git" ]; then
  say "Atualizando codigo em $APP_DIR..."
  b="${BRANCH:-$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)}"
  git -C "$APP_DIR" fetch --quiet origin "$b"
  git -C "$APP_DIR" checkout --quiet "$b" 2>/dev/null || git -C "$APP_DIR" checkout --quiet -b "$b" "origin/$b"
  git -C "$APP_DIR" reset --quiet --hard "origin/$b"
else
  say "Baixando o VM//PANEL de $REPO..."
  rm -rf "$APP_DIR"
  if [ -n "$BRANCH" ]; then
    git clone --quiet --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR"
  else
    git clone --quiet --depth 1 "$REPO" "$APP_DIR"
  fi
fi
chown -R root:root "$APP_DIR"
chmod -R go-w "$APP_DIR"
chmod 0755 "$APP_DIR/bin/vmpanel"

exec "$APP_DIR/bin/vmpanel" setup
