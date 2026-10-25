#!/usr/bin/env python3
"""Identifica un equipo OLT (modelo/firmware) con credenciales del `.env`, SOLO LECTURA.

Qué hace (en este orden, un intento por método, sin reintentos de credenciales):
  1. Muestra qué variables TKC_<VENDOR>_* existen (nombre y presencia; jamás valores).
  2. TCP: si hay CLI_PORT, se conecta y LEE el banner sin enviar nada. Con --probe, si el
     servicio calla, hace 3 sondeos SIN credenciales: Enter (¿Telnet?), GET / (¿HTTP?) y
     handshake TLS (¿HTTPS?), y muestra cabeceras/título para ubicar el modelo.
  3. SNMP v2c (si hay RO_COMMUNITY) y/o v3 (si hay SNMPV3_USER): GET de
     sysDescr, sysObjectID, sysName y sysUpTime. Nada más: sin walk, sin SET.
  4. Interpreta sysObjectID contra config/vendors.yaml.

Uso:
    python3 scripts/vendor_identify.py VSOL
    python3 scripts/vendor_identify.py ZTE --model C600
    python3 scripts/vendor_identify.py VSOL --dry-run        # solo muestra qué variables faltan
    python3 scripts/vendor_identify.py VSOL --probe          # si el puerto calla: Telnet/HTTP/HTTPS

Variables: ver src/creds.py (p. ej. TKC_VSOL_HOST, TKC_VSOL_SNMP_PORT, TKC_VSOL_RO_COMMUNITY,
TKC_VSOL_CLI_PORT, TKC_VSOL_CLI_USER, TKC_VSOL_CLI_PASSWORD, TKC_VSOL_SNMPV3_USER ...).
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import creds                      # noqa: E402
from src.profiles import default_registry  # noqa: E402

SYS_OIDS = [("sysDescr", "1.3.6.1.2.1.1.1.0"), ("sysObjectID", "1.3.6.1.2.1.1.2.0"),
            ("sysUpTime", "1.3.6.1.2.1.1.3.0"), ("sysName", "1.3.6.1.2.1.1.5.0")]
AUTH = {"MD5": "usmHMACMD5AuthProtocol", "SHA": "usmHMACSHAAuthProtocol",
        "SHA224": "usmHMAC128SHA224AuthProtocol", "SHA256": "usmHMAC192SHA256AuthProtocol"}
PRIV = {"DES": "usmDESPrivProtocol", "AES": "usmAesCfb128Protocol"}


class Scrub:
    def __init__(self, secrets):
        self.secrets = [s for s in secrets if s]

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return text


# --- 1. variables ------------------------------------------------------------
def show_env(vendor: str, model: str | None) -> None:
    print(f"== Variables para {vendor}{' ' + model if model else ''} (valores nunca se muestran)")
    for r in creds.describe(vendor, model):
        mark = "OK " if r["present"] else "-- "
        src = f"← {r['var']}" if r["present"] else f"(define {r['expected']})"
        print(f"  {mark}{r['key']:22s} {src}")


# --- 2. TCP --------------------------------------------------------------------
def tcp_banner(host: str, port: int, timeout: float) -> None:
    print(f"\n== TCP {host}:{port} (solo lectura del banner, sin enviar nada)")
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            try:
                data = s.recv(512)
            except socket.timeout:
                data = b""
    except OSError as exc:
        print(f"  no conecta: {exc}")
        return
    if not data:
        print("  conectó pero no envió banner (puede ser Telnet/HTTP esperando datos)")
        return
    kind = "desconocido"
    if data.startswith(b"SSH-"):
        kind = "SSH"
    elif data[:1] == b"\xff":
        kind = "Telnet (negociación IAC)"
    elif data[:5] in (b"HTTP/", b"<html", b"<!DOC"):
        kind = "HTTP"
    elif b"ogin" in data or b"sername" in data:
        kind = "Telnet (prompt de login)"
    text = "".join(chr(b) if 32 <= b < 127 else " " for b in data).strip()
    print(f"  tipo probable: {kind}\n  banner: {text[:160]}")


def _printable(data: bytes, n: int = 200) -> str:
    return "".join(chr(b) if 32 <= b < 127 else " " for b in data).strip()[:n]


def _http_summary(raw: bytes) -> list[str]:
    import re
    txt = raw.decode("latin-1", "replace")
    head, _, body = txt.partition("\r\n\r\n")
    lines = head.split("\r\n")
    out = [f"    {lines[0][:100]}"]
    for h in lines[1:]:
        if h.split(":", 1)[0].lower() in ("server", "www-authenticate", "content-type", "location",
                                           "x-powered-by"):
            out.append(f"    {h[:120]}")
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if m:
        out.append(f"    <title>: {m.group(1).strip()[:100]}")
    for tag, rx in (("meta", r'<meta[^>]+(?:name|http-equiv)=["\'](?:generator|description|keywords|refresh)["\'][^>]*>'),
                    ("script", r'<script[^>]+src=["\']([^"\']+)'),
                    ("frame/iframe", r'<i?frame[^>]+src=["\']([^"\']+)'),
                    ("form", r'<form[^>]+action=["\']([^"\']*)'),
                    ("link", r'<link[^>]+href=["\']([^"\']+)')):
        found = re.findall(rx, body, re.I)[:5]
        if found:
            out.append(f"    {tag}: {found}")
    hints = sorted({h.upper() for h in re.findall(
        r"\b(V-?SOL(?:UTION)?|V[13]\d{3}[A-Z0-9-]*|XG-?PON|GPON|EPON|OLT|ONU)\b", body, re.I)})
    out.append(f"    pistas de modelo en el HTML: {hints or 'ninguna'}  (cuerpo={len(body)} bytes)")
    if not m or len(m.group(1).strip()) < 6:
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", body, flags=re.S | re.I)
        out.append(f"    texto: {re.sub(r'\s+', ' ', text).strip()[:200]!r}")
    return out


def probe_silent_port(host: str, port: int, timeout: float) -> None:
    """Sondeos sin credenciales para un puerto TCP que no envía banner."""
    import ssl
    print("\n== Sondeo (sin credenciales) de un puerto que no habla primero")
    # A) Enter → servidores Telnet/CLI suelen responder con login/prompt
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(b"\r\n")
            try:
                d = s.recv(512)
            except socket.timeout:
                d = b""
        kind = ("Telnet/CLI (negociación IAC)" if d[:1] == b"\xff" else
                "HTTP (rechaza líneas vacías)" if d.startswith(b"HTTP/") else
                "TLS (alerta)" if d[:1] in (b"\x15", b"\x16") else
                "Telnet/CLI (prompt)" if any(k in d.lower() for k in (b"login", b"user", b"password", b">", b"#")) else
                "sin respuesta" if not d else "desconocido")
        print(f"  A) Enter        → {kind}: {_printable(d, 100)!r}")
    except OSError as exc:
        print(f"  A) Enter        → error: {exc}")
    req = f"GET / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: tkc-identify\r\nConnection: close\r\n\r\n".encode()
    # B) HTTP en claro
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(req)
            buf = b""
            try:
                while len(buf) < 16384:
                    c = s.recv(2048)
                    if not c:
                        break
                    buf += c
            except socket.timeout:
                pass
        if buf.startswith(b"HTTP/"):
            print("  B) HTTP         → responde:")
            print("\n".join(_http_summary(buf)))
        else:
            print(f"  B) HTTP         → {'sin respuesta HTTP' if not buf else 'no es HTTP: ' + repr(_printable(buf, 60))}")
    except OSError as exc:
        print(f"  B) HTTP         → error: {exc}")
    # C) TLS (sin verificar el certificado: solo se inspecciona)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=None) as s:
                s.settimeout(timeout)
                tls_ver = s.version() or "TLS"
                s.sendall(req)
                buf = b""
                try:
                    while len(buf) < 16384:
                        c = s.recv(2048)
                        if not c:
                            break
                        buf += c
                except (socket.timeout, ssl.SSLError):
                    pass
        print(f"  C) TLS          → handshake OK ({tls_ver})")
        if buf.startswith(b"HTTP/"):
            print("\n".join(_http_summary(buf)))
    except (ssl.SSLError, OSError) as exc:
        print(f"  C) TLS          → no ({type(exc).__name__})")


# --- 3. SNMP -------------------------------------------------------------------
async def _snmp_get(host: str, port: int, auth, timeout: float):
    from pysnmp.hlapi.v3arch.asyncio import (ContextData, ObjectIdentity, ObjectType,
                                             SnmpEngine, UdpTransportTarget, get_cmd)
    eng = SnmpEngine()
    try:
        tgt = await UdpTransportTarget.create((host, port), timeout=timeout, retries=1)
        return await get_cmd(eng, auth, tgt, ContextData(),
                             *[ObjectType(ObjectIdentity(o)) for _, o in SYS_OIDS])
    finally:
        try:
            eng.close_dispatcher()
        except Exception:
            pass


def snmp_try(label: str, host: str, port: int, auth, timeout: float, scrub: Scrub):
    print(f"\n== SNMP {label} {host}:{port}/udp (1 intento)")
    try:
        err_ind, err_stat, err_idx, vbs = asyncio.run(_snmp_get(host, port, auth, timeout))
    except Exception as exc:                       # pysnmp/sockets
        print("  error:", scrub(f"{type(exc).__name__}: {exc}"))
        return None
    if err_ind:
        print("  sin respuesta válida:", scrub(str(err_ind)))
        return None
    if err_stat:
        print("  error del agente:", scrub(err_stat.prettyPrint()))
        return None
    out = {}
    for (name, _), vb in zip(SYS_OIDS, vbs):
        val = vb[1]
        # OIDs en numérico (prettyPrint los resuelve a nombre simbólico y no coincidiría)
        out[name] = ".".join(map(str, val.asTuple())) if hasattr(val, "asTuple") else val.prettyPrint()
        print(f"  {name:12s} {scrub(out[name])[:140]}")
    return out


def v2c_auth(community: str):
    from pysnmp.hlapi.v3arch.asyncio import CommunityData
    return CommunityData(community, mpModel=1)


def v3_auth(user: str, ap: str | None, apw: str | None, pp: str | None, ppw: str | None):
    import pysnmp.hlapi.v3arch.asyncio as api
    kw = {}
    if apw:
        kw["authKey"] = apw
        kw["authProtocol"] = getattr(api, AUTH.get((ap or "SHA").upper(), AUTH["SHA"]))
    if ppw:
        kw["privKey"] = ppw
        kw["privProtocol"] = getattr(api, PRIV.get((pp or "AES").upper(), PRIV["AES"]))
    return api.UsmUserData(user, **kw)


# --- 4. interpretación -----------------------------------------------------------
def interpret(info: dict) -> None:
    oid = (info.get("sysObjectID") or "").lstrip(".")
    descr = (info.get("sysDescr") or "").lower()
    print("\n== Interpretación")
    reg = default_registry()
    owner = None
    for v in reg.vendors():
        ent = reg.get(v).enterprise_oid
        if ent and (oid == ent or oid.startswith(ent + ".")):
            owner = v
            break
    if oid.startswith("1.3.6.1.4.1."):
        print(f"  enterprise: {oid.split('.')[6]}  → vendor en vendors.yaml: {owner or 'NO registrado'}")
    if owner:
        toks = [t for t in reg.get(owner).families if t.lower() in descr]
        print(f"  modelo(s) de vendors.yaml citados en sysDescr: {toks or 'ninguno (revisar sysDescr)'}")
    if oid.startswith("1.3.6.1.4.1.37950.1.1.5"):
        print("  sysObjectID cuelga de 37950.1.1.5 → aplica el MIB V1600D (LibreNMS/vsolution).")
    elif oid.startswith("1.3.6.1.4.1.37950"):
        print("  VSOL pero fuera de 37950.1.1.5 → el MIB V1600D NO se asume; buscar el MIB de esa rama.")


def _ensure_pysnmp() -> None:
    """Si pysnmp no está en este intérprete, se relanza con el del .venv del proyecto."""
    try:
        import pysnmp  # noqa: F401
        return
    except ImportError:
        pass
    import os
    venv_py = ROOT / ".venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), *sys.argv])
    sys.exit("falta pysnmp: usa .venv/bin/python scripts/vendor_identify.py ... "
             "o instala requirements.txt")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("vendor")
    ap.add_argument("--model")
    ap.add_argument("--dry-run", action="store_true", help="solo muestra variables presentes/faltantes")
    ap.add_argument("--skip-tcp", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="si el puerto TCP no envía banner: sondeo Telnet/HTTP/HTTPS sin credenciales")
    ap.add_argument("--skip-snmp", action="store_true")
    ap.add_argument("--timeout", type=float, default=4.0)
    a = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass

    if not a.dry_run and not a.skip_snmp:
        _ensure_pysnmp()
    show_env(a.vendor, a.model)
    if a.dry_run:
        return 0
    host = creds.get(a.vendor, "HOST", a.model)
    if not host:
        print(f"\nFalta el host: define TKC_{a.vendor.upper()}_HOST en el .env")
        return 2
    scrub = Scrub([creds.get(a.vendor, k, a.model) for k in creds.SECRET_KEYS])

    cli_port = creds.get(a.vendor, "CLI_PORT", a.model)
    if cli_port and not a.skip_tcp:
        chost = creds.get(a.vendor, "CLI_HOST", a.model) or host
        tcp_banner(chost, int(cli_port), a.timeout)
        if a.probe:
            probe_silent_port(chost, int(cli_port), a.timeout)

    info = None
    if not a.skip_snmp:
        snmp_port = int(creds.get(a.vendor, "SNMP_PORT", a.model) or 161)
        comm = creds.get(a.vendor, "RO_COMMUNITY", a.model)
        if comm:
            info = snmp_try("v2c", host, snmp_port, v2c_auth(comm), a.timeout, scrub)
        v3u = creds.get(a.vendor, "SNMPV3_USER", a.model)
        if v3u and not info:
            auth = v3_auth(v3u, creds.get(a.vendor, "SNMPV3_AUTH_PROTO", a.model),
                           creds.get(a.vendor, "SNMPV3_AUTH_PASSWORD", a.model),
                           creds.get(a.vendor, "SNMPV3_PRIV_PROTO", a.model),
                           creds.get(a.vendor, "SNMPV3_PRIV_PASSWORD", a.model))
            info = snmp_try("v3", host, snmp_port, auth, a.timeout, scrub)
        if not comm and not v3u:
            print("\n(sin RO_COMMUNITY ni SNMPV3_USER: se omite SNMP)")
    if info:
        interpret(info)
    return 0 if info or cli_port else 1


if __name__ == "__main__":
    sys.exit(main())
