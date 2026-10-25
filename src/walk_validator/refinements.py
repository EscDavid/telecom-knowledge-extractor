"""Refinamientos posteriores a la validación del catálogo ZTE C6xx (revisión 2026-10-02).

Se ejecutan sobre el catálogo ya escrito (`catalog/<vendor>/<familia>/catalog-<v>/`) y son ADITIVOS/CORRECTIVOS:
no cambian ningún `id` de OID, comando, entidad ni alarma existente, ni los nombres de atributo ni `scale_formula`.

  Correcciones: escala de tensión óptica, `scale` espurio, firmware coherente con los comandos, nombre de hojas sin nombre MIB,
                `onu_id_append` en escalares/IF-MIB, unidad y centinela de rx/tx de ONU, manifest.
  Mejoras:      OID IF-MIB de uplink_port, atributos de entidad, entidades de perfiles, alarmas de ONU por causa de baja,
                relaciones con orden de creación verificado.
"""
from __future__ import annotations

import bisect
import json
import logging
import re
from pathlib import Path

from ..profiles import default_registry

log = logging.getLogger(__name__)

C6_FAMILIES = {"ZXA10 C620", "ZXA10 C600"}
CLASSIC_FAMILIES = {"ZXA10 C300", "ZXA10 C320"}       # refinamiento 1.2.0 (2026-10): subconjunto de los de C6, sin CLI propia verificada
FAMILIES = C6_FAMILIES | CLASSIC_FAMILIES
FIRMWARE = ["1.2.2"]
UNIT_FIX = {"Volts": "V", "Degrees": "°C", "Centigrade": "°C"}
NO_SCALE_IDS = {"oid.zte.gpon.pon_port.pon_rx_power_detect_period"}       # segundos: 900 s, no 9 s
SENTINEL_IDS = {"oid.zte.gpon.onu.onu_rx_power", "oid.zte.gpon.onu.onu_tx_power"}
CLASSIC_SENTINEL_IDS = {"oid.zte.gpon.onu.onu_rx_power_type", "oid.zte.gpon.onu.onu_tx_power_type"}     # rama 1012.3.50.12.1.1.{10,14}
PII_IDS = {"oid.zte.gpon.onu.onu_name", "oid.zte.gpon.onu.onu_description"}
PII_TXT = " DATO PERSONAL del abonado (nombre/dirección): la CLI lo enmascara; no leer ni almacenar sin base legal."
ONU_STATUS_ID = "oid.zte.gpon.onu.onu_status"
STATUS_NOT_OBSERVED = {"1": "Logging", "3": "Synchronization", "6": "AuthFailed"}     # enum de clásicas; no vistos en C6
STATUS_NOTE = (" Rama 1082.500.10.2.3.8.1.4 (C6). LOS(2) incluye las ONU deshabilitadas por administración "
               "(causa de última baja 10 = DeactiveSucc): no equivale a corte de fibra.")
SERIAL_FORMAT = {"oid.zte.gpon.onu.onu_serial_number": "ascii-pon-prefixed", "oid.zte.gpon.onu.uncfg_onu_serial": "binary-8"}
NOT_EXPOSED_ATTRS = {"onu_ip_address": "sin OID en la rama 1082.500 de C6; no existe fuente SNMP"}
CLASSIC_SERIAL_FORMAT = {"oid.zte.gpon.onu.onu_serial_number_type": "binary-8", "oid.zte.gpon.onu.uncfg_onu_serial": "binary-8"}
CLASSIC_STATUS_ID = "oid.zte.gpon.onu.onu_status_type"
CLASSIC_NOT_EXPOSED = {
    "onu_name": "sin filas en la rama 1082.500.10.2.3 de la familia; el nombre vive en la OLT pero no se expone por SNMP: traerlo de la BD/SmartOLT",
    "onu_description": "ídem onu_name",
    "onu_ip_address": "sin filas en 1012.3.50.16; no existe fuente SNMP de la IP de gestión en esta familia",
}
CLASSIC_DOWNGRADE_TXT = (" [1.2.0] La fuente community la lista, pero la familia no tiene NINGUNA fila en su walk completo "
                         "(ni en los diagnósticos): no se puede leer por SNMP en este equipo. Se usa el gemelo de la rama 1012.3.50 si existe.")
CLASSIC_CMD_NOTE = ("Sintaxis tomada del manual del C320 sin ejecutar en hardware (la CLI real de clásicas usa `gpon-onu_1/1/1:1`, "
                    "`gpon-olt_1/1/1` y `no onu N`). No usar para escribir sin verificarla antes.")
# Ramas cuyo ÍNDICE es texto sensible (comunidades SNMP, cuentas y peticiones web de la OLT): sus hallazgos `ascii_index`
# llevan el valor decodificado y el propio OID lo codifica en decimal. No deben llegar a `tkc_results`.
SENSITIVE_PREFIXES = default_registry().get("ZTE").sensitive_prefixes   # fuente única: config/vendors.yaml
SENTINEL_TXT = " 65535 = sin señal (ONU apagada/OffLine); fórmula raw*0.002-30 en dBm."
UPLINK_PREFIXES = ("1.3.6.1.2.1.2.2.1.", "1.3.6.1.2.1.31.1.1.1.")
UPLINK_ENTITY = "entity.zte.gpon.port.uplink_port"
UPLINK_IFINDEX = "285279233"                                              # xgei-1/4/1 (ifType 6)

NEW_ENTITIES = {
    "tcont_profile": ("Perfil T-CONT", "Perfil de ancho de banda de subida (T-CONT) reutilizable por varias ONU (profile tcont).",
                      ["name", "type", "fixed_bw", "assured_bw", "max_bw"]),
    "traffic_profile": ("Perfil de velocidad de bajada", "Perfil qos traffic-profile (CIR/CBS/PIR/PBS) usado como egress del service-port; también legible por SNMP.",
                        ["name", "cir", "cbs", "pir", "pbs", "type"]),
    "onu_traffic_profile": ("Perfil de tráfico de ONU", "Perfil 'onu profile traffic' (SIR/PIR/CBS/PBS) para gemport/switchport traffic-limit.",
                            ["name", "sir", "pir", "cbs", "pbs"]),
}
# valores permitidos por los ENUM de ispm_tkc.tkc_alarms (severity: warning|major|critical)
ALARM_TYPE = {"LOS": "optical", "LOSi": "optical", "DyingGasp": "power", "DeactiveSucc": "protocol"}
OFFLINE_CAUSES = {          # onu_last_offline_cause (verificado: valores observados en el walk)
    "2": ("LOS", "major", "Pérdida de señal óptica de la ONU (LOS): fibra cortada/atenuada, ONU apagada o puerto PON caído."),
    "3": ("LOSi", "major", "Pérdida de señal de la ONU detectada por el OLT (LOSi): ONU no responde en el rango asignado."),
    "9": ("DyingGasp", "warning", "La ONU avisó de apagón (dying gasp): corte eléctrico del cliente o equipo apagado."),
    "10": ("DeactiveSucc", "warning", "Desactivación ordenada por el OLT (por ejemplo reinicio o baja por gestión)."),
}


def _rd(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _wr(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _walk_text(walks_dir: Path, family: str) -> str:
    stem = family.split()[-1]
    files = [f for f in sorted(walks_dir.glob(f"ZTE_{stem}*.txt")) if "bak" not in f.name]
    if family in CLASSIC_FAMILIES:      # los diagnósticos dirigidos (uncfg, ifTable…) también cuentan como filas del equipo
        files += sorted((walks_dir / "diagnostics").glob(f"ZTE_{stem}*.txt"))
    return "".join(f.read_text(errors="ignore") for f in files)


def _walk_index(text: str) -> list[tuple]:
    rx = re.compile(r"^(?:\.|iso\.)?(1\.3\.6\.1\.4\.1\.3902(?:\.\d+)+) = ", re.M)
    return sorted(tuple(int(x) for x in m.group(1).split(".")) for m in rx.finditer(text))


def _has(idx: list[tuple], t: tuple) -> bool:
    i = bisect.bisect_left(idx, t)
    return i < len(idx) and idx[i][:len(t)] == t


def _annotate_documented(o: dict, idx: list[tuple], confirmed: dict | None = None, fw_label: str = "1.2.2") -> bool:
    """Explica por qué un OID `documented` no aparece en el walk (no cambia su estado)."""
    t = tuple(int(x) for x in o["oid"].split("."))
    node = (o.get("syntax") or "").startswith("SEQUENCE") or o.get("access") == "not-accessible"
    if o.get("access") == "accessible-for-notify":
        cat, why = "notification", "objeto de notificación (trap); no se lee con walk"
    elif _has(idx, t[:-1]) or _has(idx, t[:-2]):
        if node:
            cat, why = "structure_node", "nodo estructural de una tabla que sí tiene filas"
        else:
            cat, why = "absent_in_populated_table", "su tabla tiene filas pero esta columna no aparece: posiblemente no soportada en el firmware " + fw_label
    elif node:
        cat, why = "structure_node", "nodo estructural de una tabla sin filas en el equipo"
    else:
        cat, why = "table_empty", "tabla sin filas en el walk (sin configurar en el equipo); objeto de configuración, no verificable por lectura"
    if cat == "absent_in_populated_table" and (confirmed or {}).get(o["oid"]) == "NO EXPUESTA":
        cat, why = "not_exposed", "confirmado por GETNEXT: el equipo (firmware " + fw_label + ") no expone esta columna aunque su tabla tenga filas"
    o["pending_validation"] = {"category": cat, "reason": why, "walk_instances": 0}
    return cat in ("absent_in_populated_table", "not_exposed")


def _fix_scale_unit(o: dict, stats: dict) -> None:
    m = re.match(r"^\s*(0?\.\d+)\s*([A-Za-z°]+)\s*$", o.get("unit") or "")
    if not m:
        return
    factor, unit = float(m.group(1)), UNIT_FIX.get(m.group(2), m.group(2))
    if o.get("scale") != factor:
        stats["scale_fixed"] += 1
    o["scale"], o["unit"] = factor, unit
    if isinstance(o.get("empirical"), dict) and o["empirical"].get("scale_confirmed") is not None:
        o["empirical"]["scale_confirmed"] = factor


CLASSIC_EVIDENCE = ("ejecutado por el importador (network-api, verificar-olts.ts) en 5 OLT clásicas y registrado en "
                    "reports/hallazgos-cli-snmp-zte-2026-10-09.md; TKC no lo ejecutó")
CLASSIC_OBSERVED = {      # id -> (syntax, descripción); lecturas confirmadas por el importador, sintaxis de clásicas
    "command.zte.gpon.onu.show.uncfg": ("show gpon onu uncfg", "ONU sin autorizar (clásicas; en C6 es `show pon onu uncfg`)."),
    "command.zte.gpon.onu.show.state": ("show gpon onu state gpon-olt_{pon}",
                                        "Fase de las ONU de un puerto PON (clásicas); sin argumento lista todas."),
}
CLASSIC_NEW = {           # lecturas que no estaban en la semilla
    "command.zte.gpon.global.show.version": ("show version", "Versión de software de la OLT (clásicas; en C6 es `show software 1`)."),
}


def _classic_commands(target: Path, stats: dict) -> None:
    """La semilla trae 18 comandos del manual del C320 marcados `verified` con confianza 0,4 y sin ejecutarse nunca
    en hardware. Se degradan a `documented` y se marcan las lecturas que el importador sí confirmó en las 5 OLT."""
    cdir = target / "commands"
    for f in sorted(cdir.glob("*/*.json")):
        c = _rd(f)
        if c["id"] in CLASSIC_OBSERVED:
            syn, desc = CLASSIC_OBSERVED[c["id"]]
            c.update({"syntax": syn, "description": desc, "status": "observed", "evidence": CLASSIC_EVIDENCE})
            c["sources"] = [{"doc_type": "hardware_verification", "pages": None, "confidence": 0.8}]
            c["confidence"] = {"extraction": 0.8, "correlation": 0.0, "overall": 0.8}
        elif c.get("status") == "verified" and all(x.get("doc_type") == "command_reference" for x in c.get("sources", [])):
            c["status"] = "documented"
            c["confidence"] = {**c.get("confidence", {}), "overall": 0.4}
            if CLASSIC_CMD_NOTE not in (c.get("description") or ""):
                c["description"] = (c.get("description") or "").rstrip() + " " + CLASSIC_CMD_NOTE
        else:
            continue
        _wr(f, c); stats["commands"] += 1
    ref = next(iter(sorted(cdir.glob("show/*.json"))), None)
    for cid, (syn, desc) in CLASSIC_NEW.items():
        p = cdir / "show" / f"{cid.split('.')[-1]}.json"
        if p.exists() or ref is None:
            continue
        c = _rd(ref)
        c.update({"id": cid, "canonical_name": syn, "category": "show", "cli_mode": "privileged_exec", "entity_ref": None,
                  "description": desc, "syntax": syn, "parameters": [], "output_fields": [], "prerequisites": [],
                  "related_commands": [], "status": "observed", "evidence": CLASSIC_EVIDENCE, "conflicts": [],
                  "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": 0.8}],
                  "confidence": {"extraction": 0.8, "correlation": 0.0, "overall": 0.8}})
        _wr(p, c); stats["commands"] += 1


def refine_catalog(target: Path, family: str, walks_dir: Path | None = None) -> dict:
    if family not in FAMILIES:
        return {}
    classic = family in CLASSIC_FAMILIES
    fw = None if classic else list(FIRMWARE)        # clásicas: el firmware del grupo (2.0/2.1) no se toca
    fw_label = "2.0/2.1" if classic else FIRMWARE[0]
    sent_ids = SENTINEL_IDS | (CLASSIC_SENTINEL_IDS if classic else set())
    serial_fmt = CLASSIC_SERIAL_FORMAT if classic else SERIAL_FORMAT
    stats = dict.fromkeys(("downgraded", "commands", "scale_fixed", "scale_removed", "names", "id_append", "firmware", "uplink_oids", "attributes",
                           "entities", "alarms", "relations", "documented_annotated", "absent_columns", "findings_redacted"), 0)
    walk = _walk_text(walks_dir, family) if walks_dir else ""

    if classic:
        _classic_commands(target, stats)

    # command_ref: comando CLI cuyo campo de salida apunta al OID (fuente única: output_fields[].oid_ref de los comandos)
    cmd_for_oid: dict[str, str] = {}
    for cf in sorted((target / "commands").glob("*/*.json")):
        c = _rd(cf)
        for fld in c.get("output_fields", []):
            if fld.get("oid_ref"):
                cmd_for_oid.setdefault(fld["oid_ref"], c["id"])
    stats["command_refs"] = 0

    # ---- OID -----------------------------------------------------------------------------------
    groups = {}
    for f in sorted((target / "oids").glob("*.json")):
        groups[f] = _rd(f)
    by_entity_attrs: dict[str, dict[str, dict]] = {}
    for f, g in groups.items():
        if fw and g.get("firmware") != fw:
            g["firmware"] = list(fw); stats["firmware"] += 1
        for o in g.get("oids", []):
            _fix_scale_unit(o, stats)
            if o["id"] in cmd_for_oid and o.get("command_ref") != cmd_for_oid[o["id"]]:
                o["command_ref"] = cmd_for_oid[o["id"]]; stats["command_refs"] += 1
            if o["id"] in NO_SCALE_IDS and o.get("scale") is not None:
                o["scale"] = None; stats["scale_removed"] += 1
                if isinstance(o.get("empirical"), dict):
                    o["empirical"]["scale_confirmed"] = None
            if o.get("name") == "UNRESOLVED" and o.get("attribute"):
                o["name"] = o["attribute"]; stats["names"] += 1
            idx = o.get("index") or {}
            if idx.get("onu_id_append") and idx.get("space") in ("scalar", "ifIndex"):
                idx["onu_id_append"] = False; stats["id_append"] += 1
            if o.get("scale_formula", "").startswith("raw") and not o.get("unit") and "dBm" in (o.get("note") or ""):
                o["unit"] = "dBm"
            if o["id"] in serial_fmt:
                o["serial_format"] = serial_fmt[o["id"]]
            if classic and o["id"] == CLASSIC_STATUS_ID:
                o["enumeration_meta"] = {"branch": "1012.3.50.11.2.1.8", "observed": [k for k in (o.get("enumeration") or {}) if k != "default"],
                                         "sentinels": [65535],
                                         "note": "{1 Online, 2 Offline, 65535 desconocido}; coincide con el equipo (C320 1572 ONU, C300 1008). "
                                                 "No usar la rama 1082.500 (sin filas en clásicas)."}
            if o["id"] == ONU_STATUS_ID and classic:
                o["enumeration_meta"] = {"branch": "1082.500.10.2.3.8.1.4", "observed": [], "not_observed": dict(o.get("enumeration") or {}),
                                         "note": "rama sin filas en clásicas: usar onu_status_type (1012.3.50.11.2.1.8)"}
            elif o["id"] == ONU_STATUS_ID:
                o["enumeration_meta"] = {"branch": "1082.500.10.2.3.8.1.4", "observed": [k for k in (o.get("enumeration") or {}) if k != "default"],
                                         "not_observed": STATUS_NOT_OBSERVED,
                                         "note": "1/3/6 provienen del enum de las clásicas (misma rama); sin ONU en esos estados en C6"}
                if STATUS_NOTE not in (o.get("description") or ""):
                    o["description"] = (o.get("description") or "").rstrip() + STATUS_NOTE
            if o["id"] in PII_IDS:
                o["sensitivity"] = "pii"
                if PII_TXT not in (o.get("description") or ""):
                    o["description"] = (o.get("description") or "").rstrip() + PII_TXT
            if o["id"] in sent_ids and not o.get("unit"):
                o["unit"] = "dBm"
            if o["id"] in sent_ids and SENTINEL_TXT not in (o.get("description") or ""):
                o["description"] = (o.get("description") or "").rstrip() + SENTINEL_TXT
                o["sentinel"] = {"65535": "sin señal"}
                o["signed_bits"] = 16                       # raw>=32768 es negativo (CLI: 63547 -> -33,978 dBm)
                o["sentinels"] = [65535]
                o["valid_range_dbm"] = [-45, 10]
                if classic:     # ONU con status Online y raw 0 (rx y/o tx): C320 5 de 1573, C300 8 de 1008; no es una potencia real
                    o["suspect_values"] = {"0": "raw 0 = -30,0 dBm: lectura no válida (ONU en línea con la otra potencia normal); no es medición real"}
            if o.get("attribute"):
                ref = o.get("entity_ref") or g.get("entity_ref")
                syn = (o.get("syntax") or "").upper()
                typ = "integer" if "INTEGER" in syn or "GAUGE" in syn else "counter" if "COUNTER" in syn else "string"
                by_entity_attrs.setdefault(ref, {})[o["attribute"]] = {
                    "name": o["attribute"], "type": typ, "range": None, "required": False, "source": "walk"}

    # uplink_port: IF-MIB de las interfaces xgei (ifType 6), copiado de las hojas ya validadas de pon_port
    up_file = target / "oids" / "uplink_port.json"
    if classic:
        up_file = None
    if up_file is not None and up_file not in groups:       # la semilla no trae el grupo de uplinks
        groups[up_file] = {"entity_ref": UPLINK_ENTITY, "vendor": "ZTE", "family": family, "firmware": list(FIRMWARE), "oids": []}
    if up_file is not None and up_file in groups and not groups[up_file].get("oids"):
        pon = groups.get(target / "oids" / "pon_port.json", {"oids": []})
        seen = {o["id"] for g in groups.values() for o in g.get("oids", [])}
        new = []
        for o in [x for g in groups.values() for x in g.get("oids", [])]:
            if not o["oid"].startswith(UPLINK_PREFIXES) or o["oid"].count(".") > 11:
                continue
            nid = "oid.zte.gpon.uplink_port." + o["id"].split(".")[-1]
            if nid in seen:
                continue
            present = (not walk) or bool(re.search(rf"\.{re.escape(o['oid'])}\.{UPLINK_IFINDEX} =", walk) or
                                         re.search(rf"{re.escape(o['oid'])}\.{UPLINK_IFINDEX} =", walk))
            c = json.loads(json.dumps(o))
            c.update({"id": nid, "entity_ref": UPLINK_ENTITY, "status": "verified_walk" if present else "inferred",
                      "description": (o.get("description") or "") + " (uplink xgei, ifType 6)"})
            c["index"] = {**(c.get("index") or {}), "space": "ifIndex", "onu_id_append": False}
            if c.get("attribute") and not c["attribute"].startswith("uplink_"):
                c["attribute"] = "uplink_" + c["attribute"]
            if c.get("full_oid_template"):
                c["full_oid_template"] = c["full_oid_template"]
            new.append(c); seen.add(nid)
        groups[up_file]["oids"] = new; stats["uplink_oids"] = len(new)
        for c in new:
            if c.get("attribute"):
                by_entity_attrs.setdefault(UPLINK_ENTITY, {})[c["attribute"]] = {
                    "name": c["attribute"], "type": "counter" if "Counter" in (c.get("syntax") or "") else "integer",
                    "range": None, "required": False, "source": "walk"}
    onu_group = groups.get(target / "oids" / "onu.json")
    if onu_group is not None and not classic:
        ids_ = {x["id"] for x in onu_group["oids"]}
        base = next((x for x in onu_group["oids"] if x.get("attribute") == "onu_type_name"), None)
        if base and "oid.zte.gpon.onu.onu_type" not in ids_:
            al = json.loads(json.dumps(base))
            al.update({"id": "oid.zte.gpon.onu.onu_type", "attribute": "onu_type", "name": "onu_type", "alias_of": base["id"],
                       "description": (base.get("description") or "") + " Alias de onu_type_name para consumidores que buscan `onu_type`."})
            onu_group["oids"].append(al)
            by_entity_attrs.setdefault("entity.zte.gpon.device.onu", {})["onu_type"] = {
                "name": "onu_type", "type": "string", "range": None, "required": False, "source": "walk"}
    if walk:
        idx = _walk_index(walk)
        cf = (walks_dir.parent / "validation" / f"absent_columns_{family.split()[-1].lower()}.json") if walks_dir else None
        confirmed = _rd(cf)["columns"] if cf and cf.exists() else {}
        if classic:     # community la lista pero el equipo no tiene ni una fila: no es legible por SNMP en esta familia
            for g in groups.values():
                for o in g.get("oids", []):
                    if o.get("status") == "verified_community" and not _has(idx, tuple(int(x) for x in o["oid"].split("."))):
                        o["community_status_was"] = "verified_community"
                        o["status"] = "documented"
                        if CLASSIC_DOWNGRADE_TXT not in (o.get("description") or ""):
                            o["description"] = (o.get("description") or "").rstrip() + CLASSIC_DOWNGRADE_TXT
                        stats["downgraded"] += 1
            live = {o["attribute"]: o["id"] for g in groups.values() for o in g.get("oids", [])
                    if o.get("attribute") and o.get("status") in ("verified", "verified_walk")}
            for g in groups.values():       # el gemelo con filas reemplaza al degradado (mismo `attribute`)
                for o in g.get("oids", []):
                    if o.get("community_status_was") and live.get(o.get("attribute")):
                        o["superseded_by"] = live[o["attribute"]]
        for g in groups.values():
            for o in g.get("oids", []):
                if o.get("status") == "documented":
                    stats["absent_columns"] += _annotate_documented(o, idx, confirmed, fw_label); stats["documented_annotated"] += 1
        del idx
    for f, g in groups.items():
        _wr(f, g)

    # ---- entidades ------------------------------------------------------------------------------
    ent_dir = target / "entities"
    template = _rd(ent_dir / "gem_port.json") if not classic else {}
    for key, (name, desc, attrs) in ({} if classic else NEW_ENTITIES).items():
        p = ent_dir / f"{key}.json"
        if not p.exists():
            e = json.loads(json.dumps(template))
            e.update({"id": f"entity.zte.gpon.logical.{key}", "canonical_name": name, "description": desc, "is_critical": False,
                      "relations": [], "attributes": [], "status": "verified",
                      "confidence": {"extraction": 0.95, "correlation": 0.0, "overall": 0.95},
                      "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": 0.95}]})
            e["aliases"] = [{"name": name, "source": "hardware_description", "firmware_scope": "all"}]
            e.pop("empirical", None)
            _wr(p, e); stats["entities"] += 1
        by_entity_attrs.setdefault(f"entity.zte.gpon.logical.{key}", {}).update(
            {a: {"name": a, "type": "string" if a in ("name", "type") else "integer", "range": None, "required": False,
                 "source": "cli"} for a in attrs})
    for p in sorted(ent_dir.glob("*.json")):
        e = _rd(p)
        if fw:
            e["firmware"] = list(fw)
        have = {a.get("name") for a in e.get("attributes", []) if isinstance(a, dict)}
        add = [a for n, a in by_entity_attrs.get(e["id"], {}).items() if n not in have]
        e.setdefault("attributes", []).extend(add); stats["attributes"] += len(add)
        _wr(p, e)

    if not classic:
        # ---- relaciones: orden de creación verificado -------------------------------------------------
        rel_dir = target / "relations"
        onu_rel = rel_dir / "onu.json"
        if onu_rel.exists():
            r = _rd(onu_rel)
            order = {"pon_port": 0, "gem_port": 2, "service_port": 3}
            for x in r["relations"]:
                t = x["target"].split(".")[-1]
                if t in order:
                    x.update({"creation_order": order[t], "prerequisite": t == "pon_port", "status": "verified",
                              "confidence": {"extraction": 0.95, "correlation": 0.0, "overall": 0.95},
                              "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": 0.95}]})
            if not any(x["target"].endswith("tcont_profile") for x in r["relations"]):
                r["relations"].append({
                    "id": "rel.zte.gpon.onu.uses.tcont_profile", "type": "uses", "target": "entity.zte.gpon.logical.tcont_profile",
                    "cardinality": "many_to_one", "required": True, "description": "tcont <n> profile <perfil> (el perfil debe existir)",
                    "prerequisite": True, "creation_order": 1,
                    "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": 0.95}],
                    "confidence": {"extraction": 0.95, "correlation": 0.0, "overall": 0.95}, "status": "verified"})
            r["firmware"] = list(FIRMWARE); _wr(onu_rel, r); stats["relations"] += 1
        for name, order in (("gem_port", 2), ("service_port", 3)):
            p = rel_dir / f"{name}.json"
            if p.exists():
                r = _rd(p)
                for x in r["relations"]:
                    x.update({"creation_order": order, "status": "verified",
                              "confidence": {"extraction": 0.95, "correlation": 0.0, "overall": 0.95}})
                r["firmware"] = list(FIRMWARE); _wr(p, r)
        for p in rel_dir.glob("*.json"):
            r = _rd(p)
            if r.get("firmware") != FIRMWARE:
                r["firmware"] = list(FIRMWARE); _wr(p, r)
        sp_rel = rel_dir / "service_port.json"
        if sp_rel.exists():
            r = _rd(sp_rel)
            if not any(x["target"].endswith("traffic_profile") for x in r["relations"]):
                r["relations"].append({
                    "id": "rel.zte.gpon.service_port.uses.traffic_profile", "type": "uses",
                    "target": "entity.zte.gpon.logical.traffic_profile", "cardinality": "many_to_one", "required": False,
                    "description": "ingress <perfil_subida> egress <traffic-profile de bajada> (deben existir antes)", "prerequisite": True,
                    "creation_order": 2, "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": 0.95}],
                    "confidence": {"extraction": 0.95, "correlation": 0.0, "overall": 0.95}, "status": "verified"})
                _wr(sp_rel, r); stats["relations"] += 1

        # ---- alarmas ----------------------------------------------------------------------------------
        al_dir = target / "alarms"
        onu_al = al_dir / "onu.json"
        if onu_al.exists():
            a = _rd(onu_al)
            have = {x["id"] for x in a["alarms"]}
            for code, (nm, sev, desc) in OFFLINE_CAUSES.items():
                aid = f"alarm.zte.gpon.onu.offline_cause_{nm.lower()}"
                if aid in have:
                    continue
                a["alarms"].append({
                    "id": aid, "code": f"offline_cause={code}", "name": f"onuOffline{nm}", "canonical_name": f"ONU offline: {nm}",
                    "entity_ref": "entity.zte.gpon.device.onu", "severity": sev, "type": ALARM_TYPE[nm],
                    "description": desc, "probable_causes": [desc],
                    "remediation": ["Consultar 'show gpon onu detail-info gpon_onu-<idx>' (historial de bajas)",
                                    "Leer el estado por SNMP: 1082.500.10.2.3.8.1.4 (onu_status) y .7 (onu_last_offline_cause)"],
                    "kind": "historical",       # última causa de baja registrada; NO el estado actual (hay ONU working con causa 2/3/9)
                    "oid_trap": None, "oid_refs": ["onu_status", "onu_last_offline_cause", "onu_last_offline_time"],
                    "auto_clear": nm == "DyingGasp" or nm.startswith("LOS"), "clear_condition": "onu_status = Working", "threshold": None,
                    "escalation": {"warning_after_minutes": None, "major_after_minutes": None, "critical_after_minutes": None},
                    "sources": [{"doc_type": "hardware_verification", "pages": None, "confidence": 0.85}],
                    "confidence": {"extraction": 0.85, "correlation": 0.0, "overall": 0.85}, "status": "verified", "conflicts": []})
                stats["alarms"] += 1
            _wr(onu_al, a)
        for p in sorted(al_dir.glob("*.json")):
            a = _rd(p)
            for x in a.get("alarms", []):
                if x.get("id", "").startswith("alarm.zte.gpon.onu.offline_cause_"):
                    x["kind"] = "historical"
            if a.get("firmware") != FIRMWARE:
                a["firmware"] = list(FIRMWARE)
            _wr(p, a)

    # ---- results.json: sin índices de comunidades/cuentas ---------------------------------------------
    rp = target / "results.json"
    if rp.exists():
        res = _rd(rp)
        keep, dropped = [], {}
        for x in res.get("findings", []):
            ref = str(x.get("tabla") or x.get("oid") or "")
            hit = next((p for p in SENSITIVE_PREFIXES if ref.startswith(p)), None)
            if hit:
                dropped[hit] = dropped.get(hit, 0) + 1
            else:
                keep.append(x)
        if dropped:
            keep.append({"trigger": "sensitive_branch_redacted", "severity": "info", "catalog_action": "ninguna",
                         "prefixes": dropped, "note": "hallazgos ascii_index omitidos: el índice de estas tablas es el nombre de "
                                                      "comunidades SNMP, cuentas o peticiones web de la OLT"})
        res["findings"] = keep
        _wr(rp, res)
        stats["findings_redacted"] = sum(dropped.values())

    # ---- manifest ---------------------------------------------------------------------------------
    mp = target / "manifest.json"
    if mp.exists():
        m = _rd(mp)
        m["observed_firmware_strings"] = [s for s in m.get("observed_firmware_strings", [])
                                          if re.search(r"\bV?\d+\.\d+(\.\d+)?", s) and "/" not in s and ".csv" not in s]
        bv = m.get("bitcalc_validation")
        if isinstance(bv, dict) and bv.get("resolution") == "accept":
            bv["verdict"] = "accepted (layout derivado aplicado)"
        n_oids = sum(len(g.get("oids", [])) for g in groups.values())
        m.setdefault("counts", {})["oids_kept"] = n_oids
        by_status = {}
        for g in groups.values():
            for o in g.get("oids", []):
                by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        m["status_distribution"] = {**m.get("status_distribution", {}), "oids": by_status}
        if isinstance(bv, dict) and bv.get("proposed_fix"):
            m["index_layout_final"] = {"slot_bits": bv["proposed_fix"].get("slot"), "port_bits": bv["proposed_fix"].get("port"),
                                       "formula": "ifIndexPON = 285278208 + slot*256 + pon (slot bits 10-8 en C620, 11-8 en C600)",
                                       "onu_key": "<ifIndexPON>.<n de ONU>"}
        m["not_exposed_attributes"] = CLASSIC_NOT_EXPOSED if classic else NOT_EXPOSED_ATTRS
        m["serial_format"] = serial_fmt
        if classic:
            sd = (walks_dir / "diagnostics" / f"ZTE_{family.split()[-1]}_sysdescr_check.txt") if walks_dir else None
            ver = re.search(r"Version (V[\d.]+)", sd.read_text(errors="ignore")) if sd and sd.exists() else None
            if ver:
                m["observed_software"] = ver.group(1)      # sysDescr de la OLT; sin versión equivalente en el catálogo de C6
        m["refinements"] = {"module": "src/walk_validator/refinements.py", "applied": stats, "firmware": fw or m.get("firmware")}
        _wr(mp, m)
    log.info("Refinamientos %s: %s", family, stats)
    return stats
