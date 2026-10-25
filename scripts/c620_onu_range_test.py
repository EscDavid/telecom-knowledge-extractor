"""Mide el rango REAL de índices de ONU por puerto PON en la C620 (la sintaxis dice 1-256; el 250 no registró).

Para cada índice N de la lista: comprueba que está libre, autoriza UNA ONU de prueba en espera con `onu N type LATIC sn <SN>`,
observa su fase durante ~90 s (registrada = cualquier fase distinta de OffLine: syncMib/working/LOS/Logging), y hace rollback
(`no onu N`) esperando a que la ONU vuelva a la lista de espera. Al final verifica que la configuración del puerto quedó idéntica.
Solo se tocan los índices de la lista (todos libres y altos); NO se escribe `write`; lista cerrada de comandos.

Uso:  python scripts/c620_onu_range_test.py <SN en espera> [--indices 64,96,127,128,129,130,192,255,256] [--pon 1/1/5]
Salida: docs/walks/diagnostics/ZTE_C620_cli_reads_onu_range.txt  (+ línea final `RESULTADO: {json}`)
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
PON = sys.argv[sys.argv.index("--pon") + 1] if "--pon" in sys.argv else "1/1/5"
INDICES = [int(x) for x in (sys.argv[sys.argv.index("--indices") + 1] if "--indices" in sys.argv else "64,96,127,128,129,130,192,255,256").split(",")]
OBSERVE_S, STEP_S = 90, 10
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_onu_range.txt", "w")

ALLOWED = {"conf t", "end", "exit", "terminal length 0", f"interface gpon_olt-{PON}"}
for n in INDICES:
    ALLOWED |= {f"onu {n} type LATIC sn {SN}", f"no onu {n}"}
READS = ["show gpon global config", "show gpon olt", "show pon olt", "show gpon slot 1", "show gpon onu state gpon_olt-" + PON]


def log(s):
    LOG.write(s + "\n"); LOG.flush(); print(s, flush=True)


tn = telnetlib.Telnet(os.environ["TKC_SNMP_HOST"], int(os.environ["TKC_TELNET_PORT"]), 20)
tn.read_until(b"sername:", 20); tn.write(os.environ["TKC_TELNET_USER"].encode() + b"\n")
tn.read_until(b"assword:", 20); tn.write(os.environ["TKC_TELNET_PASSWORD"].encode() + b"\n")
time.sleep(3); tn.read_very_eager()
PROMPT = re.compile(r"(ZXAN[\w()\-/:.]*#)\s*$")
in_config = False


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
        if PROMPT.search(buf):
            break
    if cmd == "conf t":
        in_config = "(config)#" in prompt_of(buf)
    elif cmd == "end":
        in_config = False
    log(f">>> {cmd}\n{buf.strip()}\n")
    return buf


def olt_cfg():
    return re.sub(r"\s+", " ", run(f"show running-config-interface gpon_olt-{PON}"))


def present(n):
    return bool(re.search(rf"onu {n} type", olt_cfg()))


def phase(n):
    o = run(f"show gpon onu state gpon_olt-{PON}")
    m = re.search(rf"{re.escape(PON)}:{n}\s+(\S+)\s+(\S+)\s+(\S+)", o)
    return (m.group(3), m.group(2)) if m else (None, None)


def remove(n):
    for _ in range(3):
        if "(config)#" not in prompt_of(run("conf t")):
            run("end"); time.sleep(2); continue
        run(f"interface gpon_olt-{PON}"); run(f"no onu {n}"); run("end"); time.sleep(2)
        if not present(n):
            return True
    return False


res = {"indices": {}, "rollback_ok": True}
started, before = False, None
try:
    run("terminal length 0")
    if SN not in run("show pon onu uncfg"):
        raise SystemExit("La ONU ya no está en espera: no se hace nada.")
    before = olt_cfg()
    busy = [n for n in INDICES if present(n)]
    if busy:
        raise SystemExit(f"Índices ya en uso {busy}: no se hace nada.")
    for c in READS:                                   # lecturas de capacidad (errores esperables)
        run(c)
    started = True
    for n in INDICES:
        info = {"autorizacion": None, "fases": [], "registra": False}
        if "(config)#" not in prompt_of(run("conf t")):
            run("end"); run("conf t")
        run(f"interface gpon_olt-{PON}")
        o = run(f"onu {n} type LATIC sn {SN}")
        err = re.search(r"%Error (\d+): ([^\n]+)", o)
        info["autorizacion"] = f"ERR {err.group(1)}: {err.group(2)}" if err else "OK"
        run("end")
        if not err:
            t = 0
            while t < OBSERVE_S:
                time.sleep(STEP_S); t += STEP_S
                ph, omcc = phase(n)
                info["fases"].append((t, ph, omcc))
                if ph and ph != "OffLine":
                    info["registra"] = True
                if ph == "working":
                    break
        ok = remove(n)
        info["rollback"] = ok
        res["rollback_ok"] &= ok
        res["indices"][str(n)] = info
        log(f"== índice {n}: {info['autorizacion']} | registra={info['registra']} | fases={info['fases']}")
        for _ in range(6):                           # esperar a que la ONU vuelva a la lista de espera
            if SN in run("show pon onu uncfg"):
                break
            time.sleep(10)
finally:
    if started:
        for n in INDICES:                             # barrido de seguridad: solo índices de la lista
            if present(n):
                res["rollback_ok"] &= remove(n)
        res["config_puerto_identica"] = (before == olt_cfg())
        res["back_in_uncfg"] = SN in run("show pon onu uncfg")
        reg = [int(k) for k, v in res["indices"].items() if v["registra"]]
        res["max_indice_que_registra"] = max(reg) if reg else None
        res["min_indice_que_no_registra"] = min([int(k) for k, v in res["indices"].items() if v["autorizacion"] == "OK" and not v["registra"]] or [0]) or None
    log("RESULTADO: " + json.dumps(res, ensure_ascii=False))
    tn.write(b"exit\n"); tn.close()
