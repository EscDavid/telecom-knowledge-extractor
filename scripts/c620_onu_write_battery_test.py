"""Batería de escrituras sobre UNA ONU de prueba NO activa (C620): ejecuta los comandos de trabajo que solo
conocíamos por `?`, relee la configuración y hace rollback completo (`no onu N` + borrado del perfil T-CONT de prueba).
Los errores `%Error` de la batería se registran pero no abortan. Uso: script.py <SN en espera>"""
import os, re, sys, time, json, warnings
warnings.filterwarnings("ignore")
import telnetlib
from dotenv import load_dotenv

ROOT = "/home/david/Escritorio/Proyectos/telecom-knowledge-extractor"
load_dotenv(f"{ROOT}/.env")
PON, IDX, TYPE = "1/1/5", 3, "LATIC"
SN = sys.argv[1] if len(sys.argv) > 1 else "DF306B41EDB0"
ONU, TP = f"gpon_onu-{PON}:{IDX}", "TKCTEST-T"
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_write_battery.txt", "w")

BASE = ["name TKCTEST", "description TKCTEST", "vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON",
        "gemport 1 name internet tcont 1", "vport 1 map-type vlan", "vport-map 1 1 vlan 101"]
ONU_B = ["tcont 2 profile SMARTOLT-50M-UP", "gemport 2 name tkctest tcont 2", "no gemport 2", "no tcont 2",
         "admin disable", "admin enable", "name TKCTEST2"]
MNG_B = ["service vlan101 gemport 1 vlan 101", "veip 1", "veip 1 state unlock",
         "interface eth eth_0/1 state unlock", "interface eth eth_0/1 speed auto", "interface eth eth_0/1 mtu 1500",
         "security-mgmt 1 state enable mode forward ingress-type lan protocol web", "dhcp-ip ethuni eth_0/1 from-onu",
         "interface video video_0/1 state lock", "interface wifi wifi_0/1 state unlock", "ssid ctrl wifi_0/1 name TKCTEST",
         "vlan port eth_0/1 vlan 101"]
SP = "service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN"
GPON_B = [f"profile tcont {TP} type 5 fixed 64 assured 64 maximum 2048"]
FIXED = ["conf t", "end", "exit", "terminal length 0", f"interface gpon_olt-{PON}", f"onu {IDX} type {TYPE} sn {SN}",
         f"no onu {IDX}", f"interface {ONU}", f"pon-onu-mng {ONU}", f"interface vport-{PON}.{IDX}:1", SP, "gpon",
         f"no profile tcont {TP}", "no gemport 2", "no tcont 2", "reboot", "no", "yes"]
ALLOWED = set(FIXED + BASE + ONU_B + MNG_B + GPON_B)


def log(s):
    LOG.write(s + "\n"); LOG.flush(); print(s, flush=True)


tn = telnetlib.Telnet(os.environ["TKC_SNMP_HOST"], int(os.environ["TKC_TELNET_PORT"]), 20)
tn.read_until(b"sername:", 20); tn.write(os.environ["TKC_TELNET_USER"].encode() + b"\n")
tn.read_until(b"assword:", 20); tn.write(os.environ["TKC_TELNET_PASSWORD"].encode() + b"\n")
time.sleep(3); tn.read_very_eager()
PROMPT = re.compile(r"(ZXAN[\w()\-/:.]*#)\s*$")


def run(cmd, wait=15):
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
    log(f">>> {cmd}\n{buf.strip()}\n")
    return buf


def prompt_of(o):
    m = re.findall(r"(ZXAN[\w()\-/:.]*#)", o)
    return m[-1] if m else "?"


def mode(cmds, enter, want, results):
    o = run(enter)
    if want not in prompt_of(o):
        raise RuntimeError(f"no entró a {enter}: {prompt_of(o)}")
    for c in cmds:
        o = run(c)
        results[c] = "ERR" if "%Error" in o or "%Warn" in o else "OK"
        if want not in prompt_of(o):
            log(f"(prompt cambió tras '{c}': {prompt_of(o)}; se vuelve a entrar)")
            o = run("end"); o = run("conf t"); run(enter)


def present():
    return bool(re.search(rf"^\s+onu {IDX} type", run(f"show running-config-interface gpon_olt-{PON}"), re.M))


def rollback():
    for _ in range(4):
        try:
            o = run("conf t")
            if "(config)#" not in prompt_of(o):
                run("end"); time.sleep(2); continue
            run(f"interface gpon_olt-{PON}"); run(f"no onu {IDX}"); run("end"); time.sleep(2)
            run("conf t"); run("gpon"); run(f"no profile tcont {TP}"); run("end")
            if not present() and TP not in run("show gpon profile tcont"):
                log("ROLLBACK OK"); return True
        except Exception as e:
            log(f"rollback: {e}"); time.sleep(2)
    return False


res = {}
try:
    run("terminal length 0")
    assert SN in run("show pon onu uncfg"), "ONU ya no está en espera"
    assert not present(), "índice en uso"
    o = run("conf t"); run(f"interface gpon_olt-{PON}"); run(f"onu {IDX} type {TYPE} sn {SN}"); run("exit")
    mode(BASE, f"interface {ONU}", "(config-if-gpon_onu", res)
    run("exit")
    mode(["service vlan101 gemport 1 vlan 101", "veip 1"], f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res)
    run("exit"); mode([SP], f"interface vport-{PON}.{IDX}:1", "(config-if-vport", res); run("exit")
    log("=== BATERÍA ===")
    mode(ONU_B, f"interface {ONU}", "(config-if-gpon_onu", res); run("exit")
    mode(MNG_B[2:], f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res); run("exit")
    mode(GPON_B, "gpon", "(config-gpon)#", res); run("end")
    res["tcont_profile_creado"] = TP in run("show gpon profile tcont")
    run(f"show running-config-interface {ONU}")
    run(f"show running-config-interface vport-{PON}.{IDX}:1")
finally:
    res["rollback_ok"] = rollback()
    res["back_in_uncfg"] = SN in run("show pon onu uncfg")
    log("RESULTADO: " + json.dumps(res, ensure_ascii=False))
    tn.write(b"exit\n"); tn.close()
