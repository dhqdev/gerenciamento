#!/usr/bin/env python3
"""Descobre como o Traefik ja existente na VM esta configurado (Docker Swarm ou container comum).

Imprime variaveis no formato KEY=valor para o bin/vmpanel usar. Nao altera nada.
"""
import json
import subprocess
import sys


def sh(*cmd):
    p = subprocess.run(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def jload(s, default):
    try:
        return json.loads(s)
    except Exception:
        return default


def arg_value(args, *prefixes):
    for a in args:
        for p in prefixes:
            if a.startswith(p + "="):
                return a.split("=", 1)[1]
    return ""


def from_labels(all_labels):
    """Copia entrypoint/certresolver/rede dos servicos que ja funcionam atras do Traefik."""
    ep = resolver = net = ""
    for labels in all_labels:
        for k, v in (labels or {}).items():
            if not k.startswith("traefik."):
                continue
            if k.endswith(".tls.certresolver") and not resolver:
                resolver = v
            elif k.endswith(".entrypoints") and not ep and ".tls" not in k:
                # prefere o entrypoint usado junto com TLS
                router = k.rsplit(".", 1)[0]
                if (router + ".tls.certresolver") in labels or (router + ".tls") in labels:
                    ep = v.split(",")[0]
            elif k == "traefik.docker.network" and not net:
                net = v
            elif k == "traefik.swarm.network" and not net:
                net = v
    return ep, resolver, net


def main():
    mode = ""
    swarm = sh("docker", "info", "--format", "{{.Swarm.LocalNodeState}}") == "active"
    args, nets, labels_all = [], [], []
    target = ""

    if swarm:
        for line in sh("docker", "service", "ls", "--format", "{{.Name}} {{.Image}}").splitlines():
            name, _, image = line.partition(" ")
            if image.split("/")[-1].startswith("traefik"):
                target = name
                break
    if target:
        mode = "swarm"
        spec = jload(sh("docker", "service", "inspect", target, "--format", "{{json .Spec}}"), {})
        cs = spec.get("TaskTemplate", {}).get("ContainerSpec", {})
        args = (cs.get("Args") or []) + (cs.get("Command") or [])
        for n in spec.get("TaskTemplate", {}).get("Networks") or []:
            nm = sh("docker", "network", "inspect", n.get("Target", ""), "--format", "{{.Name}}")
            if nm and nm != "ingress":
                nets.append(nm)
        ids = sh("docker", "service", "ls", "-q").split()
        if ids:
            for s in jload(sh("docker", "service", "inspect", *ids), []):
                labels_all.append(s.get("Spec", {}).get("Labels") or {})
    else:
        for line in sh("docker", "ps", "--format", "{{.Names}} {{.Image}}").splitlines():
            name, _, image = line.partition(" ")
            if image.split("/")[-1].startswith("traefik"):
                target = name
                break
        if target:
            mode = "container"
            c = jload(sh("docker", "inspect", target), [{}])[0]
            args = (c.get("Args") or [])
            nets = [n for n in (c.get("NetworkSettings", {}).get("Networks") or {}).keys() if n not in ("host", "none")]
            ids = sh("docker", "ps", "-q").split()
            if ids:
                for x in jload(sh("docker", "inspect", *ids), []):
                    labels_all.append(x.get("Config", {}).get("Labels") or {})

    if not mode:
        print("TRAEFIK_MODE=")
        return

    ep_l, res_l, net_l = from_labels(labels_all)
    net = arg_value(args, "--providers.docker.network", "--providers.swarm.network") or net_l
    if not net or net not in nets:
        net = net if net else (nets[0] if nets else "")

    resolver = res_l
    if not resolver:
        for a in args:
            if a.startswith("--certificatesresolvers.") or a.startswith("--certificatesResolvers."):
                resolver = a.split(".")[1]
                break

    ep = ep_l
    if not ep:
        for a in args:
            if a.startswith("--entrypoints.") and a.endswith(":443"):
                ep = a.split(".")[1]
                break
    ep = ep or "websecure"

    exposed_default = arg_value(args, "--providers.docker.exposedbydefault", "--providers.swarm.exposedbydefault")

    print("TRAEFIK_MODE=%s" % mode)
    print("TRAEFIK_NAME=%s" % target)
    print("TRAEFIK_NETWORK=%s" % net)
    print("TRAEFIK_ENTRYPOINT=%s" % ep)
    print("TRAEFIK_RESOLVER=%s" % resolver)
    print("TRAEFIK_EXPOSED_DEFAULT=%s" % (exposed_default or "true"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # nunca quebra o instalador
        print("TRAEFIK_MODE=")
        print("# erro: %s" % e, file=sys.stderr)
