"""Autenticacao do VM//PANEL: usuario unico, scrypt, 2FA (TOTP), sessoes e rate limit.

Tudo com a biblioteca padrao do Python, sem dependencias externas.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import time

AUTH_FILE = os.environ.get("VMPANEL_AUTH", "/etc/vmpanel/auth.json")
# sessoes sobrevivem a reinicios do painel (ex.: botao de atualizar); so guarda o hash do token
SESSIONS_FILE = os.environ.get("VMPANEL_SESSIONS", os.path.join(
    os.path.dirname(os.environ.get("VMPANEL_DB", "/var/lib/vmpanel/vmpanel.db")), "sessions.json"))

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024

SESSION_IDLE = 2 * 3600        # expira apos 2h sem uso
SESSION_ABSOLUTE = 12 * 3600   # e no maximo 12h apos o login

MAX_FAILS_PER_IP = 5           # tentativas erradas por IP...
FAIL_WINDOW = 15 * 60          # ...dentro desta janela
LOCK_BASE = 15 * 60            # bloqueio inicial; dobra a cada reincidencia
GLOBAL_MAX_FAILS = 30          # protecao contra ataques distribuidos


def _b64(b):
    return base64.b64encode(b).decode()


def _unb64(s):
    return base64.b64decode(s.encode())


def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                        p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P, _b64(salt), _b64(dk))


def verify_password(password, stored):
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r),
                              p=int(p), maxmem=SCRYPT_MAXMEM, dklen=len(_unb64(dk)))
        return hmac.compare_digest(calc, _unb64(dk))
    except Exception:
        return False


# ---------------------------------------------------------------- TOTP (RFC 6238)

def new_totp_secret():
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret, counter):
    pad = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + pad)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % 1000000
    return "%06d" % code


def totp_now(secret, t=None):
    return _hotp(secret, int((t or time.time()) // 30))


def _counters(t=None):
    now = int((t or time.time()) // 30)
    return (now - 1, now, now + 1)


def totp_uri(secret, username, issuer="VM-PANEL"):
    return "otpauth://totp/%s:%s?secret=%s&issuer=%s&digits=6&period=30" % (
        issuer, username, secret, issuer)


# ---------------------------------------------------------------- arquivo de credenciais

def load_auth():
    with open(AUTH_FILE) as f:
        return json.load(f)


def save_auth(data):
    d = os.path.dirname(AUTH_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = AUTH_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, AUTH_FILE)


class Auth(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}
        self.fails = {}          # ip -> [timestamps]
        self.locks = {}          # ip -> (ate_quando, reincidencias)
        self.global_fails = []
        self.last_totp_counter = -1
        self._mtime = 0
        self._cfg = None
        self._saved_at = 0
        self._load_sessions()

    def _load_sessions(self):
        try:
            with open(SESSIONS_FILE) as f:
                data = json.load(f)
            m = os.path.getmtime(AUTH_FILE)
        except (OSError, ValueError):
            return
        if data.get("auth_mtime") != m:
            return   # credenciais trocadas desde entao
        now = time.time()
        self._cfg, self._mtime = load_auth(), m
        for k, v in (data.get("sessions") or {}).items():
            if now - v.get("seen", 0) <= SESSION_IDLE and now - v.get("created", 0) <= SESSION_ABSOLUTE:
                self.sessions[k] = v

    def _save_sessions(self):
        """Chamar com self.lock. O desbloqueio do terminal nao e persistido."""
        self._saved_at = time.time()
        try:
            data = {"auth_mtime": self._mtime, "sessions": {
                k: {x: y for x, y in v.items() if x != "term_until"} for k, v in self.sessions.items()}}
            tmp = SESSIONS_FILE + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, SESSIONS_FILE)
        except OSError:
            pass

    # recarrega o arquivo se ele mudar (ex.: `vmpanel passwd`)
    def cfg(self):
        try:
            m = os.path.getmtime(AUTH_FILE)
        except OSError:
            return None
        if m != self._mtime:
            self._cfg = load_auth()
            self._mtime = m
            with self.lock:
                self.sessions.clear()   # credenciais trocadas: derruba todas as sessoes
                self._save_sessions()
        return self._cfg

    def totp_enabled(self):
        c = self.cfg()
        return bool(c and c.get("totp_secret"))

    def locked_for(self, ip):
        with self.lock:
            until, _ = self.locks.get(ip, (0, 0))
            return max(0, int(until - time.time()))

    def _register_fail(self, ip):
        now = time.time()
        with self.lock:
            lst = [t for t in self.fails.get(ip, []) if now - t < FAIL_WINDOW]
            lst.append(now)
            self.fails[ip] = lst
            self.global_fails = [t for t in self.global_fails if now - t < FAIL_WINDOW] + [now]
            if len(lst) >= MAX_FAILS_PER_IP:
                _, strikes = self.locks.get(ip, (0, 0))
                self.locks[ip] = (now + LOCK_BASE * (2 ** min(strikes, 6)), strikes + 1)
                self.fails[ip] = []
                return True
        return False

    def check_login(self, ip, username, password, code):
        """Retorna (ok, motivo)."""
        if self.locked_for(ip):
            return False, "locked"
        with self.lock:
            busy = len(self.global_fails) >= GLOBAL_MAX_FAILS
        if busy:
            time.sleep(3)   # desacelera ataques distribuidos
        c = self.cfg()
        if not c:
            return False, "not_configured"
        user_ok = hmac.compare_digest(username.encode("utf-8"), c["username"].encode("utf-8"))
        pass_ok = verify_password(password, c["password_hash"])  # sempre calcula (tempo constante)
        totp_ok = True
        if c.get("totp_secret"):
            totp_ok = self._check_totp(c["totp_secret"], code)
        if user_ok and pass_ok and totp_ok:
            with self.lock:
                self.fails.pop(ip, None)
                self.locks.pop(ip, None)
            return True, "ok"
        time.sleep(0.8)
        locked = self._register_fail(ip)
        return False, ("locked" if locked else "invalid")

    def _check_totp(self, secret, code):
        code = (code or "").strip().replace(" ", "")
        if len(code) != 6 or not code.isdigit():
            return False
        now = int(time.time() // 30)
        for c in (now - 1, now, now + 1):
            if hmac.compare_digest(_hotp(secret, c), code):
                with self.lock:
                    if c <= self.last_totp_counter:   # impede reuso do mesmo codigo
                        return False
                    self.last_totp_counter = c
                return True
        return False

    # ------------------------------------------------------------ sessoes

    def create_session(self, ip, ua):
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = {
                "created": now, "seen": now, "ip": ip, "ua": (ua or "")[:200]}
            self._save_sessions()
        return token

    def get_session(self, token):
        if not token:
            return None
        self.cfg()
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        with self.lock:
            s = self.sessions.get(key)
            if not s:
                return None
            if now - s["seen"] > SESSION_IDLE or now - s["created"] > SESSION_ABSOLUTE:
                del self.sessions[key]
                self._save_sessions()
                return None
            s["seen"] = now
            if now - self._saved_at > 60:
                self._save_sessions()
            return s

    def destroy_session(self, token):
        if token:
            with self.lock:
                self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)
                self._save_sessions()

    def destroy_all(self):
        with self.lock:
            self.sessions.clear()
            self._save_sessions()

    def list_sessions(self):
        with self.lock:
            return [dict(v) for v in self.sessions.values()]
