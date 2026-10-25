"""Cierra dos datos pendientes en la C620 con la ONU de prueba (índice 3 del puerto 1/1/5, no activa):
 1) valor guardado de `splitter 1-2-3` (se lee `show gpon onu detail-info` y la configuración ANTES de `no splitter`);
 2) cambio de tipo (`type <tipo>`) a un tipo EQUIVALENTE ya existente (LATIC -> ZTE-F600: mismas capacidades), con la confirmación [yes/no].
Rollback completo (`no onu 3`), comprobación de configuración idéntica, lista cerrada, sin `write`, bandera `started`.

Uso:  python scripts/c620_retype_splitter_test.py <SN en espera>
Salida: docs/walks/diagnostics/ZTE_C620_cli_reads_retype_splitter.txt  (+ línea final `RESULTADO: {json}`)
"""
import json
import os
import re
import sys
import time
import warnings

warnings.filterwarnings("ignore")
import telnetlib  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

ROOT = "/home/david/Escritorio/Proyectos/telecom-knowledge-extractor"
load_dotenv(f"{ROOT}/.env")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
SN = args[0] if args else "DF306B41EDB0"
PON, IDX = "1/1/5", 3
ONU = f"gpon_onu-{PON}:{IDX}"
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_retype_splitter.txt", "w")
ALLOWED = {"conf t", "end", "exit", "terminal length 0", f"interface gpon_olt-{PON}", f"onu {IDX} type LATIC sn {SN}", f"no onu {IDX}",
           f"interface {ONU}", "name TKCTEST", "vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON",
           "gemport 1 name internet tcont 1", "splitter 1-2-3", "no splitter", "type ZTE-F600", "type LATIC", "yes", "no"}

tn = telnetlib.Telnet(os.environ["TKC_SNMP_HOST"], int(os.environ["TKC_TELNET_PORT"]), 20)
tn.read_until(b"sername:", 20); tn.write(os.environ["TKC_TELNET_USER"].encode() + b"\n")
tn.read_until(b"assword:", 20); tn.write(os.environ["TKC_TELNET_PASSWORD"].encode() + b"\n")
time.sleep(3); tn.read_very_eager()
PROMPT = re.compile(r"(ZXAN[\w()\-/:.]*#)\s*$")
in_config = False


def log(s):
    LOG.write(s + "\n"); LOG.flush(); print(s, flush=True)


def prompt_of(o):
    m = re.findall(r"(ZXAN[\w()\-/:.]*#)", o)
    return m[-1] if m else "?"


def run(cmd, wait=15):
    global in_config
    if cmd not in ALLOWED and not cmd.startswith("show "):
        raise SystemExit(f"COMANDO NO PERMITIDO: {cmd}")
    tn.write(cmd.encode() + b"\n")
    buf, t0 = "", time.time()
    while time.time() - t0 < wait:
        time.sleep(0.5)
        d = tn.read_very_eager().decode(errors="replace").replace("\r", "")
        buf += d
        if "--More--" in d:
            tn.write(b" "); continue
        if "[yes/no]" in buf or PROMPT.search(buf):
            break
    if cmd == "conf t":
        in_config = "(config)#" in prompt_of(buf)
    elif cmd == "end":
        in_config = False
    log(f">>> {cmd}\n{buf.strip()}\n")
    return buf


def cfg():
    return re.sub(r"\s+", " ", run(f"show running-config-interface gpon_olt-{PON}"))


def err(o):
    e = re.search(r"%Error (\d+): ([^\n]+)", o)
    return f"ERR {e.group(1)}: {e.group(2)}" if e else "OK"


res = {"rollback_ok": False}
started, before = False, None
try:
    run("terminal length 0")
    if SN not in run("show pon onu uncfg"):
        raise SystemExit("La ONU ya no está en espera: no se hace nada.")
    before = cfg()
    if re.search(rf"onu {IDX} type", before):
        raise SystemExit(f"El índice {IDX} está en uso: no se hace nada.")
    started = True
    run("conf t"); run(f"interface gpon_olt-{PON}")
    res["alta"] = err(run(f"onu {IDX} type LATIC sn {SN}")); run("exit")
    run(f"interface {ONU}")
    for c in ("name TKCTEST", "vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON", "gemport 1 name internet tcont 1"):
        res[c] = err(run(c))
    # 1) splitter: leer ANTES de borrarlo
    res["splitter 1-2-3"] = err(run("splitter 1-2-3"))
    run("end")
    d = run(f"show gpon onu detail-info {ONU}")
    m = re.search(r"Splitter:\s*(.*)", d)
    res["splitter_en_detail_info"] = m.group(1).strip() if m else None
    rc = run(f"show running-config-interface {ONU}")
    res["splitter_en_config"] = [l.strip() for l in rc.splitlines() if "splitter" in l.lower()]
    run("conf t"); run(f"interface {ONU}"); res["no splitter"] = err(run("no splitter"))
    # 2) cambio de tipo a un tipo equivalente
    o = run("type ZTE-F600")
    res["type ZTE-F600"] = err(o)
    if "[yes/no]" in o:
        res["type ZTE-F600 -> yes"] = err(run("yes", wait=25))
    run("end")
    d2 = run(f"show gpon onu detail-info {ONU}")
    m2 = re.search(r"Type:\s*(\S+)", d2)
    res["tipo_tras_cambio"] = m2.group(1) if m2 else None
    res["config_onu_tras_cambio"] = re.sub(r"\s+", " ", run(f"show running-config-interface {ONU}"))[:400]
finally:
    if started:
        for _ in range(4):
            if "(config)#" not in prompt_of(run("conf t")):
                run("end"); time.sleep(2); continue
            run(f"interface gpon_olt-{PON}"); run(f"no onu {IDX}"); run("end"); time.sleep(2)
            if not re.search(rf"onu {IDX} type", cfg()):
                res["rollback_ok"] = True
                break
        res["config_puerto_identica"] = (before == cfg())
        res["sn_sigue_en_espera"] = SN in run("show pon onu uncfg")
    log("RESULTADO: " + json.dumps(res, ensure_ascii=False))
    tn.write(b"exit\n"); tn.close()
