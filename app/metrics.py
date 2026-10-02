"""Coleta de metricas do sistema lendo /proc e /sys diretamente (sem psutil)."""
import os
import platform
import pwd
import socket
import subprocess
import threading
import time

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")

REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "vfat", "exfat", "ntfs",
           "f2fs", "jfs", "reiserfs", "nfs", "nfs4", "cifs", "fuseblk"}


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return default


def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, universal_newlines=True)
        return p.returncode, p.stdout
    except Exception:
        return -1, ""


# ---------------------------------------------------------------- leituras basicas

def cpu_times():
    out = {}
    for line in _read("/proc/stat").splitlines():
        if line.startswith("cpu"):
            parts = line.split()
            vals = [int(x) for x in parts[1:9]]
            idle = vals[3] + vals[4]
            out[parts[0]] = (sum(vals), idle, vals)
    return out


def meminfo():
    m = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        try:
            m[k] = int(v.split()[0]) * 1024
        except Exception:
            pass
    total = m.get("MemTotal", 0)
    avail = m.get("MemAvailable", m.get("MemFree", 0))
    used = total - avail
    return {
        "total": total, "used": used, "available": avail,
        "free": m.get("MemFree", 0), "buffers": m.get("Buffers", 0),
        "cached": m.get("Cached", 0) + m.get("SReclaimable", 0),
        "percent": round(used * 100.0 / total, 1) if total else 0,
        "swap_total": m.get("SwapTotal", 0),
        "swap_used": m.get("SwapTotal", 0) - m.get("SwapFree", 0),
        "swap_percent": round((m.get("SwapTotal", 0) - m.get("SwapFree", 0)) * 100.0 /
                              m["SwapTotal"], 1) if m.get("SwapTotal") else 0,
    }


def disks():
    seen = set()
    out = []
    for line in _read("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mnt, fs = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fs not in REAL_FS or dev in seen:
            continue
        if mnt.startswith(("/snap", "/var/lib/docker", "/run", "/boot/efi")):
            continue
        seen.add(dev)
        try:
            st = os.statvfs(mnt)
        except Exception:
            continue
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - st.f_bfree * st.f_frsize
        if total == 0:
            continue
        out.append({
            "device": dev, "mount": mnt, "fs": fs, "total": total, "used": used, "free": free,
            "percent": round(used * 100.0 / (used + free), 1) if used + free else 0,
            "inodes_total": st.f_files,
            "inodes_percent": round((st.f_files - st.f_ffree) * 100.0 / st.f_files, 1) if st.f_files else 0,
        })
    out.sort(key=lambda d: d["mount"])
    return out


def net_counters():
    out = {}
    for line in _read("/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        v = rest.split()
        if len(v) < 16 or name == "lo" or name.startswith(("veth", "ifb")):
            continue
        out[name] = (int(v[0]), int(v[8]), int(v[1]), int(v[9]), int(v[2]) + int(v[10]))
    return out


def disk_io_counters():
    out = {}
    for line in _read("/proc/diskstats").splitlines():
        v = line.split()
        if len(v) < 14:
            continue
        name = v[2]
        if name.startswith(("loop", "ram", "dm-", "sr", "zram")):
            continue
        if not os.path.exists("/sys/block/%s" % name):   # ignora particoes
            continue
        out[name] = (int(v[5]) * 512, int(v[9]) * 512, int(v[12]))
    return out


def temperatures():
    temps = []
    base = "/sys/class/thermal"
    try:
        for z in sorted(os.listdir(base)):
            if not z.startswith("thermal_zone"):
                continue
            t = _read(os.path.join(base, z, "temp")).strip()
            if t:
                temps.append({"name": _read(os.path.join(base, z, "type")).strip() or z,
                              "c": round(int(t) / 1000.0, 1)})
    except Exception:
        pass
    return temps


def static_info():
    osr = {}
    for line in _read("/etc/os-release").splitlines():
        k, _, v = line.partition("=")
        osr[k] = v.strip('"')
    model = ""
    for line in _read("/proc/cpuinfo").splitlines():
        if line.lower().startswith(("model name", "hardware", "cpu model")):
            model = line.split(":", 1)[1].strip()
            break
    if not model:
        rc, out = run(["lscpu"])
        for line in out.splitlines():
            if line.startswith("Model name"):
                model = line.split(":", 1)[1].strip()
                break
    return {
        "hostname": socket.gethostname(),
        "os": osr.get("PRETTY_NAME", platform.system()),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "cpu_model": model or platform.processor() or "desconhecido",
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }


def ip_addresses():
    rc, out = run(["ip", "-o", "addr", "show"])
    addrs = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 4 and p[2] in ("inet", "inet6") and p[1] != "lo":
            if p[3].startswith("fe80"):
                continue
            addrs.append({"iface": p[1], "family": p[2], "addr": p[3]})
    return addrs


# ---------------------------------------------------------------- processos

_users = {}


def _user(uid):
    if uid not in _users:
        try:
            _users[uid] = pwd.getpwuid(uid).pw_name
        except Exception:
            _users[uid] = str(uid)
    return _users[uid]


def proc_snapshot():
    procs = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            raw = _read("/proc/%s/stat" % pid)
            if not raw:
                continue
            rpar = raw.rfind(")")
            name = raw[raw.find("(") + 1:rpar]
            f = raw[rpar + 2:].split()
            cpu = int(f[11]) + int(f[12])
            rss = int(f[21]) * PAGE
            st = os.stat("/proc/%s" % pid)
            cmd = _read("/proc/%s/cmdline" % pid).replace("\x00", " ").strip()
            procs[int(pid)] = {"pid": int(pid), "name": name, "state": f[0], "cpu_ticks": cpu,
                               "rss": rss, "threads": int(f[17]), "user": _user(st.st_uid),
                               "cmd": (cmd or "[%s]" % name)[:300]}
        except Exception:
            continue
    return procs


# ---------------------------------------------------------------- amostrador

class Sampler(object):
    """Roda em background e mantem o ultimo snapshot do sistema."""

    def __init__(self, interval=2.0):
        self.interval = interval
        self.lock = threading.Lock()
        self.static = static_info()
        self.latest = {}
        self.processes = []
        self._prev = None

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while True:
            try:
                self.sample()
            except Exception as e:  # nunca deixa a thread morrer
                print("sampler error:", e, flush=True)
            time.sleep(self.interval)

    def sample(self):
        now = time.time()
        cpu = cpu_times()
        net = net_counters()
        dio = disk_io_counters()
        procs = proc_snapshot()
        prev = self._prev
        self._prev = {"t": now, "cpu": cpu, "net": net, "dio": dio, "procs": procs}
        if not prev:
            return
        dt = max(now - prev["t"], 0.001)

        cores = []
        total_pct = 0.0
        steal_pct = 0.0
        for k in sorted(cpu, key=lambda x: (len(x), x)):
            if k not in prev["cpu"]:
                continue
            tot = cpu[k][0] - prev["cpu"][k][0]
            idl = cpu[k][1] - prev["cpu"][k][1]
            pct = round(100.0 * (tot - idl) / tot, 1) if tot > 0 else 0.0
            if k == "cpu":
                total_pct = pct
                st = cpu[k][2][7] - prev["cpu"][k][2][7]
                steal_pct = round(100.0 * st / tot, 1) if tot > 0 else 0.0
            else:
                cores.append(pct)

        ifaces = []
        rx_rate = tx_rate = 0
        for name, v in net.items():
            p = prev["net"].get(name)
            if not p:
                continue
            rx = max(0, v[0] - p[0]) / dt
            tx = max(0, v[1] - p[1]) / dt
            rx_rate += rx
            tx_rate += tx
            ifaces.append({"name": name, "rx_rate": rx, "tx_rate": tx, "rx_total": v[0],
                           "tx_total": v[1], "errors": v[4]})

        io = []
        r_rate = w_rate = 0
        for name, v in dio.items():
            p = prev["dio"].get(name)
            if not p:
                continue
            r = max(0, v[0] - p[0]) / dt
            w = max(0, v[1] - p[1]) / dt
            busy = min(100.0, max(0, v[2] - p[2]) / (dt * 10.0))
            r_rate += r
            w_rate += w
            io.append({"name": name, "read_rate": r, "write_rate": w, "busy": round(busy, 1)})

        tot_ticks = (cpu["cpu"][0] - prev["cpu"]["cpu"][0]) / max(1, len(cores) or 1)
        plist = []
        states = {}
        for pid, p in procs.items():
            states[p["state"]] = states.get(p["state"], 0) + 1
            old = prev["procs"].get(pid)
            d = p["cpu_ticks"] - old["cpu_ticks"] if old else 0
            pct = round(100.0 * d / tot_ticks, 1) if tot_ticks > 0 else 0.0
            item = dict(p)
            item.pop("cpu_ticks")
            item["cpu"] = pct
            plist.append(item)

        mem = meminfo()
        for p in plist:
            p["mem"] = round(p["rss"] * 100.0 / mem["total"], 1) if mem["total"] else 0

        load = _read("/proc/loadavg").split()
        uptime = float(_read("/proc/uptime", "0 0").split()[0])
        snap = {
            "time": now,
            "uptime": uptime,
            "load": [float(x) for x in load[:3]] if load else [0, 0, 0],
            "cpu": {"percent": total_pct, "cores": cores, "steal": steal_pct},
            "memory": mem,
            "disks": disks(),
            "net": {"rx_rate": rx_rate, "tx_rate": tx_rate, "ifaces": ifaces},
            "io": {"read_rate": r_rate, "write_rate": w_rate, "devices": io},
            "temps": temperatures(),
            "procs": {"total": len(procs), "running": states.get("R", 0),
                      "sleeping": states.get("S", 0) + states.get("I", 0),
                      "zombie": states.get("Z", 0)},
        }
        with self.lock:
            self.latest = snap
            self.processes = plist

    def get(self):
        with self.lock:
            return dict(self.latest)

    def top_processes(self, sort="cpu", limit=40, query=""):
        with self.lock:
            plist = list(self.processes)
        if query:
            q = query.lower()
            plist = [p for p in plist if q in p["cmd"].lower() or q in p["name"].lower()
                     or q == str(p["pid"]) or q == p["user"]]
        key = {"cpu": "cpu", "mem": "rss", "pid": "pid"}.get(sort, "cpu")
        plist.sort(key=lambda p: p[key], reverse=(key != "pid"))
        return plist[:limit]


# ---------------------------------------------------------------- extras (sob demanda, com cache)

_cache = {}


def cached(key, ttl, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def listening_ports():
    rc, out = run(["ss", "-tulnH"])
    ports = []
    for line in out.splitlines():
        p = line.split()
        if len(p) < 5:
            continue
        local = p[4]
        addr, _, port = local.rpartition(":")
        ports.append({"proto": p[0], "addr": addr.strip("[]"), "port": port, "state": p[1]})
    ports.sort(key=lambda x: (int(x["port"]) if x["port"].isdigit() else 0, x["proto"]))
    return ports


def connections_summary():
    rc, out = run(["ss", "-tanH"])
    states = {}
    peers = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) < 5:
            continue
        states[p[0]] = states.get(p[0], 0) + 1
        if p[0] == "ESTAB":
            ip = p[4].rpartition(":")[0].strip("[]")
            if ip not in ("127.0.0.1", "::1") and not ip.startswith("::ffff:127."):
                peers[ip] = peers.get(ip, 0) + 1
    top = sorted(peers.items(), key=lambda x: -x[1])[:10]
    return {"states": states, "top_peers": [{"ip": a, "count": b} for a, b in top]}


def failed_services():
    rc, out = run(["systemctl", "list-units", "--failed", "--no-legend", "--plain", "--no-pager"])
    res = []
    for line in out.splitlines():
        p = line.split(None, 4)
        if p:
            res.append({"unit": p[0], "desc": p[4] if len(p) > 4 else ""})
    return res


WATCH_SERVICES = ["vmpanel", "caddy", "docker", "ssh", "sshd", "cron", "crond", "fail2ban",
                  "nginx", "apache2", "mysql", "postgresql", "redis-server"]


def services_status():
    res = []
    for s in WATCH_SERVICES:
        rc, out = run(["systemctl", "show", s, "--no-pager",
                       "--property=LoadState,ActiveState,SubState,ActiveEnterTimestamp"])
        props = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        if props.get("LoadState") != "loaded":
            continue
        res.append({"name": s, "active": props.get("ActiveState"), "sub": props.get("SubState"),
                    "since": props.get("ActiveEnterTimestamp", "")})
    return res


def logged_users():
    rc, out = run(["who"])
    return [l for l in out.splitlines() if l.strip()]


def ssh_failures():
    """Tentativas de login SSH com falha nas ultimas 24h (via journald)."""
    rc, out = run(["journalctl", "-q", "--no-pager", "-o", "cat", "--since", "24 hours ago",
                   "_COMM=sshd"], timeout=20)
    if rc != 0:
        rc, out = run(["journalctl", "-q", "--no-pager", "-o", "cat", "--since", "24 hours ago",
                       "-t", "sshd"], timeout=20)
    total = 0
    ips = {}
    users = {}
    accepted = []
    for line in out.splitlines():
        if "Failed password" in line or "Invalid user" in line or "authentication failure" in line:
            total += 1
            parts = line.split()
            if " from " in line:
                ip = parts[parts.index("from") + 1] if "from" in parts else "?"
                ips[ip] = ips.get(ip, 0) + 1
            if "Invalid user" in line:
                try:
                    u = parts[parts.index("user") + 1]
                    users[u] = users.get(u, 0) + 1
                except Exception:
                    pass
        elif line.startswith("Accepted"):
            accepted.append(line[:200])
    return {
        "failed_24h": total,
        "top_ips": [{"ip": a, "count": b} for a, b in sorted(ips.items(), key=lambda x: -x[1])[:10]],
        "top_users": [{"user": a, "count": b} for a, b in sorted(users.items(), key=lambda x: -x[1])[:10]],
        "accepted": accepted[-10:],
        "available": rc == 0,
    }


def pending_updates():
    if os.path.exists("/usr/bin/apt"):
        rc, out = run(["apt", "list", "--upgradable"], timeout=60)
        pkgs = [l.split("/")[0] for l in out.splitlines() if "/" in l and "upgradable" in l]
        sec = [l.split("/")[0] for l in out.splitlines() if "-security" in l]
        return {"manager": "apt", "count": len(pkgs), "security": len(sec), "packages": pkgs[:50]}
    if os.path.exists("/usr/bin/dnf"):
        rc, out = run(["dnf", "-q", "check-update"], timeout=90)
        pkgs = [l.split()[0] for l in out.splitlines() if l and not l.startswith(" ") and "." in l.split()[0]]
        return {"manager": "dnf", "count": len(pkgs), "security": None, "packages": pkgs[:50]}
    return {"manager": None, "count": 0, "security": None, "packages": []}


def reboot_required():
    return os.path.exists("/var/run/reboot-required")
