"""Genera docs/validation/commands/zte_c6xx_verified_commands.json: catálogo de comandos CLI verificados en hardware
(ZXA10 C620 prioridad, ZXA10 C600) a partir del informe reports/cli_verification_c620_c600_2026-10-02.md.

Estados por comando y familia:  V = ejecutado y verificado en la OLT · L = visto en la configuración/bitácora real de la OLT
(ejecutado por SmartOLT) · H = sintaxis descubierta solo con la ayuda `?` · None = no aplica en esa familia.
Uso:  python scripts/build_c620_command_catalog.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/validation/commands/zte_c6xx_verified_commands.json"
STATUS = {"V": ("verified", 0.95, "ejecutado y verificado en la OLT el 2026-10-02"),
          "L": ("observed", 0.85, "visto en la configuración/bitácora real de la OLT (ejecutado por SmartOLT)"),
          "H": ("documented", 0.60, "sintaxis obtenida solo con la ayuda '?' de la OLT (no ejecutada)")}
E = {"onu": "entity.zte.gpon.device.onu", "olt": "entity.zte.gpon.device.olt", "pon": "entity.zte.gpon.port.pon_port",
     "up": "entity.zte.gpon.port.uplink_port", "sp": "entity.zte.gpon.logical.service_port", "vlan": "entity.zte.gpon.logical.vlan",
     "gem": "entity.zte.gpon.logical.gem_port", "card": "entity.zte.gpon.hardware.card", None: None}
MODE = {"exec": "privileged_exec", "cfg": "global_config", "if": "interface_config", "gpon": "pon_config", "pon": "pon_config"}
CMDS = []


def P(name, typ="string", rng=None, req=True, ex=None, desc=""):
    return {"name": name, "type": typ, "pattern": None, "range": rng, "required": req, "description": desc, "example": ex}


def C(slug, cat, name, syn, ent=None, mode="exec", ctx=None, desc="", params=(), s620="V", s600="H", rollback=None,
      notes=None, prereq=(), related=(), out=()):
    CMDS.append({"slug": slug, "cat": cat, "name": name, "syn": syn, "ent": ent, "mode": mode, "ctx": ctx, "desc": desc,
                 "params": list(params), "s": {"ZXA10 C620": s620, "ZXA10 C600": s600}, "rollback": rollback,
                 "notes": notes, "prereq": list(prereq), "related": list(related), "out": list(out)})


PON = P("pon", "string", None, True, "1/1/5", "puerto PON rack/slot/puerto")
IDX = P("onu-idx", "string", None, True, "1/1/5:3", "índice de ONU rack/slot/puerto:n")
# ------------------------------------------------------------------ LECTURAS (privileged_exec)
C("clock", "show", "show clock", "show clock", None, desc="Hora del equipo; prueba de conexión.", s600="V")
C("software", "show", "show software", "show software <1-7>", None, desc="Versión de software, imagen y paquetes por slot (equivale a 'show version', que no existe). Slots 1-7 en C620, 1-21 en C600.", s600="V",
  params=[P("slot", "integer", "1-7 (C620) / 1-21 (C600)", True, "1")])
C("card", "show", "show card", "show card", E["card"], desc="Tarjetas: shelf, slot, tipo, nombre, puertos, versión de hardware y estado (INSERVICE/STANDBY). 'show shelf' no existe.", s600="V")
C("onu_state", "show", "show gpon onu state", "show gpon onu state [gpon_olt-<pon>]", E["onu"], desc="Estado de las ONU: Admin, OMCC y Phase state (working, OffLine, LOS, DyingGasp, syncMib, Logging).", s600="V",
  params=[P("gpon_olt", "string", None, False, "gpon_olt-1/1/5")], out=["onu_index", "admin_state", "omcc_state", "phase_state", "speed_mode"])
C("onu_baseinfo", "show", "show gpon onu baseinfo", "show gpon onu baseinfo gpon_olt-<pon>", E["onu"], desc="Tipo, modo de autenticación, serial y estado de las ONU de un puerto.", s600="V",
  params=[P("gpon_olt", "string", None, True, "gpon_olt-1/1/5")], out=["onu_index", "type", "authentication_mode", "serial_number", "state"])
C("onu_detail", "show", "show gpon onu detail-info", "show gpon onu detail-info gpon_onu-<idx>", E["onu"], s600="V",
  desc="Detalle de una ONU: tipo, estado, serial, distancia, tiempo en línea y últimas 10 altas/bajas con causa. Name/Description salen enmascarados (********).",
  params=[P("gpon_onu", "string", None, True, "gpon_onu-1/1/5:1")], out=["phase_state", "serial_number", "onu_distance", "online_duration", "authpass_time", "offline_time", "offline_cause"])
C("onu_by_sn", "show", "show gpon onu by sn", "show gpon onu by sn <SN>", E["onu"], s600="V", desc="Busca una ONU por serial.", params=[P("sn", "string", None, True, "DF306B41EDB0")])
C("onu_uncfg", "show", "show pon onu uncfg", "show pon onu uncfg [gpon_olt-<pon>] [first-find-time] [last-find-time] [auth-fail-reason] [model <WORD>] [mac] [pw]", E["onu"], s600="V",
  desc="ONU sin autorizar (equivale a 'show gpon onu uncfg', que no existe). Acepta puerto y columnas opcionales.",
  params=[P("gpon_olt", "string", None, False, "gpon_olt-1/1/5")], out=["olt_index", "model", "serial_number", "pw", "first_find_time", "last_find_time", "auth_fail_reason"],
  notes="Por SNMP en la C620: tabla 1082.500.2.2.11.2.1.<col>.<ifIndexPON>.<n> (serial col 2, PW 3, modelo 8, firmware 10, primer hallazgo 12, último 13); verificado contra este comando el 2026-10-09. En la C600 no verificado (0 ONU sin autorizar).")
C("onu_type_list", "show", "show onu-type", "show onu-type [gpon|epon]", E["onu"], s600="V", desc="Tipos de ONU definidos en la OLT (nombre, descripción, máx. T-CONT/GEM/VEIP/IP host, etc.).")
C("tcont_profile_list", "show", "show gpon profile tcont", "show gpon profile tcont", None, s600="V", desc="Perfiles T-CONT (subida): tipo, FBW/ABW/MBW, contador de uso. Los SMARTOLT-<vel>-UP son perfiles T-CONT tipo 5.")
C("traffic_profile_list", "show", "show qos traffic-profile", "show qos traffic-profile [name <WORD>]", None, s600="V",
  desc="Perfiles de velocidad de bajada (qos traffic-profile). Sin argumento lista nombres; con 'name' da CIR/CBS/PIR/PBS. También legibles por SNMP en .1.3.6.1.4.1.3902.1082.50.2.2.1.1.<col>.<nombre ASCII>.",
  out=["profile_name", "cir_kbps", "cbs_kbytes", "pir_kbps", "pbs_kbytes"])
C("onu_profile_traffic", "show", "show gpon onu profile traffic", "show gpon onu profile traffic [<WORD>]", None, s600="H",
  desc="Perfiles de tráfico de ONU (para gemport/switchport traffic-limit): SIR, PIR, CBS, PBS, colour mode, meter type. Vacío si no hay ninguno (%Error 224040).")
C("onu_profile_vlan", "show", "show gpon onu profile vlan", "show gpon onu profile vlan", E["vlan"], s600="L", desc="Perfiles de VLAN de ONU (p. ej. SMARTOLT_VLAN_101: tag mode, CVLAN, prioridad).")
C("rc_olt", "show", "show running-config-interface (puerto PON)", "show running-config-interface gpon_olt-<pon>", E["pon"], s600="V",
  desc="Configuración del puerto PON: líneas 'onu <N> type <TIPO> sn <SN>' de las ONU ocupadas y estado 'no shutdown'. Equivale a 'show running-config interface gpon-olt_X' de la clásica.",
  params=[P("gpon_olt", "string", None, True, "gpon_olt-1/1/5")])
C("rc_onu", "show", "show running-config-interface (ONU)", "show running-config-interface gpon_onu-<idx>", E["onu"], s600="V",
  desc="Configuración completa de una ONU: bloque de interfaz (name/description enmascarados, vport-mode, tcont, gemport, vport-map) y bloque pon-onu-mng (servicio, VLAN, WAN, WiFi, Ethernet, CATV, límites de tasa).",
  params=[P("gpon_onu", "string", None, True, "gpon_onu-1/1/5:1")])
C("rc_vport", "show", "show running-config-interface (vport)", "show running-config-interface vport-<pon>.<n>:<v>", E["sp"], s600="V",
  desc="Service-port de una ONU: 'service-port <id> user-vlan <V> vlan <V> ingress <perfil> egress <perfil>'.", params=[P("vport", "string", None, True, "vport-1/1/5.1:1")])
C("service_port", "show", "show service-port interface", "show service-port interface {gpon_onu-<idx>|vport-<pon>.<n>:<v>}", E["sp"], s600="V", desc="Tabla de service-ports de la ONU (Sport, Vport, VLAN, ingress/egress, estado).", out=["sport_id", "vport", "user_vlan", "vlan", "ingress_profile", "egress_profile"])
C("mac_if", "show", "show mac interface", "show mac interface {gpon_onu-<idx>|vport-<pon>.<n>:<v>}", E["onu"], s600="V",
  desc="MAC aprendidas de la ONU (MAC, VLAN, tipo, vport). Equivale a 'show mac gpon onu' de la clásica, que no existe. No hay tabla MAC por SNMP.", out=["mac_address", "vlan", "type", "vport"])
C("vlan_summary", "show", "show vlan summary", "show vlan summary", E["vlan"], s600="V", desc="VLAN creadas.")
C("vlan_detail", "show", "show vlan", "show vlan <1-4094>", E["vlan"], s600="V", params=[P("vlan", "integer", "1-4094", True, "100")], desc="Detalle de una VLAN.")
C("onu_distance", "show", "show gpon onu distance", "show gpon onu distance gpon_onu-<idx>", E["onu"], s600="V", desc="Distancia OLT-ONU en metros (también por SNMP .1082.500.10.2.3.10.1.2).", out=["eqd_bit", "distance_m"])
C("pon_power", "show", "show pon power", "show pon power {onu-rx|onu-tx|olt-rx|attenuation} gpon_onu-<idx>", E["onu"], s600="V",
  desc="Potencias ópticas: onu-rx, onu-tx (también por SNMP .1082.500.20.2.2.2.1.10/.14, escala raw*0.002-30), olt-rx (solo CLI) y attenuation (subida y bajada). 'olt-tx' no existe.",
  out=["onu_rx_dbm", "onu_tx_dbm", "olt_rx_dbm", "attenuation_db"])
C("onu_information", "show", "show pon onu information", "show pon onu information gpon_onu-<idx>", E["onu"], s600="V", desc="Resumen de la ONU: autenticación, SN reportado, ONU ID, tipo configurado/reportado y estado.")
C("remote_equip", "show", "show gpon remote-onu equip", "show gpon remote-onu equip gpon_onu-<idx>", E["onu"], s600="V", desc="Equipment ID, vendor y versiones reportadas por la ONU.")
C("remote_capability", "show", "show gpon remote-onu capability", "show gpon remote-onu capability gpon_onu-<idx>", E["onu"], s600="V", desc="Capacidades de la ONU (T-CONT, GEM, etc.).")
C("remote_interface", "show", "show gpon remote-onu interface", "show gpon remote-onu interface {eth|video|wifi|pon|pots|ces|video-ani} gpon_onu-<idx>", E["onu"], s600="V",
  desc="Interfaces de usuario de la ONU. 'wifi' devuelve 'No related information' si la ONU no tiene radio.")
C("remote_service", "show", "show gpon remote-onu service", "show gpon remote-onu service gpon_onu-<idx>", E["onu"], s600="V", desc="Servicios (nombre, GEM, VLAN) configurados en la ONU.")
C("remote_sysattr", "show", "show gpon remote-onu sys-attr", "show gpon remote-onu sys-attr gpon_onu-<idx>", E["onu"], s600="V", desc="CPU y memoria de la ONU y sus umbrales.")
C("remote_wifi_info", "show", "show gpon remote-onu wifi info", "show gpon remote-onu wifi info gpon_onu-<idx>", E["onu"], s600="V", desc="Estado de la radio WiFi (admin/operación, modo, ancho de banda).")
C("remote_ssid_info", "show", "show gpon remote-onu ssid info", "show gpon remote-onu ssid info gpon_onu-<idx>", E["onu"], s620="V", s600=None,
  desc="SSID de la ONU. Solo en C620 (en C600 da Invalid input).")
C("remote_mac", "show", "show gpon remote-onu mac", "show gpon remote-onu mac gpon_onu-<idx> {ethuni <if>|wifiuni <wifi_slot/port>}", E["onu"], s600="H", desc="MAC aprendidas en una UNI de la ONU.")
C("iface_stats", "show", "show interface", "show interface {xgei-<r/s/p>|gpon_olt-<pon>}", E["up"], s600="V", desc="Estadísticas y tasa de un puerto (también ifHC* por SNMP).")
C("alarm_current", "show", "show alarm current", "show alarm current", None, desc="Alarmas activas ('%GPON% GPON alarm link olt dgi (rack/shelf/slot/port/onu)'). También por SNMP en zxr10AlarmMIB (.3902.3.302).", s600="H")
C("alarm_history", "show", "show alarm history", "show alarm history", None, desc="Historial de alarmas.", s600="H")
C("alarm_other", "show", "show alarm", "show alarm {class <id>|level-change <code>|notification [code|flowid|end-time|earliest-first|latest-first]}", None, s620="H", s600="H", desc="Variantes de consulta de alarmas (solo ayuda).")
C("logfile_brief", "show", "show logfile brief", "show logfile brief", None, desc="Bitácora de comandos de la OLT (más reciente primero): bloques 'Time / User (usuario, vty, IP) / CMDLine' con cada comando y cada inicio de sesión Telnet. Cubre ~14 h. Equivalente CLI de la rama SNMP 3902.3.305.2.1.3.", s600="V",
  out=["time", "user", "cmdline"], notes="Verificado en la C620 y la C600 el 2026-10-09. Contiene el usuario de la sesión: no publicar salidas crudas.")
C("logging_alarm", "show", "show logging alarm", "show logging alarm", None, desc="Registro de alarmas y notificaciones (más reciente primero, ~48 min): 'An alarm <n>-(<m>) ID <id> level <l> occurred|cleared at <hh:mm:ss> <dd-mm-aaaa> sent by ZXAN PFU-1/1/0' + línea '%GPON% GPON alarm link olt <tipo> (rack 1 shelf 1 slot S port P onu N)' o '%PON% XPON alarm general event (… alarm <id> restore)'. Tipos vistos: losi(lobi), dgi (dying gasp).", s600="V",
  out=["alarm_number", "alarm_id", "level", "state", "timestamp", "alarm_type", "slot", "port", "onu"], notes="Verificado en la C620 y la C600 el 2026-10-09. 'level 2' = alarma, 'level 6' = notificación. Distinto de 'show alarm current/history'.")
C("onu_config_fail", "show", "show gpon onu config-fail", "show gpon onu config-fail gpon_onu-<idx>", E["onu"], s620="V", s600="H", desc="ONU con fallo de configuración ('No related information' si no hay).")
C("onu_offline", "show", "show pon onu offline information", "show pon onu offline information gpon_olt-<pon>", E["onu"], s620="H", s600="H", desc="Estadísticas de ONU fuera de línea (solo ayuda).")
# ------------------------------------------------------------------ ESCRITURAS
C("config_enter", "modify", "configure terminal", "configure terminal", None, "exec", desc="Entra a modo configuración (en la bitácora aparece como 'conf t'). 'end' vuelve a exec; 'exit' sube un nivel.", rollback="end", s600="V")
C("tcont_profile_create", "create", "profile tcont (perfil T-CONT)", "profile tcont <WORD> type {1 fixed <v>|2 assured <v>|3 assured <v> maximum <v>|4 maximum <v> [priority <1-4> [weight <n>]]|5 fixed <v> assured <v> maximum <v> [priority <1-4> [weight <n>]]}",
  None, "gpon", "gpon", desc="Crea un perfil T-CONT (subida). Velocidades 64-9953280 kbps. Los perfiles SMARTOLT-<vel>-UP son tipo 5 con fixed 64 assured 64 maximum <kbps>.",
  params=[P("name", "string", None, True, "SMARTOLT-30M-UP"), P("type", "integer", "1-5", True, "5"), P("fixed/assured/maximum", "integer", "64-9953280 kbps", True, "64")], rollback="no profile tcont <WORD> (modo gpon)", s600="H")
C("tcont_profile_delete", "delete", "no profile tcont", "no profile tcont <WORD>", None, "gpon", "gpon", s600="H", desc="Borra un perfil T-CONT.", params=[P("name", "string", None, True, "SMARTOLT-30M-UP")])
C("traffic_profile_create", "create", "traffic-profile (perfil de bajada)", "traffic-profile <NOMBRE> cir <kbps> cbs <KB> pir <kbps> pbs <KB>", None, "cfg", "conf t",
  desc="Crea un perfil de velocidad de bajada (no aparece en la ayuda '?'). SmartOLT redondea la velocidad (10220->10240) y usa CBS=PBS=CIR/80 en KB (10240->128; 52480->656; 104960->1312; verificado en 9 perfiles C620 y 5 C600); rango CBS/PBS aceptado 0-131072 KB.",
  params=[P("name", "string", None, True, "SMARTOLT-30M-DOWN"), P("cir", "integer", "kbps", True, "10240"), P("cbs", "integer", "KB", True, "128"), P("pir", "integer", "kbps", True, "10240"), P("pbs", "integer", "KB", True, "128")],
  rollback="no traffic-profile <NOMBRE>", s600="H", notes="Por SNMP la fila no se puede crear (RowStatus -> wrongValue).")
C("traffic_profile_delete", "delete", "no traffic-profile", "no traffic-profile <NOMBRE>", None, "cfg", "conf t", s600="H", desc="Borra un perfil de velocidad de bajada.", params=[P("name", "string", None, True, "SMARTOLT-30M-DOWN")])
C("onu_profile_traffic_create", "create", "onu profile traffic", "onu profile traffic <WORD> sir <kbps> pir <kbps> [cbs <n>] [colour-mode …] [meter-type …]", None, "gpon", "gpon", s600="H",
  desc="Crea un perfil de tráfico de ONU (usado por gemport/switchport traffic-limit). Por defecto CBS/PBS 0, colour-blind, no-marking.",
  params=[P("name", "string", None, True, "TKC-OP"), P("sir", "integer", "0-10000000 kbps", True, "1024"), P("pir", "integer", "0-10000000 kbps", True, "1024")], rollback="no onu profile traffic <WORD>")
C("onu_profile_traffic_delete", "delete", "no onu profile traffic", "no onu profile traffic <WORD>", None, "gpon", "gpon", s600="H", desc="Borra un perfil de tráfico de ONU.")
C("onu_type_create", "create", "onu-type", "onu-type <WORD> gpon [description <WORD>] [max-tcont <1-255>] [max-gemport <1-255>] [max-veip <0-255>] [max-iphost <0-127>] [max-ipv6-host <0-127>] [max-switch-perslot <1-255>] [max-flow-perswitch <1-255>] [service-ability N:1] [omci-send-mode {async|sync}] [mgc-cfg-mode {both|itu-t|zte}] [ex-omci {enable|disable}] [default-multicast-range {all-inclusive|none}] [location {enable|disable}]",
  E["onu"], "pon", "pon", desc="Crea un tipo de ONU. Los tipos nuevos nacen con max-switch-perslot/max-flow-perswitch=255. El tipo de una ONU ya creada no se puede cambiar (222366, tampoco a un tipo equivalente ni con la ONU nunca en línea; pide [yes/no] y falla): dar de alta la ONU con el tipo correcto.",
  rollback="no onu-type <WORD>", s600="H")
C("onu_type_if", "modify", "onu-type-if", "onu-type-if <tipo> {eth_0/<n>|pots_0/<n>|wifi_0/<n>|video_0/<n>}", E["onu"], "pon", "pon", s600="H",
  desc="Declara una interfaz de usuario en un tipo de ONU. La interfaz WiFi (wifi_0/1) debe existir en el tipo para poder configurar WiFi/SSID. El CATV se declara SOLO como 'rf_0/1' (tipos reales ZTE-F625/F628/F640, LATIC, PROFILE-DEFAULT; verificado creando tipos de prueba): 'video_0/1', 'video-ani_0/1' y 'catv_0/1' dan Parameter error (230263) aunque la ayuda genérica (type_slot/port) los da por válidos. Interfaces de un tipo: 'show onu-type-if <tipo>'.")
C("onu_type_delete", "delete", "no onu-type", "no onu-type <WORD>", E["onu"], "pon", "pon", s600="H", desc="Borra un tipo de ONU.")
C("onu_create", "create", "onu <N> type … sn …", "onu <1-256> type <TIPO> {sn|sn+pw|sn+hpw|sn+rid|sn+hrid|pw|hpw|rid|hrid|loid|loid+loidpw|loid+loidhpw|psk} <valor>", E["onu"], "if", "interface gpon_olt-<pon>", s600="L",
  desc="Autoriza una ONU en un puerto PON. El índice debe estar libre y en 1-128: la sintaxis admite 1-256 y la OLT acepta cualquier valor, pero solo registran las ONU de los índices 1-128 (medido: 128 registra; 129, 130, 192, 255, 256 y 250 no). Un SN ya autorizado en otro índice da 222320. Con el tipo correcto desde el alta.",
  params=[P("onu-id", "integer", "1-256", True, "3"), P("type", "string", None, True, "LATIC"), P("sn", "string", None, True, "DF306B41EDB0")], rollback="no onu <N>", prereq=[E["pon"]])
C("onu_delete", "delete", "no onu", "no onu <1-256>", E["onu"], "if", "interface gpon_olt-<pon>", s600="L", desc="Elimina la ONU y todo su aprovisionamiento; la ONU física vuelve a la lista de espera.")
C("onu_name", "modify", "name / description (ONU)", "name <WORD> | description <WORD>", E["onu"], "if", "interface gpon_onu-<idx>", s600="L", desc="Nombre y descripción de la ONU (se leen enmascarados con la cuenta de solo lectura).")
C("onu_vport_mode", "modify", "vport-mode", "vport-mode {manual|gemport}", E["onu"], "if", "interface gpon_onu-<idx>", s600="L", desc="Modo de vport (la plantilla real usa manual).")
C("onu_tcont", "create", "tcont (ONU)", "tcont <1-255> {profile <WORD>|name <WORD> profile <WORD>|allocid <256-4095>|gap {default|mode0|mode1|mode2|mode3}}", E["onu"], "if", "interface gpon_onu-<idx>", s600="L",
  desc="Asocia un T-CONT a un perfil. Para varios parámetros 'name' exige 'profile' a continuación.", rollback="no tcont <1-255>", params=[P("tcont-id", "integer", "1-255", True, "1"), P("profile", "string", None, True, "SMARTOLT_DEFAULT_TCONT_GPON")])
C("onu_gemport", "create", "gemport (ONU)", "gemport <1-255> name <WORD> tcont <1-255> [queue <0-7>]", E["gem"], "if", "interface gpon_onu-<idx>", s600="L", rollback="no gemport <1-255>",
  desc="Crea un GEM port. 'gemport <n> portid <129-4095> tcont <m>' da 'Not support this operation' (222370) porque portid solo se admite con 'resource mode2' en el puerto PON (por defecto mode1: la OLT asigna Port-ID y Alloc-ID automáticamente y la configuración no los muestra). Con mode2 (verificado en un puerto vacío) el valor 300 se rechaza igualmente (230405 Port-id / 230404 Alloc-id out of range): los asignados automáticamente empiezan en 1024; en mode2 la configuración lista 'tcont 1 allocid 1024 profile <P>' y 'gemport 1 name <n> portid 1024 tcont 1'. No es necesario para aprovisionar.", prereq=[E["onu"]])
C("onu_vport", "create", "vport / vport-map", "vport <1-128> map-type {vlan|1:1|cos|cos+vlan} ; vport-map <vport> <gem> vlan {<1-4094>|untag} [cos <0-7>]", E["sp"], "if", "interface gpon_onu-<idx>", s600="L",
  rollback="no vport <1-128> (limpia el vport y sus mapeos) o 'no vport-map <vport> <gem> vlan <V>' (verificado: hay que repetir el vlan del alta; sin él da 222386)", desc="Crea el vport y mapea un GEM a una VLAN. Un GEM ya mapeado a otro vport da 'Port-id has been used'. Borrar un mapeo concreto: 'no vport-map <vport> <gem> vlan <V>' (con cos o sin el vlan da 222386).")
C("onu_admin", "disable", "admin disable", "admin disable", E["onu"], "if", "interface gpon_onu-<idx>", s620="V", s600="H", desc="Deshabilita administrativamente la ONU.", rollback="admin enable")
C("onu_admin_enable", "enable", "admin enable", "admin enable", E["onu"], "if", "interface gpon_onu-<idx>", s620="V", s600="H", desc="Habilita administrativamente la ONU.")
C("onu_splitter", "modify", "splitter (ONU)", "splitter <N>-<N>-<N>", E["onu"], "if", "interface gpon_onu-<idx>", s620="V", s600="H",
  desc="Ubicación de la ONU en el árbol óptico: niveles NUMÉRICOS separados por guion, p. ej. '1-2-3' (máx. 32 caracteres). Texto como TKCSPL o L1-L2-L3 da 230263. No depende de 'location' del tipo (esa opción no se puede cambiar con el tipo en uso: 230296). Se guarda literal (visible en 'show gpon onu detail-info' como 'Splitter:' y en la config). Borrado: 'no splitter'.")
C("onu_type_if_show", "show", "show onu-type-if", "show onu-type-if <tipo>", E["onu"], s620="V", s600="H", desc="Interfaces de usuario declaradas en un tipo de ONU (eth_0/n, pots_0/n, rf_0/1, wifi_0/n, e1, xdsl).")
C("onu_misc", "modify", "parámetros de ONU", "sn-bind {enable|disable} {sn|both|update-sn} | fec {auto|default|enable|disable} | authpass-control <0-10> | auto-replace {enable|disable} | auth-id {sn|pw|loid|rid|hpw|hrid|psk} <v>", E["onu"], "if", "interface gpon_onu-<idx>", s600="H",
  desc="Ajustes de autenticación/FEC/reemplazo automático de la ONU (ejecutados con éxito en la C620 con la ONU de prueba).")
C("onu_reset", "reset", "reset (ONU)", "reset", E["onu"], "if", "interface gpon_onu-<idx>", s620="V", s600="H", desc="Reinicia la ONU (sin confirmación).")
C("onu_deregister", "reset", "deregister", "deregister", E["onu"], "if", "interface gpon_onu-<idx>", s620="V", s600="H", desc="Desregistra la ONU (sin confirmación).")
C("onu_reboot", "reset", "reboot (pon-onu-mng)", "reboot", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s620="V", s600="H",
  desc="Reinicia la ONU: pide 'Confirm to reboot? [yes/no]:'; 'no' cancela; 'yes' es silencioso. En una ONU en línea: working -> LOS (~30 s) -> syncMib -> working, corte de ~45-55 s.",
  notes="Verificado en una ONU en línea de la C620 (2026-10-02).")
C("mng_service", "create", "service (pon-onu-mng)", "service <nombre> gemport <1-255> {vlan <V>|untag|cos <0-7>|ethuni <if>|veip <1-255>}", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s600="L",
  desc="Servicio de la ONU: GEM y VLAN (plantilla real: 'service vlan101 gemport 1 vlan 101' + 'veip 1'). Borrado: 'no service <nombre>'.", rollback="no service <nombre>")
C("mng_veip", "modify", "veip", "veip <1-255> [state {lock|unlock}] [port <1-65535> {tcp|udp}] [inter-domain <WORD>]", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s600="L", desc="Interfaz VEIP de la ONU.")
C("mng_vlan_port", "modify", "vlan port", "vlan port <if> mode {hybrid|tag|transparent|trunk} [vlan <1-4094>] [pri …]", E["vlan"], "if", "pon-onu-mng gpon_onu-<idx>", s600="H",
  desc="Modo VLAN de un puerto de la ONU. La VLAN va dentro del mismo comando ('vlan port eth_0/1 mode tag vlan 101'); 'vlan port eth_0/1 vlan 101' suelto da 'Port mode error'.")
C("mng_wan_ip", "modify", "wan-ip", "wan-ip <1-255> ipv4 mode {dhcp [id <WORD>|vlan-profile <WORD>]|inner|pppoe|static} ; wan-ip <1-255> ipv4 ping-response {enable|disable} traceroute-response {enable|disable}", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s600="H",
  desc="WAN IP de la ONU. Primero 'mode …' y después 'ping-response …' (sin el WAN IP previo da 'This wan-ip does not exist'). Se guarda como 'wan-ip ipv4 mode dhcp vlan-profile <P> host 1'.")
C("mng_security", "modify", "security-mgmt", "security-mgmt <1-255> state {enable [mode {discard|forward}] [ingress-type {iphost|lan|wan}] [protocol {ftp|https|snmp|ssh|telnet|tr069|web}] [start-src-ip <A.B.C.D>]|disable}", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s600="H", desc="Gestión remota segura de la ONU.")
C("mng_dhcp_ip", "modify", "dhcp-ip", "dhcp-ip ethuni <if> {from-onu|from-internet|forbidden|no-ctrl}", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s600="H", desc="Control de DHCP en una UNI Ethernet.")
C("mng_eth", "modify", "interface eth", "interface eth <if> {state {lock|unlock}|speed {auto|full-10|full-100|full-1000|full-10000|half-10|half-100}|mtu <64-12288>|pause-time <0-65535>|l2l3 {l2|l3|either}|loop {enable|disable}|pppoe-filter {enable|disable}|power-control {enable|disable}|arc {enable arc-interval <n>|disable}|type <0-255>|wiring {dce|dte}}",
  E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s600="H", desc="Puerto Ethernet de la ONU. Los valores por defecto se aceptan pero no se guardan en la configuración.")
C("mng_video", "modify", "interface video / video-ani", "interface video video_0/<n> {state {lock|unlock}|arc|power-control} ; interface video-ani {state {lock|unlock}|optical-thresh lower <dBm> upper <dBm>|agc-mode|arc|pilot-frequency}", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s600="L",
  desc="CATV. 'video_0/n' exige que el tipo de la ONU lo declare. En ONU CATV reales se ve 'interface video video_0/1 state lock' y 'interface video-ani state lock'.")
C("mng_wifi", "modify", "WiFi (pon-onu-mng)", "interface wifi wifi_0/<n> {state {lock|unlock}|arc {enable arc-interval <n>|disable}} ; ssid ctrl wifi_0/<n> {name <WORD>|hide {enable|disable}|max-users <1-32>|user-isolation {enable|disable}} ; wifi enable [channel <0-13>] [qos-type {disable|ssid|wmm}] [radio-measure …] [ssid-isolate …] [tx-power-percent {20|40|60|80|100}] [tx-rate …] [work-mode {802.11b|802.11g|802.11n|802.11b-11g|802.11b-11g-11n}] ; wifi 5g {enable|disable} ; ssid auth {wep|wpa}",
  E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s620="V", s600=None, desc="WiFi de la ONU. Solo en C620. Requiere que la ONU se haya dado de alta con un tipo que tenga wifi_0/1 (si no: 'UNI does not exist'). Orden obligatorio: work-mode, domain, channel (verificado: 'wifi enable channel 6 work-mode … domain …' da Invalid input). 'domain bra' solo con 'work-mode 802.11b' (sin él: 230263); el resto de países (usa esp chn ger fra uk…) valen con cualquier work-mode; canal 0-11 en CAN/USA. Verificado: 'wifi enable work-mode 802.11b domain bra channel 6 tx-power-percent 80', 'wifi enable domain usa channel 6', 'wifi 5g enable domain chn channel 36'. El dominio por defecto (chn) no se guarda en la configuración.")
C("mng_traffic_limit", "modify", "traffic-limit (ONU)", "gemport traffic-limit <1-255> {upstream <perfil>|downstream <perfil>} ; switchport ethuni <if> traffic-limit {in|out} <perfil>", E["onu"], "if", "pon-onu-mng gpon_onu-<idx>", s620="V", s600="H",
  desc="Limita la tasa con un perfil de 'onu profile traffic' (NO con los SMARTOLT-* de qos traffic-profile). Se guarda como 'gemport traffic-limit 1 downstream <P> upstream <P>'.", prereq=[])
C("sp_create", "create", "service-port", "service-port <1-128> user-vlan {<1-4094>|untagged} vlan <1-4094> [ingress <perfil_subida> [egress <perfil_bajada>]] [user-priority|user-etype|user-svlan …] [car-threshold …] [new-cos|svlan …]",
  E["sp"], "if", "interface vport-<pon>.<n>:<v>", s600="L", desc="Service-port de la ONU con los perfiles de velocidad (ingress = perfil de subida, egress = traffic-profile de bajada).", rollback="no service-port <1-128>",
  params=[P("id", "integer", "1-128", True, "1"), P("user-vlan", "integer", "1-4094", True, "101"), P("ingress", "string", None, False, "SMARTOLT-50M-UP"), P("egress", "string", None, False, "SMARTOLT-50M-DOWN")], prereq=[E["onu"]])
C("sp_delete", "delete", "no service-port", "no service-port <1-128>", E["sp"], "if", "interface vport-<pon>.<n>:<v>", s600="L", desc="Elimina el service-port.")
C("pon_description", "modify", "description / blacklist (puerto PON)", "description <LINE> | no description | blacklist sn <SN> | no blacklist sn <SN>", E["pon"], "if", "interface gpon_olt-<pon>", s600="H",
  desc="Descripción del puerto y lista negra de ONU. El SN de la lista negra necesita formato válido (4 letras de fabricante + 8 caracteres); 'TKCBL0000001' dio error.")
C("save", "modify", "write", "write", None, "exec", desc="Guarda la configuración en el arranque (solo en modo exec, tras 'end'; en config da Invalid input). Responde '......[OK].'.", s620="V", s600="H",
  notes="Ejecutado tras verificar que la configuración era idéntica a la inicial.")

PROFILE_ENT = {"tcont_profile_list": "tcont_profile", "tcont_profile_create": "tcont_profile", "tcont_profile_delete": "tcont_profile",
               "traffic_profile_list": "traffic_profile", "traffic_profile_create": "traffic_profile", "traffic_profile_delete": "traffic_profile",
               "onu_profile_traffic": "onu_traffic_profile", "onu_profile_traffic_create": "onu_traffic_profile",
               "onu_profile_traffic_delete": "onu_traffic_profile"}
RELATED = {  # slug -> slugs relacionados (alta/baja/lectura/rollback)
    "onu_create": ["onu_delete", "onu_uncfg", "onu_state", "rc_olt", "onu_detail"], "onu_delete": ["onu_create", "rc_olt"],
    "onu_tcont": ["tcont_profile_create", "tcont_profile_list", "onu_gemport"], "onu_gemport": ["onu_tcont", "onu_vport", "rc_onu"],
    "onu_vport": ["onu_gemport", "sp_create", "rc_onu"], "sp_create": ["sp_delete", "service_port", "rc_vport", "traffic_profile_create"],
    "sp_delete": ["sp_create", "service_port"], "tcont_profile_create": ["tcont_profile_delete", "tcont_profile_list"],
    "tcont_profile_delete": ["tcont_profile_create", "tcont_profile_list"], "traffic_profile_create": ["traffic_profile_delete", "traffic_profile_list"],
    "traffic_profile_delete": ["traffic_profile_create", "traffic_profile_list"], "onu_profile_traffic_create": ["onu_profile_traffic_delete", "onu_profile_traffic"],
    "onu_profile_traffic_delete": ["onu_profile_traffic_create", "onu_profile_traffic"], "onu_type_create": ["onu_type_delete", "onu_type_if", "onu_type_list"],
    "onu_type_delete": ["onu_type_create", "onu_type_list"], "onu_type_if": ["onu_type_create", "onu_type_if_show"],
    "onu_admin": ["onu_admin_enable", "onu_state"], "onu_admin_enable": ["onu_admin", "onu_state"], "onu_reboot": ["onu_reset", "onu_state"],
    "onu_reset": ["onu_reboot", "onu_deregister"], "onu_deregister": ["onu_reset", "onu_state"], "mng_service": ["mng_veip", "mng_vlan_port", "onu_gemport"],
    "mng_wan_ip": ["mng_service", "remote_service"], "mng_wifi": ["remote_wifi_info", "remote_ssid_info", "onu_type_if"],
    "onu_state": ["onu_baseinfo", "onu_detail", "onu_uncfg"], "onu_detail": ["onu_state", "onu_distance", "pon_power"],
    "onu_uncfg": ["onu_create", "onu_by_sn"], "vlan_summary": ["vlan_detail"], "vlan_detail": ["vlan_summary", "onu_profile_vlan"],
    "mng_traffic_limit": ["onu_profile_traffic_create", "onu_profile_traffic"], "save": ["config_enter"]}
ROLLBACK = {"onu_splitter": "no splitter"}      # único 'no <cmd>' verificado entre los modify sin rollback declarado
CTX_PREREQ = (("interface gpon_onu", "onu"), ("pon-onu-mng", "onu"), ("interface gpon_olt", "pon"), ("interface vport", "onu"))


O = "oid.zte.gpon."
OUTMAP = {   # slug -> {campo de salida: id de OID equivalente por SNMP}; los demás campos son solo CLI
    "onu_state": {"phase_state": O + "onu.onu_status"},
    "onu_baseinfo": {"type": O + "onu.onu_type_name", "serial_number": O + "onu.onu_serial_number", "state": O + "onu.onu_status"},
    "onu_detail": {"phase_state": O + "onu.onu_status", "serial_number": O + "onu.onu_serial_number", "onu_distance": O + "onu.onu_distance",
                   "authpass_time": O + "onu.onu_last_auth_time", "offline_time": O + "onu.onu_last_offline_time", "offline_cause": O + "onu.onu_last_offline_cause"},
    "onu_distance": {"distance_m": O + "onu.onu_distance"},
    "pon_power": {"onu_rx_dbm": O + "onu.onu_rx_power", "onu_tx_dbm": O + "onu.onu_tx_power"},
    "traffic_profile_list": {"cir_kbps": O + "onu.traffic_profile_cir", "cbs_kbytes": O + "onu.traffic_profile_cbs",
                             "pir_kbps": O + "onu.traffic_profile_pir", "pbs_kbytes": O + "onu.traffic_profile_pbs"},
    "onu_uncfg": {"serial_number": O + "onu.uncfg_onu_serial", "model": O + "onu.uncfg_onu_type", "pw": O + "onu.uncfg_onu_password",
                  "first_find_time": O + "onu.uncfg_onu_detected", "last_find_time": O + "onu.uncfg_onu_last_found"},
    "service_port": {"user_vlan": O + "service_port.srv_port_user_vid", "vlan": O + "service_port.srv_port_c_vid",
                     "ingress_profile": O + "onu.service_port_ingress_profile", "egress_profile": O + "onu.service_port_egress_profile"},
}


BEHAVIOR = json.loads((ROOT / "docs/validation/commands/zte_c6xx_cli_behavior.json").read_text(encoding="utf-8"))
ERR_INFO = {224040, 230285, 90}                    # lecturas vacías y 'no' sin nada que borrar: no son fallos
ERRORS = {  # slug -> códigos que ese comando produce de forma verificada
    "onu_profile_traffic": [224040], "onu_config_fail": [224040], "remote_wifi_info": [224040, 230285],
    "remote_ssid_info": [224040, 230285], "remote_interface": [224040, 230285], "onu_state": [230285],
    "onu_create": [222320, 222366], "onu_tcont": [222306, 140305], "onu_gemport": [222357, 222370, 230404, 230405],
    "onu_vport": [222357, 222386], "mng_vlan_port": [223983], "mng_wan_ip": [224011], "mng_wifi": [223845, 230263, 140305],
    "mng_eth": [223845], "mng_video": [223845, 230263], "mng_traffic_limit": [223876, 223981], "sp_create": [241874],
    "onu_type_if": [223845, 230263, 230296], "onu_type_create": [230296], "onu_splitter": [230263], "pon_description": [141000],
    "onu_reboot": [99], "onu_reset": [99], "onu_delete": [90], "sp_delete": [90], "tcont_profile_delete": [90],
    "traffic_profile_delete": [90], "onu_profile_traffic_delete": [90], "onu_type_delete": [90]}


def errors_for(slug):
    by = {e["code"]: e for e in BEHAVIOR["errors"]}
    return [{"code": c, "meaning": by[c]["meaning"], "severity": "info" if c in ERR_INFO else "error", "retry": bool(by[c].get("retry"))}
            for c in ERRORS.get(slug, []) if c in by]


def parse_params(syntax):
    """Parámetros a partir de la sintaxis: <a-b> o <nombre> y {a|b}; los de [..] son opcionales."""
    out, seen, depth = [], set(), 0
    for m in re.finditer(r"\[|\]|<([^<>]+)>|\{([^{}]+)\}", syntax):
        t = m.group(0)
        if t == "[":
            depth += 1; continue
        if t == "]":
            depth = max(0, depth - 1); continue
        if m.group(1):
            inner = m.group(1)
            if re.fullmatch(r"\d+-\d+", inner):
                before = syntax[:m.start()].split()
                name, typ, rng = (before[-1] if before else "valor"), "integer", inner
            else:
                name, typ, rng = re.sub(r"[^\w-]+", "_", inner).strip("_"), "string", None
        else:
            if "<" in m.group(2) or "{" in m.group(2):
                continue
            before = syntax[:m.start()].split()
            name, typ, rng = (before[-1] if before else "opcion"), "enum", m.group(2)
        name = re.sub(r"[^\w-]+", "_", name).strip("_") or "valor"
        if name in seen:
            continue
        seen.add(name)
        out.append(P(name, typ, rng, depth == 0))
    return out


def _cid(c):
    return f"command.zte.gpon.{c['ent'].split('.')[-1] if c['ent'] else 'global'}.{c['cat']}.{c['slug']}"


def build():
    by_slug = {c["slug"]: c for c in CMDS}
    IDS = {c["slug"]: _cid(c) for c in CMDS}
    by_family = {}
    for fam in ("ZXA10 C620", "ZXA10 C600"):
        by_family[fam] = []
    for c in CMDS:
        for fam, code in c["s"].items():
            if code is None:
                continue
            status, conf, ev = STATUS[code]
            fid = f"command.zte.gpon.{(c['ent'] or 'entity.zte.gpon.global').split('.')[-1] if c['ent'] else 'global'}.{c['cat']}.{c['slug']}"
            om = {k: v for k, v in OUTMAP.get(c["slug"], {}).items() if not (c["slug"] == "onu_uncfg" and fam != "ZXA10 C620")}
            ent = c["ent"] or (f"entity.zte.gpon.logical.{PROFILE_ENT[c['slug']]}" if c["slug"] in PROFILE_ENT else None)
            params = c["params"] or parse_params(c["syn"])
            prereq = c["prereq"] or [E[k] for pre, k in CTX_PREREQ if (c["ctx"] or "").startswith(pre)][:1]
            rollback = c["rollback"] or ROLLBACK.get(c["slug"])
            related = [IDS[x] for x in RELATED.get(c["slug"], []) if x in IDS and by_slug[x]["s"][fam]]
            by_family[fam].append({
                "id": fid, "canonical_name": c["name"], "vendor": "ZTE", "family": fam, "firmware": ["1.2.2"], "technology": "gpon",
                "category": c["cat"], "cli_mode": MODE[c["mode"]], "cli_context": c["ctx"], "entity_ref": ent, "description": c["desc"],
                "syntax": c["syn"], "parameters": params, "output_fields": [{"name": o, "type": "string", "unit": None, "oid_ref": om.get(o),
                                  "oid_status": "mapped" if om.get(o) else "not_mapped"} for o in c["out"]],
                "prerequisites": prereq, "related_commands": related, "rollback": rollback, "errors": errors_for(c["slug"]), "notes": c["notes"],
                "evidence": ev, "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": conf}],
                "confidence": {"extraction": conf, "correlation": 0.0, "overall": conf}, "status": status, "conflicts": []})
    doc = {"meta": {"doc_type": "commands", "vendor": "ZTE", "families": list(by_family), "replace_seed": True,
                    "source": "reports/cli_verification_c620_c600_2026-10-02.md", "generated_by": "scripts/build_c620_command_catalog.py"},
           "commands": by_family}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    for fam, lst in by_family.items():
        from collections import Counter
        print(fam, len(lst), dict(Counter(x["status"] for x in lst)))
    ids = [x["id"] for lst in by_family.values() for x in lst if x["family"] == "ZXA10 C620"]
    assert len(ids) == len(set(ids)), "ids duplicados"


if __name__ == "__main__":
    build()
