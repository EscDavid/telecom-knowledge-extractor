"""Sonda Telnet de SOLO LECTURA para OLT Huawei VRP (MA5608T y compatibles).

v2 (2026-10-23): corrige un bug de desincronización de sesión del v1 — el paginador
real de este firmware es `---- More ( Press 'Q' to break ) ----`, no `--More--`, y
tras un `display <cmd>` sin argumentos el equipo a veces muestra un menú de parámetro
opcional (`{ <cr>|...K> }:`) que exige un Enter adicional antes de ejecutar. Si
cualquiera de los dos no se drena por completo, el siguiente comando se escribe
ENCIMA de la sesión paginada/pendiente y el equipo puede devolver contenido ajeno al
comando pedido — en la v1 esto hizo aparecer, sin haberlo pedido, tablas de ONT con
datos de abonado (nombre, dirección, plan) como arrastre de una paginación sin
cerrar. Por eso aquí CADA comando se antecede de una resincronización explícita
(drena cualquier paginador/menú pendiente antes de escribir nada nuevo) y la batería
se mantiene deliberadamente corta: solo comandos ya verificados por el operador en
este mismo equipo (ver conversación) o de bajo riesgo de salida extensa/paginada.
NO incluye display board <slot>/<detalle>, display cpu, ni la familia display ont
(autofind/info) — esas ya probaron, por accidente, arrastrar datos de abonado al
desincronizarse; el listado de ONT en autofind se obtiene por SNMP (ver
docs/walks/partial/, tabla hwGponDeviceAutoFindOntInfoTable), que no tiene paginador.

Nunca entra en modo configuración: cualquier comando que no empiece por "display "
(salvo `screen-length 0 temporary` y la resincronización `q`) se rechaza antes de
enviarse — misma disciplina que scripts/telnet_read_probe.py (ZTE).

Credenciales por marca (ver src/creds.py): TKC_HUAWEI_HOST, TKC_HUAWEI_CLI_PORT,
TKC_HUAWEI_CLI_USER, TKC_HUAWEI_CLI_PASSWORD. Para pasar por el túnel de gestión,
sobrescribe host/puerto en el entorno:

    TKC_HUAWEI_HOST=192.168.10.5 TKC_HUAWEI_CLI_PORT=23 \\
        .venv/bin/python scripts/huawei_telnet_read_probe.py
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
import telnetlib  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import creds  # noqa: E402

PROMPT_RE = re.compile(rb"\r?\n?[\w.\-()]+[#>] ?$")
# paginador real de este firmware: "---- More ( Press 'Q' to break ) ----"
# (más laxo que el --More-- de ZTE: admite texto entre los bloques de guiones)
MORE_RE = re.compile(rb"-{2,}[^\r\n]{0,80}\bMore\b[^\r\n]{0,80}-{2,}", re.I)
# menú de parámetro opcional que VRP muestra tras un `display <cmd>` sin argumentos;
# exige un <cr> (Enter) adicional para ejecutar con los valores por defecto
PARAM_HELPER_RE = re.compile(rb"\}:\s*$")
SESSION_OK = {"screen-length 0 temporary"}
PACE_S = 1.5
IDLE_POLL_S = 0.15


class ReadOnlyViolation(Exception):
    pass


class DesyncError(Exception):
    """La sesión no volvió a un prompt limpio: se detiene todo, no se adivina."""


class Probe:
    def __init__(self, host: str, port: int, timeout: float = 25.0):
        self.tn = telnetlib.Telnet(host, port, timeout)
        self.timeout = timeout

    def _read(self, deadline: float, allow_param_helper: bool = True) -> tuple[bytes, bool]:
        """Lee hasta el prompt final, drenando paginador y menú de parámetro.
        Devuelve (buffer, encontrado_prompt)."""
        buf = b""
        sent_helper_cr = False
        while time.monotonic() < deadline:
            chunk = self.tn.read_very_eager()
            if chunk:
                buf += chunk
                if MORE_RE.search(buf[-160:]):
                    buf = MORE_RE.sub(b"", buf)
                    self.tn.write(b" ")
                    time.sleep(0.05)
                    continue
                if PROMPT_RE.search(buf.rstrip(b"\x00")):
                    return buf, True
            else:
                stripped = buf.rstrip()
                if allow_param_helper and not sent_helper_cr and stripped and PARAM_HELPER_RE.search(stripped):
                    self.tn.write(b"\n")
                    sent_helper_cr = True
                    time.sleep(0.2)
                    continue
                time.sleep(IDLE_POLL_S)
        return buf, False

    def _resync(self) -> None:
        """Garantiza una sesión limpia antes de aceptar el siguiente comando: drena
        cualquier paginador pendiente. Usa Ctrl+C (control, nunca texto) — probado
        que la letra 'q' + Enter en este CLI VRP se interpreta como abreviatura del
        comando `quit` (cierre de sesión) y no como "romper paginador" (ver
        docs/adaptacion_multivendor.md / notas de esta sonda). Si tras Ctrl+C no
        vuelve un prompt limpio, se detiene: no se sigue adivinando sobre una
        sesión corrupta."""
        self.tn.write(b"\x03")
        time.sleep(0.3)
        self.tn.write(b"\n")
        buf, ok = self._read(time.monotonic() + 6.0, allow_param_helper=False)
        if not ok:
            raise DesyncError("no se pudo resincronizar la sesión antes del siguiente comando "
                              f"(resto en buffer: {buf[-200:]!r})")

    def login(self, user: str, password: str) -> str:
        self.tn.read_until(b"sername:", self.timeout)
        self.tn.write(user.encode() + b"\n")
        self.tn.read_until(b"assword:", self.timeout)
        self.tn.write(password.encode() + b"\n")
        banner, ok = self._read(time.monotonic() + self.timeout)
        if not ok or re.search(r"(?i)(sername|assword):\s*$", banner.decode(errors="replace")):
            raise SystemExit("Login rechazado por la OLT.")
        return banner.decode(errors="replace")

    def run(self, cmd: str, timeout: float | None = None, resync_first: bool = True) -> str:
        if not (cmd.startswith("display ") or cmd in SESSION_OK):
            raise ReadOnlyViolation(cmd)
        if resync_first:
            self._resync()
        self.tn.write(cmd.encode() + b"\n")
        buf, ok = self._read(time.monotonic() + (timeout or self.timeout))
        time.sleep(PACE_S)
        out = buf.decode(errors="replace").replace("\r", "")
        if not ok:
            out += "\n[TIMEOUT esperando prompt]"
        lines = out.split("\n")
        if lines and lines[0].strip() == cmd:
            lines = lines[1:]
        return "\n".join(lines).rstrip()

    def close(self):
        try:
            self.tn.write(b"quit\n")
        finally:
            self.tn.close()


REJECT_RE = re.compile(r"%\s*(Error|Unrecognized|Wrong|Ambiguous)|Unknown command|Incomplete command|"
                       r"error locates at|not exist", re.I)


def verdict(out: str) -> str:
    if "[TIMEOUT" in out:
        return "TIMEOUT"
    if REJECT_RE.search(out):
        return "RECHAZADO"
    body = [l for l in out.split("\n") if l.strip() and not PROMPT_RE.search(l.encode())
            and not re.match(r"^\{.*\}:\s*$", l.strip())]
    return "OK" if body else "VACIO"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "docs/walks/diagnostics/Huawei_MA5608T_cli_reads.txt"))
    ap.add_argument("--timeout", type=float, default=25.0)
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass

    host = creds.get("HUAWEI", "HOST")
    port = int(creds.get("HUAWEI", "CLI_PORT") or 23)
    user, pwd = creds.get("HUAWEI", "CLI_USER"), creds.get("HUAWEI", "CLI_PASSWORD")
    missing = [k for k, v in {"HOST": host, "CLI_USER": user, "CLI_PASSWORD": pwd}.items() if not v]
    if missing:
        print(f"Faltan en .env: {', '.join('TKC_HUAWEI_' + m for m in missing)}", file=sys.stderr)
        return 2

    results: list[tuple[str, str]] = []
    p = Probe(host, port, args.timeout)
    try:
        p.login(user, pwd)
        del pwd

        def do(cmd: str, timeout: float | None = None) -> str:
            try:
                out = p.run(cmd, timeout)
            except DesyncError as exc:
                print(f"[DETENIDO ] sesión desincronizada antes de: {cmd}\n  {exc}", flush=True)
                raise SystemExit(3)
            results.append((cmd, out))
            print(f"[{verdict(out):9}] {cmd}", flush=True)
            return out

        # Deliberadamente corto: solo lo ya verificado manualmente en ESTE equipo
        # (ver conversación) + sesión. Sin per-slot board/cpu ni la familia `ont`.
        do("screen-length 0 temporary", timeout=10)
        do("display version")
        do("display board 0")
        do("display snmp-agent sys-info")
        do("display acl all")
        do("display ip interface brief")
        do("display clock")
    finally:
        p.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Sonda Telnet solo lectura (VRP/Huawei) v2 — {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"# objetivo: x.x.x.{host.split('.')[-1]}:{port}\n\n## Resumen\n")
        for c, o in results:
            f.write(f"{verdict(o):9} {c}\n")
        for c, o in results:
            f.write(f"\n{'=' * 78}\n## {c}\n{'=' * 78}\n{o}\n")
    print(f"\nSalida completa en {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
