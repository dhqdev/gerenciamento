#!/usr/bin/env python3
"""VM//PANEL - painel retro de monitoramento de VM.

Servidor HTTP com a biblioteca padrao do Python. Escuta somente em 127.0.0.1;
o Caddy fica na frente cuidando do HTTPS.
"""
import ipaddress
import json
import mimetypes
import os
import socketserver
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth as authmod      # noqa: E402
import docker_api           # noqa: E402
import metrics              # noqa: E402
import webterm              # noqa: E402
from store import Store, Recorder, notify  # noqa: E402

VERSION = "2.0.0"
TERM_UNLOCK_SECS = 30 * 60   # depois de confirmar a senha, o terminal fica liberado por 30 min
# um ou mais enderecos separados por virgula (ex.: "127.0.0.1,172.18.0.1" no modo Traefik)
HOSTS = [h.strip() for h in os.environ.get("VMPANEL_HOST", "127.0.0.1").split(",") if h.strip()]
# proxies cujo X-Forwarded-For e confiavel (Caddy local ou o Traefik do Docker)
TRUSTED_PROXIES = [ipaddress.ip_network(n.strip(), strict=False) for n in
                   os.environ.get("VMPANEL_TRUSTED_PROXIES", "127.0.0.1/32,::1/128").split(",") if n.strip()]
PORT = int(os.environ.get("VMPANEL_PORT", "8787"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
COOKIE = "vmp_session"
MAX_BODY = 64 * 1024

# 'unsafe-inline' so em estilos: o xterm.js cria <style> para as cores do terminal
CSP = ("default-src 'self'; script-src 'self'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

AUTH = authmod.Auth()
STORE = None
SAMPLER = None
DOCKER = None
RECORDER = None


class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = "vmpanel"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass  # sem log de acesso (o proxy na frente ja registra)

    # ------------------------------------------------------------ utilitarios

    def client_ip(self):
        ip = self.client_address[0]
        fwd = self.headers.get("X-Forwarded-For")
        if fwd and trusted_proxy(ip):
            ip = fwd.split(",")[-1].strip()
        return ip

    def is_https(self):
        return self.headers.get("X-Forwarded-Proto", "") == "https"

    def token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def session(self):
        return AUTH.get_session(self.token())

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("corpo muito grande")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def csrf_ok(self):
        if self.headers.get("X-VMPanel") != "1":
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host")
            if urllib.parse.urlparse(origin).netloc != host:
                return False
        return True

    def terminal(self, sess):
        origin = self.headers.get("Origin", "")
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host")
        if not origin or urllib.parse.urlparse(origin).netloc != host:
            return self.send(403, {"error": "origem invalida"})
        if sess.get("term_until", 0) < time.time():
            return self.send(403, {"error": "confirme a senha para abrir o terminal"})
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        if not webterm.handshake(self):
            return self.send(400, {"error": "esperado websocket"})
        ip = self.client_ip()
        self.close_connection = True
        webterm.bridge_terminal(self.connection, int(q.get("cols", 100)), int(q.get("rows", 30)),
                                lambda user: STORE.event("terminal", ip, "shell como %s" % user))

    def static(self, name):
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC + os.sep) or not os.path.isfile(path):
            return self.send(404, {"error": "nao encontrado"})
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            self.send(200, f.read(), ctype)

    # ------------------------------------------------------------ roteamento

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self.route_get()
        except Exception as e:
            self.send(500, {"error": str(e)})

    def do_POST(self):
        try:
            self.route_post()
        except Exception as e:
            self.send(500, {"error": str(e)})

    def route_get(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        q = dict(urllib.parse.parse_qsl(u.query))

        if p == "/healthz":
            return self.send(200, {"ok": True})
        if p.startswith("/static/"):
            return self.static(p[len("/static/"):])
        if p == "/login":
            if self.session():
                return self.redirect("/")
            return self.static("login.html")
        if p == "/api/login-info":
            return self.send(200, {"totp": AUTH.totp_enabled(), "locked": AUTH.locked_for(self.client_ip())})

        sess = self.session()
        if p == "/" or p == "/index.html":
            return self.static("index.html") if sess else self.redirect("/login")
        if not sess:
            return self.send(401, {"error": "nao autenticado"})

        if p == "/api/term":
            return self.terminal(sess)
        if p == "/api/version":
            return self.send(200, webterm.agent_call("version"))
        if p == "/api/update/log":
            return self.send(200, webterm.agent_call("update-log", timeout=10))
        if p == "/api/swarm":
            return self.send(200, metrics.cached("swarm", 4, docker_api.swarm))
        if p == "/api/swarm/logs":
            return self.send(200, {"logs": docker_api.service_logs(q.get("id", ""), q.get("tail", 200))})
        if p == "/api/me":
            c = AUTH.cfg() or {}
            return self.send(200, {"user": c.get("username"), "totp": bool(c.get("totp_secret")),
                                   "ip": self.client_ip(), "version": VERSION,
                                   "agent": webterm.agent_available(),
                                   "term_unlocked": sess.get("term_until", 0) > time.time()})
        if p == "/api/overview":
            snap = SAMPLER.get()
            d = DOCKER.get()
            return self.send(200, {
                "static": SAMPLER.static, "now": snap, "version": VERSION,
                "docker": {"available": d["available"], "info": d["info"],
                           "top": sorted(d["containers"], key=lambda c: -c["cpu"])[:5]},
                "alerts": RECORDER.active_alerts,
                "oracle": oracle_status(),
                "reboot_required": metrics.reboot_required(),
            })
        if p == "/api/processes":
            return self.send(200, SAMPLER.top_processes(q.get("sort", "cpu"), int(q.get("limit", 60)), q.get("q", "")))
        if p == "/api/docker":
            return self.send(200, DOCKER.get())
        if p == "/api/docker/images":
            return self.send(200, docker_api.images())
        if p == "/api/docker/df":
            return self.send(200, metrics.cached("docker_df", 120, docker_api.disk_usage))
        if p == "/api/docker/logs":
            return self.send(200, {"logs": docker_api.logs(q.get("id", ""), q.get("tail", 200))})
        if p == "/api/docker/inspect":
            return self.send(200, docker_api.inspect(q.get("id", "")))
        if p == "/api/network":
            return self.send(200, {
                "ips": metrics.cached("ips", 60, metrics.ip_addresses),
                "ports": metrics.cached("ports", 10, metrics.listening_ports),
                "conns": metrics.cached("conns", 5, metrics.connections_summary),
                "ifaces": (SAMPLER.get().get("net") or {}).get("ifaces", []),
            })
        if p == "/api/system":
            return self.send(200, {
                "static": SAMPLER.static,
                "services": metrics.cached("svc", 15, metrics.services_status),
                "failed": metrics.cached("failed", 15, metrics.failed_services),
                "updates": metrics.cached("updates", 3600, metrics.pending_updates),
                "reboot_required": metrics.reboot_required(),
                "temps": (SAMPLER.get() or {}).get("temps", []),
            })
        if p == "/api/security":
            return self.send(200, {
                "ssh": metrics.cached("ssh", 60, metrics.ssh_failures),
                "who": metrics.cached("who", 30, metrics.logged_users),
                "events": STORE.events(100),
                "sessions": AUTH.list_sessions(),
            })
        if p == "/api/history":
            rng = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
            secs = rng.get(q.get("range", "24h"), 86400)
            return self.send(200, STORE.history(secs))
        if p == "/api/settings":
            s = STORE.settings()
            for k in ("discord_webhook", "telegram_token"):
                s[k] = "********" if s[k] else ""
            return self.send(200, s)
        return self.send(404, {"error": "nao encontrado"})

    def route_post(self):
        p = urllib.parse.urlparse(self.path).path
        if not self.csrf_ok():
            return self.send(403, {"error": "requisicao bloqueada (CSRF)"})
        ip = self.client_ip()

        if p == "/api/login":
            data = self.body()
            ok, why = AUTH.check_login(ip, str(data.get("username", ""))[:128],
                                       str(data.get("password", ""))[:256], str(data.get("totp", ""))[:12])
            if not ok:
                STORE.event("login_fail", ip, why)
                if why == "locked":
                    STORE.event("ip_locked", ip, "bloqueado por excesso de tentativas")
                    return self.send(429, {"error": "IP bloqueado temporariamente", "retry": AUTH.locked_for(ip)})
                return self.send(401, {"error": "credenciais invalidas"})
            tok = AUTH.create_session(ip, self.headers.get("User-Agent"))
            STORE.event("login_ok", ip, (self.headers.get("User-Agent") or "")[:200])
            cfg = STORE.settings()
            if cfg.get("alert_login"):
                threading.Thread(target=notify, args=(cfg, "[VM//PANEL %s] Login no painel a partir de %s"
                                                      % (SAMPLER.static["hostname"], ip)), daemon=True).start()
            cookie = "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d%s" % (
                COOKIE, tok, authmod.SESSION_ABSOLUTE, "; Secure" if self.is_https() else "")
            return self.send(200, {"ok": True}, headers={"Set-Cookie": cookie})

        if p == "/api/logout":
            AUTH.destroy_session(self.token())
            return self.send(200, {"ok": True}, headers={
                "Set-Cookie": "%s=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" % COOKIE})

        if not self.session():
            return self.send(401, {"error": "nao autenticado"})
        data = self.body()

        if p == "/api/docker/action":
            cid, act = str(data.get("id", "")), str(data.get("action", ""))
            try:
                docker_api.action(cid, act)
            except Exception as e:
                return self.send(400, {"error": str(e)})
            STORE.event("docker_" + act, ip, cid)
            try:
                DOCKER.refresh()
            except Exception:
                pass
            return self.send(200, {"ok": True})
        if p == "/api/settings":
            clean = {k: v for k, v in data.items() if not (k in ("discord_webhook", "telegram_token") and v == "********")}
            for k in ("discord_webhook",):
                if clean.get(k) and not str(clean[k]).startswith("https://"):
                    return self.send(400, {"error": "webhook precisa comecar com https://"})
            STORE.save_settings(clean)
            STORE.event("settings", ip, ",".join(sorted(clean.keys())))
            return self.send(200, {"ok": True})
        if p == "/api/term/unlock":
            c = AUTH.cfg() or {}
            if not authmod.verify_password(str(data.get("password", ""))[:256], c.get("password_hash", "")):
                AUTH._register_fail(ip)
                STORE.event("term_unlock_fail", ip, "")
                return self.send(401, {"error": "senha incorreta"})
            self.session()["term_until"] = time.time() + TERM_UNLOCK_SECS
            STORE.event("term_unlock", ip, "")
            return self.send(200, {"ok": True})
        if p == "/api/update":
            r = webterm.agent_call("update", timeout=30)
            STORE.event("panel_update", ip, "ok" if r.get("ok") else r.get("error", ""))
            return self.send(200 if r.get("ok") else 500, r)
        if p == "/api/swarm/action":
            try:
                docker_api.service_action(str(data.get("id", "")), str(data.get("action", "")))
            except Exception as e:
                return self.send(400, {"error": str(e)})
            STORE.event("swarm_" + str(data.get("action", "")), ip, str(data.get("id", "")))
            metrics._cache.pop("swarm", None)
            return self.send(200, {"ok": True})
        if p == "/api/settings/test":
            errs = notify(STORE.settings(), "[VM//PANEL %s] Teste de notificacao OK" % SAMPLER.static["hostname"])
            return self.send(200 if not errs else 502, {"ok": not errs, "errors": errs})
        if p == "/api/sessions/revoke":
            AUTH.destroy_all()
            STORE.event("sessions_revoked", ip, "")
            return self.send(200, {"ok": True})
        return self.send(404, {"error": "nao encontrado"})


def trusted_proxy(ip):
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in n for n in TRUSTED_PROXIES)


def serve(host):
    """Escuta em um endereco; se a interface ainda nao existir (ex.: Docker subindo), tenta de novo."""
    while True:
        try:
            srv = Server((host, PORT), Handler)
        except OSError as e:
            print("aguardando %s:%d (%s)" % (host, PORT, e), flush=True)
            time.sleep(5)
            continue
        print("VM//PANEL %s ouvindo em http://%s:%d" % (VERSION, host, PORT), flush=True)
        srv.serve_forever()


def oracle_status():
    """Regra de instancia ociosa do Oracle Always Free: CPU p95 < 20% em 7 dias."""
    cpu95, span = STORE.percentile("cpu", 7 * 86400, 95)
    mem95, _ = STORE.percentile("mem", 7 * 86400, 95)
    return {"cpu_p95": cpu95, "mem_p95": mem95, "days": round(span / 86400.0, 1),
            "at_risk": span >= 86400 and cpu95 is not None and cpu95 < 20 and (mem95 is None or mem95 < 20)}


def main():
    global STORE, SAMPLER, DOCKER, RECORDER
    if not os.path.exists(authmod.AUTH_FILE):
        print("ERRO: credenciais nao configuradas (%s). Rode: vmpanel passwd" % authmod.AUTH_FILE, flush=True)
        sys.exit(1)
    STORE = Store()
    SAMPLER = metrics.Sampler()
    SAMPLER.start()
    DOCKER = docker_api.DockerWatcher()
    DOCKER.start()
    RECORDER = Recorder(STORE, SAMPLER, DOCKER, SAMPLER.static["hostname"])
    RECORDER.start()
    STORE.event("start", "", "VM//PANEL %s iniciado" % VERSION)
    for h in HOSTS[1:]:
        threading.Thread(target=serve, args=(h,), daemon=True).start()
    serve(HOSTS[0])


if __name__ == "__main__":
    main()
