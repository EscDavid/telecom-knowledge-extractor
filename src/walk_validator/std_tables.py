"""Fase 2 — extractores de tablas MIB-2 estándar (no del enterprise del vendor).

Dos walks complementarios describen el mismo equipo desde ángulos estándar:

  entity_table (<VENDOR>_*_entities.txt) → entPhysicalTable (1.3.6.1.2.1.47.1.1.1.1)
      inventario físico real: chasis, tarjetas, fuentes, fans, sensores.
      → confirma entidades tkc de tipo hardware.

  if_table (<VENDOR>_*_ifnames.txt) → ifXTable (1.3.6.1.2.1.31.1.1.1.1 = ifName)
      interfaces reales y sus ifIndex compuestos.
      → confirma entidades de tipo port y VALIDA el bit_calculation del índice.

A diferencia del walk enterprise, aquí no se cruza contra OIDs del enterprise sino
que se enriquecen ENTIDADES (a nivel de dict JSON) y se valida el mapa de bits del
índice. Lo específico de cada vendor (nombres de interfaz, fórmulas, ramas) llega en
el `VendorProfile` (config/vendors.yaml); sin perfil se usa el de compatibilidad.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from collections import Counter, defaultdict
from typing import Any, Optional

from ..ids import build_entity_id, build_oid_id
from ..normalizer.normalizer import CRITICAL_SHORT, ENTITY_DESCRIPTIONS, SHORT_NAME_TYPE
from ..profiles import (LEGACY_DEFAULT_VENDOR, VendorProfile, default_registry)
from .triggers import Findings, decode_ascii_index, trigger_ifname_unparsed


def _profile(profile: Optional[VendorProfile]) -> VendorProfile:
    """Perfil explícito o, para llamadas heredadas sin perfil, el de compatibilidad."""
    return profile or default_registry().get(LEGACY_DEFAULT_VENDOR)

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
def _ensure_entity(entities_by_short: dict[str, dict], short: str, *, vendor: str,
                   family: str, technology: str, firmware: list[str]) -> dict:
    """Entidad existente, o (solo en modo walk-first, sin semilla) una mínima
    sintetizada ahora mismo — ver backlog #1 de docs/adaptacion_multivendor.md.
    Fuera de walk-first, `short` ausente del dict significa "no aplica a esta
    familia" y NO debe crearse una entidad nueva (por eso los llamadores solo
    pasan por aquí cuando ya se confirmó walk_first=True)."""
    ent = entities_by_short.get(short)
    if ent:
        return ent
    etype = SHORT_NAME_TYPE.get(short, "logical")
    canonical = short.replace("_", " ").title()
    ent = {
        "id": build_entity_id(vendor, technology, etype, canonical),
        "canonical_name": canonical,
        "vendor": vendor, "family": family, "firmware": list(firmware),
        "technology": technology, "type": etype,
        "description": ENTITY_DESCRIPTIONS.get(short),
        "is_critical": short in CRITICAL_SHORT,
        "aliases": [], "attributes": [],
        "sources": [{"doc_type": "walk", "pages": None, "confidence": 0.0}],
        "status": "observed",
        "confidence": {"overall": 0.0},
    }
    entities_by_short[short] = ent
    return ent


def _verify_entity(ent: dict, source: str, empirical: dict) -> None:
    ent["status"] = "verified"
    conf = ent.setdefault("confidence", {})
    conf["overall"] = round(min(1.0, (conf.get("overall") or 0.0) + _CONFIRM_BUMP), 3)
    ent["empirical"] = {"source": source, **empirical}


_MODULE_REFINE = [("fan", "fan"), ("power board", "power_supply"), ("power supply", "power_supply")]


def _refine_module(short: str, row: dict) -> str:
    """Un `module` (clase 9) cuya descripción es ventilador/fuente no es una tarjeta."""
    text = (row.get("descr") or row.get("model") or row.get("name") or "").lower()
    for kw, refined in _MODULE_REFINE:
        if kw in text:
            return refined
    return short


def enrich_hardware_entities(entities_by_short: dict[str, dict], walk: dict[str, dict],
                             source: str, findings: Findings,
                             profile: Optional[VendorProfile] = None,
                             walk_first: bool = False, family: Optional[str] = None) -> int:
    """Confirma entidades hardware con el inventario real de entPhysicalTable.

    walk_first=True (sin semilla, ver backlog #1) o profile.ent_synthesize_from_walk
    (backlog #8: la semilla de este vendor no cubre hardware, pero entPhysicalClass
    sí confirma uno real) → una entidad sin equivalente en el catálogo se SINTETIZA
    (status=observed) en vez de descartarse. Con ninguno de los dos, "no está en el
    catálogo" sigue significando "no aplica a esta familia", no se inventa."""
    profile = _profile(profile)
    refine = bool(profile and profile.ent_module_refine)
    rows = extract_ent_physical(walk)
    counts: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    for row in rows.values():
        # entPhysicalClass si está; si el walk trae solo Descr, se clasifica por texto
        short = ENT_CLASS_TO_SHORT.get(row.get("class"))
        if not short and not (refine and row.get("class") is not None):
            # la descripción solo clasifica si el walk NO trae entPhysicalClass (con perfil
            # estricto, una clase presente pero no mapeada —p. ej. 11 "stack" de Huawei con
            # 65 filas "RACK-300"— no se reinterpreta por texto)
            short = classify_ent_descr(row.get("descr") or row.get("model") or row.get("name"))
        if not short:
            continue
        if refine and short == "card":
            short = _refine_module(short, row)
        counts[short] += 1
        label = row.get("descr") or row.get("model") or row.get("name")
        if label and label not in samples[short] and len(samples[short]) < 5:
            samples[short].append(label)
    confirmed = 0
    synth_ok = walk_first or profile.ent_synthesize_from_walk
    for short, n in counts.items():
        ent = entities_by_short.get(short)
        if not ent:
            if not synth_ok:
                continue
            ent = _ensure_entity(entities_by_short, short, vendor=profile.vendor,
                                 family=family or "", technology=profile.technology,
                                 firmware=[])
        _verify_entity(ent, source, {"via": "entPhysicalTable", "instances": n,
                                     "samples": [s for s in samples[short] if s]})
        confirmed += 1
        findings.add({"trigger": "entity_confirmed", "entity": short, "instances": n,
                      "via": "entPhysicalTable",
                      "catalog_action": f"status=verified para {short} (hardware real)",
                      "severity": "low"})
    return confirmed


# --- puertos + validación de bit_calculation ----------------------------------
def classify_ifname(name: str, profile: Optional[VendorProfile] = None) -> Optional[str]:
    p = _profile(profile)
    low = (name or "").lower()
    if any(k in low for k in p.pon_keywords):          # gpon/pon-onu → puerto PON
        return "pon_port"
    if any(k in low for k in p.uplink_keywords):
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
                         walk: dict[str, dict], source: str, findings: Findings,
                         profile: Optional[VendorProfile] = None,
                         walk_first: bool = False, family: Optional[str] = None) -> None:
    """Confirma entidades de puerto por ifName y valida bit_calculation con ifIndex real."""
    profile = _profile(profile)
    if_rows = extract_if_names(walk)
    counts: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    for name in if_rows.values():
        short = classify_ifname(name, profile)
        if not short:
            continue
        counts[short] += 1
        if len(samples[short]) < 5:
            samples[short].append(name)
    for short, n in counts.items():
        ent = entities_by_short.get(short)
        if not ent:
            if not walk_first:
                continue
            ent = _ensure_entity(entities_by_short, short, vendor=profile.vendor,
                                 family=family or "", technology=profile.technology,
                                 firmware=[])
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
    # backlog #4: un ifName clasificado pon_port/uplink_port que no se pudo
    # descomponer (ifname.regex del perfil no matchea, o el fallback de 3
    # números tampoco aplica) ya NO desaparece en silencio.
    total_by_short: Counter = Counter()
    unparsed_count: Counter = Counter()
    unparsed_samples: dict[str, list[str]] = defaultdict(list)
    for ifindex, name in if_rows.items():
        short = classify_ifname(name, profile)
        if not short:
            continue
        total_by_short[short] += 1
        parsed = _ifname_indices(name, profile)
        if parsed:
            try:
                pairs.append((int(ifindex), parsed, name))
            except ValueError:
                parsed = None
        if not parsed:
            unparsed_count[short] += 1
            if len(unparsed_samples[short]) < 5:
                unparsed_samples[short].append(name)
    has_regex = bool(profile.ifname_regex)
    for short, n in unparsed_count.items():
        trigger_ifname_unparsed(findings, short, total_by_short[short], n,
                                unparsed_samples[short], has_regex)
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


def _ifname_indices(name: str, profile: Optional[VendorProfile] = None) -> Optional[tuple[int, int, int]]:
    """`gpon_1/2/1` → (rack=1, slot=2, port=1).

    Si el perfil define `ifname.regex` (grupos rack/slot/port) se usa; si no, los
    últimos 3 números del nombre.
    """
    rx = _profile(profile).ifname_regex
    if rx:
        m = re.search(rx, name or "")
        if not m:
            return None
        try:
            return int(m.group("rack")), int(m.group("slot")), int(m.group("port"))
        except (IndexError, ValueError):
            return None
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


# Compatibilidad: ramas de software del perfil heredado (antes constantes del módulo).
_LEGACY_SW = (_profile(None).software_branches or {})
SOFTWARE_ALT_BRANCH = _LEGACY_SW.get("alt_branch", "")


def _short_oid(oid: str) -> str:
    """`1.3.6.1.4.1.<ent>.1015.2.1.2.4` → `1015.2.1.2.4` (sin el prefijo enterprise)."""
    arcs = oid.strip(".").split(".")
    return ".".join(arcs[7:]) if arcs[:6] == ["1", "3", "6", "1", "4", "1"] and len(arcs) > 7 else oid.strip(".")


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
                           findings: Findings, source: str = "enterprise_ascii",
                           profile: Optional[VendorProfile] = None) -> int:
    """Confirma componentes de índice tipo string con instancias reales del walk enterprise.

    Los índices de software/parche (rama 20.30) se codifican como cadena ASCII en el OID.
    El ifXTable no los ve, pero el walk enterprise sí: se decodifica la cola ASCII de las
    instancias reales y, si hay muestras legibles, se valida el componente. Devuelve nº OIDs.
    """
    # ¿el equipo expone el software en la rama alternativa conocida del perfil?
    sw = _profile(profile).software_branches or {}
    alt_branch = sw.get("alt_branch") or ""
    catalog_prefix = sw.get("catalog_prefix") or ""
    alt_samples = _ascii_samples_under(alt_branch, sorted_walk) if alt_branch else []
    pending = ({"candidate_source": alt_branch,
                "evidence_samples": alt_samples,
                "action": f"mapear la tabla de software del catálogo ({_short_oid(catalog_prefix)}) a la rama "
                          f"real del equipo ({_short_oid(alt_branch)}) y validar los índices ASCII allí"}
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
            if (not samples and catalog_prefix and alt_samples
                    and o.get("oid", "").startswith(catalog_prefix)):
                # la tabla teórica del catálogo no responde en este equipo, pero la rama
                # alternativa real del perfil sí trae inventario de software/patch —
                # se confirma el concepto vía esa evidencia, en vez de dejarlo "absent".
                for c in str_comps:
                    c["validated"] = True
                    c["source"] = f"{source}_alt_branch"
                    c["samples"] = alt_samples
                    c["note"] = (f"tabla propia sin instancias en el walk; confirmado vía "
                                 f"rama alternativa real {alt_branch}")
                    c.pop("reason", None)
                    c.pop("pending_validation", None)
                _annotate_components(idx)
                confirmed += 1
                findings.add({
                    "trigger": "ascii_index_validation",
                    "oid": o.get("oid", ""),
                    "components": [c["name"] for c in str_comps],
                    "samples": alt_samples,
                    "via_alt_branch": alt_branch,
                    "catalog_action": ("índice ASCII confirmado vía rama alternativa real "
                                       f"{alt_branch} (tabla propia sin instancias)"),
                    "severity": "low",
                })
                continue
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
IF_OPER_ENUM = {"1": "up", "2": "down", "3": "testing", "4": "unknown",
                "5": "dormant", "6": "notPresent", "7": "lowerLayerDown"}
IF_ADMIN_ENUM = {"1": "up", "2": "down", "3": "testing"}


def _iftable_col(walk: dict[str, dict], col: str) -> dict[str, str]:
    """{ifIndex: valor} para la columna IF_TABLE.<col>."""
    prefix = f"{IF_TABLE}.{col}."
    return {oid[len(prefix):]: data.get("value", "")
            for oid, data in walk.items() if oid.startswith(prefix)}


def _pon_port_index(pidx: Optional[dict]) -> dict:
    """Índice de los OIDs de ifTable a nivel de PON port, según el perfil.

    Con fórmula verificada en el perfil → índice compuesto; sin ella no se afirma
    ninguna fórmula (el ifIndex se usa tal cual).
    """
    if pidx and pidx.get("formula"):
        return {"type": "composite", "bit_calculation": True,
                "decoder": "community_formula", "space": pidx.get("space", "ONU-ID"),
                "formula": pidx["formula"], "shelf": pidx.get("shelf", 1),
                "onu_id_append": False,
                "note": "nivel puerto: ifIndex = suffix (sin onuID)",
                "validated": True, "source": "ifTable", "status": _STATUS_WALK}
    return {"type": "simple", "bit_calculation": False,
            "note": "nivel puerto: ifIndex tal cual (sin fórmula de índice verificada para este vendor)",
            "validated": False, "source": "ifTable", "status": _STATUS_WALK}


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
                           vendor: str | None = None, technology: str = "gpon",
                           family: str | None = None,
                           profile: Optional[VendorProfile] = None,
                           walk_first: bool = False) -> None:
    """Mapea ifOperStatus/ifType del ifTable a la operación de PON ports.

    PON port / uplink se reconocen por el ifType del perfil (IANAifType: gpon=250,
    ethernetCsmacd=6). Enriquece las entidades y agrega los OIDs operativos
    (oper/admin/type) como verified_walk para que getPonPorts() sepa qué consultar.
    """
    profile = _profile(profile)
    vendor = vendor or profile.vendor
    pon_t, upl_t = str(profile.iftype_pon), str(profile.iftype_uplink)
    iftype = _iftable_col(walk, "3")
    ifoper = _iftable_col(walk, "8")
    if not ifoper:
        return

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    pon_idx = [i for i, t in iftype.items() if str(t).strip() == pon_t] or list(ifoper)
    up = sum(1 for i in pon_idx if _int(ifoper.get(i)) == 1)
    down = sum(1 for i in pon_idx if _int(ifoper.get(i)) == 2)

    ent = entities_by_short.get("pon_port")
    if not ent and walk_first and pon_idx:
        ent = _ensure_entity(entities_by_short, "pon_port", vendor=vendor,
                             family=family or "", technology=technology, firmware=[])
    if ent:
        ent["status"] = _STATUS_WALK
        c = ent.setdefault("confidence", {})
        c["overall"] = round(min(1.0, (c.get("overall") or 0.0) + 0.15), 3)
        ent["empirical"] = {**(ent.get("empirical") or {}),
                            "oper_via": f"ifTable (ifType={pon_t})", "pon_ports": len(pon_idx),
                            "oper_up": up, "oper_down": down, "source": source}
    upl = [i for i, t in iftype.items() if str(t).strip() == upl_t]
    e2 = entities_by_short.get("uplink_port")
    if not e2 and walk_first and upl:
        e2 = _ensure_entity(entities_by_short, "uplink_port", vendor=vendor,
                            family=family or "", technology=technology, firmware=[])
    if upl and e2:
        e2["status"] = _STATUS_WALK
        e2["empirical"] = {**(e2.get("empirical") or {}), "via": f"ifTable (ifType={upl_t})",
                           "ports": len(upl), "source": source}

    pon_ref = build_entity_id(vendor, technology, "port", "pon_port")
    grp = _port_group(oid_groups, pon_ref, vendor, family)
    pidx = profile.pon_port_index
    existing = {o.get("oid") for g in oid_groups for o in g.get("oids", [])}
    cols = [(f"{IF_TABLE}.8", "oper_status", IF_OPER_ENUM,
             "estado operativo real por PON port (IF-MIB ifOperStatus); 1=up, 2=down"),
            (f"{IF_TABLE}.7", "admin_status", IF_ADMIN_ENUM,
             "estado administrativo por PON port (IF-MIB ifAdminStatus)"),
            (f"{IF_TABLE}.3", "if_type", None,
             f"tipo de interfaz ({pon_t}=gpon PON port, {upl_t}=uplink)")]
    for oid_str, attr, enum, desc in cols:
        if oid_str in existing:
            continue
        grp["oids"].append({
            "id": build_oid_id(vendor, technology, "pon_port", attr),
            "oid": oid_str, "name": "UNRESOLVED", "mib_name": "IF-MIB", "attribute": attr,
            "entity_ref": pon_ref, "mib_table": "ifTable",
            "index": _pon_port_index(pidx),
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
                  "catalog_action": f"pon_port.oper mapeado desde ifOperStatus (ifType={pon_t})",
                  "severity": "low"})


def derive_pon_onu_count(entities_by_short: dict[str, dict], enterprise_sorted: list[str],
                         findings: Findings, profile: Optional[VendorProfile] = None) -> None:
    """Deriva ONUs por PON port contando instancias de la tabla ONU del perfil.

    `onu_count_source.oid` es el prefijo (con punto final) tras el cual el OID trae
    `<...>.<port>.<onu>`; `port_pos`/`onu_pos` dicen en qué posición. Sin fuente en
    el perfil no se deriva nada.
    """
    src = _profile(profile).onu_count_source
    if not src or not src.get("oid"):
        return
    prefix = src["oid"]
    port_pos, onu_pos = int(src.get("port_pos", 0)), int(src.get("onu_pos", 1))
    label = src.get("label") or prefix.strip(".")
    per_port: dict[str, set] = defaultdict(set)
    for oid in enterprise_sorted:
        if oid.startswith(prefix):
            rest = oid[len(prefix):].split(".")
            if len(rest) > max(port_pos, onu_pos):
                per_port[rest[port_pos]].add(rest[onu_pos])
    if not per_port:
        return
    counts = [len(v) for v in per_port.values()]
    total = sum(counts)
    ent = entities_by_short.get("pon_port")
    if ent:
        ent.setdefault("empirical", {})["onu_count"] = {
            "derived": True, "status": _STATUS_WALK,
            "source": f"conteo por puerto en la tabla ONU {label}",
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
