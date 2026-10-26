"""Sonda Telnet de SOLO LECTURA para una OLT ZTE clásica (C320 / C300). No escribe ni cambia nada.

Seguridad:
  - Lista cerrada: solo `terminal length 0` y comandos que empiezan por `show ` (se ejecutan) o líneas `show … ?`
    (ayuda: se envían SIN Enter y se borran con Ctrl-U). Cualquier otra cosa se rechaza ANTES de enviarse.
  - Nunca entra en modo configuración. Credenciales por prompt (la contraseña, oculta); no se leen del .env ni se guardan.
  - La salida completa (seriales, MAC, nombres de ONU) va a un archivo ignorado por git (`*cli_reads*`); el resumen
    que se pega en el chat solo lleva veredictos por comando (OK / VACIO / RECHAZADO / TIMEOUT).

Qué mide (para pasar comandos de `documented` a `verified` y fijar el signo de la potencia):
  1. sesión y descubrimiento global (versión, tarjetas, ONU sin autorizar, estado de las ONU, tipos, VLAN, perfiles, bitácora)
  2. un puerto PON y dos ONU (una `working` y, si existe, una que no lo esté), con la sintaxis de clásicas (`gpon-onu_1/1/1:1`)
     y la de C6 (`gpon_onu-1/1/1:1`) para ver cuál acepta este equipo
  3. potencia por CLI (`show pon power attenuation`) de ONU concretas: con --signed-fixture se usan las ONU cuyo valor SNMP
     crudo era >= 32768 (negativo con signo de 16 bits) para comparar CLI contra SNMP
  4. ayuda `?` de los árboles `show gpon onu`, `show pon`, `show gpon remote-onu`, `show alarm`

Uso:
    .venv/bin/python scripts/c320_readonly_probe.py [--pon 1/1/1] [--onu 1/1/1:1 ...] [--model c320|c300]
        [--signed-fixture docs/fixtures/zte-real/c320-20261001/snmp/onu_rx_power_signed.txt]
Salida: docs/walks/diagnostics/ZTE_<MODELO>_cli_reads_<fecha>.txt  y  docs/validation/<modelo>_readonly_probe.json (solo veredictos)
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
import telnetlib  # noqa: E402  (stdlib en 3.12, deprecado)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_RE = re.compile(r"(?:^|\n)[\w.\-()/:]*[#>] ?$")
MORE_RE = re.compile(r"--\s*More\s*--", re.I)
REJECT_RE = re.compile(r"%\s*(Invalid|Unknown|Incomplete|Ambiguous)|%Error|Error \d+|not exist|No related|Unrecognized", re.I)
PACE_S = 1.0
SESSION_OK = {"terminal length 0"}


class Unsafe(Exception):
    pass


def check_allowed(line: str) -> None:
    s = line.strip()
    if s in SESSION_OK:
        return
    if s.startswith("show ") and "\n" not in s and ";" not in s and "|" not in s:
        return
    raise Unsafe(f"comando no permitido: {line!r}")


class Probe:
    def __init__(self, host: str, port: int, timeout: float = 25.0):
        self.tn = telnetlib.Telnet(host, port, timeout)
        self.timeout = timeout

    def _read(self, wait: float) -> str:
        buf, t0, quiet = "", time.time(), 0
        while time.time() - t0 < wait:
            time.sleep(0.4)
            d = self.tn.read_very_eager().decode(errors="replace").replace("\r", "")
            if d:
                buf += d
                quiet = 0
                t0 = max(t0, time.time() - wait + 4)       # mientras haya salida, seguir leyendo
            else:
                quiet += 1
            if "--More--" in d:
                self.tn.write(b" ")
                continue
            if quiet >= 2 and PROMPT_RE.search(buf.rstrip("\x00")):
                break
        return re.sub(r"\s*--More--\s*", "\n", buf)

    def login(self, user: str, password: str) -> None:
        self.tn.read_until(b"sername:", self.timeout)
        self.tn.write(user.encode() + b"\n")
        self.tn.read_until(b"assword:", self.timeout)
        self.tn.write(password.encode() + b"\n")
        banner = self._read(8)
        if not PROMPT_RE.search(banner) or re.search(r"(?i)(sername|assword):\s*$", banner):
            raise SystemExit("Login rechazado por la OLT.")

    def run(self, line: str, wait: float = 12.0) -> str:
        if line.rstrip().endswith("?"):
            return self.help(line, min(wait, 6.0))
        check_allowed(line)
        self.tn.write(line.encode() + b"\n")
        out = self._read(wait)
        time.sleep(PACE_S)
        lines = out.split("\n")
        if lines and lines[0].strip() == line:
            lines = lines[1:]
        return "\n".join(lines).rstrip()

    def help(self, line: str, wait: float) -> str:
        """Ayuda `?`: se envía SIN Enter y la línea se borra con Ctrl-U (no se ejecuta nada)."""
        if not line.strip().startswith("show "):
            raise Unsafe(f"ayuda no permitida: {line!r}")
        self.tn.write(line.encode())
        out = self._read(wait)
        self.tn.write(b"\x15")
        time.sleep(0.3)
        self.tn.write(b"\n")
        self._read(2)
        return out

    def close(self) -> None:
        try:
            self.tn.write(b"exit\n")
        finally:
            self.tn.close()


def verdict(out: str) -> str:
    if "[TIMEOUT" in out:
        return "TIMEOUT"
    if REJECT_RE.search(out):
        return "RECHAZADO"
    body = [l for l in out.split("\n") if l.strip() and not PROMPT_RE.search(l)]
    return "OK" if body else "VACIO"


def onu_from_ifindex(ifindex: int, n: int) -> str | None:
    """ifIndex de clásicas 0x1SSPP00 ->  shelf/slot/pon:n  (268435456 + slot*65536 + pon*256, shelf 1)."""
    d = ifindex - 268435456
    slot, pon = d // 65536, (d % 65536) // 256
    return f"1/{slot}/{pon}:{n}" if 0 < slot < 32 and 0 < pon <= 32 else None


def signed_onus(path: Path) -> list[str]:
    out = []
    for l in path.read_text(errors="ignore").splitlines():
        m = re.search(r"1012\.3\.50\.12\.1\.1\.10\.(\d+)\.(\d+)(?:\.1)? = INTEGER: (\d+)", l)
        if m and 32768 <= int(m.group(3)) < 65535:
            o = onu_from_ifindex(int(m.group(1)), int(m.group(2)))
            if o:
                out.append(o)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="c320", choices=["c320", "c300"])
    ap.add_argument("--pon", help="puerto PON (p. ej. 1/1/1); por defecto el primero con ONU working")
    ap.add_argument("--onu", action="append", default=[], help="ONU extra a medir (p. ej. 1/1/4:12); repetible")
    ap.add_argument("--signed-fixture", help="fixture SNMP de potencia con signo de ESTA misma OLT (derivan ONU extra)")
    args = ap.parse_args()

    host = input("Host de la OLT (IP o nombre): ").strip()
    port = int(input("Puerto Telnet [23]: ").strip() or "23")
    user = input("Usuario Telnet (solo lectura): ").strip()
    pwd = getpass.getpass("Contraseña Telnet (no se muestra): ")
    if not (host and user and pwd):
        print("Faltan datos.", file=sys.stderr)
        return 2

    extra = list(args.onu)
    if args.signed_fixture:
        fx = Path(args.signed_fixture)
        if not fx.exists():
            print(f"No existe {fx}", file=sys.stderr)
            return 2
        extra += signed_onus(fx)
    extra = list(dict.fromkeys(extra))

    results: list[tuple[str, str, str, str]] = []                # (grupo, variante, cmd, salida)
    p = Probe(host, port)
    try:
        p.login(user, pwd)

        def do(group: str, variant: str, cmd: str, wait: float = 12.0) -> str:
            out = p.run(cmd, wait)
            results.append((group, variant, cmd, out))
            print(f"[{verdict(out):9}] {variant:7} {cmd}", flush=True)
            return out

        # 1. Sesión y descubrimiento global
        do("sesion", "-", "terminal length 0")
        do("sesion", "-", "show clock")
        do("sesion", "-", "show version")
        do("sesion", "c6", "show software 1")
        do("global", "-", "show card", 20)
        state = do("global", "-", "show gpon onu state", 120)
        do("global", "classic", "show gpon onu uncfg", 30)
        do("global", "c6", "show pon onu uncfg", 30)
        do("global", "classic", "show onu-type", 20)
        do("global", "c6", "show onu-type gpon", 20)
        do("global", "-", "show vlan summary", 20)
        do("global", "-", "show gpon profile tcont", 30)
        do("global", "-", "show gpon profile traffic", 30)
        do("global", "c6", "show qos traffic-profile", 30)
        do("global", "-", "show logfile brief", 30)
        do("global", "-", "show logging alarm", 30)
        do("global", "-", "show alarm current", 30)
        do("global", "-", "show alarm history", 30)

        # Elegir PON y ONU (una working, otra no working si existe)
        rows = re.findall(r"(\d+/\d+/\d+):(\d+)\s+\S+\s+\S+\s+(\w+)", state)
        working = [(a, b) for a, b, s in rows if s.lower() == "working"]
        other = [(a, b) for a, b, s in rows if s.lower() != "working"]
        if args.pon:
            working = [(a, b) for a, b in working if a == args.pon] or working
        pon, n = working[0] if working else (args.pon or "1/1/1", "1")
        targets = [f"{pon}:{n}"]
        if other:
            targets.append(f"{other[0][0]}:{other[0][1]}")
        print(f"-- puerto {pon}; ONU a medir: {targets}; extra (potencia con signo): {extra}", flush=True)

        # 2. Puerto PON
        for v, ifc in (("classic", f"gpon-olt_{pon}"), ("c6", f"gpon_olt-{pon}")):
            do("puerto", v, f"show gpon onu state {ifc}", 40)
            do("puerto", v, f"show gpon onu baseinfo {ifc}", 40)
            do("puerto", v, f"show gpon onu uncfg {ifc}", 20)
            do("puerto", v, f"show running-config-interface {ifc}", 60)
            do("puerto", v, f"show interface {ifc}", 20)
            do("puerto", v, f"show pon power olt-rx {ifc}", 30)

        # 3. ONU (las dos sintaxis de nombre de interfaz)
        for idx in targets:
            for v, ifc in (("classic", f"gpon-onu_{idx}"), ("c6", f"gpon_onu-{idx}")):
                for cmd in (
                    f"show gpon onu detail-info {ifc}",
                    f"show gpon onu distance {ifc}",
                    f"show running-config-interface {ifc}",
                    f"show service-port interface {ifc}",
                    f"show mac interface {ifc}",
                    f"show pon onu information {ifc}",
                    f"show pon power attenuation {ifc}",
                    f"show pon power onu-rx {ifc}",
                    f"show pon power onu-tx {ifc}",
                    f"show gpon remote-onu equip {ifc}",
                    f"show gpon remote-onu capability {ifc}",
                    f"show gpon remote-onu interface eth {ifc}",
                    f"show gpon remote-onu sys-attr {ifc}",
                ):
                    do("onu", v, cmd, 30)

        # 4. Potencia por CLI de las ONU cuyo SNMP crudo era >= 32768 (verdad de terreno del signo)
        for idx in extra:
            for v, ifc in (("classic", f"gpon-onu_{idx}"), ("c6", f"gpon_onu-{idx}")):
                do("potencia", v, f"show pon power attenuation {ifc}", 30)
                do("potencia", v, f"show gpon onu detail-info {ifc}", 30)

        # 5. Ayuda de los árboles (sin Enter)
        for h in ("show gpon onu ?", "show pon ?", "show pon power ?", "show gpon remote-onu ?", "show alarm ?",
                  "show gpon profile ?", "show qos ?"):
            do("ayuda", "-", h, 6)
    finally:
        p.close()

    stamp = datetime.now().strftime("%Y%m%d")
    model = args.model.upper()
    out = ROOT / f"docs/walks/diagnostics/ZTE_{model}_cli_reads_{stamp}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    masked = f"x.x.x.{host.split('.')[-1]}" if re.fullmatch(r"[\d.]+", host) else "<host>"
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Sonda Telnet solo lectura — {datetime.now().isoformat(timespec='seconds')}\n# objetivo: {masked}:{port}\n\n## Resumen\n")
        for g, v, c, o in results:
            f.write(f"{verdict(o):9} {g:10} {v:7} {c}\n")
        for g, v, c, o in results:
            f.write(f"\n{'=' * 78}\n## [{g}/{v}] {c}\n{'=' * 78}\n{o}\n")
    summ = ROOT / f"docs/validation/{args.model}_readonly_probe.json"
    summ.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"), "model": model,
         "results": [{"group": g, "variant": v, "cmd": re.sub(r"\d+/\d+/\d+(:\d+)?", "<idx>", c), "verdict": verdict(o)}
                     for g, v, c, o in results]}, ensure_ascii=False, indent=1))
    print(f"\nSalida completa (con datos de ONU, NO subir a git): {out}\nResumen sin datos sensibles: {summ}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
