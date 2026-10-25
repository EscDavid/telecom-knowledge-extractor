"""Batería 2 (C620) sobre UNA ONU de prueba no activa: vlan port/modo, wan-ip, tipos de ONU (crear/borrar, con interfaz WiFi
y cambio de tipo de la ONU de prueba para probar WiFi/SSID) y T-CONT tipos 1-4. Rollback completo y verificado.
Los %Error se registran y NO abortan. Uso: script.py <SN en espera>"""
import os, re, sys, time, json, warnings
warnings.filterwarnings("ignore")
import telnetlib
from dotenv import load_dotenv

ROOT = "/home/david/Escritorio/Proyectos/telecom-knowledge-extractor"
load_dotenv(f"{ROOT}/.env")
PON, IDX, TYPE = "1/1/5", 3, "LATIC"
SN = sys.argv[1] if len(sys.argv) > 1 else "DF306B41EDB0"
ONU, VP = f"gpon_onu-{PON}:{IDX}", f"vport-{PON}.{IDX}:1"
NT = "TKCTEST-TYPE"
TCS = {"TKCT1": "type 1 fixed 64", "TKCT2": "type 2 assured 64", "TKCT3": "type 3 assured 64 maximum 128", "TKCT4": "type 4 maximum 128"}
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_write_battery2.txt", "w")

BASE = ["name TKCTEST", "vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON", "gemport 1 name internet tcont 1",
        "vport 1 map-type vlan", "vport-map 1 1 vlan 101"]
MNG_BASE = ["service vlan101 gemport 1 vlan 101", "veip 1"]
SP = "service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN"
MNG_B = ["vlan port eth_0/1 mode tag vlan 101", "wan-ip 1 ipv4 mode dhcp vlan-profile SMARTOLT_VLAN_101",
         "wan-ip 1 ipv4 ping-response enable traceroute-response enable",
         "interface wifi wifi_0/1 state unlock", "ssid ctrl wifi_0/1 name TKCTEST", "ssid ctrl wifi_0/1 hide disable"]
MNG_HELP = ["wan-ip 1 ipv4 ping-response enable traceroute-response ?"]
PON_B = [f"onu-type {NT} gpon description TKCTEST max-tcont 8 max-gemport 32 max-veip 1", f"onu-type-if {NT} eth_0/1", f"onu-type-if {NT} wifi_0/1"]
ONU_TYPE = [f"type {NT}"]
FIXED = ["conf t", "end", "exit", "terminal length 0", f"interface gpon_olt-{PON}", f"onu {IDX} type {TYPE} sn {SN}", f"no onu {IDX}",
         f"interface {ONU}", f"pon-onu-mng {ONU}", f"interface {VP}", SP, "gpon", "pon", f"no onu-type {NT}"]
TCCMDS = [f"profile tcont {k} {v}" for k, v in TCS.items()] + [f"no profile tcont {k}" for k in TCS]
ALLOWED = set([f"onu {IDX} type {NT} sn {SN}"] + FIXED + BASE + MNG_BASE + MNG_B + PON_B + ONU_TYPE + TCCMDS)


def log(s):
    LOG.write(s + "\n"); LOG.flush(); print(s, flush=True)


tn = telnetlib.Telnet(os.environ["TKC_SNMP_HOST"], int(os.environ["TKC_TELNET_PORT"]), 20)
tn.read_until(b"sername:", 20); tn.write(os.environ["TKC_TELNET_USER"].encode() + b"\n")
tn.read_until(b"assword:", 20); tn.write(os.environ["TKC_TELNET_PASSWORD"].encode() + b"\n")
time.sleep(3); tn.read_very_eager()
PROMPT = re.compile(r"(ZXAN[\w()\-/:.]*#)\s*$")
in_config = False


def _read(wait):
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
    if cmd.endswith("?"):
        if cmd not in MNG_HELP:
            raise SystemExit(f"AYUDA NO PERMITIDA: {cmd}")
        tn.write(cmd.encode()); buf = _read(6); tn.write(b"\x15"); time.sleep(0.3); tn.write(b"\n"); _read(2)
    else:
        if cmd not in ALLOWED and not cmd.startswith("show "):
            raise SystemExit(f"COMANDO NO PERMITIDO: {cmd}")
        tn.write(cmd.encode() + b"\n"); buf = _read(wait)
        global in_config
        if cmd == "conf t":
            in_config = "(config)#" in prompt_of(buf)
        elif cmd == "end":
            in_config = False
    log(f">>> {cmd}\n{buf.strip()}\n")
    return buf


def prompt_of(o):
    m = re.findall(r"(ZXAN[\w()\-/:.]*#)", o)
    return m[-1] if m else "?"


def mode(cmds, enter, want, res):
    if not in_config:
        run("conf t")
    o = run(enter)
    if want not in prompt_of(o):
        raise RuntimeError(f"no entró a {enter}: {prompt_of(o)}")
    for c in cmds:
        o = run(c)
        res[c] = "ERR" if "%Error" in o or "%Warn" in o else "OK"
        if "[yes/no]" in o and c.startswith("type "):
            o = run("yes", wait=20)                       # confirma el cambio de tipo (reinicia solo la ONU de prueba)
            res[c + " -> yes"] = "ERR" if "%Error" in o else "OK"
        if want not in prompt_of(o) and not c.endswith("?"):
            log(f"(prompt cambió tras '{c}': {prompt_of(o)})")
            run("end"); run("conf t"); run(enter)


def present():
    return bool(re.search(rf"^\s+onu {IDX} type", run(f"show running-config-interface gpon_olt-{PON}"), re.M))


def rollback():
    ok = True
    for _ in range(4):
        try:
            if "(config)#" not in prompt_of(run("conf t")):
                run("end"); time.sleep(2); continue
            run(f"interface gpon_olt-{PON}"); run(f"no onu {IDX}"); run("end"); time.sleep(2)
            run("conf t"); run("pon"); run(f"no onu-type {NT}"); run("end")
            run("conf t"); run("gpon")
            for k in TCS: run(f"no profile tcont {k}")
            run("end")
            left = run("show gpon profile tcont") + run("show onu-type gpon")
            if not present() and NT not in left and not any(k in left for k in TCS):
                log("ROLLBACK OK"); return True
        except Exception as e:
            log(f"rollback: {e}"); time.sleep(2)
    return False


res = {}
try:
    run("terminal length 0")
    assert SN in run("show pon onu uncfg"), "ONU ya no está en espera"
    assert not present(), "índice en uso"
    assert NT not in run("show onu-type gpon"), "el tipo de prueba ya existe"
    mode(PON_B, "pon", "(config-pon)#", res); run("end")          # 1) crear antes el tipo con wifi_0/1
    res["tipo_creado"] = NT in run("show onu-type gpon")
    run("conf t"); run(f"interface gpon_olt-{PON}"); o = run(f"onu {IDX} type {NT} sn {SN}"); res["alta con tipo wifi"] = "ERR" if "%Error" in o else "OK"; run("exit")
    mode(BASE, f"interface {ONU}", "(config-if-gpon_onu", res); run("exit")
    mode(MNG_BASE, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res); run("exit")
    mode([SP], f"interface {VP}", "(config-if-vport", res); run("exit")
    log("=== BATERÍA 2 ===")
    mode(MNG_HELP, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res)   # ayuda dentro del modo
    run("exit")
    run("show onu-type gpon")
    mode(MNG_B, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res); run("exit")
    run("end") if in_config else None
    left = run("show gpon profile tcont")
    res["tcont_tipos_creados"] = [k for k in TCS if k in left]
    run(f"show running-config-interface {ONU}")
finally:
    res["rollback_ok"] = rollback()
    res["back_in_uncfg"] = SN in run("show pon onu uncfg")
    log("RESULTADO: " + json.dumps(res, ensure_ascii=False))
    tn.write(b"exit\n"); tn.close()
