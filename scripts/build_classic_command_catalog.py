"""Genera docs/validation/commands/zte_classic_verified_commands.json (comandos de C300/C320) a partir de la sonda de solo lectura del
2026-10-26 (OLT ZXA10 C300 V2.1.0): C300 = `verified` (ejecutado), C320 = `observed` (misma plataforma y firmware, no ejecutado en C320).
No reemplaza la semilla (los ids heredados se conservan, ver refinements._classic_commands). Uso: python scripts/build_classic_command_catalog.py"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/validation/commands/zte_classic_verified_commands.json"
BEH = json.loads((ROOT / "docs/validation/commands/zte_classic_cli_behavior.json").read_text(encoding="utf-8"))
ERR = {e["code"]: e for e in BEH["errors"]}
INFO = {62310, 64040}
EV = {"V": ("verified", 0.95, "ejecutado y verificado en una OLT ZXA10 C300 V2.1.0 el 2026-10-26 (solo lectura)"),
      "W": ("verified", 0.95, "ejecutado y verificado en una OLT ZXA10 C320 V2.1.0 el 2026-10-27 (solo lectura)"),
      "O": ("observed", 0.85, "ejecutado en una OLT ZXA10 C300 V2.1.0 el 2026-10-26; misma plataforma y firmware, no ejecutado en esta C320 (o sin respuesta válida)"),
      "S": ("observed", 0.70, "visto en la configuración real de una OLT ZXA10 C300 V2.1.0 (show running-config); no ejecutado por TKC"),
      # Escrituras certificadas en vivo el 2026-11-03 (scripts de ISP Management: certificar-onu-clasica, verificar-pon-vlan, verificar-olt-clasica).
      # Cada cambio se verificó releyendo el equipo y se devolvió al estado original; la salida va anonimizada (docs/fixtures/zte-real/classic-write-20261103).
      "P": ("verified", 0.95, "ejecutado en escritura y verificado releyendo la OLT Unete Popular (ZXA10 C300 V2.1.0) el 2026-11-03; estado original restaurado"),
      "V3": ("verified", 0.95, "ejecutado en escritura y verificado releyendo la OLT PRIMAVERA (ZXA10 C320 V2.1.0) el 2026-11-03; estado original restaurado"),
      "Pm": ("observed", 0.80, "ejecutado el 2026-11-03 en la OLT PRIMAVERA (ZXA10 C320 V2.1.0): la OLT lo aceptó pero la ONU de prueba (ZP_CABLE) lo rechazó por OMCI (%Code 63993 unknown ME); depende del modelo de ONU")}
E = {"onu": "entity.zte.gpon.device.onu", "olt": "entity.zte.gpon.device.olt", "pon": "entity.zte.gpon.port.pon_port",
     "card": "entity.zte.gpon.hardware.card", "sp": "entity.zte.gpon.logical.service_port", "gem": "entity.zte.gpon.logical.gem_port",
     "vlan": "entity.zte.gpon.logical.vlan", None: None}
MODE = {"exec": "privileged_exec", "if": "interface_config", "gpon": "interface_config", "mng": "pon_config", "cfg": "global_config"}
PON = {"name": "pon", "type": "string", "pattern": None, "range": None, "required": True, "description": "puerto PON rack/slot/puerto", "example": "1/3/1"}
IDX = {"name": "onu-idx", "type": "string", "pattern": None, "range": None, "required": True, "description": "ONU rack/slot/puerto:n", "example": "1/3/1:2"}
O = "oid.zte.gpon.onu."
CMDS = []


def _executed_c320():
    """Comandos con respuesta válida (OK o VACIO) en la C320: resúmenes de la sonda (sin ayuda `?`, sin sintaxis de C6)."""
    out = set()
    for f in sorted((ROOT / "docs/validation").glob("c320_readonly_probe*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if not str(d.get("generated_at", "")).startswith("2026-10-27"):       # los del 26-oct (nombre c320) eran de un C300
            continue
        for r in d["results"]:
            if r["verdict"] in ("OK", "VACIO") and r["group"] != "ayuda" and r["cmd"] != "terminal length 0" and r["variant"] != "c6":
                out.add(tuple(r["cmd"].split()))
    return out


def _was_run(syn, executed):
    base = []
    for tok in syn.replace("[", " [").split():
        if tok.startswith("[") or tok.startswith("<") or "<" in tok:
            break
        base.append(tok)
    return any(e[:len(base)] == tuple(base) for e in executed)



def C(slug, cat, name, syn, ent=None, mode="exec", ctx=None, desc="", params=(), errs=(), out=(), idp=None, kind="V", notes=None, rb=None):
    CMDS.append(dict(slug=slug, cat=cat, name=name, syn=syn, ent=ent, mode=mode, ctx=ctx, desc=desc, params=list(params), errs=list(errs),
                     out=list(out), idp=idp, kind=kind, notes=notes, rb=rb))


F = lambda n, oid=None, ok=False: {"name": n, "type": "string", "unit": None, "oid_ref": oid, "oid_status": ("mapped" if ok else "inferred") if oid else "not_mapped"}
# ------------------------------------------------------------- lecturas
C("clock", "show", "show clock", "show clock", None, desc="Hora del equipo; prueba de conexión.")
C("version", "show", "show version-running", "show version-running", None, idp="command.zte.gpon.global.show.version",
  desc="Versión en ejecución por tarjeta (tipo de fichero MVR/BT/FW, versión y fecha de compilación). `show version` es ambiguo (20204) y `show software 1` no existe en clásicas.",
  errs=[20204], out=[F("phy_loc"), F("file_type"), F("ver_type"), F("ver_tag"), F("build_time"), F("ver_length")],
  notes="La versión del sistema también sale de `show system-group` (System Description: `C300 Version V2.1.0 Software…`).")
C("system_group", "show", "show system-group", "show system-group", None,
  desc="Descripción del sistema (modelo y versión), ObjectId, tiempo en línea, nombre y contacto. Equivale a sysDescr/sysObjectID por CLI.",
  out=[F("system_description"), F("system_object_id"), F("uptime"), F("system_name")])
C("show", "show", "show card", "show card", "card", idp="command.zte.gpon.card.show",
  desc="Tarjetas por slot: CfgType, RealType, puertos, versión de hardware y software, estado (INSERVICE, STANDBY, NOPOWER).",
  out=[F("rack"), F("shelf"), F("slot"), F("cfg_type"), F("real_type"), F("port"), F("hard_ver"), F("soft_ver"), F("status")])
C("card_temperature", "show", "show card-temperature", "show card-temperature", "card", desc="Temperatura por tarjeta (actual, 5 min, 1 h, óptica).")
C("card_power", "show", "show card-power", "show card-power", "card", desc="Potencia (W), tensión (V) y corriente (A) por tarjeta y del ventilador.")
C("state", "show", "show gpon onu state", "show gpon onu state [gpon-olt_<pon>]", "onu", idp="command.zte.gpon.onu.show.state",
  desc="Estado de las ONU (todas o de un puerto): Admin State, OMCC State, Phase State (working, OffLine, DyingGasp, LOS…) y canal.",
  params=[{**PON, "required": False}], errs=[20202], out=[F("onu_index"), F("admin_state"), F("omcc_state"), F("phase_state"), F("channel")])
C("baseinfo", "show", "show gpon onu baseinfo", "show gpon onu baseinfo gpon-olt_<pon>", "onu", idp="command.zte.gpon.onu.show.baseinfo",
  desc="ONU de un puerto con tipo, modo de autenticación, serial/contraseña y estado.", params=[PON], errs=[20202],
  out=[F("onu_index"), F("type"), F("mode"), F("auth_info"), F("state")])
C("uncfg", "show", "show gpon onu uncfg", "show gpon onu uncfg [gpon-olt_<pon>]", "onu", idp="command.zte.gpon.onu.show.uncfg",
  desc="ONU sin autorizar. Con 0 ONU responde `%Code 62310-GPONSRV : No related information to show.` (válido, no es un fallo).",
  params=[{**PON, "required": False}], errs=[62310])
C("detail_info", "show", "show gpon onu detail-info", "show gpon onu detail-info gpon-onu_<idx>", "onu", idp="command.zte.gpon.onu.show.detail_info",
  desc="Detalle de ONU: tipo, Admin/Phase/Config state, serial, distancia, tiempo en línea, FEC, Vport mode, DBA mode. `Name` y `Description` salen EN CLARO (PII).",
  params=[IDX], errs=[20202], notes="PII: Name/Description visibles con la cuenta de lectura; no almacenar ni registrar.",
  out=[F("type"), F("admin_state"), F("phase_state"), F("config_state"), F("serial_number"), F("onu_distance"), F("online_duration")])
C("distance", "show", "show gpon onu distance", "show gpon onu distance gpon-onu_<idx>", "onu", desc="Distancia de la ONU (Eqd en bits y metros).",
  params=[IDX], errs=[20202], out=[F("eqd_bit"), F("distance_m")])
C("by_sn", "show", "show gpon onu by sn", "show gpon onu by sn <sn>", "onu", desc="Busca la ONU configurada con ese serial y devuelve su índice.",
  params=[{"name": "sn", "type": "string", "pattern": None, "range": None, "required": True, "description": "serial de la ONU", "example": "ZTEGXXXXXXXX"}])
C("onu_information", "show", "show pon onu information", "show pon onu information gpon-onu_<idx>", "onu",
  desc="Autenticación, SN reportado, tipo configurado y reportado, versiones de hardware/software de la ONU e historial de altas/bajas (hora y causa).",
  params=[IDX], errs=[20202], out=[F("auth_information"), F("sn_reported"), F("onu_id"), F("onu_type_configured"), F("onu_type_reported"), F("state")])
C("power_attenuation", "show", "show pon power attenuation", "show pon power attenuation gpon-onu_<idx>", "onu",
  desc="Potencias y atenuación de ambos sentidos: `up Rx` (recibida por la OLT), `up Tx` (transmitida por la ONU), `down Tx` (de la OLT) y `down Rx` (recibida por la ONU).",
  params=[IDX], errs=[20202],
  out=[F("up_rx_dbm"), F("up_tx_dbm", O + "onu_tx_power_type", True), F("up_attenuation_db"), F("down_tx_dbm"), F("down_rx_dbm", O + "onu_rx_power_type", True), F("down_attenuation_db")],
  notes="Verificado en una C320 V2.1.0 (2026-10-27) leyendo a la vez la CLI y el SNMP de la misma ONU: onu_rx_power_type (1012.3.50.12.1.1.10) = `down Rx` / `show pon power onu-rx` "
        "(raw 207 → -29,586 dBm, idéntico) y onu_tx_power_type (…14) = `up Tx` / `onu-tx` (raw 16032 → 2,064 dBm, idéntico). La potencia recibida por la OLT (`up Rx`, `olt-rx`) NO está en esas columnas: solo CLI.")
C("pon_power_onu_rx", "show", "show pon power onu-rx", "show pon power onu-rx gpon-onu_<idx>", "onu", idp="command.zte.gpon.global.show.pon_power_onu_rx",
  desc="Potencia recibida por la ONU (sentido bajada). Es el valor de onu_rx_power_type por SNMP (idéntico, verificado en C320).", params=[IDX], errs=[20202],
  out=[F("rx_power_dbm", O + "onu_rx_power_type", True)])
C("pon_power_onu_tx", "show", "show pon power onu-tx", "show pon power onu-tx gpon-onu_<idx>", "onu",
  desc="Potencia transmitida por la ONU. Es el valor de onu_tx_power_type por SNMP (idéntico, verificado en C320).", params=[IDX], errs=[20202],
  out=[F("tx_power_dbm", O + "onu_tx_power_type", True)])
C("pon_power_olt_rx", "show", "show pon power olt-rx", "show pon power olt-rx gpon-olt_<pon>", "pon",
  desc="Potencia recibida POR LA OLT de cada ONU del puerto (sentido subida; `no signal` si la ONU está apagada). Solo CLI: no está en las columnas 10/14 de 1012.3.50.12.1.1.", params=[PON], errs=[20202],
  out=[F("olt_rx_power_dbm")])
C("pon_power_olt_tx", "show", "show pon power olt-tx", "show pon power olt-tx gpon-olt_<pon>", "pon", desc="Potencia transmitida por el puerto PON (por canal).", params=[PON], errs=[20202])
C("interface_olt", "show", "show interface gpon-olt", "show interface gpon-olt_<pon>", "pon",
  desc="Estado del puerto PON: ONU soportadas (128), registradas, tasas de entrada/salida y ancho de banda.", params=[PON], errs=[20202])
C("service_port", "show", "show service-port interface", "show service-port interface gpon-onu_<idx>", "sp",
  desc="Service-port de la ONU: vport, VLAN, perfiles ingress/egress, estado.", params=[IDX], errs=[20202])
C("mac", "show", "show mac gpon onu", "show mac gpon onu gpon-onu_<idx>", "onu", desc="Direcciones MAC aprendidas de la ONU (VLAN, tipo, vport).", params=[IDX], errs=[20202])
C("running_olt", "show", "show running-config interface (puerto PON)", "show running-config interface gpon-olt_<pon>", "pon",
  desc="Configuración del puerto: ONU declaradas (`onu <n> type <tipo> sn <serial>`) y estado administrativo. Con espacio: `show running-config-interface` no existe.",
  params=[PON], errs=[20202])
C("running_onu", "show", "show running-config interface (ONU)", "show running-config interface gpon-onu_<idx>", "onu",
  desc="Configuración de la ONU: name, description (EN CLARO), tcont, gemport, `gemport … traffic-limit downstream`, service-port.",
  params=[IDX], errs=[20202], notes="PII: name/description en claro.")
C("onu_running_config", "show", "show onu running config", "show onu running config gpon-onu_<idx>", "onu",
  desc="Bloque pon-onu-mng de la ONU: flow, switchport-bind, ip-host, vlan-filter, dhcp-ip, security-mgmt.", params=[IDX], errs=[20202])
for k, d in (("equip", "Equipo: Vendor ID, versión, SN, estado administrativo, Equipment ID, versión OMCC."),
             ("capability", "Capacidades: T-CONT, GEM ports, colas, UNI (Ethernet, WiFi, vídeo…)."),
             ("sys_attr", "CPU y memoria de la ONU y sus umbrales.")):
    C(f"remote_{k}", "show", f"show gpon remote-onu {k.replace('_', '-')}", f"show gpon remote-onu {k.replace('_', '-')} gpon-onu_<idx>", "onu", desc=d, params=[IDX], errs=[20202])
C("remote_interface_eth", "show", "show gpon remote-onu interface eth", "show gpon remote-onu interface eth gpon-onu_<idx>", "onu",
  desc="Puertos Ethernet de la ONU: velocidad, estado operativo y administrativo, trama máxima.", params=[IDX], errs=[20202])
C("onu_type_list", "show", "show onu-type", "show onu-type", None, desc="Plantillas de tipo de ONU (nombre, PON, T-CONT, GEM, interfaces).")
C("vlan_summary", "show", "show vlan summary", "show vlan summary", "vlan", desc="VLAN creadas (cantidad y lista).")
C("profile_tcont", "show", "show gpon profile tcont", "show gpon profile tcont", None, desc="Perfiles T-CONT (tipo, FBW/ABW/MBW en kbps).")
C("profile_traffic", "show", "show gpon profile traffic", "show gpon profile traffic", None, desc="Perfiles de tráfico (SIR/PIR en kbps, CBS/PBS en KB).")
C("onu_profile_vlan", "show", "show gpon onu profile vlan", "show gpon onu profile vlan", None, desc="Perfiles de VLAN de ONU (vacío si no hay).", errs=[64040])
C("onu_profile_traffic", "show", "show gpon onu profile traffic", "show gpon onu profile traffic", None, desc="Perfiles de tráfico de ONU (vacío si no hay).", errs=[64040])
C("logging_alarm", "show", "show logging alarm", "show logging alarm", None,
  desc="Registro de alarmas y notificaciones (hasta 2000): `An alarm <id> level <nivel> occurred at <fecha> … <gpon-onu_P:N> …`; incluye alarm y restore.")
C("alarm_pool", "show", "show alarm pool", "show alarm pool", None, desc="Alarmas activas: Alarm ID, código, nivel, hora y descripción (`<gpon-onu_P:N> …`).")
C("alarm_counter", "show", "show alarm counter", "show alarm counter", None, desc="Contadores del subsistema de alarmas.")
# ------------------------------------------------------------- escrituras (solo vistas en la configuración real)
C("onu_create", "create", "onu <n> type <tipo> sn <serial>", "onu <1-128> type <onu-type> sn <sn>", "onu", mode="gpon", ctx="interface gpon-olt_<pon>",
  desc="Declara una ONU en el puerto PON con su tipo y serial.", kind="W", rb="no onu <n>")
C("onu_name", "modify", "name (ONU)", "name <texto>", "onu", mode="if", ctx="interface gpon-onu_<idx>", desc="Nombre de la ONU (PII).", kind="W", rb="name <texto-anterior>")
C("onu_description", "modify", "description (ONU)", "description <texto>", "onu", mode="if", ctx="interface gpon-onu_<idx>", desc="Descripción de la ONU (PII).", kind="W", rb="no description")
C("onu_tcont", "modify", "tcont (ONU)", "tcont <n> profile <perfil-subida>", "onu", mode="if", ctx="interface gpon-onu_<idx>", desc="Asocia un perfil T-CONT de subida.", kind="W", rb="tcont <n> profile <perfil-anterior>")
C("onu_gemport", "modify", "gemport (ONU)", "gemport <n> tcont <m>", "gem", mode="if", ctx="interface gpon-onu_<idx>", desc="Crea el GEM port sobre un T-CONT.", kind="W", rb="no gemport <n>")
C("onu_gemport_traffic_limit", "modify", "gemport traffic-limit", "gemport <n> traffic-limit downstream <perfil-bajada>", "gem", mode="if", ctx="interface gpon-onu_<idx>",
  desc="Perfil de velocidad de bajada (en clásicas va aquí; en C6 va en el service-port).", kind="W", rb="gemport <n> traffic-limit downstream <perfil-anterior>")
C("onu_service_port", "create", "service-port (ONU)", "service-port <n> vport <v> user-vlan <vlan> vlan <vlan>", "sp", mode="if", ctx="interface gpon-onu_<idx>",
  desc="Service-port declarado dentro de la interfaz de la ONU.", kind="W", rb="no service-port <n>")

# ------------------------------------------------------------- escrituras certificadas en vivo (2026-11-03)
INT = {"mode": "if", "ctx": "interface gpon-onu_<idx>"}
MNG = {"mode": "mng", "ctx": "pon-onu-mng gpon-onu_<idx>"}
PN = lambda n, ex, rng=None, d="": {"name": n, "type": "string", "pattern": None, "range": rng, "required": True, "description": d, "example": ex}
C("onu_description_clear", "modify", "no description (ONU)", "no description", "onu", **INT, desc="Quita la descripción de la ONU.", kind="W", rb="description <texto-anterior>")
C("onu_no_service_port", "delete", "no service-port (ONU)", "no service-port <n>", "sp", **INT, desc="Quita el service-port; con `service-port` de nuevo se reasigna la VLAN.", kind="W",
  rb="service-port <n> vport <v> user-vlan <vlan> vlan <vlan>")
C("onu_delete", "delete", "no onu <n>", "no onu <n>", "onu", mode="gpon", ctx="interface gpon-olt_<pon>",
  desc="Da de baja la ONU del puerto con toda su configuración. Dar de alta de nuevo exige reponer interfaz y pon-onu-mng (el equipo no los conserva).", params=[PON], kind="W",
  rb="onu <n> type <tipo> sn <sn> y reponer interfaz y pon-onu-mng", notes="La ONU vuelve a `working` unos 6 s (C300) a 12 s (C320) tras el alta; verificado por relectura idéntica al estado previo.")
C("onu_reboot", "reset", "reboot (ONU)", "reboot", "onu", **MNG, desc="Reinicia la ONU. El equipo pregunta `Confirm to reboot? [yes/no]:` y espera `yes`.", kind="W",
  notes="Medido: sale de `working` a los 17 s (C300) / 7 s (C320) y vuelve a los ~102 s / ~91 s. La pregunta de confirmación debe contestarse solo para esta línea.")
C("onu_mng_flow", "create", "flow / gemport flow (pon-onu-mng)", "flow mode <n> tag-filter vlan-filter untag-filter discard ; flow <n> pri <p> vlan <v> ; gemport <n> flow <m>", "onu", **MNG,
  desc="Flujo de la ONU hacia la VLAN de servicio (plantilla clásica).", kind="W")
C("onu_mng_switchport_bind", "create", "switchport-bind", "switchport-bind switch_0/<n> {iphost|veip} <m>", "onu", **MNG, desc="Ata el puerto virtual (iphost/veip) al switch de la ONU.", kind="W")
C("onu_mng_vlan_filter", "create", "vlan-filter", "vlan-filter-mode iphost <n> tag-filter vlan-filter untag-filter discard ; vlan-filter iphost <n> pri <p> vlan <v>", "onu", **MNG,
  desc="Filtro de VLAN del host IP de la ONU.", kind="W")
C("onu_mng_dhcp_ip", "modify", "dhcp-ip ethuni", "dhcp-ip ethuni eth_0/<n> from-onu", "onu", **MNG, desc="El puerto Ethernet de la ONU obtiene IP de la propia ONU.", kind="Wv",
  notes="Verificado en una ONU ZP_CABLE de la C320; la ONU ADC de la C300 usada no lo tenía en su configuración.")
C("onu_mng_security_mgmt", "modify", "security-mgmt", "security-mgmt <n> state enable [mode forward] ingress-type lan protocol <proto…>", "onu", **MNG,
  desc="Gestión de la ONU por servicios (web, ftp, telnet, ssh, snmp, tr069) desde la LAN.", kind="W",
  notes="Las líneas largas llegan partidas por el ancho del terminal; al leer hay que unirlas (`https` y `tr069` salen en dos renglones).")
C("onu_catv", "modify", "interface video state", "interface video video_0/<n> state {lock|unlock}", "onu", **MNG, desc="Habilita o deshabilita el puerto CATV de la ONU.", kind="W",
  rb="interface video video_0/<n> state {unlock|lock} (el valor anterior)")
C("onu_eth_state", "modify", "interface eth state", "interface eth eth_0/<n> state {lock|unlock}", "onu", **MNG, desc="Habilita o deshabilita un puerto Ethernet de la ONU.", kind="W",
  rb="interface eth eth_0/<n> state {unlock|lock} (el valor anterior)")
C("onu_eth_speed", "modify", "interface eth speed", "interface eth eth_0/<n> speed {auto|full-10|full-100|full-1000|half-10|half-100}", "onu", **MNG,
  desc="Velocidad de negociación del puerto Ethernet de la ONU.", kind="W", rb="interface eth eth_0/<n> speed <valor-anterior>")
C("onu_wifi_radio", "modify", "interface wifi state", "interface wifi wifi_0/<n> state {lock|unlock}", "onu", **MNG, desc="Habilita o deshabilita un radio WiFi de la ONU.", kind="W",
  rb="interface wifi wifi_0/<n> state {unlock|lock} (el valor anterior)")
C("onu_wifi_global", "modify", "wifi {enable|disable}", "wifi {enable|disable}", "onu", **MNG, desc="WiFi global de la ONU.", kind="Wm", rb="wifi {disable|enable} (el valor anterior)",
  notes="Depende del MODELO DE ONU: en la ONU ADC de la C300 funcionó; la ONU ZP_CABLE de la C320 lo rechazó (%Code 63993-GPONRM : ONT return error:unknown ME).")
C("olt_write", "modify", "write", "write", None, desc="Guarda la configuración en uso de la OLT. Responde `[OK]`.", kind="W",
  notes="Duración medida: 41 s en la C300 y 1,8 s en la C320 (el plazo de espera debe ser ≥ 60 s).")
C("pon_description", "modify", "description / no description (puerto PON)", "description <texto> | no description", "pon", mode="gpon", ctx="interface gpon-olt_<pon>",
  desc="Descripción del puerto PON (aparece en el running-config del puerto).", kind="W", rb="no description")
C("pon_shutdown", "modify", "shutdown / no shutdown (puerto PON)", "shutdown | no shutdown", "pon", mode="gpon", ctx="interface gpon-olt_<pon>",
  desc="Apaga o enciende el puerto PON. Apagarlo corta a todas sus ONU; el running-config muestra `shutdown` cuando está apagado y `no shutdown` si no.", kind="W", rb="no shutdown")
C("vlan_create", "create", "vlan <id>", "vlan <1-4094>", "vlan", mode="cfg", ctx="configure terminal", desc="Crea una VLAN en la OLT; `show vlan <id>` la devuelve.", params=[PN("vlan-id", "3999", "1-4094")],
  kind="W", rb="no vlan <id>", notes="Inexistente: `show vlan <id>` responde `%Code 60514: This vlan does not exist.`")
C("vlan_delete", "delete", "no vlan <id>", "no vlan <1-4094>", "vlan", mode="cfg", ctx="configure terminal", desc="Borra una VLAN de la OLT.", params=[PN("vlan-id", "3999", "1-4094")], kind="W", rb="vlan <id>")
C("profile_tcont_create", "create", "profile tcont", "profile tcont <nombre> type 5 fixed <kbps> assured <kbps> maximum <kbps>", None, mode="gpon", ctx="gpon",
  desc="Crea un perfil T-CONT de subida (modo `gpon`).", params=[PN("nombre", "SMARTOLT-90M-UP")], kind="W", rb="no profile tcont <nombre>")
C("profile_tcont_delete", "delete", "no profile tcont", "no profile tcont <nombre>", None, mode="gpon", ctx="gpon", desc="Borra un perfil T-CONT.", params=[PN("nombre", "SMARTOLT-90M-UP")], kind="W")
C("profile_traffic_create", "create", "profile traffic", "profile traffic <nombre> sir <kbps> pir <kbps>", None, mode="gpon", ctx="gpon",
  desc="Crea un perfil de tráfico de bajada (modo `gpon`); CBS/PBS toman el valor por defecto.", params=[PN("nombre", "SMARTOLT-100M-DOWN")], kind="W", rb="no profile traffic <nombre>")
C("profile_traffic_delete", "delete", "no profile traffic", "no profile traffic <nombre>", None, mode="gpon", ctx="gpon", desc="Borra un perfil de tráfico.", params=[PN("nombre", "SMARTOLT-100M-DOWN")], kind="W")
C("onu_type_create", "create", "onu-type … gpon / onu-type-if", "onu-type <nombre> gpon description <d> max-tcont <n> max-gemport <n> max-switch-perslot <n> max-flow-perswitch <n> ; onu-type-if <nombre> eth_0/<1-n>", None,
  mode="mng", ctx="pon", desc="Crea un tipo de ONU GPON con sus puertos Ethernet (modo `pon`).", params=[PN("nombre", "ADC")], kind="W", rb="no onu-type <nombre>",
  notes="La sintaxis salía solo del manual (§2.1); ahora ejecutada y verificada con `show onu-type`.")
C("onu_type_delete", "delete", "no onu-type", "no onu-type <nombre>", None, mode="mng", ctx="pon", desc="Borra un tipo de ONU.", params=[PN("nombre", "ADC")], kind="W")


def build():
    by = {}
    for fam, code in (("ZXA10 C300", None), ("ZXA10 C320", None)):
        by[fam] = []
    ids = {}
    executed = _executed_c320()
    for c in CMDS:
        ids[c["slug"]] = c["idp"] or f"command.zte.gpon.{(c['ent'] or 'x.global').split('.')[-1] if c['ent'] else 'global'}.{c['cat']}.{c['slug']}"
    for c in CMDS:
        for fam in by:
            if c["kind"] == "W":
                code = "P" if fam == "ZXA10 C300" else "V3"
            elif c["kind"] == "Wp":           # verificado en Popular (C300); en C320 no se probó con una ONU que lo tuviera
                code = "P" if fam == "ZXA10 C300" else "O"
            elif c["kind"] == "Wv":           # verificado en Primavera (C320); en C300 no se probó con una ONU que lo tuviera
                code = "O" if fam == "ZXA10 C300" else "V3"
            elif c["kind"] == "Wm":           # C300 verificado; en C320 la OLT lo aceptó pero la ONU de prueba lo rechazó
                code = "P" if fam == "ZXA10 C300" else "Pm"
            else:
                code = c["kind"] if c["kind"] == "S" else ("V" if fam == "ZXA10 C300" else ("W" if _was_run(c["syn"], executed) else "O"))
            st, conf, ev = EV[code]
            by[fam].append({
                "id": ids[c["slug"]], "canonical_name": c["name"], "vendor": "ZTE", "family": fam, "firmware": ["2.0", "2.1"], "technology": "gpon",
                "category": c["cat"], "cli_mode": MODE[c["mode"]], "cli_context": c["ctx"], "entity_ref": E[c["ent"]], "description": c["desc"],
                "syntax": c["syn"], "parameters": c["params"], "output_fields": c["out"], "prerequisites": [], "related_commands": [],
                "rollback": c["rb"],
                "errors": [{"code": k, "meaning": ERR[k]["meaning"], "severity": "info" if k in INFO else "error", "retry": False} for k in c["errs"]],
                "notes": c["notes"], "evidence": ev, "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": conf}],
                "confidence": {"extraction": conf, "correlation": 0.0, "overall": conf}, "status": st, "conflicts": []})
    doc = {"meta": {"doc_type": "commands", "vendor": "ZTE", "families": list(by), "replace_seed": False,
                    "source": "reports/cli_verification_c620_c600_2026-10-02.md (BJ, BK); certificaciones en vivo 2026-11-03", "generated_by": "scripts/build_classic_command_catalog.py"},
           "commands": by}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    assert len({v["id"] for v in by["ZXA10 C300"]}) == len(by["ZXA10 C300"]), "ids duplicados"
    for fam, lst in by.items():
        print(fam, len(lst), dict(Counter(x["status"] for x in lst)))


if __name__ == "__main__":
    build()
