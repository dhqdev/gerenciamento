"""WebSocket minimo (RFC 6455) + ponte para o agente root (terminal, versao e update)."""
import base64
import hashlib
import json
import os
import select
import socket
import struct

AGENT_SOCK = os.environ.get("VMPANEL_AGENT_SOCK", "/run/vmpanel/agent.sock")
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---------------------------------------------------------------- agente

def agent_connect(req, timeout=90):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(AGENT_SOCK)
    s.sendall((json.dumps(req) + "\n").encode())
    return s


def _read_line(s):
    line = b""
    while not line.endswith(b"\n"):
        c = s.recv(1)
        if not c:
            break
        line += c
    return json.loads(line.decode() or "{}")


def agent_call(action, timeout=90):
    try:
        s = agent_connect({"action": action}, timeout)
    except OSError:
        return {"ok": False, "error": "agente do painel indisponivel (rode: curl .../update.sh | sudo bash)"}
    try:
        return _read_line(s)
    finally:
        s.close()


def agent_available():
    return os.path.exists(AGENT_SOCK)


# ---------------------------------------------------------------- websocket

def handshake(handler):
    key = handler.headers.get("Sec-WebSocket-Key", "")
    if not key or handler.headers.get("Upgrade", "").lower() != "websocket":
        return False
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    handler.protocol_version = "HTTP/1.1"
    handler.close_connection = True
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.wfile.flush()
    return True


def ws_send(sock, data, opcode=0x2):
    n = len(data)
    if n < 126:
        hdr = struct.pack(">BB", 0x80 | opcode, n)
    elif n < 65536:
        hdr = struct.pack(">BBH", 0x80 | opcode, 126, n)
    else:
        hdr = struct.pack(">BBQ", 0x80 | opcode, 127, n)
    sock.sendall(hdr + data)


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def ws_recv(sock):
    """Retorna (opcode, payload) ou (None, None) se fechou. Junta fragmentos."""
    parts = []
    first_op = None
    while True:
        hdr = _recv_exact(sock, 2)
        if not hdr:
            return None, None
        fin, op = hdr[0] & 0x80, hdr[0] & 0x0F
        masked, n = hdr[1] & 0x80, hdr[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", _recv_exact(sock, 2))[0]
        elif n == 127:
            n = struct.unpack(">Q", _recv_exact(sock, 8))[0]
        if n > 1024 * 1024:
            return None, None
        mask = _recv_exact(sock, 4) if masked else b"\0\0\0\0"
        data = bytearray(_recv_exact(sock, n) or b"")
        for i in range(len(data)):
            data[i] ^= mask[i % 4]
        if op >= 0x8:  # frames de controle
            if op == 0x8:
                return None, None
            if op == 0x9:
                ws_send(sock, bytes(data), 0xA)
            continue
        if first_op is None:
            first_op = op
        parts.append(bytes(data))
        if fin:
            return first_op, b"".join(parts)


def bridge_terminal(sock, cols, rows, on_event):
    """Liga o websocket do navegador ao PTY do agente ate um dos lados fechar."""
    try:
        agent = agent_connect({"action": "term", "cols": cols, "rows": rows}, timeout=None)
        hello = _read_line(agent)
    except OSError:
        ws_send(sock, b"\r\n\x1b[31mAgente do painel indisponivel. Rode o update.sh na VM.\x1b[0m\r\n")
        return
    if not hello.get("ok"):
        ws_send(sock, ("\r\n\x1b[31m%s\x1b[0m\r\n" % hello.get("error", "erro")).encode())
        return
    on_event(hello.get("user", "?"))
    agent.settimeout(None)
    sock.settimeout(None)
    try:
        while True:
            r, _, _ = select.select([sock, agent], [], [], 60)
            if agent in r:
                data = agent.recv(65536)
                if not data:
                    break
                ws_send(sock, data)
            if sock in r:
                op, payload = ws_recv(sock)
                if op is None:
                    break
                if op == 0x1:  # texto = JSON de controle (resize) ou digitacao
                    try:
                        msg = json.loads(payload.decode())
                    except Exception:
                        msg = None
                    if isinstance(msg, dict) and msg.get("type") == "resize":
                        p = json.dumps({"cols": msg.get("cols"), "rows": msg.get("rows")}).encode()
                        agent.sendall(b"\x01" + struct.pack(">I", len(p)) + p)
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "input":
                        payload = msg.get("data", "").encode()
                agent.sendall(b"\x00" + struct.pack(">I", len(payload)) + payload)
    finally:
        agent.close()
        try:
            ws_send(sock, b"", 0x8)
        except Exception:
            pass
