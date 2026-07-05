"""Fase 2 — extractores de tablas MIB-2 estándar (no vendor 3902).

Dos walks complementarios describen el mismo equipo desde ángulos estándar:

  entity_table (ZTE_*_entities.txt) → entPhysicalTable (1.3.6.1.2.1.47.1.1.1.1)
      inventario físico real: chasis, tarjetas, fuentes, fans, sensores.
      → confirma entidades tkc de tipo hardware.

  if_table (ZTE_*_ifnames.txt) → ifXTable (1.3.6.1.2.1.31.1.1.1.1 = ifName)
      interfaces reales y sus ifIndex compuestos.
      → confirma entidades de tipo port y VALIDA el bit_calculation del índice.

A diferencia del walk enterprise, aquí no se cruza contra OIDs 3902 sino que se
enriquecen ENTIDADES (a nivel de dict JSON) y se valida el mapa de bits del índice.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from collections import Counter, defaultdict
from typing import Any, Optional

from ..ids import build_oid_id
from .triggers import Findings, decode_ascii_index

_STATUS_WALK = "verified_walk"

# --- OIDs estándar ------------------------------------------------------------
ENT_PHYSICAL = "1.3.6.1.2.1.47.1.1.1.1"
ENT_COLS = {
    ENT_PHYSICAL + ".2": "descr",
    ENT_PHYSICAL + ".5": "class",
    ENT_PHYSICAL + ".7": "name",
    ENT_PHYSICAL + ".11": "serial",
    ENT_PHYSICAL + ".13": "model",
}
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"

# entPhysicalClass (RFC 2737) → short_name de entidad tkc
ENT_CLASS_TO_SHORT = {
    3: "shelf",         # chassis
    6: "power_supply",  # powerSupply
    7: "fan",           # fan
    8: "sensor",        # sensor
    9: "card",          # module
}

# Fallback cuando el walk trae solo entPhysicalDescr (sin entPhysicalClass): se
# clasifica por el texto de la descripción. El orden importa (más específico primero).
_DESCR_KEYWORDS = [
    ("shelf", "shelf"), ("chassis", "shelf"), ("rack", "shelf"),
    ("fan", "fan"), ("sensor", "sensor"), ("power", "power_supply"),
    ("card", "card"), ("olt", "card"),        # "interface card" gana sobre "optical"
    ("optical", "optical_module"), ("module", "card"),
]


def classify_ent_descr(descr: str) -> Optional[str]:
    low = (descr or "").lower()
    for kw, short in _DESCR_KEYWORDS:
        if kw in low:
            return short
    return None

_CONFIRM_BUMP = 0.15


# --- extracción ---------------------------------------------------------------
def _clean(value: str) -> str:
    return (value or "").strip().strip('"')


def extract_ent_physical(walk: dict[str, dict]) -> dict[str, dict]:
    """entPhysicalTable → {index: {descr, class(int), name, serial, model}}."""
    rows: dict[str, dict] = defaultdict(dict)
    for oid, data in walk.items():
        for col, field in ENT_COLS.items():
            if oid.startswith(col + "."):
                idx = oid[len(col) + 1:]
                val = _clean(data.get("value", ""))
                if field == "class":
                    try:
                        val = int(val)
                    except ValueError:
                        continue
                rows[idx][field] = val
                break
    return dict(rows)


def extract_if_names(walk: dict[str, dict]) -> dict[str, str]:
    """ifXTable ifName → {ifIndex: nombre}."""
    rows: dict[str, str] = {}
    prefix = IF_NAME + "."
    for oid, data in walk.items():
        if oid.startswith(prefix):
            rows[oid[len(prefix):]] = _clean(data.get("value", ""))
    return rows


# --- enriquecimiento de entidades --------------------------------------------
def _verify_entity(ent: dict, source: str, empirical: dict) -> None:
    ent["status"] = "verified"
    conf = ent.setdefault("confidence", {})
    conf["overall"] = round(min(1.0, (conf.get("overall") or 0.0) + _CONFIRM_BUMP), 3)
    ent["empirical"] = {"source": source, **empirical}


def enrich_hardware_entities(entities_by_short: dict[str, dict], walk: dict[str, dict],
                             source: str, findings: Findings) -> int:
    """Confirma entidades hardware con el inventario real de entPhysicalTable."""
    rows = extract_ent_physical(walk)
    counts: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    for row in rows.values():
        # entPhysicalClass si está; si el walk trae solo Descr, se clasifica por texto
        short = ENT_CLASS_TO_SHORT.get(row.get("class"))
        if not short:
            short = classify_ent_descr(row.get("descr") or row.get("model") or row.get("name"))
        if not short:
            continue
        counts[short] += 1
        label = row.get("descr") or row.get("model") or row.get("name")
        if label and label not in samples[short] and len(samples[short]) < 5:
            samples[short].append(label)
    confirmed = 0
    for short, n in counts.items():
        ent = entities_by_short.get(short)
        if not ent:
            continue
        _verify_entity(ent, source, {"via": "entPhysicalTable", "instances": n,
                                     "samples": [s for s in samples[short] if s]})
        confirmed += 1
        findings.add({"trigger": "entity_confirmed", "entity": short, "instances": n,
                      "via": "entPhysicalTable",
                      "catalog_action": f"status=verified para {short} (hardware real)",
                      "severity": "low"})
    return confirmed


# --- puertos + validación de bit_calculation ----------------------------------
def classify_ifname(name: str) -> Optional[str]:
    low = (name or "").lower()
    if "pon" in low:                       # gpon/pon-onu → puerto PON
        return "pon_port"
    if any(k in low for k in ("uplink", "gei", "xge", "eth", "gigabit")):
        return "uplink_port"
    return None


def _find_bitcalc_components(oid_groups: list[dict]) -> Optional[list[dict]]:
    """Toma el mapa de bits (shelf/slot/port...) de algún OID con índice compuesto."""
    for g in oid_groups:
        for o in g.get("oids", []):
            idx = o.get("index") or {}
            comps = [c for c in (idx.get("components") or []) if c.get("bits")]
            if idx.get("bit_calculation") and comps:
                return comps
    return None


def decode_composite(index_int: int, components: list[dict]) -> dict[str, int]:
    """Decodifica un entero compuesto según rangos de bits 'hi-lo' (ej. '31-28')."""
    out: dict[str, int] = {}
    for c in components:
        bits = c.get("bits") or ""
        if "-" not in bits:
            continue
        try:
            hi, lo = (int(x) for x in bits.split("-"))
        except ValueError:
            continue
        width = hi - lo + 1
        out[c["name"]] = (index_int >> lo) & ((1 << width) - 1)
    return out


def enrich_port_entities(entities_by_short: dict[str, dict], oid_groups: list[dict],
                         walk: dict[str, dict], source: str, findings: Findings) -> None:
    """Confirma entidades de puerto por ifName y valida bit_calculation con ifIndex real."""
    if_rows = extract_if_names(walk)
    counts: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    for name in if_rows.values():
        short = classify_ifname(name)
        if not short:
            continue
        counts[short] += 1
        if len(samples[short]) < 5:
            samples[short].append(name)
    for short, n in counts.items():
        ent = entities_by_short.get(short)
        if ent:
            _verify_entity(ent, source, {"via": "ifXTable", "instances": n,
                                         "samples": samples[short]})
            findings.add({"trigger": "entity_confirmed", "entity": short, "instances": n,
                          "via": "ifXTable",
                          "catalog_action": f"status=verified para {short} (interfaces reales)",
                          "severity": "low"})

    # Validación del índice compuesto: se compara el decode del catálogo contra el
    # rack/slot/port REAL que trae el ifName (ground truth). No basta con que los
    # valores estén "en rango": deben COINCIDIR con la interfaz observada.
    comps = _find_bitcalc_components(oid_groups)
    pairs = []  # (ifIndex_int, (rack, slot, port))
    for ifindex, name in if_rows.items():
        try:
            iv = int(ifindex)
        except ValueError:
            continue
        parsed = _ifname_indices(name)
        if parsed:
            pairs.append((iv, parsed, name))
    if not pairs or not comps:
        return

    catalog_map = {c["name"]: c.get("bits") for c in comps}
    agree = disagree = 0
    mism_samples: list[dict] = []
    for iv, (rack, slot, port), name in pairs:
        dec = decode_composite(iv, comps)
        expected = {"shelf": rack, "rack": rack, "slot": slot, "port": port}
        match = all(dec.get(k) == expected.get(k) for k in dec if k in expected)
        if match:
            agree += 1
        else:
            disagree += 1
            if len(mism_samples) < 5:
                mism_samples.append({"ifIndex": iv, "ifName": name,
                                     "decoded": dec, "real_rack_slot_port": [rack, slot, port]})
    verdict = "match" if disagree == 0 else "mismatch"
    finding = {
        "trigger": "bitcalc_validation",
        "catalog_map": catalog_map,
        "compared": len(pairs), "agree": agree, "disagree": disagree,
        "verdict": verdict,
        "mismatch_samples": mism_samples,
        "catalog_action": ("bit_calculation confirmado contra ifName real"
                           if verdict == "match" else
                           "bit_calculation del catálogo NO coincide con el ifName real "
                           "(el índice compuesto usa otro layout de bits) → revisar mapa de bits"),
        "severity": "low" if verdict == "match" else "high",
    }
    if verdict == "mismatch":
        # deriva empíricamente el layout correcto desde los pares (ifIndex, ifName)
        layout = derive_bit_layout([(iv, r, s, p) for iv, (r, s, p), _ in pairs])
        finding["derived_layout"] = layout
        finding["proposed_fix"] = {name: layout[name]["bits"]
                                   for name in ("shelf", "slot", "port")
                                   if layout.get(name, {}).get("bits")}
        # error de integridad → bloquea el pipeline hasta confirmación/rechazo
        finding["blocking"] = True
    findings.add(finding)


def _ifname_indices(name: str) -> Optional[tuple[int, int, int]]:
    """`gpon_1/2/1` → (rack=1, slot=2, port=1). Usa los últimos 3 números del nombre."""
    nums = [int(x) for x in re.findall(r"\d+", name or "")]
    if len(nums) >= 3:
        return nums[-3], nums[-2], nums[-1]
    return None


# --- derivación empírica del layout de bits -----------------------------------
def derive_bit_layout(pairs: list[tuple[int, int, int, int]],
                      labels: tuple[str, ...] = ("shelf", "slot", "port")) -> dict:
    """Deriva los rangos de bits de cada campo desde (ifIndex, rack, slot, port).

    Para cada campo busca el (width, shift) MÍNIMO cuyo `(ifIndex >> shift) & mask`
    reproduce el valor real en TODOS los pares. Un campo constante (ej. rack=1 en
    todo el walk) no es derivable y se marca como tal.
    """
    out: dict[str, dict] = {}
    for i, label in enumerate(labels):
        values = [p[i + 1] for p in pairs]
        if not values:
            out[label] = {"bits": None, "status": "no_data"}
            continue
        if len(set(values)) <= 1:
            out[label] = {"bits": None, "status": "constant", "observed_value": values[0]}
            continue
        best = None
        for width in range(1, 13):
            mask = (1 << width) - 1
            for shift in range(0, 33 - width):
                if all(((iv >> shift) & mask) == v for (iv, *_), v in zip(pairs, values)):
                    best = (width, shift)
                    break
            if best:
                break
        if best:
            width, shift = best
            out[label] = {"bits": f"{shift + width - 1}-{shift}", "status": "derived"}
        else:
            out[label] = {"bits": None, "status": "not_derivable"}
    return out


def _annotate_components(idx: dict) -> None:
    """`fully_validated` = todos con validated:true. Marca el alcance single-shelf."""
    comps = idx.get("components") or []
    idx["fully_validated"] = bool(comps) and all(c.get("validated") for c in comps)
    if any(c.get("source") == "single_shelf" for c in comps):
        idx["validation_scope"] = "single_shelf"
    idx.pop("bitcalc_validated", None)   # reemplaza el flag engañoso a nivel de OID
    idx.pop("bitcalc_source", None)


def _is_rack(name: str) -> bool:
    return name == "shelf" or "rack" in name


def noevidence_reason(name: str) -> str:
    """Razón + fuente sugerida para un componente que el ifXTable no puede validar."""
    n = name.lower()
    if any(k in n for k in ("patch", "image", "software", "set", "filename")) or n.endswith("name"):
        return ("sin evidencia en el walk (índice ASCII de software/parche; la rama del "
                "catálogo no respondió — este equipo expone su software en otra rama enterprise)")
    if "intervalno" in n:
        return ("sin evidencia en ifXTable (contador de intervalo de historial → "
                "validar si la tabla de performance tiene filas en el walk)")
    if n.endswith("vid") or "vlan" in n:
        return ("sin evidencia en ifXTable (VLAN id → validar con la rama enterprise "
                "40.50 o un walk de configuración)")
    return "sin evidencia en ifXTable"


def apply_bitcalc_fix(oid_groups: list[dict], proposed_fix: dict[str, str],
                      derived_layout: Optional[dict] = None,
                      single_shelf: bool = True) -> int:
    """Corrige los bits derivados y marca la validación POR COMPONENTE.

    - proposed_fix (slot/port): bits corregidos, validated:true, source:ifXTable.
    - shelf/rack: en equipos single-shelf (rack=1 siempre) se aceptan como válidos con
      source:single_shelf y una nota de revalidación multi-shelf.
    - resto (VLAN, patch, historial…): validated:false, con razón + fuente sugerida.
    Devuelve nº de OIDs con al menos un bit corregido.
    """
    derived_layout = derived_layout or {}
    const_val = (derived_layout.get("shelf") or {}).get("observed_value", 1)
    fixed = 0
    for g in oid_groups:
        for o in g.get("oids", []):
            idx = o.get("index") or {}
            comps = idx.get("components") or []
            if not (idx.get("bit_calculation") and comps):
                continue
            touched = False
            for c in comps:
                name = c.get("name", "")
                if name in proposed_fix:
                    c["bits"] = proposed_fix[name]
                    c["validated"] = True
                    c["source"] = "ifXTable"
                    c.pop("reason", None)
                    c.pop("note", None)
                    c.pop("pending_validation", None)
                    touched = True
                elif single_shelf and _is_rack(name):
                    # todos los equipos son single-shelf: rack=1 es correcto y estable
                    c["validated"] = True
                    c["source"] = "single_shelf"
                    c["value"] = const_val
                    c["note"] = ("rack constante en equipos single-shelf; revalidar el "
                                 "layout de bits en despliegues multi-shelf")
                    c.pop("reason", None)
                    c.pop("pending_validation", None)
                elif c.get("validated") is True:
                    continue                     # ya validado por otra evidencia (ej. enterprise_ascii)
                else:
                    c["validated"] = False
                    c.pop("source", None)
                    c.pop("note", None)
                    c["reason"] = noevidence_reason(name)
            _annotate_components(idx)
            if touched:
                fixed += 1
    return fixed


# Rama donde estos equipos exponen realmente el inventario de software (distinta de
# la del catálogo, 1082.20.30). Candidato conocido para el mapeo pendiente.
SOFTWARE_ALT_BRANCH = "1.3.6.1.4.1.3902.1015.2.1.2.4"


def _is_string_index(name: str) -> bool:
    """Componente cuyo índice es una cadena ASCII (nombre de software/parche/imagen)."""
    n = name.lower()
    if _is_rack(name):
        return False   # rack (aunque contenga 'patch', ej. zxanswpatchrack) → single_shelf
    if "intervalno" in n or n.endswith("vid") or "vlan" in n:
        return False   # contadores de historial / VLAN id → numéricos, no ASCII
    return any(k in n for k in ("name", "filename", "image", "patch", "software", "set", "type"))


def _ascii_samples_under(base: str, sorted_walk: list[str], limit: int = 5) -> list[str]:
    """Decodifica la cola ASCII de las instancias reales bajo un OID base."""
    b = base.lstrip(".")
    i = bisect_left(sorted_walk, b + ".")
    out: list[str] = []
    seen: set[str] = set()
    while i < len(sorted_walk) and sorted_walk[i].startswith(b + "."):
        dec = decode_ascii_index(sorted_walk[i])
        if len(dec) >= 2 and dec not in seen:
            seen.add(dec)
            out.append(dec)
            if len(out) >= limit:
                break
        i += 1
    return out


def validate_ascii_indices(oid_groups: list[dict], sorted_walk: list[str],
                           findings: Findings, source: str = "enterprise_ascii") -> int:
    """Confirma componentes de índice tipo string con instancias reales del walk enterprise.

    Los índices de software/parche (rama 20.30) se codifican como cadena ASCII en el OID.
    El ifXTable no los ve, pero el walk enterprise sí: se decodifica la cola ASCII de las
    instancias reales y, si hay muestras legibles, se valida el componente. Devuelve nº OIDs.
    """
    # ¿el equipo expone el software en la rama alternativa conocida (1015)?
    alt_samples = _ascii_samples_under(SOFTWARE_ALT_BRANCH, sorted_walk)
    pending = ({"candidate_source": SOFTWARE_ALT_BRANCH,
                "evidence_samples": alt_samples,
                "action": "mapear la tabla de software del catálogo (1082.20.30) a la rama "
                          "real del equipo (1015.2.1.2.4) y validar los índices ASCII allí"}
               if alt_samples else None)

    confirmed = 0
    absent: list[str] = []
    for g in oid_groups:
        for o in g.get("oids", []):
            idx = o.get("index") or {}
            comps = idx.get("components") or []
            if not (idx.get("bit_calculation") and comps):
                continue
            str_comps = [c for c in comps
                         if not c.get("bits") and _is_string_index(c.get("name", ""))]
            if not str_comps:
                continue
            samples = _ascii_samples_under(o.get("oid", ""), sorted_walk)
            if not samples:
                absent.append(o.get("oid", ""))
                if pending:                       # deja la validación trackeada como pendiente
                    for c in str_comps:
                        c["pending_validation"] = pending
                continue
            for c in str_comps:
                c["validated"] = True
                c["source"] = source
                c["samples"] = samples
                c.pop("reason", None)
                c.pop("pending_validation", None)
            _annotate_components(idx)
            confirmed += 1
            findings.add({
                "trigger": "ascii_index_validation",
                "oid": o.get("oid", ""),
                "components": [c["name"] for c in str_comps],
                "samples": samples,
                "catalog_action": "índice ASCII confirmado con instancias reales del walk enterprise",
                "severity": "low",
            })
    if absent:
        # las tablas ASCII del catálogo existen, pero el equipo no las expone en esa rama
        findings.add({
            "trigger": "ascii_branch_absent",
            "oids": absent,
            "count": len(absent),
            "pending": bool(pending),
            "pending_validation": pending,
            "catalog_action": ("tablas de índice ASCII del catálogo sin instancias en el walk; "
                               "el equipo expone estos datos en otra rama enterprise "
                               "(marcado pending_validation para retomar)"),
            "severity": "low",
        })
    return confirmed


# --- PON port operacional (ifTable) + onu_count derivado ----------------------
IF_TABLE = "1.3.6.1.2.1.2.2.1"
IFTYPE_GPON = "250"
IF_OPER_ENUM = {"1": "up", "2": "down", "3": "testing", "4": "unknown",
                "5": "dormant", "6": "notPresent", "7": "lowerLayerDown"}
IF_ADMIN_ENUM = {"1": "up", "2": "down", "3": "testing"}
ONU_VENDOR_COL = "1.3.6.1.4.1.3902.1012.3.50.11.2.1.1."   # tabla ONU, col vendor


def _iftable_col(walk: dict[str, dict], col: str) -> dict[str, str]:
    """{ifIndex: valor} para la columna IF_TABLE.<col>."""
    prefix = f"{IF_TABLE}.{col}."
    return {oid[len(prefix):]: data.get("value", "")
            for oid, data in walk.items() if oid.startswith(prefix)}


def _port_group(oid_groups: list[dict], entity_ref: str, vendor: str,
                family: str | None) -> dict:
    for g in oid_groups:
        if g.get("entity_ref") == entity_ref:
            return g
    g = {"entity_ref": entity_ref, "vendor": vendor, "family": family,
         "firmware": [], "oids": []}
    oid_groups.append(g)
    return g


def enrich_pon_operational(entities_by_short: dict[str, dict], oid_groups: list[dict],
                           walk: dict[str, dict], source: str, findings: Findings,
                           vendor: str = "ZTE", technology: str = "gpon",
                           family: str | None = None) -> None:
    """Mapea ifOperStatus/ifType del ifTable a la operación de PON ports.

    PON port = ifType 250; uplink = ifType 6. Enriquece las entidades y agrega los
    OIDs operativos (oper/admin/type) como verified_walk para que getPonPorts() sepa
    qué consultar.
    """
    iftype = _iftable_col(walk, "3")
    ifoper = _iftable_col(walk, "8")
    if not ifoper:
        return

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    pon_idx = [i for i, t in iftype.items() if str(t).strip() == IFTYPE_GPON] or list(ifoper)
    up = sum(1 for i in pon_idx if _int(ifoper.get(i)) == 1)
    down = sum(1 for i in pon_idx if _int(ifoper.get(i)) == 2)

    ent = entities_by_short.get("pon_port")
    if ent:
        ent["status"] = _STATUS_WALK
        c = ent.setdefault("confidence", {})
        c["overall"] = round(min(1.0, (c.get("overall") or 0.0) + 0.15), 3)
        ent["empirical"] = {**(ent.get("empirical") or {}),
                            "oper_via": "ifTable (ifType=250)", "pon_ports": len(pon_idx),
                            "oper_up": up, "oper_down": down, "source": source}
    upl = [i for i, t in iftype.items() if str(t).strip() == "6"]
    e2 = entities_by_short.get("uplink_port")
    if upl and e2:
        e2["status"] = _STATUS_WALK
        e2["empirical"] = {**(e2.get("empirical") or {}), "via": "ifTable (ifType=6)",
                           "ports": len(upl), "source": source}

    grp = _port_group(oid_groups, "entity.zte.gpon.port.pon_port", vendor, family)
    existing = {o.get("oid") for g in oid_groups for o in g.get("oids", [])}
    cols = [(f"{IF_TABLE}.8", "oper_status", IF_OPER_ENUM,
             "estado operativo real por PON port (IF-MIB ifOperStatus); 1=up, 2=down"),
            (f"{IF_TABLE}.7", "admin_status", IF_ADMIN_ENUM,
             "estado administrativo por PON port (IF-MIB ifAdminStatus)"),
            (f"{IF_TABLE}.3", "if_type", None,
             "tipo de interfaz (250=gpon PON port, 6=uplink)")]
    for oid_str, attr, enum, desc in cols:
        if oid_str in existing:
            continue
        grp["oids"].append({
            "id": build_oid_id(vendor, technology, "pon_port", attr),
            "oid": oid_str, "name": "UNRESOLVED", "mib_name": "IF-MIB", "attribute": attr,
            "entity_ref": "entity.zte.gpon.port.pon_port", "mib_table": "ifTable",
            "index": {"type": "composite", "bit_calculation": True,
                      "decoder": "community_formula", "space": "ONU-ID",
                      "formula": "suffix = 285278208 + slot*256 + pon", "shelf": 1,
                      "onu_id_append": False,
                      "note": "nivel puerto: ifIndex = suffix (sin onuID)",
                      "validated": True, "source": "ifTable", "status": _STATUS_WALK},
            "syntax": "INTEGER", "unit": None, "scale": None, "access": "read-only",
            "enumeration": enum, "description": desc,
            "full_oid_template": f".{oid_str}.<ifIndex>", "command_ref": None,
            "status": _STATUS_WALK,
            "sources": [{"doc_type": "walk", "pages": None, "confidence": 0.0}],
            "confidence": {"extraction": 0.9, "correlation": 0.0, "overall": 0.9},
            "provenance": f"walk ifTable: {source}", "conflicts": []})
        existing.add(oid_str)

    findings.add({"trigger": "pon_operational", "pon_ports": len(pon_idx),
                  "oper_up": up, "oper_down": down, "uplink_ports": len(upl),
                  "catalog_action": "pon_port.oper mapeado desde ifOperStatus (ifType=250)",
                  "severity": "low"})


def derive_pon_onu_count(entities_by_short: dict[str, dict], enterprise_sorted: list[str],
                         findings: Findings) -> None:
    """Deriva ONUs por PON port contando en la tabla ONU (.1012.3.50.11.2.1)."""
    per_port: dict[str, set] = defaultdict(set)
    for oid in enterprise_sorted:
        if oid.startswith(ONU_VENDOR_COL):
            rest = oid[len(ONU_VENDOR_COL):].split(".")
            if len(rest) >= 2:
                per_port[rest[0]].add(rest[1])
    if not per_port:
        return
    counts = [len(v) for v in per_port.values()]
    total = sum(counts)
    ent = entities_by_short.get("pon_port")
    if ent:
        ent.setdefault("empirical", {})["onu_count"] = {
            "derived": True, "status": _STATUS_WALK,
            "source": "conteo por puerto en la tabla ONU .1012.3.50.11.2.1",
            "total_onus": total, "ports_with_onus": len(per_port),
            "min_per_port": min(counts), "max_per_port": max(counts),
            "rule": "count distinct onuID per port suffix (TYPE space)"}
    findings.add({"trigger": "pon_onu_count_derived", "total_onus": total,
                  "ports": len(per_port), "max_per_port": max(counts),
                  "catalog_action": "onu_count por PON port derivado de la tabla ONU (verified_walk)",
                  "severity": "low"})


def mark_bitcalc_unvalidated(oid_groups: list[dict]) -> int:
    """Rechazo: mantiene los bits del catálogo y marca cada componente no validado."""
    n = 0
    for g in oid_groups:
        for o in g.get("oids", []):
            idx = o.get("index") or {}
            comps = idx.get("components") or []
            if not (idx.get("bit_calculation") and comps):
                continue
            for c in comps:
                c["validated"] = False
                c.pop("source", None)
                c.setdefault("reason", "rechazado: sin confirmación empírica")
            _annotate_components(idx)
            n += 1
    return n
