#!/usr/bin/env python3
"""Gerencia as credenciais do painel. Uso (como root):

  manage.py passwd           define/troca usuario e senha
  manage.py 2fa-on           ativa 2FA (TOTP) e mostra o QR code
  manage.py 2fa-off          desativa 2FA
  manage.py check            verifica se as credenciais existem
"""
import getpass
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auth  # noqa: E402

TTY_IN = None


def ask(prompt, secret=False):
    """Le do terminal mesmo quando o script veio de `curl | bash`."""
    global TTY_IN
    if secret:
        return getpass.getpass(prompt)
    if TTY_IN is None:
        try:
            TTY_IN = open("/dev/tty")
        except OSError:
            TTY_IN = sys.stdin
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return TTY_IN.readline().strip()


def has_tty():
    try:
        open("/dev/tty").close()
        return True
    except OSError:
        return False


def strong(pw):
    classes = sum(bool(re.search(r, pw)) for r in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^a-zA-Z0-9]"))
    return len(pw) >= 12 and classes >= 3


def load():
    try:
        return auth.load_auth()
    except Exception:
        return {}


def cmd_passwd():
    data = load()
    user = os.environ.get("VMPANEL_USER") or ask("Usuario do painel [%s]: " % (data.get("username") or "admin"))
    user = user or data.get("username") or "admin"
    if not re.match(r"^[A-Za-z0-9_.@-]{3,64}$", user):
        sys.exit("Usuario invalido (3-64 caracteres: letras, numeros, _ . @ -)")
    pw = os.environ.get("VMPANEL_PASSWORD")
    if not pw and not has_tty():
        sys.exit("Sem terminal interativo: defina VMPANEL_USER e VMPANEL_PASSWORD ou rode 'sudo vmpanel passwd' via SSH.")
    if not pw:
        while True:
            pw = ask("Senha (min. 12 caracteres, misture maiusculas, numeros e simbolos): ", True)
            if not strong(pw):
                print("  Senha fraca. Use 12+ caracteres com pelo menos 3 tipos (a-z, A-Z, 0-9, simbolo).")
                continue
            if ask("Repita a senha: ", True) != pw:
                print("  As senhas nao conferem.")
                continue
            break
    elif not strong(pw):
        sys.exit("VMPANEL_PASSWORD fraca demais.")
    data["username"] = user
    data["password_hash"] = auth.hash_password(pw)
    auth.save_auth(data)
    fix_perms()
    print("Credenciais salvas. Sessoes abertas foram encerradas.")


def show_qr(uri):
    if shutil.which("qrencode"):
        subprocess.call(["qrencode", "-t", "ANSIUTF8", uri])
    else:
        print("(instale 'qrencode' para ver o QR code no terminal)")
    print("\nOu digite manualmente no app autenticador:\n  %s\n" % uri)


def cmd_2fa_on():
    if not has_tty():
        sys.exit("2FA precisa de terminal interativo: rode 'sudo vmpanel 2fa-on' via SSH.")
    data = load()
    if not data.get("password_hash"):
        sys.exit("Defina a senha primeiro: vmpanel passwd")
    secret = auth.new_totp_secret()
    uri = auth.totp_uri(secret, data["username"])
    print("\nEscaneie no Google Authenticator / Authy / 1Password / Bitwarden:\n")
    show_qr(uri)
    for _ in range(3):
        code = ask("Digite o codigo de 6 digitos para confirmar: ")
        if code.strip() in (auth._hotp(secret, c) for c in auth._counters()):
            data["totp_secret"] = secret
            auth.save_auth(data)
            fix_perms()
            print("2FA ativado.")
            return
        print("  Codigo incorreto, tente de novo.")
    sys.exit("2FA NAO foi ativado.")


def cmd_2fa_off():
    data = load()
    data.pop("totp_secret", None)
    auth.save_auth(data)
    fix_perms()
    print("2FA desativado.")


def fix_perms():
    try:
        import grp
        g = grp.getgrnam("vmpanel")
        os.chown(auth.AUTH_FILE, 0, g.gr_gid)   # root:vmpanel, servico so le
        os.chmod(auth.AUTH_FILE, 0o640)
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    c = sys.argv[1]
    if c == "passwd":
        cmd_passwd()
    elif c == "2fa-on":
        cmd_2fa_on()
    elif c == "2fa-off":
        cmd_2fa_off()
    elif c == "check":
        d = load()
        sys.exit(0 if d.get("password_hash") else 1)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
