#!/usr/bin/env python3
"""VM//PANEL - manutencao da VM (roda como root, chamado pelo agente).

Limpeza de espaco, verificacao da instalacao, atualizacoes do sistema e agendamentos.
Tudo aqui sao comandos FIXOS: do navegador so chegam ids de uma lista fechada,
nomes de pacote validados por regex e horarios.

As tarefas longas (limpar, atualizar, reiniciar) rodam fora do agente, numa unidade
systemd temporaria (`python3 maint.py run`), para nao morrer se o apt reiniciar servicos.
"""
import datetime
import glob
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docker_api  # noqa: E402

APP_DIR = os.environ.get("VMPANEL_DIR", "/opt/vmpanel")
CONF_DIR = "/etc/vmpanel"
DATA_DIR = "/var/lib/vmpanel"
JOB_FILE = os.path.join(DATA_DIR, "maint-job.json")
JOB_LOG = os.path.join(DATA_DIR, "maint.log")
SCHED_FILE = os.path.join(CONF_DIR, "schedule.json")

JOURNAL_KEEP = 200 * 1024 * 1024      # o journal fica com no maximo 200 MB depois da limpeza
TMP_DAYS = 7                          # arquivos temporarios sem uso ha mais de 7 dias
PKG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:~-]{0,127}$")
APT = ["apt-get", "-y", "-q", "-o", "DPkg::Lock::Timeout=600",
       "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"]
APT_ENV = {"DEBIAN_FRONTEND": "noninteractive", "NEEDRESTART_MODE": "a", "NEEDRESTART_SUSPEND": "1"}


# ---------------------------------------------------------------- utilitarios

def run(cmd, timeout=60, env=None):
    e = dict(os.environ)
    e.update(env or {})
    e.setdefault("LANG", "C.UTF-8")
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=timeout, env=e)
        return p.returncode, p.stdout
    except Exception as ex:
        return -1, str(ex)


def which(name):
    return shutil.which(name) is not None


def pkg_mgr():
    if which("apt-get"):
        return "apt"
    if which("dnf"):
        return "dnf"
    if which("yum"):
        return "yum"
    return None


def human_to_bytes(txt):
    m = re.match(r"([\d.]+)\s*([KMGTP]?)i?B?", txt.strip(), re.I)
    if not m:
        return 0
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4, "P": 1024 ** 5}
    return int(float(m.group(1)) * mult[m.group(2).upper()])


def fmt(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%.0f %s" if u == "B" else "%.1f %s") % (n, u)
        n /= 1024


def du(paths):
    """Tamanho somado (bytes) de arquivos/pastas, sem sair do sistema de arquivos."""
    paths = [p for p in paths if os.path.lexists(p)]
    if not paths:
        return 0
    rc, out = run(["du", "-sxbc", "--"] + paths, timeout=120)
    for line in reversed(out.splitlines()):
        if line.endswith("\ttotal"):
            return int(line.split("\t")[0])
    return 0


def disk_free(path="/"):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def home_dirs():
    homes = {"/root"}
    for p in pwd.getpwall():
        if p.pw_uid >= 1000 and p.pw_dir.startswith("/home/") and os.path.isdir(p.pw_dir):
            homes.add(p.pw_dir)
    return sorted(homes)


def _new_id():
    return "%x%s" % (int(time.time()), os.urandom(3).hex())


def docker_ok():
    return os.path.exists(docker_api.SOCK)


# ---------------------------------------------------------------- o que da para limpar

def _walk_files(roots, match, xdev=True):
    """Arquivos regulares sob roots que satisfazem match(path, stat). Nao segue links."""
    for root in roots:
        if not os.path.isdir(root):
            continue
        dev = os.lstat(root).st_dev
        for d, dirs, files in os.walk(root):
            if xdev:
                dirs[:] = [x for x in dirs if _same_dev(os.path.join(d, x), dev)]
            for f in files:
                p = os.path.join(d, f)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if not os.path.isfile(p) or os.path.islink(p):
                    continue
                if match(p, st):
                    yield p, st


def _same_dev(p, dev):
    try:
        st = os.lstat(p)
        return st.st_dev == dev and not os.path.islink(p)
    except OSError:
        return False


ROTATED = re.compile(r"(\.(gz|xz|bz2|zst|old)|\.\d+|-\d{8})$")


def _old_log(p, st):
    return "/journal/" not in p and ROTATED.search(p) is not None


def _old_tmp(p, st):
    limit = time.time() - TMP_DAYS * 86400
    return st.st_mtime < limit and st.st_atime < limit and "/.X11-unix/" not in p


def _remove_files(roots, match):
    n = 0
    for p, st in list(_walk_files(roots, match)):
        try:
            os.unlink(p)
            n += 1
        except OSError:
            pass
    print("%d arquivo(s) removido(s)" % n, flush=True)


USER_CACHES = [".cache/pip", ".npm/_cacache", ".cache/yarn", ".cache/go-build", ".cache/thumbnails",
               ".cache/composer", ".cache/node-gyp", ".cache/typescript"]


def _user_cache_dirs():
    return [os.path.join(h, c) for h in home_dirs() for c in USER_CACHES if os.path.isdir(os.path.join(h, c))]


def _rm_tree_contents(dirs):
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
        print("limpo: %s" % d, flush=True)


def _autoremove_list():
    rc, out = run(["apt-get", "-s", "autoremove"], timeout=60)
    return [l.split()[1] for l in out.splitlines() if l.startswith("Remv ")]


def _pkg_sizes(names):
    if not names:
        return 0
    rc, out = run(["dpkg-query", "-W", "-f=${Installed-Size}\n"] + names, timeout=30)
    return sum(int(x) for x in out.split() if x.isdigit()) * 1024


def _snap_disabled():
    if not which("snap"):
        return []
    rc, out = run(["snap", "list", "--all"], timeout=30)
    res = []
    for line in out.splitlines()[1:]:
        p = line.split()
        if len(p) >= 3 and "disabled" in line:
            f = "/var/lib/snapd/snaps/%s_%s.snap" % (p[0], p[2])
            res.append((p[0], p[2], os.path.getsize(f) if os.path.exists(f) else 0))
    return res


def _docker_df():
    return docker_api.request("GET", "/system/df", timeout=90)


def _is_anon_volume(name):
    return re.match(r"^[0-9a-f]{64}$", name or "") is not None


def _docker_prune(path, label):
    r = docker_api.request("POST", path, timeout=1800) or {}
    print("%s: %s liberados" % (label, fmt(r.get("SpaceReclaimed", 0))), flush=True)


def _docker_rm_anon_volumes():
    # um por um: em Docker antigo o /volumes/prune apagaria tambem os volumes com nome
    n = 0
    for v in _docker_df().get("Volumes") or []:
        if (v.get("UsageData") or {}).get("RefCount", 1) == 0 and _is_anon_volume(v.get("Name")):
            try:
                docker_api.request("DELETE", "/volumes/%s" % v["Name"], timeout=120, raw=True)
                n += 1
            except Exception as e:
                print("volume %s: %s" % (v["Name"][:12], e), flush=True)
    print("%d volume(s) anonimo(s) apagado(s)" % n, flush=True)


def _docker_logs():
    return glob.glob("/var/lib/docker/containers/*/*-json.log")


def _truncate(files):
    for f in files:
        try:
            with open(f, "r+") as fh:
                fh.truncate(0)
        except OSError:
            pass
    print("%d log(s) zerado(s)" % len(files), flush=True)


def _measure(cid, df_cache):
    """Retorna (bytes, detalhe) do que a categoria libera. bytes None = nao da para estimar."""
    pm = pkg_mgr()
    if cid == "pkgcache":
        if pm == "apt":
            return du(glob.glob("/var/cache/apt/archives/*.deb") + glob.glob("/var/cache/apt/*.bin")), "/var/cache/apt"
        return du(["/var/cache/dnf", "/var/cache/yum"]), "/var/cache/" + (pm or "?")
    if cid == "autoremove":
        if pm != "apt":
            return None, "pacotes que ninguem mais usa"
        names = _autoremove_list()
        kernels = [n for n in names if n.startswith("linux-")]
        det = "%d pacote(s)" % len(names)
        if kernels:
            det += ", incluindo kernels antigos"
        return _pkg_sizes(names), det
    if cid == "journal":
        rc, out = run(["journalctl", "--disk-usage"], timeout=30)
        m = re.search(r"take up ([\d.]+\s*[KMGTP]?)", out)
        used = human_to_bytes(m.group(1)) if m else 0
        return max(0, used - JOURNAL_KEEP), "journal usa %s, fica com ate %s" % (fmt(used), fmt(JOURNAL_KEEP))
    if cid == "oldlogs":
        files = list(_walk_files(["/var/log"], _old_log))
        return sum(st.st_size for _, st in files), "%d arquivo(s) .gz/.1/.old em /var/log" % len(files)
    if cid == "tmp":
        files = list(_walk_files(["/tmp", "/var/tmp"], _old_tmp))
        return sum(st.st_size for _, st in files), "%d arquivo(s) sem uso ha %d+ dias" % (len(files), TMP_DAYS)
    if cid == "crash":
        files = glob.glob("/var/crash/*") + glob.glob("/var/lib/systemd/coredump/*")
        return du(files), "%d relatorio(s) de travamento" % len(files)
    if cid == "usercache":
        dirs = _user_cache_dirs()
        return du(dirs), ", ".join(d.replace("/home/", "~") for d in dirs[:4]) or "nada"
    if cid == "snap":
        revs = _snap_disabled()
        return sum(r[2] for r in revs), "%d revisao(oes) antigas" % len(revs)
    if cid.startswith("docker_"):
        if cid == "docker_logs":
            files = _docker_logs()
            return du(files), "%d container(s)" % len(files)
        if "df" not in df_cache:
            df_cache["df"] = _docker_df()
        df = df_cache["df"]
        imgs = df.get("Images") or []
        if cid == "docker_dangling":
            sel = [i for i in imgs if (not i.get("RepoTags") or i["RepoTags"] == ["<none>:<none>"]) and i.get("Containers", 0) == 0]
            return sum(i.get("Size", 0) for i in sel), "%d imagem(ns) <none>" % len(sel)
        if cid == "docker_images":
            sel = [i for i in imgs if i.get("Containers", 0) == 0]
            return sum(i.get("Size", 0) for i in sel), "%d imagem(ns) sem container" % len(sel)
        if cid == "docker_build":
            sel = [b for b in df.get("BuildCache") or [] if not b.get("InUse")]
            return sum(b.get("Size", 0) for b in sel), "%d camada(s) de cache" % len(sel)
        if cid == "docker_containers":
            sel = [c for c in df.get("Containers") or [] if c.get("State") in ("exited", "created", "dead")]
            return sum(c.get("SizeRw", 0) or 0 for c in sel), "%d container(s) parado(s)" % len(sel)
        if cid == "docker_volumes":
            sel = [v for v in df.get("Volumes") or [] if (v.get("UsageData") or {}).get("RefCount", 1) == 0
                   and _is_anon_volume(v.get("Name"))]
            return sum(max(0, (v.get("UsageData") or {}).get("Size", 0)) for v in sel), "%d volume(s) anonimo(s) sem uso" % len(sel)
    return None, ""


# id, titulo, explicacao, marcado por padrao (limpeza rapida), perigoso
CATEGORIES = [
    ("pkgcache", "Cache de pacotes", "Instaladores .deb/.rpm ja usados. Sao baixados de novo se precisar.", True, False),
    ("autoremove", "Pacotes orfaos e kernels antigos", "Dependencias que nada mais usa. O kernel atual nunca e removido.", True, False),
    ("journal", "Logs do sistema (journal)", "Mantem os ultimos 200 MB de logs do systemd.", True, False),
    ("oldlogs", "Logs antigos rotacionados", "Arquivos .gz, .1 e .old em /var/log. Os logs atuais ficam.", True, False),
    ("tmp", "Arquivos temporarios", "Arquivos em /tmp e /var/tmp sem uso ha mais de 7 dias.", True, False),
    ("crash", "Relatorios de travamento", "Core dumps e relatorios em /var/crash.", True, False),
    ("usercache", "Cache de pip, npm, yarn e go", "Caches de download dos usuarios. Sao refeitos sozinhos.", True, False),
    ("snap", "Versoes antigas do snap", "Revisoes desativadas que o snap guarda para voltar versao.", True, False),
    ("docker_dangling", "Docker: imagens soltas (<none>)", "Sobras de builds e pulls antigos. Nenhum container usa.", True, False),
    ("docker_build", "Docker: cache de build", "Camadas guardadas para acelerar builds. Sao refeitas no proximo build.", True, False),
    ("docker_logs", "Docker: logs dos containers", "Zera os arquivos de log dos containers (o container continua rodando).", False, False),
    ("docker_images", "Docker: todas as imagens sem uso", "Imagens que nenhum container usa agora. Sao baixadas de novo se precisar.", False, False),
    ("docker_containers", "Docker: containers parados", "Apaga containers que estao parados (os dados de volumes ficam).", False, True),
    ("docker_volumes", "Docker: volumes anonimos sem uso", "Apaga dados de volumes sem nome que nenhum container usa. Nao tem volta.", False, True),
]
CAT_IDS = [c[0] for c in CATEGORIES]


def _available(cid):
    pm = pkg_mgr()
    if cid in ("pkgcache", "autoremove"):
        return pm in ("apt", "dnf", "yum")
    if cid == "snap":
        return which("snap")
    if cid.startswith("docker_"):
        return docker_ok()
    return True


def scan():
    res = []
    df_cache = {}
    for cid, label, desc, default, danger in CATEGORIES:
        if not _available(cid):
            continue
        try:
            size, detail = _measure(cid, df_cache)
        except Exception as e:
            size, detail = None, "erro ao medir: %s" % e
        res.append({"id": cid, "label": label, "desc": desc, "default": default, "danger": danger,
                    "bytes": size, "detail": detail})
    quick = sum(c["bytes"] or 0 for c in res if c["default"])
    return {"ok": True, "categories": res, "quick_bytes": quick, "free": disk_free("/"), "time": time.time()}


def clean_steps(cid):
    """Passos (titulo, comando ou funcao) para limpar uma categoria."""
    pm = pkg_mgr()
    if cid == "pkgcache":
        return [("Limpando cache de pacotes", ["apt-get", "clean"] if pm == "apt" else [pm, "clean", "all"])]
    if cid == "autoremove":
        if pm == "apt":
            return [("Removendo pacotes orfaos e kernels antigos", APT + ["--purge", "autoremove"])]
        return [("Removendo pacotes orfaos", [pm, "-y", "autoremove"])]
    if cid == "journal":
        return [("Compactando logs do journal", ["journalctl", "--vacuum-size=%dM" % (JOURNAL_KEEP // 1024 // 1024)])]
    if cid == "oldlogs":
        return [("Apagando logs antigos", lambda: _remove_files(["/var/log"], _old_log))]
    if cid == "tmp":
        return [("Apagando temporarios antigos", lambda: _remove_files(["/tmp", "/var/tmp"], _old_tmp))]
    if cid == "crash":
        return [("Apagando relatorios de travamento", lambda: [os.unlink(f) for f in glob.glob("/var/crash/*") +
                                                               glob.glob("/var/lib/systemd/coredump/*") if os.path.isfile(f)])]
    if cid == "usercache":
        return [("Limpando caches de pip/npm/yarn/go", lambda: _rm_tree_contents(_user_cache_dirs()))]
    if cid == "snap":
        return [("Removendo snap %s (rev %s)" % (n, r), ["snap", "remove", n, "--revision=" + r]) for n, r, _ in _snap_disabled()]
    if cid == "docker_dangling":
        return [("Docker: removendo imagens soltas", lambda: _docker_prune("/images/prune", "imagens soltas"))]
    if cid == "docker_images":
        return [("Docker: removendo imagens sem uso",
                 lambda: _docker_prune("/images/prune?filters=%7B%22dangling%22%3A%5B%22false%22%5D%7D", "imagens sem uso"))]
    if cid == "docker_build":
        return [("Docker: limpando cache de build", lambda: _docker_prune("/build/prune?all=1", "cache de build"))]
    if cid == "docker_containers":
        return [("Docker: apagando containers parados", lambda: _docker_prune("/containers/prune", "containers parados"))]
    if cid == "docker_volumes":
        return [("Docker: apagando volumes anonimos sem uso", _docker_rm_anon_volumes)]
    if cid == "docker_logs":
        return [("Docker: zerando logs dos containers", lambda: _truncate(_docker_logs()))]
    return []


def quick_items():
    return [c[0] for c in CATEGORIES if c[3] and _available(c[0])]


def drop_ram_cache():
    def mem():
        m = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                m[k] = int(v.split()[0]) * 1024
        return m
    before = mem()
    os.sync()
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3\n")
    after = mem()
    print("Cache de memoria: %s -> %s (livre agora: %s)" % (fmt(before.get("Cached", 0)), fmt(after.get("Cached", 0)),
                                                            fmt(after.get("MemFree", 0))), flush=True)


# ---------------------------------------------------------------- explorar espaco

def du_dir(path):
    path = os.path.realpath(path or "/")
    if not os.path.isabs(path) or not os.path.isdir(path):
        return {"ok": False, "error": "pasta invalida"}
    rc, out = run(["du", "-xb", "-d", "1", "--", path], timeout=180)
    entries = []
    total = 0
    for line in out.splitlines():
        size, _, p = line.partition("\t")
        if not size.isdigit():
            continue
        if p == path:
            total = int(size)
            continue
        entries.append({"name": os.path.basename(p), "path": p, "bytes": int(size), "dir": True})
    try:
        for e in os.scandir(path):
            if e.is_file(follow_symlinks=False):
                entries.append({"name": e.name, "path": e.path, "bytes": e.stat(follow_symlinks=False).st_size, "dir": False})
    except OSError:
        pass
    entries.sort(key=lambda x: -x["bytes"])
    return {"ok": True, "path": path, "parent": os.path.dirname(path) if path != "/" else None,
            "total": total, "entries": entries[:60], "timeout": rc == -1}


def big_files(limit=40):
    rc, out = run(["find", "/", "-xdev", "-type", "f", "-size", "+100M", "-printf", "%s\t%p\n"], timeout=180)
    files = []
    for line in out.splitlines():
        size, _, p = line.partition("\t")
        if size.isdigit():
            files.append({"path": p, "bytes": int(size)})
    files.sort(key=lambda x: -x["bytes"])
    return {"ok": True, "files": files[:limit]}


# ---------------------------------------------------------------- atualizacoes do sistema

def updates_list():
    pm = pkg_mgr()
    pkgs = []
    if pm == "apt":
        rc, out = run(["apt", "list", "--upgradable"], timeout=90)
        for line in out.splitlines():
            if "upgradable from" not in line or "/" not in line:
                continue
            parts = line.split()
            name, _, suites = parts[0].partition("/")
            old = line.split("upgradable from:")[-1].strip(" ]")
            pkgs.append({"name": name, "new": parts[1] if len(parts) > 1 else "", "old": old,
                         "security": "-security" in suites})
        stamp = "/var/lib/apt/periodic/update-success-stamp"
        if not os.path.exists(stamp):
            stamp = "/var/lib/apt/lists"
        checked = os.path.getmtime(stamp) if os.path.exists(stamp) else None
    elif pm in ("dnf", "yum"):
        rc, out = run([pm, "-q", "check-update"], timeout=180)
        rc2, sec = run([pm, "-q", "updateinfo", "list", "--security"], timeout=120)
        secnames = set()
        for l in sec.splitlines():
            p = l.split()
            if len(p) >= 3:
                secnames.add(p[-1].rsplit("-", 2)[0])
        for line in out.splitlines():
            p = line.split()
            if len(p) >= 3 and "." in p[0] and not line.startswith(" "):
                n = p[0].rsplit(".", 1)[0]
                pkgs.append({"name": n, "new": p[1], "old": "", "security": n in secnames})
        checked = time.time()
    else:
        return {"ok": True, "manager": None, "packages": []}
    pkgs.sort(key=lambda x: (not x["security"], x["name"]))
    return {"ok": True, "manager": pm, "packages": pkgs, "checked": checked,
            "reboot_required": reboot_required(), "auto": auto_updates()}


def reboot_required():
    if os.path.exists("/var/run/reboot-required"):
        return True
    if which("needs-restarting"):
        return run(["needs-restarting", "-r"], timeout=30)[0] == 1
    return False


def auto_updates():
    """Atualizacoes de seguranca automaticas ja ligadas na VM?"""
    if os.path.exists("/etc/apt/apt.conf.d/20auto-upgrades"):
        with open("/etc/apt/apt.conf.d/20auto-upgrades") as f:
            return 'Unattended-Upgrade "1"' in f.read()
    return run(["systemctl", "is-enabled", "dnf-automatic.timer"], timeout=10)[1].strip() == "enabled"


def upgrade_steps(mode, packages=None, reboot="no"):
    pm = pkg_mgr()
    steps = []
    if pm == "apt":
        steps.append(("Buscando a lista de pacotes (apt update)", APT + ["update"]))
        if mode == "all":
            steps.append(("Atualizando todos os pacotes", APT + ["--with-new-pkgs", "upgrade"]))
        elif mode == "security":
            steps.append(("Atualizando so os pacotes de seguranca", _apt_security))
        else:
            steps.append(("Atualizando %d pacote(s) escolhido(s)" % len(packages), APT + ["--only-upgrade", "install"] + packages))
    elif pm in ("dnf", "yum"):
        if mode == "all":
            steps.append(("Atualizando todos os pacotes", [pm, "-y", "upgrade"]))
        elif mode == "security":
            steps.append(("Atualizando so os pacotes de seguranca", [pm, "-y", "upgrade", "--security"]))
        else:
            steps.append(("Atualizando %d pacote(s) escolhido(s)" % len(packages), [pm, "-y", "upgrade"] + packages))
    else:
        raise ValueError("gerenciador de pacotes nao suportado")
    if reboot == "if-needed":
        steps.append(("Reiniciando se a atualizacao pedir", _reboot_if_needed))
    return steps


def _apt_security():
    names = [p["name"] for p in updates_list()["packages"] if p["security"]]
    if not names:
        print("Nenhuma atualizacao de seguranca pendente.", flush=True)
        return
    _stream(APT + ["--only-upgrade", "install"] + names, APT_ENV)


def _reboot_if_needed():
    if reboot_required():
        print("A atualizacao pediu reinicio: a VM reinicia em 1 minuto.", flush=True)
        _stream(["shutdown", "-r", "+1", "VM//PANEL: reinicio apos atualizacao"])
    else:
        print("Nao precisa reiniciar.", flush=True)


# ---------------------------------------------------------------- verificar instalacao e acessos

def _env():
    d = {}
    try:
        with open(os.path.join(CONF_DIR, "env")) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k:
                    d[k] = v
    except OSError:
        pass
    return d


def check():
    """Lista de verificacoes: ok True (verde), False (problema) ou None (aviso/informacao)."""
    items = []

    def add(label, ok, detail, fix=False):
        detail = (detail or "").strip().splitlines()
        items.append({"label": label, "ok": ok, "detail": detail[0][:200] if detail else "", "fix": fix})

    env = _env()
    a = run(["systemctl", "is-active", "vmpanel"], 10)[1].strip()
    add("Servico do painel (vmpanel)", a == "active", a)
    e = run(["systemctl", "is-enabled", "vmpanel", "vmpanel-agent"], 10)[1].split()
    add("Painel e agente sobem com a VM", e == ["enabled", "enabled"], " / ".join(e) or "?", fix=True)
    add("Comando vmpanel na VM", os.path.exists("/usr/local/bin/vmpanel"), "/usr/local/bin/vmpanel", fix=True)

    auth = os.path.join(CONF_DIR, "auth.json")
    if os.path.exists(auth):
        st = os.stat(auth)
        good = (st.st_mode & 0o777) == 0o640 and st.st_uid == 0
        add("Credenciais protegidas", good, "%s (%o)" % (auth, st.st_mode & 0o777), fix=not good)
    else:
        add("Credenciais protegidas", False, "faltando: rode sudo vmpanel passwd")

    try:
        groups = run(["id", "-nG", "vmpanel"], 10)[1].split()
    except Exception:
        groups = []
    if docker_ok():
        add("Painel tem acesso ao Docker", "docker" in groups, "grupo docker" if "docker" in groups else "fora do grupo docker", fix=True)
    jg = [g for g in ("systemd-journal", "adm") if g in groups]
    add("Painel le os logs (SSH, OOM)", bool(jg), ", ".join(jg) or "fora dos grupos systemd-journal/adm", fix=not jg)

    dom = env.get("VMPANEL_DOMAIN", "")
    proxy = env.get("VMPANEL_PROXY", "")
    if not dom:
        add("Acesso pela internet", None, "so local (tunel SSH). Publique com: sudo vmpanel domain SEU.DOMINIO")
    elif proxy == "traefik":
        rc, out = run(["docker", "ps", "--format", "{{.Names}}"], 15)
        up = any(l.startswith("vmpanel-proxy") for l in out.splitlines())
        add("Ponte do Traefik (vmpanel-proxy)", up, "%s -> rodando" % dom if up else "parada", fix=not up)
    else:
        c = run(["systemctl", "is-active", "caddy"], 10)[1].strip()
        add("HTTPS (Caddy)", c == "active", "%s -> %s" % (dom, c), fix=c != "active")

    ntp = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], 10)[1].strip()
    add("Relogio sincronizado (2FA depende)", ntp == "yes" if ntp else None, ntp or "nao deu para verificar")

    if os.path.isdir(os.path.join(APP_DIR, ".git")):
        dirty = run(["git", "-C", APP_DIR, "status", "--porcelain"], 15)[1].strip()
        rev = run(["git", "-C", APP_DIR, "log", "-1", "--format=%h %cd", "--date=short"], 10)[1].strip()
        add("Codigo do painel intacto", not dirty, rev + ("" if not dirty else " (arquivos alterados a mao)"))
    else:
        add("Codigo do painel intacto", False, "%s nao e um repositorio git" % APP_DIR)

    missing = [t for t in ("git", "curl", "ss", "journalctl", "systemd-run", "du", "find") if not which(t)]
    add("Ferramentas do sistema", not missing, "faltando: " + ", ".join(missing) if missing else "todas presentes")

    free = disk_free("/")
    st = os.statvfs("/")
    pct = 100.0 * free / (st.f_blocks * st.f_frsize) if st.f_blocks else 0
    add("Espaco livre em /", True if pct >= 15 else (None if pct >= 5 else False), "%s livres (%.0f%%)" % (fmt(free), pct))

    term = env.get("VMPANEL_TERMINAL", "on")
    tu = env.get("VMPANEL_TERM_USER", "")
    add("Terminal web", None if term != "on" else True, "%s, abre como %s" % (term, tu or "?"))

    failed = [l.split()[0] for l in run(["systemctl", "list-units", "--failed", "--no-legend", "--plain"], 15)[1].splitlines() if l.strip()]
    add("Servicos com falha no systemd", not failed, ", ".join(failed[:5]) or "nenhum")
    add("Reinicio pendente", not reboot_required(), "sim, depois de atualizacoes" if reboot_required() else "nao")
    au = auto_updates()
    add("Atualizacoes de seguranca automaticas", True if au else None, "ligadas" if au else "desligadas (agende abaixo)")
    return {"ok": True, "items": items}


def fix_steps():
    return [("Reinstalando servicos, grupos e permissoes (vmpanel restart)", [os.path.join(APP_DIR, "bin", "vmpanel"), "restart"]),
            ("Protegendo credenciais", ["sh", "-c", "chown root:vmpanel /etc/vmpanel/auth.json && chmod 0640 /etc/vmpanel/auth.json"])]


# ---------------------------------------------------------------- tarefas (rodam fora do agente)

def _read_job():
    try:
        with open(JOB_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_job(job):
    tmp = JOB_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(job, f)
    os.chmod(tmp, 0o640)
    os.rename(tmp, JOB_FILE)


def job_running():
    j = _read_job()
    if not j or j.get("state") != "running":
        return False
    pid = j.get("pid")
    if pid:
        return os.path.exists("/proc/%d" % pid)
    return time.time() - j.get("created", 0) < 60   # ainda subindo


def job_status():
    j = _read_job() or {}
    if j.get("state") == "running" and not job_running():
        j["state"] = "error"
        j["error"] = "a tarefa foi interrompida"
    try:
        with open(JOB_LOG) as f:
            log = f.read()[-12000:]
    except OSError:
        log = ""
    return {"ok": True, "job": j or None, "log": log}


JOB_TITLES = {"clean": "Limpeza", "ram": "Liberar cache da memoria", "upgrade": "Atualizacao do sistema",
              "refresh": "Buscar atualizacoes", "reboot": "Reiniciar a VM", "fix": "Corrigir instalacao"}


def validate(kind, params):
    """Confere tudo que veio do navegador. Retorna params limpos ou levanta ValueError."""
    p = {}
    if kind == "clean":
        items = params.get("items") or []
        if items == "quick":
            items = quick_items()
        if not isinstance(items, list) or not items or any(i not in CAT_IDS for i in items):
            raise ValueError("itens de limpeza invalidos")
        p["items"] = [i for i in CAT_IDS if i in items]
    elif kind == "upgrade":
        mode = params.get("mode")
        if mode not in ("all", "security", "selected"):
            raise ValueError("modo de atualizacao invalido")
        p["mode"] = mode
        if mode == "selected":
            pk = params.get("packages") or []
            if not isinstance(pk, list) or not pk or len(pk) > 500 or not all(isinstance(x, str) and PKG_RE.match(x) for x in pk):
                raise ValueError("lista de pacotes invalida")
            p["packages"] = pk
        p["reboot"] = "if-needed" if params.get("reboot") in (True, "if-needed") else "no"
    elif kind not in ("ram", "refresh", "reboot", "fix"):
        raise ValueError("tarefa desconhecida")
    if not pkg_mgr() and kind in ("upgrade", "refresh"):
        raise ValueError("gerenciador de pacotes nao suportado")
    return p


def start_job(kind, params, source="painel"):
    if job_running():
        return {"ok": False, "error": "ja tem uma tarefa rodando; espere terminar"}
    try:
        p = validate(kind, params)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    os.makedirs(DATA_DIR, exist_ok=True)
    jid = _new_id()
    title = JOB_TITLES[kind]
    if kind == "upgrade":
        title += {"all": " (tudo)", "security": " (seguranca)", "selected": " (%d pacotes)" % len(p.get("packages", []))}[p["mode"]]
    _write_job({"id": jid, "kind": kind, "title": title, "params": p, "source": source, "created": time.time(),
                "state": "running", "steps": []})
    with open(JOB_LOG, "w") as f:
        f.write("")
    os.chmod(JOB_LOG, 0o640)
    rc, out = run(["systemd-run", "--unit", "vmpanel-maint-%s" % jid, "--collect", "--quiet",
                   "--setenv=VMPANEL_DIR=%s" % APP_DIR, sys.executable, os.path.abspath(__file__), "run"], timeout=30)
    if rc != 0:
        _write_job({"id": jid, "kind": kind, "title": title, "params": p, "state": "error", "error": out.strip(),
                    "created": time.time(), "steps": []})
        return {"ok": False, "error": "nao consegui iniciar: %s" % out.strip()}
    return {"ok": True, "id": jid, "title": title}


def _stream(cmd, env=None):
    """Roda um comando mandando a saida para o log da tarefa (stdout ja aponta para ele)."""
    e = dict(os.environ)
    e.update(env or {})
    e.setdefault("LANG", "C.UTF-8")
    print("$ " + " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, stdout=sys.stdout, stderr=subprocess.STDOUT, env=e, stdin=subprocess.DEVNULL)
    if rc != 0:
        raise RuntimeError("comando terminou com codigo %d" % rc)


def job_steps(job):
    kind, p = job["kind"], job.get("params") or {}
    if kind == "clean":
        steps = []
        for cid in p["items"]:
            steps += clean_steps(cid)
        return steps
    if kind == "ram":
        return [("Liberando cache da memoria", drop_ram_cache)]
    if kind == "upgrade":
        return upgrade_steps(p["mode"], p.get("packages"), p.get("reboot", "no"))
    if kind == "refresh":
        pm = pkg_mgr()
        return [("Buscando atualizacoes", APT + ["update"] if pm == "apt" else [pm, "-q", "makecache"])]
    if kind == "reboot":
        return [("Reiniciando a VM em 1 minuto", ["shutdown", "-r", "+1", "VM//PANEL: reinicio pedido pelo painel"])]
    if kind == "fix":
        return fix_steps()
    return []


def run_job():
    """Executado pelo systemd-run: faz os passos e grava o progresso."""
    job = _read_job()
    if not job or job.get("state") != "running":
        return
    log = open(JOB_LOG, "a", buffering=1)
    sys.stdout = log
    sys.stderr = log
    job["pid"] = os.getpid()
    job["started"] = time.time()
    job["free_before"] = disk_free("/")
    print("== %s (%s)" % (job["title"], datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")), flush=True)
    try:
        steps = job_steps(job)
    except Exception as e:
        steps = []
        job["state"], job["error"] = "error", str(e)
    job["steps"] = [{"label": s[0], "state": "wait"} for s in steps]
    _write_job(job)
    failed = 0
    for i, (label, action) in enumerate(steps):
        job["steps"][i]["state"] = "run"
        _write_job(job)
        print("\n== %s" % label, flush=True)
        t0 = time.time()
        try:
            if callable(action):
                action()
            else:
                _stream(action, APT_ENV)
            job["steps"][i]["state"] = "ok"
        except Exception as e:
            failed += 1
            job["steps"][i]["state"] = "fail"
            job["steps"][i]["error"] = str(e)[:300]
            print("ERRO: %s" % e, flush=True)
        job["steps"][i]["secs"] = round(time.time() - t0, 1)
        _write_job(job)
    job["free_after"] = disk_free("/")
    job["freed"] = max(0, job["free_after"] - job["free_before"])
    job["finished"] = time.time()
    if job.get("state") == "running":
        job["state"] = "done" if not failed else "error"
        if failed:
            job["error"] = "%d passo(s) falharam" % failed
    print("\n== Fim: %s. Espaco livre em /: %s -> %s (+%s)" % (
        "OK" if job["state"] == "done" else "com erros", fmt(job["free_before"]), fmt(job["free_after"]), fmt(job["freed"])), flush=True)
    _write_job(job)


# ---------------------------------------------------------------- agendamentos

SCHED_TASKS = {
    "clean": "Limpeza rapida",
    "upgrade-security": "Atualizar so seguranca",
    "upgrade-all": "Atualizar tudo",
    "refresh": "Buscar atualizacoes",
    "reboot": "Reiniciar a VM",
}
DAYS = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]


def sched_load():
    try:
        with open(SCHED_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def sched_save(items):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = SCHED_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, indent=1)
    os.chmod(tmp, 0o600)
    os.rename(tmp, SCHED_FILE)


def _occurrence(s, now):
    """Ultima vez (datetime local) em que o agendamento deveria ter rodado ate agora, ou None."""
    hh, mm = [int(x) for x in s["at"].split(":")]
    if s["when"] == "once":
        t = datetime.datetime.strptime(s["date"] + " " + s["at"], "%Y-%m-%d %H:%M")
        return t if t <= now else None
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if s["when"] == "daily":
        return t if t <= now else t - datetime.timedelta(days=1)
    back = (now.weekday() - int(s["dow"])) % 7
    t -= datetime.timedelta(days=back)
    return t if t <= now else t - datetime.timedelta(days=7)


def _next(s, now):
    hh, mm = [int(x) for x in s["at"].split(":")]
    if s["when"] == "once":
        t = datetime.datetime.strptime(s["date"] + " " + s["at"], "%Y-%m-%d %H:%M")
        return t if t > now and s.get("enabled", True) else None
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if s["when"] == "daily":
        return t if t > now else t + datetime.timedelta(days=1)
    t += datetime.timedelta(days=(int(s["dow"]) - now.weekday()) % 7)
    return t if t > now else t + datetime.timedelta(days=7)


def sched_list():
    now = datetime.datetime.now()
    out = []
    for s in sched_load():
        n = _next(s, now)
        d = dict(s)
        d["task_label"] = SCHED_TASKS.get(s["task"], s["task"])
        d["next"] = n.strftime("%d/%m/%Y %H:%M") if n else None
        d["next_ts"] = time.mktime(n.timetuple()) if n else None
        out.append(d)
    return {"ok": True, "items": out, "now": now.strftime("%d/%m/%Y %H:%M"),
            "tz": time.strftime("%Z"), "tasks": SCHED_TASKS, "days": DAYS}


def sched_add(req):
    task, when, at = req.get("task"), req.get("when"), str(req.get("at", ""))
    if task not in SCHED_TASKS:
        return {"ok": False, "error": "tarefa invalida"}
    if when not in ("once", "daily", "weekly"):
        return {"ok": False, "error": "frequencia invalida"}
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", at):
        return {"ok": False, "error": "horario invalido (use HH:MM)"}
    s = {"id": _new_id(), "task": task, "when": when, "at": at, "enabled": True,
         "reboot": bool(req.get("reboot")) and task.startswith("upgrade"), "created": time.time(), "last_run": None}
    if when == "once":
        date = str(req.get("date", ""))
        try:
            t = datetime.datetime.strptime(date + " " + at, "%Y-%m-%d %H:%M")
        except ValueError:
            return {"ok": False, "error": "data invalida"}
        if t <= datetime.datetime.now():
            return {"ok": False, "error": "escolha uma data no futuro"}
        s["date"] = date
    if when == "weekly":
        try:
            s["dow"] = int(req.get("dow"))
        except (TypeError, ValueError):
            s["dow"] = -1
        if not 0 <= s["dow"] <= 6:
            return {"ok": False, "error": "dia da semana invalido"}
    items = sched_load()
    if len(items) >= 20:
        return {"ok": False, "error": "limite de 20 agendamentos"}
    items.append(s)
    sched_save(items)
    return {"ok": True, "id": s["id"]}


def sched_delete(sid):
    items = sched_load()
    keep = [s for s in items if s.get("id") != sid]
    if len(keep) == len(items):
        return {"ok": False, "error": "agendamento nao encontrado"}
    sched_save(keep)
    return {"ok": True}


def sched_tick():
    """Chamado pelo agente a cada 30s: dispara o que venceu (ate 6h de atraso, se a VM estava desligada)."""
    items = sched_load()
    if not items:
        return
    now = datetime.datetime.now()
    changed = False
    for s in items:
        if not s.get("enabled", True):
            continue
        try:
            occ = _occurrence(s, now)
        except Exception:
            continue
        if not occ:
            continue
        ts = time.mktime(occ.timetuple())
        if ts <= max(s.get("last_run") or 0, s.get("created") or 0) or time.time() - ts > 6 * 3600:
            continue
        if job_running():
            return   # tenta de novo no proximo ciclo
        t = s["task"]
        if t == "clean":
            r = start_job("clean", {"items": "quick"}, "agendamento")
        elif t.startswith("upgrade"):
            r = start_job("upgrade", {"mode": t.split("-")[1], "reboot": s.get("reboot")}, "agendamento")
        else:
            r = start_job(t, {}, "agendamento")
        s["last_run"] = time.time()
        s["last_result"] = "iniciada" if r.get("ok") else str(r.get("error", "")).splitlines()[0][:200]
        if s["when"] == "once":
            s["enabled"] = False
        changed = True
    if changed:
        sched_save(items)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        if os.geteuid() != 0:
            sys.exit("precisa rodar como root")
        run_job()
    else:
        print("uso: maint.py run   (chamado pelo vmpanel-agent)")
