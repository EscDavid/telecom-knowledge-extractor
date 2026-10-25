"""Prueba de `gemport … portid` / `tcont … allocid` (C620) en un puerto PON VACÍO, sin riesgo para clientes.

Contexto: `gemport N portid <129-4095> tcont M` da 222370 'Not support this operation'; la ayuda dice que portid/allocid manuales
solo se admiten con `resource mode2` en `interface gpon_olt-<pon>` (por defecto mode1: la OLT asigna Port-ID/Alloc-ID).
El gemport normal (`gemport N name <x> tcont M`) YA está verificado y es el que usa el aprovisionamiento real; esto solo prueba la
asignación manual. Para no afectar a ninguna ONU en producción se usa un puerto sin ONU configuradas (por defecto 1/1/16).

Flujo: comprueba que el puerto está vacío → `resource mode2` → autoriza la ONU de prueba (índice 1, solo configuración; la ONU física
está en otro puerto y no se registra) → prueba portid/allocid → relee la configuración → rollback (`no onu 1`, `resource mode1`).
Lista cerrada de comandos; sin `write`; la bandera `started` evita el rollback si las comprobaciones previas fallan.

Uso:  python scripts/c620_gemport_portid_test.py <SN en espera> [--pon 1/1/16]
Salida: docs/walks/diagnostics/ZTE_C620_cli_reads_gemport_portid.txt  (+ línea final `RESULTADO: {json}`)
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
PON = sys.argv[sys.argv.index("--pon") + 1] if "--pon" in sys.argv else "1/1/16"
IDX = 1
ONU = f"gpon_onu-{PON}:{IDX}"
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_gemport_portid.txt", "w")

BASE = ["vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON", "gemport 1 name internet tcont 1"]
TESTS = ["gemport 2 name tkc portid 1025 tcont 1", "gemport 3 portid 1026 tcont 1", "gemport 4 portid 300 tcont 1", "tcont 2 allocid 1025 profile SMARTOLT-50M-UP",
         "tcont 3 name tkcalloc allocid 1026 profile SMARTOLT-50M-UP", "tcont 4 allocid 300 profile SMARTOLT-50M-UP",
         "no gemport 2", "no gemport 3", "no gemport 4", "no tcont 2", "no tcont 3", "no tcont 4"]
HELP = ["gemport 2 ?", "gemport 2 name tkc ?", "gemport 2 name tkc portid 1025 ?", "tcont 2 ?", "tcont 2 allocid 1025 ?"]
ALLOWED = {"conf t", "end", "exit", "terminal length 0", f"interface gpon_olt-{PON}", "resource mode2", "resource mode1",
           f"onu {IDX} type LATIC sn {SN}", f"no onu {IDX}", f"interface {ONU}"} | set(BASE + TESTS)


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


def read(wait):
    buf, t0 = "", time.time()
    while time.time() - t0 < wait:
        time.sleep(0.5)
        d = tn.read_very_eager().decode(errors="replace").replace("\r", "")
        buf += d
        if "--More--" in d:
            tn.write(b" "); continue
        if PROMPT.search(buf):
            break
    return buf


def run(cmd, wait=15):
    global in_config
    if cmd.endswith("?"):                                  # ayuda: sin Enter y se borra con Ctrl-U
        if cmd not in HELP:
            raise SystemExit(f"AYUDA NO PERMITIDA: {cmd}")
        tn.write(cmd.encode()); buf = read(6); tn.write(b"\x15"); time.sleep(0.3); tn.write(b"\n"); read(2)
    else:
        if cmd not in ALLOWED and not cmd.startswith("show "):
            raise SystemExit(f"COMANDO NO PERMITIDO: {cmd}")
        tn.write(cmd.encode() + b"\n"); buf = read(wait)
        if cmd == "conf t":
            in_config = "(config)#" in prompt_of(buf)
        elif cmd == "end":
            in_config = False
    log(f">>> {cmd}\n{buf.strip()}\n")
    return buf


def cfg():
    return run(f"show running-config-interface gpon_olt-{PON}")


def mode(cmds, enter, want, res):
    if not in_config:
        run("conf t")
    o = run(enter)
    if want not in prompt_of(o):
        res[f"[no entró] {enter}"] = "ERR"
        return
    for c in cmds:
        o = run(c)
        e = re.search(r"%Error (\d+): ([^\n]+)", o)
        res[c] = f"ERR {e.group(1)}: {e.group(2)}" if e else "OK"
        if want not in prompt_of(o):
            run("end"); run("conf t"); run(enter)


def rollback(res):
    for _ in range(4):
        if "(config)#" not in prompt_of(run("conf t")):
            run("end"); time.sleep(2); continue
        run(f"interface gpon_olt-{PON}"); run(f"no onu {IDX}"); run("resource mode1"); run("end"); time.sleep(2)
        if not re.search(rf"onu {IDX} type", cfg()):
            return True
    return False


res = {"rollback_ok": False}
started, before = False, None
try:
    run("terminal length 0")
    if SN not in run("show pon onu uncfg"):
        raise SystemExit("La ONU de prueba ya no está en la lista de espera: no se hace nada.")
    before = cfg()
    if re.search(r"onu \d+ type", before):
        raise SystemExit(f"El puerto {PON} TIENE ONU configuradas: no se hace nada (elige otro con --pon).")
    if re.search(r"gpon_onu-" + re.escape(PON), run(f"show gpon onu state gpon_olt-{PON}")):
        raise SystemExit(f"El puerto {PON} tiene ONU: no se hace nada.")
    run("show gpon onu state gpon_olt-" + PON)
    started = True
    mode(["resource mode2"], f"interface gpon_olt-{PON}", "(config-if-gpon_olt", res)
    o = run(f"onu {IDX} type LATIC sn {SN}")
    res["alta"] = "ERR" if "%Error" in o else "OK"
    run("exit")
    mode(BASE, f"interface {ONU}", "(config-if-gpon_onu", res)
    for h in HELP:
        run(h)
    mode(TESTS, f"interface {ONU}", "(config-if-gpon_onu", res)
    run("end")
    run(f"show running-config-interface {ONU}")
    res["config_puerto_con_resource_mode2"] = bool(re.search(r"resource mode2", cfg()))
finally:
    if started:
        res["rollback_ok"] = rollback(res)
        after = cfg()
        res["config_puerto_identica"] = (re.sub(r"\s+", " ", before) == re.sub(r"\s+", " ", after))
        res["resource_en_config_final"] = bool(re.search(r"resource", after))
        res["sn_sigue_en_espera"] = SN in run("show pon onu uncfg")
    log("RESULTADO: " + json.dumps(res, ensure_ascii=False))
    tn.write(b"exit\n"); tn.close()
