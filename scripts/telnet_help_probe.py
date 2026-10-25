"""Descubrimiento de sintaxis CLI por Telnet SIN ejecutar ningún cambio (ZTE C6x0).

Garantías (verificadas por código antes de enviar cada línea):
  - Modo exec: solo `show ...` (se ejecuta) o cualquier línea terminada en `?` (ayuda).
  - Modo config: solo `configure terminal`, entradas de sub-modo (`interface X`,
    `pon-onu-mng X`, `gpon`, `pon`), `end`, y líneas terminadas en `?`.
    Nunca se pulsa Enter sobre un comando de configuración: la ayuda se pide con `?`
    (que el CLI atiende al instante) y la línea se borra con Ctrl-U.

    .venv/bin/python scripts/telnet_help_probe.py --target c620|c600 [--cmds-file F]
Credenciales por entorno: TKC_TELNET_HOST/PORT/USER/PASSWORD (como telnet_read_probe.py).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
import telnetlib  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROMPT = re.compile(r"ZXAN[\w()\-]*#\s*$")
ENTER_OK = re.compile(r"^(configure terminal|end|exit|show .+|(interface|pon-onu-mng) \S+|gpon|pon)$")


class Unsafe(Exception):
    pass


class Session:
    def __init__(self, host, port, user, pwd):
        self.tn = telnetlib.Telnet(host, port, 20)
        self.tn.read_until(b"sername:", 20)
        self.tn.write(user.encode() + b"\n")
        self.tn.read_until(b"assword:", 20)
        self.tn.write(pwd.encode() + b"\n")
        time.sleep(3)
        self.tn.read_very_eager()
        self.in_config = False

    def _read(self, wait=6.0):
        buf, t0, quiet = "", time.time(), 0
        while time.time() - t0 < wait:
            time.sleep(0.5)
            d = self.tn.read_very_eager().decode(errors="replace").replace("\r", "")
            buf += d
            if d:
                quiet = 0
                t0 = max(t0, time.time() - wait + 4)   # mientras haya salida, seguir leyendo
            else:
                quiet += 1
            if "--More--" in d:
                self.tn.write(b" ")
                continue
            if quiet >= 3 and PROMPT.search(buf.rstrip("\x00")):
                break
        return re.sub(r"\s*--More--\s*", "\n", buf)

    def help(self, line: str, wait=5.0) -> str:
        """`line` debe terminar en '?': se envía SIN Enter y se borra con Ctrl-U."""
        if not line.rstrip().endswith("?"):
            raise Unsafe(line)
        self.tn.write(line.encode())
        out = self._read(wait)
        self.tn.write(b"\x15")          # Ctrl-U: borra la línea (no se ejecuta nada)
        time.sleep(0.3)
        self.tn.write(b"\n")            # línea vacía -> prompt limpio
        self._read(2)
        return out

    def run(self, line: str, wait=8.0) -> str:
        if line.rstrip().endswith("?"):
            return self.help(line)
        if not ENTER_OK.match(line):
            raise Unsafe(line)
        if self.in_config and line.startswith("show "):
            raise Unsafe("show en modo config: " + line)
        self.tn.write(line.encode() + b"\n")
        out = self._read(wait)
        if line == "configure terminal":
            self.in_config = True
        elif line in ("end",):
            self.in_config = False
        return out

    def close(self):
        try:
            if self.in_config:
                self.tn.write(b"end\n")
                time.sleep(1)
            self.tn.write(b"exit\n")
        finally:
            self.tn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["c620", "c600"], required=True)
    ap.add_argument("--cmds-file", required=True, help="una línea por comando (# comentarios)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    if args.target == "c620":
        host, port = os.environ["TKC_SNMP_HOST"], int(os.environ["TKC_TELNET_PORT"])
        user, pwd = os.environ["TKC_TELNET_USER"], os.environ["TKC_TELNET_PASSWORD"]
    else:
        host, port = os.environ["C600_HOST"], int(os.environ["C600_TELNET_PORT"])
        user, pwd = os.environ["C600_USER"], os.environ["C600_PASS"]
    cmds = [l.rstrip("\n") for l in open(args.cmds_file) if l.strip() and not l.startswith("#")]
    for c in cmds:                       # validar TODO antes de conectar
        if not (c.rstrip().endswith("?") or ENTER_OK.match(c)):
            print("RECHAZADO (no seguro):", c, file=sys.stderr)
            return 2
    s = Session(host, port, user, pwd)
    with open(args.out, "w", encoding="utf-8") as f:
        try:
            for c in cmds:
                out = s.run(c)
                f.write(f"\n{'=' * 78}\n## {c}\n{'=' * 78}\n{out.strip()}\n")
                print(f"[{'?' if c.endswith('?') else 'ok'}] {c}", flush=True)
                time.sleep(0.8)
        finally:
            s.close()
    print("salida en", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
