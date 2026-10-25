"""Batería FINAL (C620) sobre UNA ONU de prueba no activa, con rollback y `write` condicionado.
Uso: python scripts/c620_final_battery_test.py <SN en espera> [--no-write] [--reboot-online 1/1/5:N]"""
import os, re, sys, time, json, warnings
warnings.filterwarnings("ignore")
import telnetlib
from dotenv import load_dotenv

ROOT = "/home/david/Escritorio/Proyectos/telecom-knowledge-extractor"
load_dotenv(f"{ROOT}/.env")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
SN = args[0] if args else "DF306B41EDB0"
DO_WRITE = "--no-write" not in sys.argv
REBOOT_ONLINE = sys.argv[sys.argv.index("--reboot-online") + 1] if "--reboot-online" in sys.argv else None
PON, IDX = "1/1/5", 3
ONU, VP = f"gpon_onu-{PON}:{IDX}", f"vport-{PON}.{IDX}:1"
NT, TP, TC, BL = "TKCTEST-TYPE", "TKCTEST-DEL", "TKCTEST-T", "TKCBL0000001"
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_final_battery.txt", "w")

PON_B = [f"onu-type {NT} gpon description TKCTEST max-tcont 8 max-gemport 32 max-veip 1", f"onu-type-if {NT} eth_0/1",
         f"onu-type-if {NT} pots_0/1", f"onu-type-if {NT} video_0/1", f"onu-type-if {NT} wifi_0/1"]
BASE = ["name TKCTEST", "vport-mode manual", "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON", "gemport 1 name internet tcont 1",
        "vport 1 map-type vlan", "vport-map 1 1 vlan 101"]
MNG_BASE = ["service vlan101 gemport 1 vlan 101", "veip 1"]
SP = "service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN"
T_GPON = [f"profile tcont {TC} type 5 fixed 64 assured 64 maximum 2048"]
T_QOS = f"traffic-profile {TP} cir 1024 cbs 128 pir 1024 pbs 128"
T_OLT = ["description TKCTEST-PORT", f"blacklist sn {BL}"]
T_ONU = ["tcont 2 profile SMARTOLT-50M-UP", "tcont 2 name TKCNAME", "tcont 2 gap default", "gemport 2 name tkctest tcont 2 queue 1",
         "gemport 2 portid 300", "vport 2 map-type vlan", "vport-map 2 1 vlan 102", "no vport-map 2", "no vport 2", "no gemport 2",
         "no tcont 2", "splitter TKCSPL", "no splitter", "sn-bind enable sn", "fec enable", "fec default", "authpass-control 5",
         "auto-replace disable", "admin disable", "admin enable", "name TKCTEST2", "reset", "deregister"]
T_MNG = ["security-mgmt 1 state enable mode forward ingress-type lan protocol web", "security-mgmt 1 state disable",
         "dhcp-ip ethuni eth_0/1 from-onu", "dhcp-ip ethuni eth_0/1 forbidden", "dhcp-ip ethuni eth_0/1 no-ctrl",
         "interface eth eth_0/1 state lock", "interface eth eth_0/1 state unlock", "interface eth eth_0/1 speed auto",
         "interface eth eth_0/1 mtu 1500", "interface eth eth_0/1 pppoe-filter enable", "interface eth eth_0/1 loop enable",
         "interface eth eth_0/1 power-control enable", "interface eth eth_0/1 arc enable", "interface eth eth_0/1 l2l3 l3",
         "interface eth eth_0/1 pause-time 10", "interface video video_0/1 state lock", "interface video video_0/1 state unlock",
         "interface video video_0/1 arc enable", "interface video-ani state lock", "interface video-ani state unlock",
         "interface wifi wifi_0/1 state unlock", "interface wifi wifi_0/1 arc enable", "ssid ctrl wifi_0/1 name TKCTEST",
         "ssid ctrl wifi_0/1 hide enable", "ssid ctrl wifi_0/1 hide disable", "ssid ctrl wifi_0/1 max-users 8",
         "ssid ctrl wifi_0/1 user-isolation enable", "wifi enable channel 6", "wifi enable tx-power-percent 80",
         "wifi enable work-mode 802.11b-11g-11n", "wifi enable domain bra", "wifi 5g disable",
         "vlan port eth_0/1 mode tag vlan 101", "wan-ip 1 ipv4 mode dhcp vlan-profile SMARTOLT_VLAN_101",
         "wan-ip 1 ipv4 ping-response enable traceroute-response enable", "veip 1 state lock", "veip 1 state unlock",
         "gemport traffic-limit 1 upstream SMARTOLT-50M-UP", "gemport traffic-limit 1 downstream SMARTOLT-50M-DOWN",
         "switchport ethuni eth_0/1 traffic-limit in SMARTOLT-50M-DOWN", "switchport ethuni eth_0/1 traffic-limit out SMARTOLT-50M-UP",
         "no service vlan101"]
T_VP = ["no service-port 1", SP]

ALLOWED = set(["conf t", "end", "exit", "terminal length 0", "yes", "write", "reboot", "gpon", "pon", f"interface gpon_olt-{PON}",
               f"onu {IDX} type {NT} sn {SN}", f"no onu {IDX}", f"interface {ONU}", f"pon-onu-mng {ONU}", f"interface {VP}",
               f"no onu-type {NT}", f"no profile tcont {TC}", f"no traffic-profile {TP}", "no description", f"no blacklist sn {BL}", T_QOS]
              + PON_B + BASE + MNG_BASE + [SP] + T_GPON + T_OLT + T_ONU + T_MNG + T_VP)
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
            res[c + " -> yes"] = "ERR" if "%Error" in o else "OK"
        res[c] = "ERR" if "%Error" in o or "%Warn" in o else "OK"
        if want not in prompt_of(o):
            log(f"(prompt cambió tras '{c}': {prompt_of(o)}; se reingresa)")
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
            run(f"interface gpon_olt-{PON}"); run(f"no onu {IDX}"); run("no description"); run(f"no blacklist sn {BL}"); run("end"); time.sleep(2)
            run("conf t"); run("pon"); run(f"no onu-type {NT}"); run("end")
            run("conf t"); run("gpon"); run(f"no profile tcont {TC}"); run("end")
            run("conf t"); run(f"no traffic-profile {TP}"); run("end")
            left = run("show gpon profile tcont") + run("show onu-type gpon") + run("show qos traffic-profile")
            if not present() and NT not in left and TC not in left and TP not in left:
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
        raise SystemExit(f"El índice {IDX} YA ESTÁ EN USO: no se hace nada (no se borra nada).")
    pre = run("show onu-type gpon") + run("show qos traffic-profile") + run("show gpon profile tcont")
    if NT in pre or TP in pre or TC in pre:
        raise SystemExit("Quedan restos de pruebas previas: no se hace nada.")
    started = True                                    # a partir de aquí el rollback es seguro
    mode(PON_B, "pon", "(config-pon)#", res); run("end")
    mode(T_GPON, "gpon", "(config-gpon)#", res); run("end")
    run("conf t"); o = run(T_QOS); res[T_QOS] = "ERR" if "%Error" in o else "OK"; run("end")
    run("conf t"); run(f"interface gpon_olt-{PON}"); o = run(f"onu {IDX} type {NT} sn {SN}"); res["alta"] = "ERR" if "%Error" in o else "OK"
    mode(T_OLT, f"interface gpon_olt-{PON}", "(config-if-gpon_olt", res); run("exit")
    mode(BASE, f"interface {ONU}", "(config-if-gpon_onu", res); run("exit")
    mode(MNG_BASE, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res); run("exit")
    mode([SP], f"interface {VP}", "(config-if-vport", res); run("exit")
    log("=== BATERÍA FINAL ===")
    mode(T_VP, f"interface {VP}", "(config-if-vport", res); run("exit")
    mode(T_MNG, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res); run("exit")
    run(f"show running-config-interface {ONU}")
    run(f"show running-config-interface {VP}")
    mode(T_ONU, f"interface {ONU}", "(config-if-gpon_onu", res); run("end")
finally:
    if started:
        res["rollback_ok"] = rollback()
        res["config_puerto_identica"] = (before == olt_cfg())
        res["back_in_uncfg"] = SN in run("show pon onu uncfg")
        if DO_WRITE and res["rollback_ok"] and res["config_puerto_identica"]:
            o = run("write", wait=60)
            res["write"] = "ERR" if "%Error" in o else "OK"
        elif DO_WRITE:
            res["write"] = "OMITIDO (rollback o configuración no verificados)"
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
