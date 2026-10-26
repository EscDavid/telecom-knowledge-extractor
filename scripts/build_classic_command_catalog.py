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
      "O": ("observed", 0.85, "ejecutado en una OLT ZXA10 C300 V2.1.0 el 2026-10-26; misma plataforma y firmware, no ejecutado en C320"),
      "S": ("observed", 0.70, "visto en la configuración real de una OLT ZXA10 C300 V2.1.0 (show running-config); no ejecutado por TKC")}
E = {"onu": "entity.zte.gpon.device.onu", "olt": "entity.zte.gpon.device.olt", "pon": "entity.zte.gpon.port.pon_port",
     "card": "entity.zte.gpon.hardware.card", "sp": "entity.zte.gpon.logical.service_port", "gem": "entity.zte.gpon.logical.gem_port",
     "vlan": "entity.zte.gpon.logical.vlan", None: None}
MODE = {"exec": "privileged_exec", "if": "interface_config", "gpon": "interface_config", "mng": "pon_config"}
PON = {"name": "pon", "type": "string", "pattern": None, "range": None, "required": True, "description": "puerto PON rack/slot/puerto", "example": "1/3/1"}
IDX = {"name": "onu-idx", "type": "string", "pattern": None, "range": None, "required": True, "description": "ONU rack/slot/puerto:n", "example": "1/3/1:2"}
O = "oid.zte.gpon.onu."
CMDS = []


def C(slug, cat, name, syn, ent=None, mode="exec", ctx=None, desc="", params=(), errs=(), out=(), idp=None, kind="V", notes=None):
    CMDS.append(dict(slug=slug, cat=cat, name=name, syn=syn, ent=ent, mode=mode, ctx=ctx, desc=desc, params=list(params), errs=list(errs),
                     out=list(out), idp=idp, kind=kind, notes=notes))


F = lambda n, oid=None: {"name": n, "type": "string", "unit": None, "oid_ref": oid, "oid_status": "inferred" if oid else "not_mapped"}
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
  desc="Potencias y atenuación de ambos sentidos: `up Rx` (recibida por la OLT, negativa; puede ser < -30 dBm), `Tx` de la ONU, `down Tx` de la OLT y `Rx` de la ONU.",
  params=[IDX], errs=[20202],
  out=[F("up_rx_dbm", O + "onu_rx_power_type"), F("up_tx_dbm", O + "onu_tx_power_type"), F("up_attenuation_db"), F("down_tx_dbm"), F("down_rx_dbm"), F("down_attenuation_db")],
  notes="La correspondencia up_rx_dbm↔onu_rx_power_type (1012.3.50.12.1.1.10) es una inferencia: queda por confirmar leyendo ese OID de la misma ONU.")
C("pon_power_onu_rx", "show", "show pon power onu-rx", "show pon power onu-rx gpon-onu_<idx>", "onu", idp="command.zte.gpon.global.show.pon_power_onu_rx",
  desc="Potencia recibida por la ONU (sentido bajada).", params=[IDX], errs=[20202])
C("pon_power_onu_tx", "show", "show pon power onu-tx", "show pon power onu-tx gpon-onu_<idx>", "onu", desc="Potencia transmitida por la ONU.", params=[IDX], errs=[20202])
C("pon_power_olt_rx", "show", "show pon power olt-rx", "show pon power olt-rx gpon-olt_<pon>", "pon",
  desc="Potencia recibida por la OLT de cada ONU del puerto (negativa; por debajo de -30 dBm el SNMP crudo es un entero de 16 bits con signo).", params=[PON], errs=[20202])
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
  desc="Declara una ONU en el puerto PON con su tipo y serial.", kind="S")
C("onu_name", "modify", "name (ONU)", "name <texto>", "onu", mode="if", ctx="interface gpon-onu_<idx>", desc="Nombre de la ONU (PII).", kind="S")
C("onu_description", "modify", "description (ONU)", "description <texto>", "onu", mode="if", ctx="interface gpon-onu_<idx>", desc="Descripción de la ONU (PII).", kind="S")
C("onu_tcont", "modify", "tcont (ONU)", "tcont <n> profile <perfil-subida>", "onu", mode="if", ctx="interface gpon-onu_<idx>", desc="Asocia un perfil T-CONT de subida.", kind="S")
C("onu_gemport", "modify", "gemport (ONU)", "gemport <n> tcont <m>", "gem", mode="if", ctx="interface gpon-onu_<idx>", desc="Crea el GEM port sobre un T-CONT.", kind="S")
C("onu_gemport_traffic_limit", "modify", "gemport traffic-limit", "gemport <n> traffic-limit downstream <perfil-bajada>", "gem", mode="if", ctx="interface gpon-onu_<idx>",
  desc="Perfil de velocidad de bajada (en clásicas va aquí; en C6 va en el service-port).", kind="S")
C("onu_service_port", "create", "service-port (ONU)", "service-port <n> vport <v> user-vlan <vlan> vlan <vlan>", "sp", mode="if", ctx="interface gpon-onu_<idx>",
  desc="Service-port declarado dentro de la interfaz de la ONU.", kind="S")


def build():
    by = {}
    for fam, code in (("ZXA10 C300", None), ("ZXA10 C320", None)):
        by[fam] = []
    ids = {}
    for c in CMDS:
        ids[c["slug"]] = c["idp"] or f"command.zte.gpon.{(c['ent'] or 'x.global').split('.')[-1] if c['ent'] else 'global'}.{c['cat']}.{c['slug']}"
    for c in CMDS:
        for fam in by:
            code = c["kind"] if c["kind"] == "S" else ("V" if fam == "ZXA10 C300" else "O")
            st, conf, ev = EV[code]
            by[fam].append({
                "id": ids[c["slug"]], "canonical_name": c["name"], "vendor": "ZTE", "family": fam, "firmware": ["2.0", "2.1"], "technology": "gpon",
                "category": c["cat"], "cli_mode": MODE[c["mode"]], "cli_context": c["ctx"], "entity_ref": E[c["ent"]], "description": c["desc"],
                "syntax": c["syn"], "parameters": c["params"], "output_fields": c["out"], "prerequisites": [], "related_commands": [],
                "rollback": None,
                "errors": [{"code": k, "meaning": ERR[k]["meaning"], "severity": "info" if k in INFO else "error", "retry": False} for k in c["errs"]],
                "notes": c["notes"], "evidence": ev, "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": conf}],
                "confidence": {"extraction": conf, "correlation": 0.0, "overall": conf}, "status": st, "conflicts": []})
    doc = {"meta": {"doc_type": "commands", "vendor": "ZTE", "families": list(by), "replace_seed": False,
                    "source": "reports/cli_verification_c620_c600_2026-10-02.md (BJ, BK)", "generated_by": "scripts/build_classic_command_catalog.py"},
           "commands": by}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    assert len({v["id"] for v in by["ZXA10 C300"]}) == len(by["ZXA10 C300"]), "ids duplicados"
    for fam, lst in by.items():
        print(fam, len(lst), dict(Counter(x["status"] for x in lst)))


if __name__ == "__main__":
    build()
