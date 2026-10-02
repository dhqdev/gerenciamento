#!/usr/bin/env bash
# VM//PANEL - remove o painel por completo (sem perguntas)
#
#   curl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/uninstall.sh | sudo bash
#
# Remove: servico, ponte do Traefik (vmpanel-proxy), regras de firewall do painel, dados e credenciais.
# NAO toca: Docker, Traefik, Portainer, seus containers e stacks.
set -euo pipefail
APP_DIR="/opt/vmpanel"
[ "$(id -u)" -eq 0 ] || { echo "Rode como root: curl ... | sudo bash" >&2; exit 1; }

if [ -d "$APP_DIR/.git" ]; then
  # usa a versao mais recente da rotina de remocao
  branch="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"
  git -C "$APP_DIR" fetch --quiet origin "$branch" 2>/dev/null && git -C "$APP_DIR" reset --quiet --hard "origin/$branch" || true
  chmod 0755 "$APP_DIR/bin/vmpanel"
  VMPANEL_YES=1 exec "$APP_DIR/bin/vmpanel" uninstall
fi

# instalacao incompleta: limpa o que tiver sobrado
docker service rm vmpanel-proxy >/dev/null 2>&1 || true
docker rm -f vmpanel-proxy >/dev/null 2>&1 || true
systemctl disable --now vmpanel vmpanel-agent vmpanel-firewall >/dev/null 2>&1 || true
rm -f /etc/systemd/system/vmpanel.service /etc/systemd/system/vmpanel-agent.service /etc/systemd/system/vmpanel-firewall.service /usr/local/bin/vmpanel
systemctl daemon-reload
rm -rf /etc/vmpanel /var/lib/vmpanel
userdel vmpanel >/dev/null 2>&1 || true
echo "> VM//PANEL removido. Docker, Traefik e seus containers nao foram tocados."
