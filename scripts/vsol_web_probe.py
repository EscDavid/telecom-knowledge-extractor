#!/usr/bin/env python3
"""Sonda de sesión de la web V-SOL (oltweb) — SOLO LECTURA, un único login.

Reproduce lo que hace la SPA (POST /action/main con who=100) y revisa, paso a paso,
por qué la sesión "expira": qué `Set-Cookie` entrega el equipo, en qué formato lo
reenvía el navegador y si el equipo lo acepta (secuencial y en paralelo). Si la sesión
funciona, lee `systeminfo` para obtener modelo y firmware.

Credenciales: TKC_VSOL_HOST, TKC_VSOL_CLI_PORT (puerto web), TKC_VSOL_CLI_USER,
TKC_VSOL_CLI_PASSWORD del .env. Nunca imprime la contraseña ni los valores de cookie.

    python3 scripts/vsol_web_probe.py            # un login
    python3 scripts/vsol_web_probe.py --no-login # solo GET públicos
    python3 scripts/vsol_web_probe.py --get loginaccess --get serviceport   # lecturas puntuales
    python3 scripts/vsol_web_probe.py --save-snmp   # además: lee la community de SOLO LECTURA
                                                    # y la guarda en TKC_VSOL_RO_COMMUNITY del .env
                                                    # (sin imprimirla; nunca toma una de escritura)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import tempfile
import http.client
import json
import ssl
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import creds  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) tkc-vsol-probe"
INTEREST = ("model", "version", "type", "name", "hard", "soft", "firm", "sys", "up", "date",
            "time", "serial", "sn", "mac", "pon")


class Web:
    def __init__(self, host: str, port: int, timeout: float, tls: bool = True):
        self.host, self.port, self.timeout, self.tls = host, port, timeout, tls

    def _conn(self):
        if self.tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def request(self, method: str, path: str, body: str | None = None, cookie: str | None = None):
        h = {"User-Agent": UA, "Accept": "*/*", "Connection": "close"}
        if body is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if cookie:
            h["Cookie"] = cookie
        c = self._conn()
        try:
            c.request(method, path, body=body, headers=h)
            r = c.getresponse()
            data = r.read()
            return r.status, r.getheaders(), data
        finally:
            c.close()


def set_cookies(headers) -> list[str]:
    return [v for k, v in headers if k.lower() == "set-cookie"]


def describe_cookie(raw: str) -> str:
    """Forma del Set-Cookie sin revelar el valor."""
    first, *attrs = [p.strip() for p in raw.split(";")]
    if "=" in first:
        name, val = first.split("=", 1)
        shape = f"nombre({len(name)}) '=' valor({len(val)})"
    else:
        shape = f"SIN '=': token({len(first)}) (formato no estándar)"
    keep = [a for a in attrs if a.split("=")[0].lower() in
            ("path", "expires", "max-age", "secure", "httponly", "samesite", "domain")]
    return shape + (" ; " + " ; ".join(keep) if keep else " ; (sin atributos → cookie de sesión)")


def header(headers, name: str) -> str | None:
    for k, v in headers:
        if k.lower() == name:
            return v
    return None


def short(body: bytes, n: int = 160) -> str:
    return body.decode("utf-8", "replace").replace("\n", " ").strip()[:n]


def try_json(body: bytes):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return None


def show_interesting(obj, prefix="", depth=0) -> None:
    if depth > 3:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                show_interesting(v, f"{prefix}{k}.", depth + 1)
            elif any(w in k.lower() for w in INTEREST):
                print(f"    {prefix}{k}: {str(v)[:80]}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            show_interesting(v, f"{prefix}[{i}].", depth + 1)


# Solo lecturas de gestión; la lista es cerrada (nada de endpoints de escritura).
GET_ALLOWED = {"loginaccess", "serviceport", "telnetmgt", "sshglobal", "sshstate", "ntp", "rtc",
               "systimeformat", "syswan", "systemstate", "snmp_v1", "snmp_v3", "snmpv3", "syslogserver",
               "user", "userRoleList", "logintimeout", "aclcontrol", "systeminfo", "devAbility",
               "auxip", "auxipv6", "gateway"}
_SECRET_KEY = re.compile(r"pass|pwd|secret|community|cmmty|key|token|cipher|auth", re.I)


def mask_secrets(obj):
    if isinstance(obj, dict):
        return {k: ("***" if _SECRET_KEY.search(k) and isinstance(v, (str, int)) else mask_secrets(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_secrets(v) for v in obj]
    return obj


def save_env_var(env_file: Path, key: str, value: str, force: bool) -> str:
    """Escribe/actualiza KEY=value en el .env conservando el resto. Devuelve qué hizo."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=(.*)$")
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            if m.group(1).strip() and not force:
                return "ya había un valor: no se sobrescribe (usa --force)"
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    fd, tmp = tempfile.mkstemp(dir=str(env_file.parent), prefix=".env.tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_file)
    return "guardada en " + env_file.name


def snmp_ro_communities(obj) -> tuple[list[str], list[str]]:
    """(solo_lectura, otras) a partir de data.community_table. Nunca se mezclan."""
    ro, other = [], []
    data = obj.get("data") if isinstance(obj, dict) else None
    for row in (data or {}).get("community_table", []) or []:
        name = str(row.get("community_name", "")).strip()
        right = str(row.get("access_right", "")).lower()
        if not name:
            continue
        (ro if ("only" in right or right in ("ro", "read-only", "readonly")) else other).append(name)
    return ro, other


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-login", action="store_true")
    ap.add_argument("--http", action="store_true", help="HTTP en claro en vez de HTTPS")
    ap.add_argument("--save-snmp", action="store_true",
                    help="lee la community de solo lectura y la guarda en el .env (no se imprime)")
    ap.add_argument("--save-snmp-rw", action="store_true",
                    help="con --save-snmp: guarda TAMBIÉN la de lectura-escritura en TKC_VSOL_RW_COMMUNITY "
                         "(solo se almacena; ningún script la usa para consultar)")
    ap.add_argument("--force", action="store_true", help="con --save-snmp: sobrescribe el valor existente")
    ap.add_argument("--get", action="append", default=[], metavar="ACCION",
                    help=f"GET de lectura de /action/<ACCION> (valores sensibles enmascarados). "
                         f"Permitidas: {', '.join(sorted(GET_ALLOWED))}")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--timeout", type=float, default=10.0)
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(a.env_file, override=False)
    except ImportError:
        pass

    host = creds.get("VSOL", "HOST")
    port = int(creds.get("VSOL", "CLI_PORT") or 0)
    user, pw = creds.get("VSOL", "CLI_USER"), creds.get("VSOL", "CLI_PASSWORD")
    if not (host and port):
        print("faltan TKC_VSOL_HOST / TKC_VSOL_CLI_PORT")
        return 2
    web = Web(host, port, a.timeout, tls=not a.http)

    print("== 0. Públicos (sin sesión)")
    st, hd, body = web.request("GET", "/action/deviceLogo")
    print(f"  GET /action/deviceLogo → {st}; Date del equipo: {header(hd, 'date')}")
    st, hd, body = web.request("GET", "/action/login")
    obj = try_json(body)
    print(f"  GET /action/login → {st}, {len(body)} B: {short(body, 140) if body else '(vacío)'}")
    if a.no_login:
        return 0
    if not (user and pw):
        print("faltan TKC_VSOL_CLI_USER / TKC_VSOL_CLI_PASSWORD")
        return 2

    print("\n== 1. Login (un solo intento): POST /action/main who=100")
    form = urllib.parse.urlencode({"user": user, "pass": pw, "verification_code": "",
                                   "button": "Login", "who": 100})
    st, hd, body = web.request("POST", "/action/main", body=form)
    del pw, form
    obj = try_json(body)
    print(f"  HTTP {st}; Date: {header(hd, 'date')}")
    cookies = set_cookies(hd)
    print(f"  Set-Cookie recibidas: {len(cookies)}")
    for c in cookies:
        print("    •", describe_cookie(c))
    if isinstance(obj, dict):
        d = obj.get("data") if isinstance(obj.get("data"), dict) else {}
        print(f"  cuerpo JSON: retcode={obj.get('retcode')!r}  "
              f"modify_password_flag={d.get('modify_password_flag')!r}  claves={sorted(d)[:8]}")
    else:
        print(f"  cuerpo: {short(body) or '(vacío)'}")
    if not cookies:
        print("\n  El equipo NO entregó cookie: el login no creó sesión (revisa credenciales/retcode).")
        return 1

    # --- reenvío fiel de las cookies tal como llegaron ---------------------------------
    segs = [c.split(";", 1)[0].strip() for c in cookies]
    variants = {
        "A tal cual (token o nombre=valor)": "; ".join(segs),
        "B con '=' añadido a las que no lo tienen": "; ".join(s if "=" in s else s + "=" for s in segs),
        "C última cookie sola": segs[-1],
    }
    print("\n== 2. ¿El equipo acepta la sesión? GET /action/rtc (vacío = sin sesión)")
    ok_variant = None
    for name, ck in variants.items():
        st, hd2, b = web.request("GET", "/action/rtc", cookie=ck)
        new = set_cookies(hd2)
        print(f"  variante {name}: HTTP {st}, {len(b)} B, cookies nuevas en la respuesta: {len(new)}")
        if b and ok_variant is None:
            ok_variant = (name, ck)
            break
    if ok_variant is None:
        print("\n  Ninguna forma de reenviar la cookie funciona: el equipo invalida la sesión")
        print("  tras el login (sesión concurrente, contraseña por cambiar o rotación inmediata).")
        return 1
    name, ck = ok_variant
    print(f"  → funciona con la variante «{name}»")

    print("\n== 3. Datos del equipo (con la sesión válida)")
    for path in ("/action/systeminfo", "/action/devAbility", "/action/oltConfigState"):
        st, hd3, b = web.request("GET", path, cookie=ck)
        o = try_json(b)
        print(f"  GET {path} → {st}, {len(b)} B")
        if o is not None:
            show_interesting(o)
        elif b:
            print("    ", short(b))
        nxt = set_cookies(hd3)
        if nxt:   # la cookie rota: usa la última
            ck = "; ".join(c.split(";", 1)[0].strip() for c in nxt)
            print(f"    (el equipo rotó la cookie: {len(nxt)} nueva(s))")

    for name in a.get:
        if name not in GET_ALLOWED:
            print(f"\n== GET /action/{name}: no permitido (lista cerrada de lecturas)")
            continue
        st, hd5, b = web.request("GET", f"/action/{name}", cookie=ck)
        nxt = set_cookies(hd5)
        if nxt:
            ck = "; ".join(c.split(";", 1)[0].strip() for c in nxt)
        o = try_json(b)
        print(f"\n== GET /action/{name} → {st}, {len(b)} B")
        txt = json.dumps(mask_secrets(o), ensure_ascii=False, indent=1) if o is not None else short(b, 600)
        print(txt[:3500] + (" …(recortado)" if len(txt) > 3500 else ""))

    if a.save_snmp:
        print("\n== 3b. Community SNMP de solo lectura (GET /action/snmp_v1)")
        st, hd4, b = web.request("GET", "/action/snmp_v1", cookie=ck)
        nxt = set_cookies(hd4)
        if nxt:
            ck = "; ".join(c.split(";", 1)[0].strip() for c in nxt)
        ro, other = snmp_ro_communities(try_json(b))
        print(f"  HTTP {st}, {len(b)} B | solo lectura: {len(ro)} | otras (escritura u otro): {len(other)}")
        if not ro:
            print("  No hay community de SOLO LECTURA: no se guarda nada (nunca se usa una de escritura).")
        else:
            weak = [n for n in ro if len(n) < 8 or "public" in n.lower() or n.lower() in ("private", "admin")]
            chosen = next((n for n in ro if n not in weak), ro[0])
            print(f"  elegida: nº {ro.index(chosen) + 1} de {len(ro)} (longitud {len(chosen)}) "
                  f"{'— ojo: parece trivial' if chosen in weak else ''}")
            print("  →", save_env_var(Path(a.env_file), "TKC_VSOL_RO_COMMUNITY", chosen, a.force))
        if a.save_snmp_rw:
            rw = [str(r.get("community_name", "")).strip() for r in
                  ((try_json(b) or {}).get("data") or {}).get("community_table", [])
                  if "write" in str(r.get("access_right", "")).lower() and r.get("community_name")]
            print(f"  RW encontradas: {len(rw)}")
            if rw:
                print("  →", save_env_var(Path(a.env_file), "TKC_VSOL_RW_COMMUNITY", rw[0], a.force))

    print("\n== 4. Peticiones en paralelo con la misma cookie (¿rotación por petición?)")
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: web.request("GET", "/action/rtc", cookie=ck), range(4)))
    print("  longitudes de respuesta:", [len(r[2]) for r in res],
          "| cookies nuevas por respuesta:", [len(set_cookies(r[1])) for r in res])
    print("\nLas credenciales y valores de cookie no se imprimen. El equipo conserva una sesión abierta"
          " (caduca sola).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
