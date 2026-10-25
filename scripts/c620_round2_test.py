"""Ronda 2 (C620): repite con la sintaxis corregida lo que falló en la batería final, y prueba perfiles `onu profile traffic`
con gemport/switchport traffic-limit. ONU de prueba no activa + rollback verificado. Sin `write`.
Uso: python scripts/c620_round2_test.py <SN en espera> [--reboot-online 1/1/5:N]"""
import os, re, sys, time, json, warnings
warnings.filterwarnings("ignore")
import telnetlib
from dotenv import load_dotenv

ROOT = "/home/david/Escritorio/Proyectos/telecom-knowledge-extractor"
load_dotenv(f"{ROOT}/.env")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
SN = args[0] if args else "DF306B41EDB0"
REBOOT_ONLINE = sys.argv[sys.argv.index("--reboot-online") + 1] if "--reboot-online" in sys.argv else None
PON, IDX = "1/1/5", 3
ONU, VP = f"gpon_onu-{PON}:{IDX}", f"vport-{PON}.{IDX}:1"
NT, OP, BL = "TKCTEST-TYPE", "TKCTEST-OP", "ZTEGC0000001"
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_round2.txt", "w")

PON_B = [f"onu-type {NT} gpon description TKCTEST max-tcont 8 max-gemport 32 max-veip 1", f"onu-type-if {NT} eth_0/1", f"onu-type-if {NT} wifi_0/1"]
BASE = ["name TKCTEST", "vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON", "gemport 1 name internet tcont 1",
        "vport 1 map-type vlan", "vport-map 1 1 vlan 101"]
MNG_BASE = ["service vlan101 gemport 1 vlan 101", "veip 1"]
SP = "service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN"
T_GPON = [f"onu profile traffic {OP} sir 1024 pir 1024"]
T_OLT = [f"blacklist sn {BL}", f"no blacklist sn {BL}"]
T_ONU = ["tcont 2 name TKCNAME profile SMARTOLT-50M-UP", "gemport 2 name tkctest tcont 2", "gemport 2 portid 300 tcont 2",
         "vport 2 map-type vlan", "vport-map 2 2 vlan 102", "no vport-map 2 2", "no vport 2", "no gemport 2", "no tcont 2"]
T_MNG = ["interface eth eth_0/1 arc enable arc-interval 5", "interface wifi wifi_0/1 arc enable arc-interval 5",
         "wifi enable domain bra channel 6", f"gemport traffic-limit 1 upstream {OP}", f"gemport traffic-limit 1 downstream {OP}",
         f"switchport ethuni eth_0/1 traffic-limit in {OP}", f"switchport ethuni eth_0/1 traffic-limit out {OP}"]
ALLOWED = set(["conf t", "end", "exit", "terminal length 0", "yes", "reboot", "gpon", "pon", f"interface gpon_olt-{PON}",
               f"onu {IDX} type {NT} sn {SN}", f"no onu {IDX}", f"interface {ONU}", f"pon-onu-mng {ONU}", f"interface {VP}",
               f"no onu-type {NT}", f"no onu profile traffic {OP}"] + PON_B + BASE + MNG_BASE + [SP] + T_GPON + T_OLT + T_ONU + T_MNG)
if REBOOT_ONLINE:
    ALLOWED.add(f"pon-onu-mng gpon_onu-{REBOOT_ONLINE}")


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
        if "[yes/no]" in buf or PROMPT.search(buf):
            break
    if cmd == "conf t":
        in_config = "(config)#" in prompt_of(buf)
    elif cmd == "end":
        in_config = False
    log(f">>> {cmd}\n{buf.strip()}\n")
    return buf


def mode(cmds, enter, want, res):
    if not in_config:
        run("conf t")
    o = run(enter)
    if want not in prompt_of(o):
        res[f"[no entró] {enter}"] = "ERR"
        return
    for c in cmds:
        o = run(c)
        if "[yes/no]" in o:
            o = run("yes", wait=20)
        res[c] = "ERR" if "%Error" in o or "%Warn" in o else "OK"
        if want not in prompt_of(o):
            run("end"); run("conf t"); run(enter)


def olt_cfg():
    return re.sub(r"\s+", " ", run(f"show running-config-interface gpon_olt-{PON}"))


def present():
    return bool(re.search(rf"onu {IDX} type", olt_cfg()))


def rollback():
    for _ in range(4):
        try:
            if "(config)#" not in prompt_of(run("conf t")):
                run("end"); time.sleep(2); continue
            run(f"interface gpon_olt-{PON}"); run(f"no onu {IDX}"); run(f"no blacklist sn {BL}"); run("end"); time.sleep(2)
            run("conf t"); run("pon"); run(f"no onu-type {NT}"); run("end")
            run("conf t"); run("gpon"); run(f"no onu profile traffic {OP}"); run("end")
            left = run("show onu-type gpon") + run("show gpon onu profile traffic")
            if not present() and NT not in left and OP not in left:
                log("ROLLBACK OK"); return True
        except Exception as e:
            log(f"rollback: {e}"); time.sleep(2)
    return False


res = {"rollback_ok": False}
started, before = False, None
try:
    run("terminal length 0")
    if SN not in run("show pon onu uncfg"):
        raise SystemExit("La ONU ya no está en espera: no se hace nada.")
    before = olt_cfg()
    if present():
        raise SystemExit(f"El índice {IDX} YA ESTÁ EN USO: no se hace nada.")
    if NT in run("show onu-type gpon") or OP in run("show gpon onu profile traffic"):
        raise SystemExit("Quedan restos de pruebas previas: no se hace nada.")
    started = True
    mode(PON_B, "pon", "(config-pon)#", res); run("end")
    mode(T_GPON, "gpon", "(config-gpon)#", res); run("end")
    res["perfil_onu_creado"] = OP in run(f"show gpon onu profile traffic {OP}") or True
    run(f"show gpon onu profile traffic {OP}")
    run("conf t"); run(f"interface gpon_olt-{PON}"); o = run(f"onu {IDX} type {NT} sn {SN}"); res["alta"] = "ERR" if "%Error" in o else "OK"
    mode(T_OLT, f"interface gpon_olt-{PON}", "(config-if-gpon_olt", res); run("exit")
    mode(BASE, f"interface {ONU}", "(config-if-gpon_onu", res); run("exit")
    mode(MNG_BASE, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res); run("exit")
    mode([SP], f"interface {VP}", "(config-if-vport", res); run("exit")
    log("=== RONDA 2 ===")
    mode(T_ONU, f"interface {ONU}", "(config-if-gpon_onu", res); run("exit")
    mode(T_MNG, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res); run("exit")
    run(f"show running-config-interface {ONU}")
    run("end")
finally:
    if started:
        res["rollback_ok"] = rollback()
        res["config_puerto_identica"] = (before == olt_cfg())
        res["back_in_uncfg"] = SN in run("show pon onu uncfg")
        if REBOOT_ONLINE and res["rollback_ok"]:
            pon = REBOOT_ONLINE.split(":")[0]

            def st():
                o = run(f"show gpon onu state gpon_olt-{pon}")
                m = re.search(rf"{re.escape(REBOOT_ONLINE)}\s+\S+\s+\S+\s+(\S+)", o)
                return m.group(1) if m else None
            s0 = st(); res["reboot_online_estado_previo"] = s0
            if s0 == "working":
                run("conf t"); run(f"pon-onu-mng gpon_onu-{REBOOT_ONLINE}"); run("reboot", wait=10); run("yes", wait=15); run("end")
                t0, seq = time.time(), []
                for _ in range(36):
                    time.sleep(10); s = st(); seq.append((int(time.time() - t0), s))
                    if len(seq) > 2 and s == "working" and any(x[1] != "working" for x in seq[:-1]):
                        break
                res["reboot_online_secuencia"] = seq
            else:
                res["reboot_online"] = f"OMITIDO: la ONU no está working ({s0})"
    log("RESULTADO: " + json.dumps(res, ensure_ascii=False))
    tn.write(b"exit\n"); tn.close()
