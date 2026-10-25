"""Sonda Telnet de SOLO LECTURA para OLT ZTE (C620/C600 y C300/C320).

Ejecuta los comandos `show` del módulo Redes en dos sintaxis:
  - doc   : la del documento (C300/C320: gpon-olt_1/1/1, gpon-onu_1/1/1:1)
  - c600  : la nativa de la familia C600 (gpon_olt-1/1/1, gpon_onu-1/1/1:1)
para comparar qué acepta el equipo. Nunca entra en modo configuración: cualquier comando
que no empiece por "show " (salvo `terminal length 0`) se rechaza antes de enviarse.

Credenciales desde .env: TKC_TELNET_HOST (por defecto TKC_SNMP_HOST), TKC_TELNET_PORT,
TKC_TELNET_USER, TKC_TELNET_PASSWORD.

    .venv/bin/python scripts/telnet_read_probe.py [--pon 1/1/1] [--out docs/walks/diagnostics/ZTE_C620_cli_reads.txt]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
import telnetlib  # noqa: E402  (stdlib en 3.12, deprecado)

from dotenv import load_dotenv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROMPT_RE = re.compile(rb"\r?\n?[\w.\-()]+[#>] ?$")
MORE_RE = re.compile(rb"--\s*More\s*--", re.I)
SESSION_OK = {"terminal length 0"}
PACE_S = 1.0


class ReadOnlyViolation(Exception):
    pass


class Probe:
    def __init__(self, host: str, port: int, timeout: float = 20.0):
        self.tn = telnetlib.Telnet(host, port, timeout)
        self.timeout = timeout

    def _read_until_prompt(self, timeout: float | None = None) -> bytes:
        deadline = time.monotonic() + (timeout or self.timeout)
        buf = b""
        while time.monotonic() < deadline:
            chunk = self.tn.read_very_eager()
            if chunk:
                buf += chunk
                if MORE_RE.search(buf[-40:]):
                    buf = MORE_RE.sub(b"", buf)
                    self.tn.write(b" ")
                    continue
                if PROMPT_RE.search(buf.rstrip(b"\x00")):
                    return buf
            else:
                time.sleep(0.1)
        return buf + b"\n[TIMEOUT esperando prompt]"

    def login(self, user: str, password: str) -> str:
        self.tn.read_until(b"sername:", self.timeout)
        self.tn.write(user.encode() + b"\n")
        self.tn.read_until(b"assword:", self.timeout)
        self.tn.write(password.encode() + b"\n")
        banner = self._read_until_prompt(self.timeout).decode(errors="replace")
        if not PROMPT_RE.search(banner.encode()) or re.search(r"(?i)(sername|assword):\s*$", banner):
            raise SystemExit("Login rechazado por la OLT.")
        return banner

    def run(self, cmd: str, timeout: float | None = None) -> str:
        if not (cmd.startswith("show ") or cmd in SESSION_OK):
            raise ReadOnlyViolation(cmd)
        self.tn.write(cmd.encode() + b"\n")
        out = self._read_until_prompt(timeout).decode(errors="replace").replace("\r", "")
        time.sleep(PACE_S)
        lines = out.split("\n")
        if lines and lines[0].strip() == cmd:  # eco del comando
            lines = lines[1:]
        return "\n".join(lines).rstrip()

    def close(self):
        try:
            self.tn.write(b"exit\n")
        finally:
            self.tn.close()


REJECT_RE = re.compile(r"%\s*(Invalid|Unknown|Incomplete|Ambiguous)|Error|not exist|No related", re.I)


def verdict(out: str) -> str:
    if "[TIMEOUT" in out:
        return "TIMEOUT"
    if REJECT_RE.search(out):
        return "RECHAZADO"
    body = [l for l in out.split("\n") if l.strip() and not PROMPT_RE.search(l.encode())]
    return "OK" if body else "VACIO"


def pon_variants(pon: str) -> dict[str, str]:
    return {"doc": f"gpon-olt_{pon}", "c600": f"gpon_olt-{pon}"}


def onu_variants(idx: str) -> dict[str, str]:
    return {"doc": f"gpon-onu_{idx}", "c600": f"gpon_onu-{idx}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pon", help="puerto PON a usar (p. ej. 1/1/1); por defecto el primero con ONUs")
    ap.add_argument("--out", default=str(ROOT / "docs/walks/diagnostics/ZTE_C620_cli_reads.txt"))
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    host = os.getenv("TKC_TELNET_HOST") or os.getenv("TKC_SNMP_HOST")
    port = int(os.getenv("TKC_TELNET_PORT", "23"))
    user, pwd = os.getenv("TKC_TELNET_USER"), os.getenv("TKC_TELNET_PASSWORD")
    missing = [k for k, v in {"host": host, "TKC_TELNET_USER": user, "TKC_TELNET_PASSWORD": pwd}.items() if not v]
    if missing:
        print(f"Faltan en .env: {', '.join(missing)}", file=sys.stderr)
        return 2

    results: list[tuple[str, str, str, str]] = []  # (grupo, variante, cmd, salida)
    p = Probe(host, port)
    try:
        p.login(user, pwd)

        def do(group: str, variant: str, cmd: str, timeout: float | None = None) -> str:
            out = p.run(cmd, timeout)
            results.append((group, variant, cmd, out))
            print(f"[{verdict(out):9}] {variant:5} {cmd}", flush=True)
            return out

        # 1. Sesión
        do("sesion", "-", "terminal length 0")
        do("sesion", "-", "show clock")
        do("sesion", "-", "show version")

        # 2. Descubrimiento global
        state = do("descubrimiento", "-", "show gpon onu state", timeout=90)
        do("descubrimiento", "doc", "show gpon onu uncfg")
        do("descubrimiento", "c600", "show pon onu uncfg")
        do("descubrimiento", "-", "show onu-type")
        do("descubrimiento", "c600", "show onu-type gpon")

        # Elegir PON y una ONU real
        m = None
        if args.pon:
            m = re.search(rf"gpon[_-]onu[_-]{re.escape(args.pon)}:(\d+)", state)
            pon = args.pon
        else:
            m = re.search(r"gpon[_-]onu[_-](\d+/\d+/\d+):(\d+)", state) or re.search(r"\b(\d+/\d+/\d+):(\d+)\b", state)
            pon = m.group(1) if m else "1/1/1"
        onu_n = m.group(m.lastindex) if m else "1"
        idx = f"{pon}:{onu_n}"
        print(f"-- usando PON {pon}, ONU {idx}", flush=True)

        for v, ifc in pon_variants(pon).items():
            do("puerto", v, f"show gpon onu state {ifc}")
            do("puerto", v, f"show gpon onu uncfg {ifc}")
            do("puerto", v, f"show running-config interface {ifc}", timeout=60)
        do("puerto", "c600", f"show gpon onu baseinfo gpon_olt-{pon}")

        # 3. Por ONU
        sn = None
        for v, ifc in onu_variants(idx).items():
            det = do("onu", v, f"show gpon onu detail-info {ifc}", timeout=40)
            sn = sn or (re.search(r"(?i)serial\s*number\s*:\s*(\S+)", det) or [None, None])[1]
            for cmd in (
                f"show running-config interface {ifc}",
                f"show onu running config {ifc}",
                f"show service-port interface {ifc}",
                f"show mac gpon onu {ifc}",
                f"show gpon remote-onu equip {ifc}",
                f"show gpon remote-onu capability {ifc}",
                f"show gpon remote-onu interface eth {ifc}",
                f"show gpon remote-onu interface video {ifc}",
                f"show gpon remote-onu interface wifi {ifc}",
                f"show gpon remote-onu wifi info {ifc}",
                f"show gpon remote-onu ssid info {ifc}",
                f"show gpon remote-onu traffic-limit {ifc}",
                f"show pon power attenuation {ifc}",
            ):
                do("onu", v, cmd, timeout=40)
        # Variantes propias de C600 (vport / running-config-interface / pon-onu-mng)
        do("onu", "c600", f"show running-config-interface gpon_onu-{idx}")
        do("onu", "c600", f"show running-config-interface vport-{pon}.{onu_n}:1")
        do("onu", "c600", f"show service-port interface vport-{pon}.{onu_n}:1")
        do("onu", "c600", f"show running-config pon-onu-mng gpon_onu-{idx}")
        do("onu", "c600", f"show mac vport-{pon}.{onu_n}:1")
        if sn:
            do("onu", "-", f"show gpon onu by sn {sn}")

        # 4. Catálogos de velocidad
        do("catalogos", "-", "show gpon profile tcont", timeout=40)
        do("catalogos", "-", "show gpon profile traffic", timeout=40)
        do("catalogos", "c600", "show running-config gpon", timeout=60)
    finally:
        p.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Sonda Telnet solo lectura — {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"# objetivo: x.x.x.{host.split('.')[-1]}:{port}\n\n## Resumen\n")
        for g, v, c, o in results:
            f.write(f"{verdict(o):9} {g:14} {v:5} {c}\n")
        for g, v, c, o in results:
            f.write(f"\n{'=' * 78}\n## [{g}/{v}] {c}\n{'=' * 78}\n{o}\n")
    print(f"\nSalida completa en {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
