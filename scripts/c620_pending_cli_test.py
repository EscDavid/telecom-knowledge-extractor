"""Pendientes de la CLI de la C620 (producción): 5 temas por secciones, sobre UNA ONU de prueba NO activa en el
índice libre 3 del puerto 1/1/5, con rollback verificado. NO ejecuta `write`.

Uso:
    .venv/bin/python scripts/c620_pending_cli_test.py <SN en espera> [--sections 1,2,3,4,5] [--resource-mode2]

Secciones (cada comando se registra como OK o ERR <código>; la ayuda `?` se envía SIN Enter y se borra con Ctrl-U):
  1  gemport <n> portid <129-4095> tcont <m> (222370 "Not support this operation"). La ayuda real dice
     "portid: Only supported when resource assign mode is mode2" (`resource mode1|mode2` en `interface gpon_olt-`).
     Se prueban variantes (con/sin name, con queue, con vport-mode manual y gemport, antes de vport-map).
     Con --resource-mode2 se repiten bajo `resource mode2` (ver RIESGOS).
  2  Borrado de un mapeo: `no vport-map <vport> <gem> [vlan <v>|cos <c>]` (la ayuda admite `vlan`/`cos`/<cr> tras el 2º
     parámetro; el simple dio 222386). Se comprueba en la configuración guardada si el mapeo desapareció.
  3  `wifi enable domain ...` (230263). La ayuda dice: dominio `bra` "assigned just when work mode is 802.11b"
     -> se prueba `work-mode 802.11b` antes/junto a `domain`, otros países y `wifi enable` sin parámetros.
  4  `onu-type-if <tipo> video_0/1` (230263). Los tipos reales de la OLT (ZTE-F625/F640/F628, LATIC) declaran el
     puerto de CATV como `rf_0/1` (`show onu-type-if <tipo>`), no `video_0/1`. Se prueba rf_0/1, video_0/1,
     video-ani_0/1, catv_0/1, tipo mínimo, y luego `interface video ...` en pon-onu-mng.
  5  `splitter <WORD>` (230263). La ayuda dice que es la "Location of the ONU: 1stLvl-2ndLvl-..." (texto libre,
     máx. 32). No existe tabla de splitters (`show splitter`/`show gpon splitter` no existen). Hipótesis: exige
     `onu-type <t> gpon location enable` en el tipo (hoy todos los tipos tienen `Location: disable`).

Salida: docs/walks/diagnostics/ZTE_C620_cli_reads_pending.txt  (última línea: RESULTADO: {json}).

RIESGOS / garantías:
  - Solo se envían comandos de la lista cerrada ALLOWED (+ `show ...` y líneas que terminan en `?`).
  - Todo ocurre sobre la ONU de prueba 1/1/5:3 (nunca en uso; si el índice 3 está ocupado el script no hace nada) y
    tipos TKCTEST-*. Rollback: `no onu 3` y `no onu-type` de los tipos de prueba; se verifica que la configuración del
    puerto quede IDÉNTICA a la inicial y que los tipos ya no existan. La bandera `started` evita el rollback si las
    comprobaciones previas fallan.
  - --resource-mode2 (OPCIONAL, desactivado por defecto): cambia `resource mode1|mode2` en `interface gpon_olt-1/1/5`,
    que es un ajuste de PUERTO (afecta el modo de asignación de Port-ID/Alloc-ID de TODAS las ONU del puerto, con
    clientes reales). La OLT no muestra el modo actual en la configuración, así que se asume mode1 (valor por defecto,
    "OLT assign automatically") y se restaura con `resource mode1` en el rollback. Puede rechazarse si hay ONU
    configuradas o provocar re-registro; úsese solo en ventana de mantenimiento. Sin esta bandera NO se toca.
  - No se toca ninguna ONU real. No se imprimen credenciales (se leen de .env).
"""
import os, re, sys, time, json, warnings
warnings.filterwarnings("ignore")
import telnetlib
from dotenv import load_dotenv

ROOT = "/home/david/Escritorio/Proyectos/telecom-knowledge-extractor"
load_dotenv(f"{ROOT}/.env")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
SN = args[0] if args else "DF306B41EDB0"
SECTIONS = set(sys.argv[sys.argv.index("--sections") + 1].split(",")) if "--sections" in sys.argv else {"1", "2", "3", "4", "5"}
if "--sections" in sys.argv:
    args = [a for a in args if a != sys.argv[sys.argv.index("--sections") + 1]]
    SN = args[0] if args else SN
RES2 = "--resource-mode2" in sys.argv
PON, IDX = "1/1/5", 3
ONU = f"gpon_onu-{PON}:{IDX}"
NT, NT2 = "TKCTEST-TYPE", "TKCTEST-MIN"
TYPES = [NT, NT2]
LOG = open(f"{ROOT}/docs/walks/diagnostics/ZTE_C620_cli_reads_pending.txt", "w")

TCONT1 = "tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON"
# --- tipos de ONU (sección 4 crea además variantes de interfaz de video) ---
PON_B = [f"onu-type {NT} gpon description TKCTEST max-tcont 8 max-gemport 32 max-veip 1",
         f"onu-type-if {NT} eth_0/1", f"onu-type-if {NT} wifi_0/1"]
PON_V = [f"onu-type-if {NT} rf_0/1", f"onu-type-if {NT} video_0/1", f"onu-type-if {NT} video-ani_0/1",
         f"onu-type-if {NT} catv_0/1", f"onu-type {NT2} gpon", f"onu-type-if {NT2} video_0/1", f"onu-type-if {NT2} rf_0/1"]
LOC_ON = f"onu-type {NT} gpon location enable"
SHOW_TYPE_IF = [f"show onu-type-if {NT}", f"show onu-type-if {NT2}"]

# --- sección 1: gemport portid ---
GEM_VARIANTS = ["gemport 1 portid 300 tcont 1", "gemport 1 name internet portid 300 tcont 1",
                "gemport 1 portid 300 tcont 1 queue 1", "gemport 1 name internet portid 300 tcont 1 queue 1",
                "gemport 1 name internet tcont 1 queue 1"]       # la última es la forma sin portid (control)
S1_HELP = ["gemport 1 ?", "gemport 1 name internet ?", "gemport 1 portid ?", "gemport 1 portid 300 ?",
           "gemport 1 portid 300 tcont 1 ?", "gemport 1 tcont 1 queue ?", "vport-mode ?"]
S1_PRE = ["vport-mode manual", TCONT1]

# --- base de la ONU (como en las rondas anteriores) ---
BASE = ["name TKCTEST", "vport-mode manual", TCONT1, "gemport 1 name internet tcont 1",
        "vport 1 map-type vlan", "vport-map 1 1 vlan 101"]
MNG_BASE = ["service vlan101 gemport 1 vlan 101", "veip 1"]

# --- sección 2: borrado de mapeo ---
S2_SETUP = ["tcont 2 name TKCNAME profile SMARTOLT-50M-UP", "gemport 2 name tkctest tcont 2", "vport 2 map-type vlan"]
S2_MAP = "vport-map 2 2 vlan 102"
S2_HELP = ["no vport-map ?", "no vport-map 2 ?", "no vport-map 2 2 ?", "no vport-map 2 2 vlan ?", "no vport-map 2 2 cos ?",
           "vport-map 2 2 ?"]
S2_DEL = ["no vport-map 2 2", "no vport-map 2 2 vlan 102", "no vport-map 2 2 cos 0", "no vport-map 2 1", "no vport-map 2 102"]
S2_END = ["no vport 2", "no gemport 2", "no tcont 2"]

# --- sección 3: wifi ---
S3_HELP = ["wifi enable ?", "wifi enable work-mode 802.11b ?", "wifi enable work-mode 802.11b domain ?",
           "wifi enable work-mode 802.11b domain bra ?", "wifi enable work-mode 802.11b domain bra channel 6 ?"]
S3_CMDS = ["wifi enable", "wifi enable domain bra channel 6",                        # control: se espera 230263
           "wifi enable work-mode 802.11b domain bra", "wifi enable work-mode 802.11b domain bra channel 6",
           "wifi enable work-mode 802.11b domain bra channel 6 tx-power-percent 80",
           "wifi enable channel 6 work-mode 802.11b domain bra",
           "wifi enable work-mode 802.11b-11g-11n domain usa channel 6", "wifi enable work-mode 802.11b-11g-11n domain esp",
           "wifi enable work-mode 802.11b-11g-11n domain chn channel 6", "wifi enable work-mode 802.11b-11g-11n domain ger channel 6",
           "wifi enable work-mode 802.11b-11g-11n domain fra", "wifi enable work-mode 802.11b-11g-11n domain uk",
           "wifi enable domain esp", "wifi enable domain usa channel 6", "wifi enable domain chn channel 6",
           "wifi 5g enable domain chn channel 36", "wifi 5g enable domain usa channel 36"]

# --- sección 4: video en pon-onu-mng ---
S4_HELP = ["interface video ?", "interface video video_0/1 ?", "interface video-ani ?"]
S4_CMDS = ["interface video video_0/1 state lock", "interface video video_0/1 state unlock", "interface video rf_0/1 state lock",
           "interface video rf_0/1 state unlock", "interface video-ani state lock", "interface video-ani state unlock"]

# --- sección 5: splitter ---
S5_HELP = ["splitter ?", "splitter TKCSPL ?"]
S5_CMDS = ["splitter TKCSPL", "splitter L1-L2-L3", "splitter 1-2-3", "no splitter"]

ALLOWED = set(["conf t", "end", "exit", "terminal length 0", "yes", "gpon", "pon", f"interface gpon_olt-{PON}",
               f"onu {IDX} type {NT} sn {SN}", f"no onu {IDX}", f"interface {ONU}", f"pon-onu-mng {ONU}",
               "resource mode2", "resource mode1", "no gemport 1", "vport-mode gemport", LOC_ON]
              + [f"no onu-type {t}" for t in TYPES]
              + PON_B + PON_V + BASE + MNG_BASE + S1_PRE + GEM_VARIANTS + S2_SETUP + [S2_MAP] + S2_DEL + S2_END
              + S3_CMDS + S4_CMDS + S5_CMDS)


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


def help_(line, wait=6):
    """Ayuda `?`: se envía SIN Enter y se borra con Ctrl-U. Nunca ejecuta nada."""
    if not line.endswith("?") or "\n" in line:
        raise SystemExit(f"AYUDA NO VÁLIDA: {line}")
    tn.write(line.encode())
    buf, t0, quiet = "", time.time(), 0
    while time.time() - t0 < wait:
        time.sleep(0.5)
        d = tn.read_very_eager().decode(errors="replace").replace("\r", "")
        buf += d
        if "--More--" in d:
            tn.write(b" "); continue
        quiet = 0 if d else quiet + 1
        if quiet >= 3 and buf:
            break
    tn.write(b"\x15"); time.sleep(0.3); tn.write(b"\n"); time.sleep(1.0)
    tn.read_very_eager()
    log(f"??? {line}\n{buf.strip()}\n")
    return buf


def run(cmd, wait=15):
    global in_config
    if cmd.endswith("?"):
        return help_(cmd)
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


def verdict(o):
    m = re.search(r"%(?:Error|Warn)\w*\s+(\d+)", o)
    if m:
        return f"ERR {m.group(1)}"
    return "ERR" if "%Error" in o or "%Warn" in o else "OK"


def mode(cmds, enter, want, res, tag):
    """Ejecuta cmds dentro de `enter`; las líneas con `?` son ayuda; sigue el modo de config."""
    if not in_config:
        run("conf t")
    o = run(enter)
    if want not in prompt_of(o):
        res[f"[no entró] {enter}"] = "ERR"
        return
    for c in cmds:
        o = run(c)
        if c.endswith("?"):
            continue
        if "[yes/no]" in o:
            o = run("yes", wait=20)
        res[f"{tag}: {c}"] = verdict(o)
        if want not in prompt_of(o):
            run("end"); run("conf t"); run(enter)


def olt_cfg():
    return re.sub(r"\s+", " ", run(f"show running-config-interface gpon_olt-{PON}"))


def present():
    return bool(re.search(rf"onu {IDX} type", olt_cfg()))


def onu_cfg():
    return re.sub(r"\s+", " ", run(f"show running-config-interface {ONU}"))


res_changed = False


def rollback():
    for _ in range(4):
        try:
            if "(config)#" not in prompt_of(run("conf t")):
                run("end"); time.sleep(2); continue
            run(f"interface gpon_olt-{PON}"); run(f"no onu {IDX}")
            if res_changed:
                run("resource mode1")
            run("end"); time.sleep(2)
            run("conf t"); run("pon")
            for t in TYPES:
                run(f"no onu-type {t}")
            run("end")
            left = run("show onu-type gpon")
            if not present() and not any(t in left for t in TYPES):
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
    tl = run("show onu-type gpon")
    if any(t in tl for t in TYPES):
        raise SystemExit("Quedan restos de pruebas previas (tipos TKCTEST-*): no se hace nada.")
    started = True
    # --- tipos ---
    mode(PON_B + (PON_V if "4" in SECTIONS else []), "pon", "(config-pon)#", res, "tipo")
    run("end")
    if "4" in SECTIONS:
        for c in SHOW_TYPE_IF:
            run(c)
    # --- alta con el tipo de prueba ---
    run("conf t"); run(f"interface gpon_olt-{PON}")
    o = run(f"onu {IDX} type {NT} sn {SN}"); res["alta"] = verdict(o)
    run("end")
    if res["alta"] != "OK":
        raise SystemExit("No se pudo dar de alta la ONU de prueba.")

    # === S1 gemport portid (antes de crear vport-map; el vport-mode se alterna) ===
    if "1" in SECTIONS:
        log("=== S1: gemport portid ===")
        mode(S1_PRE + S1_HELP + GEM_VARIANTS + ["no gemport 1"], f"interface {ONU}", "(config-if-gpon_onu", res, "S1 manual")
        run("exit")
        mode(["vport-mode gemport", TCONT1] + GEM_VARIANTS + ["no gemport 1", "vport-mode manual"],
             f"interface {ONU}", "(config-if-gpon_onu", res, "S1 vport-mode gemport")
        run("exit")
        if RES2:
            log("=== S1b: resource mode2 (CAMBIA AJUSTE DE PUERTO; se restaura a mode1 en el rollback) ===")
            res_changed = True
            mode(["resource mode2"], f"interface gpon_olt-{PON}", "(config-if-gpon_olt", res, "S1b")
            run("exit")
            mode(S1_PRE + GEM_VARIANTS + ["no gemport 1"], f"interface {ONU}", "(config-if-gpon_onu", res, "S1b mode2")
            run("exit")
            mode(["resource mode1"], f"interface gpon_olt-{PON}", "(config-if-gpon_olt", res, "S1b")
            run("exit"); res_changed = False
    # --- base ---
    mode(BASE, f"interface {ONU}", "(config-if-gpon_onu", res, "base"); run("exit")
    mode(MNG_BASE, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res, "base-mng"); run("exit")

    # === S2 no vport-map ===
    if "2" in SECTIONS:
        log("=== S2: no vport-map ===")
        mode(S2_SETUP + S2_HELP, f"interface {ONU}", "(config-if-gpon_onu", res, "S2 setup"); run("exit")
        for c in S2_DEL:
            if not in_config:
                run("conf t")
            run(f"interface {ONU}")
            run(S2_MAP)                                   # (re)crear el mapeo; si existe da 222357 (inocuo)
            o = run(c); res[f"S2: {c}"] = verdict(o)
            run("end")
            cfg = onu_cfg()
            res[f"S2: {c} -> mapeo borrado"] = "vport-map 2 2" not in cfg
        mode(S2_END, f"interface {ONU}", "(config-if-gpon_onu", res, "S2 fin"); run("exit")

    # === S5 splitter (antes y después de habilitar location en el tipo) ===
    if "5" in SECTIONS:
        log("=== S5: splitter ===")
        mode(S5_HELP + S5_CMDS, f"interface {ONU}", "(config-if-gpon_onu", res, "S5 location disable"); run("exit")
        run("end"); run("show gpon onu detail-info " + ONU)
        mode([LOC_ON], "pon", "(config-pon)#", res, "S5 tipo"); run("end")
        run("show onu-type gpon")
        mode(S5_CMDS, f"interface {ONU}", "(config-if-gpon_onu", res, "S5 location enable")
        run("end"); run("show gpon onu detail-info " + ONU)
        mode(["no splitter"], f"interface {ONU}", "(config-if-gpon_onu", res, "S5 limpieza"); run("exit")

    # === S3 wifi ===
    if "3" in SECTIONS:
        log("=== S3: wifi enable domain ===")
        mode(S3_HELP + S3_CMDS, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res, "S3"); run("exit")

    # === S4 video ===
    if "4" in SECTIONS:
        log("=== S4: video ===")
        mode(S4_HELP + S4_CMDS, f"pon-onu-mng {ONU}", "(config-gpon-onu-mng)#", res, "S4"); run("exit")
    run("end")
    log("=== configuración final de la ONU antes del rollback ===")
    run(f"show running-config-interface {ONU}")
finally:
    if started:
        res["rollback_ok"] = rollback()
        res["config_puerto_identica"] = (before == olt_cfg())
        res["back_in_uncfg"] = SN in run("show pon onu uncfg")
    log("RESULTADO: " + json.dumps(res, ensure_ascii=False))
    try:
        tn.write(b"exit\n"); tn.close()
    except Exception:
        pass
