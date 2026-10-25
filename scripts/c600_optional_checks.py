"""Comprobaciones de SOLO LECTURA en la C600 antes de subir el catálogo (pide las credenciales por prompt oculto; no se guardan):
  1) GETNEXT de las columnas `absent_in_populated_table` → docs/validation/absent_columns_c600.json
  2) Telnet (solo `show` y ayuda `?`): ayuda de `show gpon remote-onu` (¿existe `ssid info`?), y `show logfile brief` / `show logging alarm`
     → docs/validation/c600_optional_checks.json (resumen sin datos sensibles) + salida cruda en docs/walks/diagnostics/ (ignorada por git).
Uso:  .venv/bin/python scripts/c600_optional_checks.py   [host 190.14.224.10, SNMP 2161, Telnet 2123 por defecto]
"""
import datetime
import getpass
import glob
import json
import os
import re
import subprocess
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import telnetlib  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("C600_HOST", "190.14.224.10")
SNMP_PORT, TELNET_PORT = os.environ.get("C600_SNMP_PORT", "2161"), int(os.environ.get("C600_TELNET_PORT", "2123"))
comm = getpass.getpass("Community SNMP de solo lectura de la C600: ")
user = input("Usuario Telnet de la C600: ")
pwd = getpass.getpass("Contraseña Telnet de la C600: ")
today = datetime.date.today().isoformat()

# 1) SNMP
cols = [o["oid"] for f in glob.glob(str(ROOT / "catalog/zte/zxa10-c600/catalog-1.1.0/oids/*.json")) for o in json.load(open(f))["oids"]
        if (o.get("pending_validation") or {}).get("category") in ("absent_in_populated_table", "not_exposed")]
res = {}
for oid in sorted(cols):
    r = subprocess.run(["snmpgetnext", "-v2c", "-On", "-c", comm, "-t", "10", "-r", "2", f"{HOST}:{SNMP_PORT}", oid], capture_output=True, text=True)
    first = (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ""
    nxt = first.split(" = ")[0].lstrip(".")
    res[oid] = "EXISTE" if nxt.startswith(oid + ".") or nxt == oid else ("NO EXPUESTA" if nxt else "SIN RESPUESTA")
    print(f"{res[oid]:13} {oid}")
json.dump({"checked": today, "method": "snmpgetnext de solo lectura sobre cada columna", "firmware": "1.2.2_RZ", "family": "ZXA10 C600", "columns": res},
          open(ROOT / "docs/validation/absent_columns_c600.json", "w"), indent=1)

# 2) Telnet
tn = telnetlib.Telnet(HOST, TELNET_PORT, 20)
tn.read_until(b"sername:", 20); tn.write(user.encode() + b"\n")
tn.read_until(b"assword:", 20); tn.write(pwd.encode() + b"\n")
time.sleep(3); tn.read_very_eager()
P = re.compile(r"(ZXAN[\w()\-/:.]*#)\s*$")


def read(wait, maxb=6000):
    buf, t0 = "", time.time()
    while time.time() - t0 < wait:
        time.sleep(0.5)
        d = tn.read_very_eager().decode(errors="replace").replace("\r", ""); buf += d
        if "--More--" in d:
            tn.write(b"q" if len(buf) > maxb else b" ")
        if P.search(buf) or len(buf) > maxb + 3000:
            break
    return buf


def show(c):
    assert c.startswith("show ") or c == "terminal length 0"
    tn.write(c.encode() + b"\n"); o = read(25); tn.write(b"\x03"); time.sleep(0.5); tn.read_very_eager(); return o


def helpq(c):
    assert c.endswith("?") and c.startswith("show ")
    tn.write(c.encode()); o = read(6); tn.write(b"\x15"); time.sleep(0.3); tn.write(b"\n"); read(2); return o


show("terminal length 0")
raw, summ = [], {"checked": today, "family": "ZXA10 C600"}
h = helpq("show gpon remote-onu ?"); raw.append(h)
summ["remote_onu_help"] = sorted(set(re.findall(r"^\s{1,4}([a-z][\w-]*)\s{2,}", h, re.M)))
summ["ssid_info_en_ayuda"] = "ssid" in h
for key, cmd in (("logfile_brief", "show logfile brief"), ("logging_alarm", "show logging alarm")):
    o = show(cmd); raw.append(o)
    summ[key] = {"acepta": "Invalid input" not in o and "%Error" not in o, "lineas": len(o.splitlines())}
    print(cmd, summ[key])
tn.write(b"exit\n"); tn.close()
(ROOT / "docs/walks/diagnostics/ZTE_C600_cli_reads_optional.txt").write_text("\n=====\n".join(raw))
json.dump(summ, open(ROOT / "docs/validation/c600_optional_checks.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(summ, ensure_ascii=False))
