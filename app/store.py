"""Historico de metricas, log de auditoria, configuracoes e alertas (SQLite)."""
import json
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

DB_PATH = os.environ.get("VMPANEL_DB", "/var/lib/vmpanel/vmpanel.db")
RETENTION_DAYS = 30

DEFAULT_SETTINGS = {
    "alert_cpu": 90,
    "alert_mem": 90,
    "alert_disk": 85,
    "alert_minutes": 5,          # quanto tempo acima do limite antes de alertar
    "alert_container_down": True,
    "alert_login": True,
    "alert_cooldown_min": 30,
    "discord_webhook": "",
    "telegram_token": "",
    "telegram_chat_id": "",
    "oracle_idle_watch": True,
}


class Store(object):
    def __init__(self, path=DB_PATH):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS samples(
                ts INTEGER PRIMARY KEY, cpu REAL, mem REAL, swap REAL, disk REAL,
                load1 REAL, rx REAL, tx REAL, rd REAL, wr REAL, containers INTEGER);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, kind TEXT, ip TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
            """)
            self.db.commit()

    # ------------------------------------------------------------ settings

    def settings(self):
        s = dict(DEFAULT_SETTINGS)
        with self.lock:
            for k, v in self.db.execute("SELECT k, v FROM settings"):
                try:
                    s[k] = json.loads(v)
                except Exception:
                    pass
        return s

    def save_settings(self, data):
        with self.lock:
            for k, v in data.items():
                if k not in DEFAULT_SETTINGS:
                    continue
                t = type(DEFAULT_SETTINGS[k])
                try:
                    v = (v in (True, "true", "1", 1, "on")) if t is bool else t(v)
                except Exception:
                    continue
                self.db.execute("INSERT OR REPLACE INTO settings(k, v) VALUES(?, ?)", (k, json.dumps(v)))
            self.db.commit()

    # ------------------------------------------------------------ eventos / auditoria

    def event(self, kind, ip="", detail=""):
        with self.lock:
            self.db.execute("INSERT INTO events(ts, kind, ip, detail) VALUES(?,?,?,?)",
                            (int(time.time()), kind, ip, str(detail)[:500]))
            self.db.commit()

    def events(self, limit=100):
        with self.lock:
            rows = self.db.execute("SELECT ts, kind, ip, detail FROM events ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()
        return [{"ts": r[0], "kind": r[1], "ip": r[2], "detail": r[3]} for r in rows]

    # ------------------------------------------------------------ historico

    def add_sample(self, row):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)", row)
            self.db.execute("DELETE FROM samples WHERE ts < ?", (int(time.time()) - RETENTION_DAYS * 86400,))
            self.db.execute("DELETE FROM events WHERE ts < ?", (int(time.time()) - 90 * 86400,))
            self.db.commit()

    def history(self, seconds, points=240):
        since = int(time.time()) - seconds
        bucket = max(60, seconds // points)
        with self.lock:
            rows = self.db.execute(
                "SELECT (ts/?)*? AS b, AVG(cpu), AVG(mem), AVG(swap), AVG(disk), AVG(load1),"
                " AVG(rx), AVG(tx), AVG(rd), AVG(wr), MAX(cpu) FROM samples WHERE ts >= ?"
                " GROUP BY b ORDER BY b", (bucket, bucket, since)).fetchall()
        keys = ["ts", "cpu", "mem", "swap", "disk", "load1", "rx", "tx", "rd", "wr", "cpu_max"]
        return [dict(zip(keys, [round(x, 2) if isinstance(x, float) else x for x in r])) for r in rows]

    def percentile(self, col, seconds, pct):
        if col not in ("cpu", "mem", "rx", "tx"):
            raise ValueError(col)
        since = int(time.time()) - seconds
        with self.lock:
            vals = [r[0] for r in self.db.execute(
                "SELECT %s FROM samples WHERE ts >= ? ORDER BY %s" % (col, col), (since,))]
            first = self.db.execute("SELECT MIN(ts) FROM samples").fetchone()[0]
        if not vals:
            return None, 0
        idx = min(len(vals) - 1, int(len(vals) * pct / 100.0))
        return vals[idx], (time.time() - first) if first else 0


# ---------------------------------------------------------------- notificacoes

def _post_json(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "vmpanel"})
    urllib.request.urlopen(req, timeout=10).read()


def notify(settings, text):
    """Envia para Discord e/ou Telegram, se configurados. Retorna lista de erros."""
    errors = []
    if settings.get("discord_webhook"):
        try:
            _post_json(settings["discord_webhook"], {"content": text[:1900]})
        except Exception as e:
            errors.append("discord: %s" % e)
    if settings.get("telegram_token") and settings.get("telegram_chat_id"):
        try:
            url = "https://api.telegram.org/bot%s/sendMessage" % urllib.parse.quote(settings["telegram_token"], safe=":")
            _post_json(url, {"chat_id": settings["telegram_chat_id"], "text": text[:3900]})
        except Exception as e:
            errors.append("telegram: %s" % e)
    return errors


class Recorder(object):
    """A cada minuto grava a media no historico e avalia os alertas."""

    def __init__(self, store, sampler, docker, hostname):
        self.store = store
        self.sampler = sampler
        self.docker = docker
        self.hostname = hostname
        self.acc = []
        self.over = {}          # metrica -> minutos consecutivos acima do limite
        self.last_alert = {}
        self.last_running = None
        self.active_alerts = []

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        tick = 0
        while True:
            time.sleep(5)
            s = self.sampler.get()
            if s:
                self.acc.append(s)
            tick += 1
            if tick % 12 == 0 and self.acc:
                try:
                    self.flush()
                except Exception as e:
                    print("recorder error:", e, flush=True)

    def flush(self):
        acc, self.acc = self.acc, []
        n = float(len(acc))

        def avg(fn):
            return sum(fn(s) for s in acc) / n

        root = [d for d in acc[-1]["disks"] if d["mount"] == "/"] or acc[-1]["disks"][:1]
        worst = max(acc[-1]["disks"], key=lambda x: x["percent"]) if acc[-1]["disks"] else None
        d = self.docker.get()
        running = [c["name"] for c in d["containers"] if c["state"] == "running"]
        row = (int(time.time()), avg(lambda s: s["cpu"]["percent"]), avg(lambda s: s["memory"]["percent"]),
               avg(lambda s: s["memory"]["swap_percent"]), root[0]["percent"] if root else 0,
               avg(lambda s: s["load"][0]), avg(lambda s: s["net"]["rx_rate"]),
               avg(lambda s: s["net"]["tx_rate"]), avg(lambda s: s["io"]["read_rate"]),
               avg(lambda s: s["io"]["write_rate"]), len(running))
        self.store.add_sample(row)
        self.check_alerts(row[1], row[2], worst, d, running)

    def _fire(self, key, text, cfg):
        now = time.time()
        if now - self.last_alert.get(key, 0) < cfg["alert_cooldown_min"] * 60:
            return
        self.last_alert[key] = now
        msg = "[VM//PANEL %s] %s" % (self.hostname, text)
        self.store.event("alert", "", text)
        threading.Thread(target=notify, args=(cfg, msg), daemon=True).start()

    def check_alerts(self, cpu, mem, disk, docker, running):
        cfg = self.store.settings()
        active = []
        for key, val, lim in (("cpu", cpu, cfg["alert_cpu"]), ("mem", mem, cfg["alert_mem"])):
            if val >= lim:
                self.over[key] = self.over.get(key, 0) + 1
                active.append("%s em %.0f%% (limite %s%%)" % (key.upper(), val, lim))
                if self.over[key] >= cfg["alert_minutes"]:
                    self._fire(key, "%s acima de %s%% ha %d min (atual %.0f%%)" %
                               (key.upper(), lim, self.over[key], val), cfg)
            else:
                self.over[key] = 0
        if disk and disk["percent"] >= cfg["alert_disk"]:
            active.append("DISCO %s em %.0f%%" % (disk["mount"], disk["percent"]))
            self._fire("disk", "Disco %s em %.0f%% (limite %s%%)" % (disk["mount"], disk["percent"], cfg["alert_disk"]), cfg)
        if cfg["alert_container_down"] and docker["available"]:
            if self.last_running is not None:
                for name in set(self.last_running) - set(running):
                    self._fire("ct:" + name, "Container parou: %s" % name, cfg)
            self.last_running = running
        if cfg["oracle_idle_watch"]:
            p95, span = self.store.percentile("cpu", 7 * 86400, 95)
            if p95 is not None and span > 86400 and p95 < 20:
                active.append("Oracle: CPU p95 7d em %.1f%% (<20%% = risco de recuperacao)" % p95)
        self.active_alerts = active
