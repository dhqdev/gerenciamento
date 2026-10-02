# VM//PANEL

Painel de monitoramento da sua VM com visual de terminal retrô (fósforo verde, scanlines de CRT). Mostra CPU, RAM, discos, rede, processos, containers Docker, segurança e histórico, tudo num só lugar e protegido por um login único.

```
 __   ____  __    __  __  ___  _   _  _ ___ _
 \ \ / /  \/  |  / / / / | _ \/_\ | \| | __| |
  \ V /| |\/| | / / / /  |  _/ _ \| .` | _|| |__
   \_/ |_|  |_|/_/ /_/   |_|/_/ \_\_|\_|___|____|
```

## Instalação (um comando)

Na sua VM (Oracle Cloud, ou qualquer Ubuntu/Debian/Oracle Linux com systemd), conectado por SSH:

```bash
curl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/install.sh | sudo bash
```

O instalador vai:

1. Instalar as dependências (git, python3, curl, qrencode). O painel não usa nenhuma biblioteca Python externa.
2. Baixar este repositório em `/opt/vmpanel`.
3. Perguntar o **usuário e a senha únicos** do painel (mínimo de 12 caracteres). A senha é guardada só como hash scrypt.
4. Oferecer **2FA** (Google Authenticator, Authy, Bitwarden...) com QR code direto no terminal. Recomendado.
5. Perguntar o **domínio** (ex.: `painel.seudominio.com`) e configurar o Caddy com **HTTPS automático (Let's Encrypt)**.
6. Liberar as portas 80 e 443 no firewall da VM (inclusive o iptables que vem bloqueado nas imagens Ubuntu da Oracle).
7. Criar o serviço `vmpanel` no systemd, que sobe sozinho quando a VM reinicia.

Funciona em x86_64 e ARM (Ampere A1 do Always Free).

### Antes de instalar

- **DNS:** crie um registro `A` no seu provedor de domínio apontando `painel.seudominio.com` para o IP público da VM. Se usar Cloudflare, deixe em "DNS only" (nuvem cinza) pelo menos até o certificado ser emitido.
- **Oracle Cloud:** libere as portas 80 e 443 na Security List da VCN. Isso só dá para fazer pelo console da Oracle:
  `Networking > Virtual Cloud Networks > sua VCN > Security Lists > Default > Add Ingress Rules`
  com Source CIDR `0.0.0.0/0`, protocolo TCP, porta de destino `80`; repita para `443`.

### Sem domínio (mais seguro ainda)

Se deixar o domínio em branco, o painel fica só em `127.0.0.1:8787`, sem nada exposto na internet. Para acessar, abra um túnel SSH do seu computador:

```bash
ssh -L 8787:127.0.0.1:8787 ubuntu@IP_DA_VM
```

e abra `http://localhost:8787`. Dá para publicar num domínio depois com `sudo vmpanel domain painel.seudominio.com`.

### Instalação sem perguntas

```bash
curl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/install.sh | sudo \
  VMPANEL_DOMAIN=painel.seudominio.com VMPANEL_EMAIL=voce@email.com \
  VMPANEL_USER=admin VMPANEL_PASSWORD='Uma-Senha-Bem-Forte-123' VMPANEL_2FA=n VMPANEL_DOCKER=n bash
```

## O que o painel mostra

| Aba | Conteúdo |
| --- | --- |
| `1` PAINEL | CPU total e por núcleo, load, steal, RAM, swap, discos, IO, rede ao vivo com gráficos, resumo do Docker, alertas ativos |
| `2` DOCKER | Todos os containers com CPU, memória, rede e portas; **iniciar, parar e reiniciar**; logs ao vivo com filtro; detalhes (volumes, redes, health, restarts); imagens e uso de disco do Docker |
| `3` PROCESSOS | Lista estilo `top`, ordenável por CPU, memória ou PID, com busca |
| `4` REDE | Tráfego por interface, IPs, portas abertas (marcando as expostas para a internet), conexões TCP e IPs mais conectados |
| `5` DISCOS | Todas as partições com uso e inodes, gráfico de leitura/escrita e ocupação por disco |
| `6` SISTEMA | Hardware e SO, serviços importantes (docker, caddy, ssh...), unidades systemd com falha, atualizações pendentes (incluindo de segurança) e aviso de reboot necessário |
| `7` SEGURANÇA | Tentativas de login SSH com falha nas últimas 24h, IPs atacantes, usuários tentados, quem está logado na VM, sessões abertas no painel e log de auditoria |
| `8` HISTÓRICO | Gráficos de 1h, 6h, 24h, 7 e 30 dias (CPU, memória, swap, rede, disco, load) |
| `9` CONFIG | Limites de alerta, notificações por Discord e Telegram, tema de cor e efeito CRT |

**Vigia do Oracle Always Free:** a Oracle pode recuperar instâncias gratuitas que ficam ociosas (CPU no percentil 95 abaixo de 20% durante 7 dias). O painel calcula isso com o histórico e avisa quando a VM está em risco.

**Alertas:** CPU ou memória altas por X minutos, disco cheio, container que parou e cada novo login no painel. Chegam no Discord (webhook) e/ou Telegram (bot).

**Console retrô:** na barra inferior dá para digitar comandos como `help`, `restart nome-do-container`, `logs nome`, `df`, `free`, `ps nginx`, `theme amber`, `crt off`. As teclas `1` a `9` trocam de aba e `/` foca o console. Temas: green, amber, cyan, white, pink.

## Segurança

- Um único usuário, senha com hash **scrypt** (N=2^15) e comparação em tempo constante.
- **2FA TOTP** opcional, com proteção contra reuso do mesmo código.
- **Bloqueio por IP:** 5 senhas erradas em 15 min bloqueiam o IP por 15 min, e o tempo dobra a cada reincidência. Também há uma trava contra ataques distribuídos.
- Sessão em cookie `HttpOnly`, `Secure` e `SameSite=Strict`, com expiração por inatividade (2h) e absoluta (12h). Trocar a senha derruba todas as sessões.
- Proteção CSRF (cabeçalho próprio e checagem de Origin), Content-Security-Policy rígida, sem scripts inline, HSTS.
- O servidor só escuta em `127.0.0.1`; quem fala com a internet é o Caddy, com HTTPS.
- O serviço roda com o usuário sem privilégios `vmpanel` e com o sandbox do systemd (`ProtectSystem=strict`, `NoNewPrivileges` e outros).
- Todo login, falha, bloqueio e ação no Docker fica registrado na auditoria.

> Atenção: estar no grupo `docker` dá controle total sobre os containers. É por isso que o painel tem login forte, 2FA e bloqueio de IP. Ative o 2FA.

## Comandos na VM

```bash
sudo vmpanel status        # estado do serviço
sudo vmpanel logs          # logs ao vivo
sudo vmpanel update        # baixa a última versão do GitHub e reinicia
sudo vmpanel passwd        # troca usuário/senha
sudo vmpanel 2fa-on        # ativa 2FA (mostra QR code)
sudo vmpanel 2fa-off       # desativa 2FA
sudo vmpanel domain X      # publica/troca o domínio (ou "domain off")
sudo vmpanel doctor        # diagnóstico (serviço, Docker, DNS, HTTPS)
sudo vmpanel uninstall     # remove o painel
```

## Problemas comuns

- **O site não abre:** rode `sudo vmpanel doctor`. Quase sempre é a Security List da Oracle sem as portas 80/443 ou o DNS ainda não propagado.
- **A aba Docker diz que não tem acesso:** `sudo usermod -aG docker vmpanel && sudo systemctl restart vmpanel`.
- **Esqueci a senha:** `sudo vmpanel passwd`.
- **Perdi o celular do 2FA:** `sudo vmpanel 2fa-off` e depois `sudo vmpanel 2fa-on`.
- **Meu IP foi bloqueado:** espere o tempo indicado ou reinicie o serviço (`sudo vmpanel restart`).

## Estrutura

```
install.sh              instalador (curl | sudo bash)
bin/vmpanel             CLI de instalação e manutenção
app/server.py           servidor HTTP e API (Python, só biblioteca padrão)
app/metrics.py          coleta de /proc e /sys
app/docker_api.py       cliente da API do Docker via unix socket
app/auth.py             senha scrypt, TOTP, sessões e rate limit
app/store.py            histórico SQLite, auditoria, configurações e alertas
app/manage.py           gerenciamento das credenciais
app/static/             interface retrô (HTML, CSS e JS puros)
deploy/                 unit do systemd e modelos do Caddy
```

Para rodar localmente durante o desenvolvimento:

```bash
export VMPANEL_AUTH=./dev-auth.json VMPANEL_DB=./dev.db
python3 app/manage.py passwd
python3 app/server.py   # http://127.0.0.1:8787
```
