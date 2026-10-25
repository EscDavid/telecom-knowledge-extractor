"""Ciclo de vida de UNA ONU en espera de autorización (C620): autorizar, aprovisionar, esperar
'working', reiniciar, esperar, borrar y verificar. Con rollback garantizado.
Comandos de escritura permitidos (lista cerrada) y verificados antes de enviarse."""
import os, re, sys, time, json, warnings
warnings.filterwarnings("ignore")
import telnetlib
from dotenv import load_dotenv

load_dotenv("/home/david/Escritorio/Proyectos/telecom-knowledge-extractor/.env")
PON, IDX = "1/1/5", 3   # índice bajo y libre: en GPON el ONU-ID está limitado (el 250 nunca llegó a registrar)
SN, TYPE = (sys.argv[1] if len(sys.argv) > 1 else "DF30A601103C"), "LATIC"   # uso: script.py <SN en espera>
ONU = f"gpon_onu-{PON}:{IDX}"
LOG = open("/home/david/Escritorio/Proyectos/telecom-knowledge-extractor/docs/walks/diagnostics/ZTE_C620_cli_reads_onu_lifecycle.txt", "w")

ALLOWED = [
    r"^conf t$", r"^end$", r"^exit$", r"^terminal length 0$",
    rf"^interface gpon_olt-{PON}$", rf"^onu {IDX} type {TYPE} sn {SN}$", rf"^no onu {IDX}$",
    rf"^interface {re.escape(ONU)}$", r"^name TKCTEST$", r"^description TKCTEST$", r"^vport-mode manual$",
    r"^tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON$", r"^gemport 1 name internet tcont 1$",
    r"^vport 1 map-type vlan$", r"^vport-map 1 1 vlan 101$",
    rf"^pon-onu-mng {re.escape(ONU)}$", r"^service vlan101 gemport 1 vlan 101$", r"^veip 1$", r"^reboot$", r"^yes$", r"^no$",
    rf"^interface vport-{PON}\.{IDX}:1$",
    r"^service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN$",
    r"^show .+$",
]


def log(s):
    LOG.write(s + "\n"); LOG.flush(); print(s, flush=True)


tn = telnetlib.Telnet(os.environ["TKC_SNMP_HOST"], int(os.environ["TKC_TELNET_PORT"]), 20)
tn.read_until(b"sername:", 20); tn.write(os.environ["TKC_TELNET_USER"].encode() + b"\n")
tn.read_until(b"assword:", 20); tn.write(os.environ["TKC_TELNET_PASSWORD"].encode() + b"\n")
time.sleep(3); tn.read_very_eager()
PROMPT = re.compile(r"(ZXAN[\w()\-/:.]*#)\s*$")


def run(cmd, wait=15, expect=None):
    if not any(re.match(p, cmd) for p in ALLOWED):
        raise SystemExit(f"COMANDO NO PERMITIDO: {cmd}")
    tn.write(cmd.encode() + b"\n")
    buf, t0 = "", time.time()
    while time.time() - t0 < wait:
        time.sleep(0.5)
        d = tn.read_very_eager().decode(errors="replace").replace("\r", "")
        buf += d
        if "--More--" in d:
            tn.write(b" "); continue
        if expect and re.search(expect, buf):
            break
        if not expect and PROMPT.search(buf):
            break
    log(f">>> {cmd}\n{buf.strip()}\n")
    return buf


def prompt_of(o):
    m = re.findall(r"(ZXAN[\w()\-/:.]*#)", o)
    return m[-1] if m else "?"


def need(o, text, cmd):
    if "%Error" in o or text not in prompt_of(o):
        raise RuntimeError(f"fallo en '{cmd}': prompt={prompt_of(o)} err={'%Error' in o}")


def onu_state():
    o = run(f"show gpon onu state gpon_olt-{PON}", wait=15)
    m = re.search(rf"{PON}:{IDX}\s+(\S+)\s+(\S+)\s+(\S+)", o)
    return m.group(3) if m else None


def present():
    o = run(f"show running-config-interface gpon_olt-{PON}")
    return bool(re.search(rf"^\s+onu {IDX} type", o, re.M))


def rollback():
    for attempt in range(4):
        try:
            o = run("conf t");
            if "(config)#" not in prompt_of(o):
                run("end"); time.sleep(2); continue
            run(f"interface gpon_olt-{PON}")
            run(f"no onu {IDX}")
            run("end")
            time.sleep(3)
            if not present():
                log("ROLLBACK OK: la ONU ya no existe")
                return True
        except Exception as e:
            log(f"rollback intento {attempt}: {e}")
            time.sleep(2)
    return False


result = {"steps": []}
try:
    run("terminal length 0")
    u = run("show pon onu uncfg")
    assert SN in u, "la ONU ya no está en espera"
    assert not present(), f"el índice {IDX} ya está en uso"
    # 1) autorizar
    o = run("conf t"); need(o, "(config)#", "conf t")
    o = run(f"interface gpon_olt-{PON}"); need(o, "(config-if-gpon_olt", "interface olt")
    o = run(f"onu {IDX} type {TYPE} sn {SN}"); need(o, "(config-if-gpon_olt", "onu type sn")
    o = run("exit"); need(o, "(config)#", "exit")
    # 2) aprovisionar (plantilla real)
    o = run(f"interface {ONU}"); need(o, "(config-if-gpon_onu", "interface onu")
    for c in ("name TKCTEST", "description TKCTEST", "vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON",
              "gemport 1 name internet tcont 1", "vport 1 map-type vlan", "vport-map 1 1 vlan 101"):
        o = run(c); need(o, "(config-if-gpon_onu", c)
    o = run("exit"); need(o, "(config)#", "exit")
    o = run(f"pon-onu-mng {ONU}"); need(o, "(config-gpon-onu-mng)#", "pon-onu-mng")
    for c in ("service vlan101 gemport 1 vlan 101", "veip 1"):
        o = run(c); need(o, "(config-gpon-onu-mng)#", c)
    o = run("exit"); need(o, "(config)#", "exit")
    o = run(f"interface vport-{PON}.{IDX}:1"); need(o, "(config-if-vport", "interface vport")
    c = "service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN"
    o = run(c); need(o, "(config-if-vport", c)
    o = run("end")
    result["provisioned"] = True
    run(f"show running-config-interface {ONU}")
    run(f"show running-config-interface vport-{PON}.{IDX}:1")
    # 3) esperar working
    states = []
    for i in range(12):
        time.sleep(10)
        st = onu_state(); states.append(st)
        log(f"estado ONU ({i*10+10}s): {st}")
        if st == "working":
            break
    result["states_before_reboot"] = states
    # 4) reiniciar
    if states and states[-1] == "working":
        run(f"show gpon onu detail-info {ONU}")
        o = run("conf t"); need(o, "(config)#", "conf t")
        o = run(f"pon-onu-mng {ONU}"); need(o, "(config-gpon-onu-mng)#", "pon-onu-mng")
        o = run("reboot", wait=10, expect=r"\[yes/no\]|\(config-gpon-onu-mng\)#\s*$")
        result["reboot_prompt"] = o.strip()[-120:]
        if re.search(r"yes/no", o):
            o2 = run("yes", wait=15)
            result["reboot_response"] = o2.strip()[-200:]
        run("end")
        after = []
        for i in range(30):
            time.sleep(10)
            st = onu_state(); after.append(st)
            log(f"estado tras reboot ({i*10+10}s): {st}")
            if len(after) > 2 and st == "working" and any(x not in ("working",) for x in after[:-1]):
                break
        result["states_after_reboot"] = after
    else:
        log("La ONU no llegó a 'working': se prueba solo el diálogo de reboot sobre la ONU de prueba (sin tocar a nadie más).")
        o = run("conf t"); need(o, "(config)#", "conf t")
        o = run(f"pon-onu-mng {ONU}"); need(o, "(config-gpon-onu-mng)#", "pon-onu-mng")
        o = run("reboot", wait=10, expect=r"\[yes/no\]|\(config-gpon-onu-mng\)#\s*$")
        result["reboot_prompt_1"] = o.strip()[-160:]
        if re.search(r"yes/no", o):
            o2 = run("no", wait=10)            # 1) cancelar: prueba el texto sin efecto
            result["reboot_cancel_response"] = o2.strip()[-160:]
            o = run("reboot", wait=10, expect=r"\[yes/no\]|\(config-gpon-onu-mng\)#\s*$")
            o3 = run("yes", wait=15)           # 2) confirmar sobre la ONU de prueba (inestable, sin clientes)
            result["reboot_yes_response"] = o3.strip()[-200:]
        run("end")
finally:
    ok = rollback()
    result["rollback_ok"] = ok
    u = run("show pon onu uncfg")
    result["back_in_uncfg"] = SN in u
    for c in (f"show running-config-interface vport-{PON}.{IDX}:1", f"show gpon onu detail-info {ONU}"):
        o = run(c); result["residue_" + c.split()[1]] = ("%Error" in o) or ("not exist" in o.lower()) or ("No related" in o)
    log("RESULTADO: " + json.dumps(result, ensure_ascii=False))
    tn.write(b"exit\n"); tn.close()
