#!/usr/bin/env python3
"""VM//PANEL agent: pequeno servico root com acoes FIXAS, usado pelo painel.

Escuta em um unix socket acessivel apenas ao grupo `vmpanel` e aceita so:
  - term     abre um terminal (PTY) como o usuario definido em VMPANEL_TERM_USER
  - version  compara a versao instalada com a do GitHub
  - update   dispara `vmpanel update` em uma unidade systemd separada

Nada que vem do cliente vira comando: o usuario do terminal e o comando de update
sao definidos aqui / em /etc/vmpanel/env (que so o root pode alterar).
"""
import fcntl
import grp
import json
import os
import pty
import pwd
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import threading

SOCK_DIR = "/run/vmpanel"
SOCK = os.path.join(SOCK_DIR, "agent.sock")
APP_DIR = os.environ.get("VMPANEL_DIR", "/opt/vmpanel")
UPDATE_LOG = "/var/lib/vmpanel/update.log"


def env(key, default=""):
    try:
        with open("/etc/vmpanel/env") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == key:
                    return v
    except OSError:
        pass
    return default


def run(cmd, timeout=60):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, timeout=timeout)
    return p.returncode, p.stdout.strip()


def send_json(conn, obj):
    conn.sendall((json.dumps(obj) + "\n").encode())


def read_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


# ---------------------------------------------------------------- acoes

def act_version(conn):
    branch = run(["git", "-C", APP_DIR, "rev-parse", "--abbrev-ref", "HEAD"])[1]
    local = run(["git", "-C", APP_DIR, "rev-parse", "--short", "HEAD"])[1]
    rc, out = run(["git", "-C", APP_DIR, "fetch", "--quiet", "origin", branch], timeout=60)
    if rc != 0:
        return send_json(conn, {"ok": False, "error": "nao consegui falar com o GitHub", "local": local})
    remote = run(["git", "-C", APP_DIR, "rev-parse", "--short", "origin/" + branch])[1]
    log = run(["git", "-C", APP_DIR, "log", "--format=%h %s", "HEAD..origin/" + branch, "-n", "30"])[1]
    send_json(conn, {"ok": True, "local": local, "remote": remote,
                     "behind": len([l for l in log.splitlines() if l.strip()]),
                     "changes": [l for l in log.splitlines() if l.strip()]})


def act_update(conn):
    # roda fora deste servico: o update reinicia o painel e o proprio agente
    cmd = "%s/bin/vmpanel update > %s 2>&1" % (APP_DIR, UPDATE_LOG)
    rc, out = run(["systemd-run", "--unit", "vmpanel-selfupdate-%d" % os.getpid(),
                   "--collect", "--quiet", "/bin/sh", "-c", cmd])
    send_json(conn, {"ok": rc == 0, "error": out if rc else ""})


def act_update_log(conn):
    try:
        with open(UPDATE_LOG) as f:
            txt = f.read()[-8000:]
    except OSError:
        txt = ""
    send_json(conn, {"ok": True, "log": txt})


def act_term(conn, req):
    if env("VMPANEL_TERMINAL", "on") != "on":
        return send_json(conn, {"ok": False, "error": "terminal desativado (sudo vmpanel terminal on)"})
    user = env("VMPANEL_TERM_USER", "")
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        return send_json(conn, {"ok": False, "error": "usuario do terminal invalido: %r" % user})
    send_json(conn, {"ok": True, "user": user})

    pid, fd = pty.fork()
    if pid == 0:
        os.environ.clear()
        os.environ.update({"TERM": "xterm-256color", "LANG": "C.UTF-8", "COLORTERM": "truecolor"})
        os.execv("/usr/sbin/runuser", ["runuser", "-l", pw.pw_name])
        os._exit(1)

    def resize(cols, rows):
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
        except Exception:
            pass

    resize(req.get("cols", 100), req.get("rows", 30))
    try:
        while True:
            r, _, _ = select.select([conn, fd], [], [], 30)
            if fd in r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                conn.sendall(data)
            if conn in r:
                hdr = read_exact(conn, 5)
                if not hdr:
                    break
                kind, n = hdr[0], struct.unpack(">I", hdr[1:])[0]
                payload = read_exact(conn, n) if n else b""
                if payload is None:
                    break
                if kind == 0:
                    os.write(fd, payload)
                elif kind == 1:
                    try:
                        sz = json.loads(payload.decode())
                        resize(sz.get("cols", 100), sz.get("rows", 30))
                    except Exception:
                        pass
    finally:
        try:
            os.kill(pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        os.close(fd)


def handle(conn):
    try:
        # so aceita o usuario do painel ou o root
        creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", creds)
        allowed = {0}
        try:
            allowed.add(pwd.getpwnam("vmpanel").pw_uid)
        except KeyError:
            pass
        if uid not in allowed:
            return
        line = b""
        while not line.endswith(b"\n"):
            c = conn.recv(1)
            if not c:
                return
            line += c
            if len(line) > 4096:
                return
        req = json.loads(line.decode())
        action = req.get("action")
        if action == "term":
            act_term(conn, req)
        elif action == "version":
            act_version(conn)
        elif action == "update":
            act_update(conn)
        elif action == "update-log":
            act_update_log(conn)
        else:
            send_json(conn, {"ok": False, "error": "acao desconhecida"})
    except Exception as e:
        try:
            send_json(conn, {"ok": False, "error": str(e)})
        except Exception:
            pass
    finally:
        conn.close()


def main():
    if os.geteuid() != 0:
        sys.exit("o agente precisa rodar como root")
    os.makedirs(SOCK_DIR, exist_ok=True)
    gid = grp.getgrnam("vmpanel").gr_gid
    os.chown(SOCK_DIR, 0, gid)
    os.chmod(SOCK_DIR, 0o750)
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chown(SOCK, 0, gid)
    os.chmod(SOCK, 0o660)
    srv.listen(16)
    print("vmpanel-agent ouvindo em %s" % SOCK, flush=True)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
