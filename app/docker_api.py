"""Cliente minimo da API do Docker via unix socket (sem SDK)."""
import http.client
import json
import os
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor

SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")


class _UnixConn(http.client.HTTPConnection):
    def __init__(self, path, timeout=10):
        http.client.HTTPConnection.__init__(self, "localhost", timeout=timeout)
        self.path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self.path)
        self.sock = s


def available():
    return os.path.exists(SOCK) and os.access(SOCK, os.R_OK | os.W_OK)


def request(method, path, timeout=10, raw=False):
    c = _UnixConn(SOCK, timeout=timeout)
    try:
        c.request(method, path, headers={"Host": "docker"})
        r = c.getresponse()
        body = r.read()
        if r.status >= 400:
            msg = body.decode("utf-8", "replace")
            try:
                msg = json.loads(msg).get("message", msg)
            except Exception:
                pass
            raise RuntimeError("docker %s: %s" % (r.status, msg))
        if raw:
            return body
        return json.loads(body.decode()) if body else None
    finally:
        c.close()


def _cpu_pct(s):
    try:
        cpu = s["cpu_stats"]
        pre = s["precpu_stats"]
        cd = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sd = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        n = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or []) or 1
        if sd > 0 and cd >= 0:
            return round(cd * 100.0 * n / sd, 1)
    except Exception:
        pass
    return 0.0


def _mem(s):
    try:
        m = s["memory_stats"]
        st = m.get("stats", {})
        cache = st.get("inactive_file", st.get("total_inactive_file", st.get("cache", 0)))
        used = m["usage"] - cache
        return used, m.get("limit", 0)
    except Exception:
        return 0, 0


def _net_io(s):
    rx = tx = 0
    for v in (s.get("networks") or {}).values():
        rx += v.get("rx_bytes", 0)
        tx += v.get("tx_bytes", 0)
    return rx, tx


def _blk_io(s):
    r = w = 0
    for e in ((s.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []):
        if e.get("op", "").lower() == "read":
            r += e.get("value", 0)
        elif e.get("op", "").lower() == "write":
            w += e.get("value", 0)
    return r, w


class DockerWatcher(object):
    """Coleta lista de containers + stats em background."""

    def __init__(self, interval=5.0):
        self.interval = interval
        self.lock = threading.Lock()
        self.containers = []
        self.info = None
        self.error = None
        self.pool = ThreadPoolExecutor(max_workers=8)

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                self.refresh()
            except Exception as e:
                with self.lock:
                    self.error = str(e)
            time.sleep(self.interval)

    def _stats(self, cid):
        try:
            return request("GET", "/containers/%s/stats?stream=false" % cid, timeout=15)
        except Exception:
            return None

    def refresh(self):
        if not available():
            with self.lock:
                self.error = "Docker nao encontrado ou sem permissao no socket"
                self.containers = []
            return
        info = request("GET", "/info")
        lst = request("GET", "/containers/json?all=1")
        running = [c["Id"] for c in lst if c.get("State") == "running"]
        stats = dict(zip(running, self.pool.map(self._stats, running)))
        out = []
        for c in lst:
            s = stats.get(c["Id"])
            used, limit = _mem(s) if s else (0, 0)
            rx, tx = _net_io(s) if s else (0, 0)
            br, bw = _blk_io(s) if s else (0, 0)
            labels = c.get("Labels") or {}
            ports = []
            for p in c.get("Ports") or []:
                if p.get("PublicPort"):
                    ports.append("%s:%s->%s/%s" % (p.get("IP", ""), p["PublicPort"], p["PrivatePort"], p["Type"]))
                else:
                    ports.append("%s/%s" % (p["PrivatePort"], p["Type"]))
            out.append({
                "id": c["Id"][:12],
                "name": (c.get("Names") or ["/?"])[0].lstrip("/"),
                "image": c.get("Image"),
                "state": c.get("State"),
                "status": c.get("Status"),
                "created": c.get("Created"),
                "project": labels.get("com.docker.compose.project", ""),
                "ports": sorted(set(ports)),
                "cpu": _cpu_pct(s) if s else 0.0,
                "mem_used": used, "mem_limit": limit,
                "mem_percent": round(used * 100.0 / limit, 1) if limit else 0,
                "net_rx": rx, "net_tx": tx, "blk_read": br, "blk_write": bw,
                "pids": (s or {}).get("pids_stats", {}).get("current", 0),
                "restart_count": None,
            })
        out.sort(key=lambda x: (x["state"] != "running", x["project"], x["name"]))
        with self.lock:
            self.containers = out
            self.info = {
                "version": info.get("ServerVersion"),
                "containers": info.get("Containers"),
                "running": info.get("ContainersRunning"),
                "paused": info.get("ContainersPaused"),
                "stopped": info.get("ContainersStopped"),
                "images": info.get("Images"),
                "driver": info.get("Driver"),
                "root": info.get("DockerRootDir"),
            }
            self.error = None

    def get(self):
        with self.lock:
            return {"available": self.error is None and self.info is not None,
                    "error": self.error, "info": self.info, "containers": list(self.containers)}


def _resolve(name_or_id):
    """Aceita nome ou id e devolve o id completo (evita injecao no path)."""
    for c in request("GET", "/containers/json?all=1"):
        names = [n.lstrip("/") for n in c.get("Names") or []]
        if c["Id"].startswith(name_or_id) and len(name_or_id) >= 6 or name_or_id in names:
            return c["Id"]
    raise RuntimeError("container nao encontrado: %s" % name_or_id)


def action(name_or_id, act):
    if act not in ("start", "stop", "restart", "pause", "unpause"):
        raise RuntimeError("acao invalida")
    cid = _resolve(name_or_id)
    request("POST", "/containers/%s/%s" % (cid, act), timeout=60, raw=True)
    return True


def logs(name_or_id, tail=200):
    cid = _resolve(name_or_id)
    tail = max(10, min(int(tail), 2000))
    insp = request("GET", "/containers/%s/json" % cid)
    raw = request("GET", "/containers/%s/logs?stdout=1&stderr=1&timestamps=1&tail=%d" % (cid, tail),
                  timeout=20, raw=True)
    if insp.get("Config", {}).get("Tty"):
        return raw.decode("utf-8", "replace")
    # stream multiplexado: [tipo, 0, 0, 0, tamanho(4 bytes)] + payload
    out = []
    i = 0
    while i + 8 <= len(raw):
        size = struct.unpack(">I", raw[i + 4:i + 8])[0]
        out.append(raw[i + 8:i + 8 + size].decode("utf-8", "replace"))
        i += 8 + size
    return "".join(out)


def inspect(name_or_id):
    cid = _resolve(name_or_id)
    d = request("GET", "/containers/%s/json" % cid)
    st = d.get("State", {})
    return {
        "id": d["Id"][:12], "name": d.get("Name", "").lstrip("/"),
        "image": d.get("Config", {}).get("Image"),
        "created": d.get("Created"), "started": st.get("StartedAt"),
        "status": st.get("Status"), "health": (st.get("Health") or {}).get("Status"),
        "restart_count": d.get("RestartCount"),
        "restart_policy": (d.get("HostConfig", {}).get("RestartPolicy") or {}).get("Name"),
        "mounts": [{"src": m.get("Source"), "dst": m.get("Destination"), "rw": m.get("RW")}
                   for m in d.get("Mounts") or []],
        "networks": list((d.get("NetworkSettings", {}).get("Networks") or {}).keys()),
        "cmd": " ".join(d.get("Config", {}).get("Cmd") or []),
    }


def images():
    res = []
    for i in request("GET", "/images/json"):
        tags = i.get("RepoTags") or ["<none>:<none>"]
        res.append({"id": i["Id"].split(":")[-1][:12], "tags": tags, "size": i.get("Size", 0),
                    "created": i.get("Created"), "containers": i.get("Containers", -1)})
    res.sort(key=lambda x: -x["size"])
    return res


def disk_usage():
    d = request("GET", "/system/df", timeout=60)
    img = sum(i.get("Size", 0) for i in d.get("Images") or [])
    img_unused = sum(i.get("Size", 0) for i in d.get("Images") or [] if i.get("Containers", 0) == 0)
    cont = sum(c.get("SizeRw", 0) or 0 for c in d.get("Containers") or [])
    vols = d.get("Volumes") or []
    vol = sum((v.get("UsageData") or {}).get("Size", 0) or 0 for v in vols)
    cache = sum(b.get("Size", 0) for b in d.get("BuildCache") or [])
    return {"images": img, "images_reclaimable": img_unused, "containers": cont,
            "volumes": vol, "volumes_count": len(vols), "build_cache": cache}
