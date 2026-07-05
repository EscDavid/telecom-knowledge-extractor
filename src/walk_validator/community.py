"""Fase 2 — ingesta de fuentes de validación 'community'.

Una fuente community (docs/validation/community/*.txt) es un extracto curado en
formato field:value que aporta SOLO lo que al catálogo le falta y que fue validado
contra hardware real: la fórmula del índice compuesto, leaves operativos de ONU,
enums de estado y la conversión óptica. No es un doc_type de Fase 1 ni un walk crudo;
se aplica como capa de correlación sobre el catálogo enriquecido.

Soporta dos clases de bloque:
  - [oid] con status/note por entrada (verified_walk | verified_community).
  - downgrade_status: degrada OIDs existentes (ej. .1082 ausentes en el walk) con nota.
  - optical_scale: resuelve la escala óptica (verified_walk) y limpia el conflicto.

Diseño:
  parse_community(path)  → estructura (meta, index_spaces, oids, optical, enums,
                           downgrade, snmp)
  apply_community(...)   → muta los grupos de OIDs del catálogo.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..ids import build_oid_id
from .triggers import Findings

STATUS_WALK = "verified_walk"            # confirmado por el walk real
STATUS_COMMUNITY = "verified_community"  # confirmado por implementación en hardware

_INLINE_COMMENT = re.compile(r"\s{2,}#.*$")
_INDEX_SPACE = re.compile(r"^index_space:\s*(\S+)")
_OPTICAL = re.compile(r"^optical\w*:")
_ENUM_HEADER = re.compile(r"^([a-zA-Z_]+_enum):")
_ENUM_ROW = re.compile(r"^(\d+|default):\s*(.+)$")
_KV = re.compile(r"^([a-zA-Z_]+):\s*(.*)$")


def _truthy(v: Any) -> bool:
    return bool(v) and str(v).strip().lower().startswith(("s", "y", "true"))


def parse_community(path: Path) -> dict[str, Any]:
    """Parsea el extracto community a una estructura navegable."""
    meta: dict[str, Any] = {}
    index_spaces: dict[str, dict] = {}
    oids: list[dict] = []
    optical: dict[str, Any] = {}
    enums: dict[str, dict] = {}
    downgrade: dict[str, Any] = {}
    snmp: dict[str, Any] = {}

    ctx = "meta"
    cur: dict = meta          # dict que se está llenando
    cur_key: str | None = None

    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = _INLINE_COMMENT.sub("", raw).rstrip()
        stripped = line.strip()
        if not stripped or set(stripped) == {"="}:
            continue
        if stripped.startswith(("# SECCIÓN 5", "# SECCION 5")):
            ctx, cur, cur_key = "snmp", snmp, None
            continue
        if stripped.startswith("#"):
            continue

        if stripped == "[oid]":
            cur = {}
            oids.append(cur)
            ctx, cur_key = "oid", None
            continue
        m = _INDEX_SPACE.match(stripped)
        if m:
            cur = {}
            index_spaces[m.group(1)] = cur
            ctx, cur_key = "index", None
            continue
        if _OPTICAL.match(stripped):
            ctx, cur, cur_key = "optical", optical, None
            continue
        m = _ENUM_HEADER.match(stripped)
        if m:
            cur = {}
            enums[m.group(1)] = cur
            ctx, cur_key = "enum", None
            continue
        if stripped.startswith("downgrade_status:"):
            ctx, cur, cur_key = "downgrade", downgrade, None
            continue

        if ctx == "enum":
            em = _ENUM_ROW.match(stripped)
            if em:
                cur[em.group(1)] = em.group(2).strip()
            continue
        if ctx == "downgrade" and stripped.startswith("- "):
            cur.setdefault("affected_oids", []).append(stripped[2:].strip())
            cur_key = None
            continue

        kv = _KV.match(stripped)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            if ctx == "meta" and key == "families":
                cur[key] = [f.strip() for f in val.split(",")]
            elif key == "affected_oids":
                cur[key] = []
                cur_key = key
            else:
                cur[key] = val
                cur_key = key
            continue

        # continuación de un valor multilínea (ej. notas envueltas)
        if cur_key and isinstance(cur.get(cur_key), str):
            cur[cur_key] = (cur[cur_key] + " " + stripped).strip()

    return {"meta": meta, "index_spaces": index_spaces, "oids": oids,
            "optical": optical, "enums": enums, "downgrade": downgrade, "snmp": snmp}


# --- aplicación al catálogo ----------------------------------------------------
def _formula_index(space_name: str, space_def: dict, quirk: str | None,
                   walk_confirmed: bool) -> dict:
    """Índice compuesto decodificado por la FÓRMULA community (reemplaza el bit-map)."""
    idx = {
        "type": "composite",
        "bit_calculation": True,
        "decoder": "community_formula",
        "space": space_name,
        "formula": space_def.get("formula"),
        "applies_to_base": space_def.get("applies_to_base"),
        "shelf": 1,
        "onu_id_append": True,
        "ranges": space_def.get("ranges"),
        "validated": True,
        "source": "community",
        "status": STATUS_WALK if walk_confirmed else STATUS_COMMUNITY,
        "supersedes": "bit_map",
    }
    if quirk:
        idx["index_quirk"] = quirk
    return idx


def _resolve_enum(ce: dict, enums: dict) -> dict | None:
    ref = ce.get("enumeration", "")
    # nombre más largo primero (evita que 'status_enum' gane sobre 'onu_status_type_enum')
    for name in sorted(enums, key=len, reverse=True):
        if name in ref:
            return enums[name]
    return None


def _find_onu_group(oid_groups: list[dict], entity_ref: str) -> dict | None:
    for g in oid_groups:
        if g.get("entity_ref") == entity_ref:
            return g
    return None


def _unique_id(base_id: str, space: str, used: set[str]) -> str:
    """Evita colisiones de id cuando dos OIDs distintos comparten atributo."""
    if base_id not in used:
        return base_id
    slug = re.sub(r"[^a-z0-9]+", "_", (space or "alt").lower()).strip("_")
    cand = f"{base_id}_{slug}"
    n = 2
    while cand in used:
        cand, n = f"{base_id}_{slug}{n}", n + 1
    return cand


def apply_community(oid_groups: list[dict], community: dict, family: str,
                    findings: Findings, *, walk_confirmed: bool = True,
                    vendor: str = "ZTE", technology: str = "gpon",
                    index_spaces: dict | None = None) -> dict:
    """Aplica la fuente community al catálogo (muta oid_groups). Devuelve resumen."""
    spaces = index_spaces or community["index_spaces"]
    enums = community["enums"]
    optical = community.get("optical", {})
    scale_resolved = _truthy(optical.get("resolves_conflict"))
    existing = {o.get("oid"): o for g in oid_groups for o in g.get("oids", [])}
    used_ids = {o.get("id") for g in oid_groups for o in g.get("oids", [])}
    stats = {"added": 0, "updated": 0, "conflicts": 0,
             "downgraded": 0, "resolved_conflicts": 0}

    for ce in community["oids"]:
        attr = ce.get("attribute", "")
        space = ce.get("base_space", "ONU-ID")
        oid_str = (ce.get("oid_prefix") or "").lstrip(".")
        entity_ref = ce.get("entity_ref", "entity.zte.gpon.device.onu")
        status = ce.get("status") or STATUS_COMMUNITY
        # El índice (la fórmula) es verified_walk: el walk lo confirma (285278721=
        # gpon_1/2/1). Es independiente del status del LEAF (que puede ser community).
        idx = _formula_index(space, spaces.get(space, {}), ce.get("index_quirk"),
                             walk_confirmed=walk_confirmed)

        d = {
            "id": _unique_id(build_oid_id(vendor, technology, "onu", attr), space, used_ids),
            "oid": oid_str,
            "name": "UNRESOLVED",
            "mib_name": ce.get("mib_name", "UNRESOLVED"),
            "attribute": attr,
            "entity_ref": entity_ref,
            "mib_table": None,
            "index": idx,
            "syntax": ce.get("syntax"),
            "unit": ce.get("unit"),
            "scale": None,
            "access": ce.get("access", "read-only"),
            "enumeration": _resolve_enum(ce, enums),
            "description": "leaf operativo de ONU (fuente community, validado en hardware)",
            "full_oid_template": ce.get("full_oid_template"),
            "command_ref": None,
            "status": status,
            "sources": [{"doc_type": "community", "pages": None, "confidence": 0.0}],
            "confidence": {"extraction": 0.9 if status == STATUS_WALK else 0.85,
                           "correlation": 0.0,
                           "overall": 0.9 if status == STATUS_WALK else 0.85},
            "provenance": f"community: {community['meta'].get('source_repo', '')}".strip(": "),
            "conflicts": [],
        }
        if ce.get("note"):
            d["note"] = ce["note"]

        scale = ce.get("scale", "")
        if scale.startswith("raw"):
            d["scale_formula"] = scale
            if scale_resolved or status == STATUS_WALK:
                d["scale_status"] = STATUS_WALK      # escala confirmada por walk
            else:
                d["conflicts"].append({
                    "field": "scale", "source_a": f"community: {scale}",
                    "source_b": "catálogo TKC: scale=null / SmartOLT: ÷100",
                    "resolution": "unresolved", "severity": "medium"})
                stats["conflicts"] += 1
        elif "UNRESOLVED" in scale:
            d["scale_formula"] = "UNRESOLVED"

        group = _find_onu_group(oid_groups, entity_ref)
        if group is None:
            group = {"entity_ref": entity_ref, "vendor": vendor, "family": family,
                     "firmware": [], "oids": []}
            oid_groups.append(group)
        if oid_str in existing:
            existing[oid_str].update(d)
            stats["updated"] += 1
        else:
            group["oids"].append(d)
            existing[oid_str] = d
            used_ids.add(d["id"])
            stats["added"] += 1

    # --- downgrade de OIDs existentes (ej. .1082 ausentes en el walk) ---------
    dg = community.get("downgrade") or {}
    if dg.get("affected_oids"):
        new_status = dg.get("new_status", STATUS_COMMUNITY)
        note = dg.get("note", "").strip('"')
        for aoid in dg["affected_oids"]:
            o = existing.get(aoid.lstrip("."))
            if not o:
                continue
            o["status"] = new_status
            o["variant_note"] = note
            for c in o.get("conflicts", []):
                if c.get("field") == "scale" and c.get("resolution") == "unresolved":
                    c["resolution"] = "resolved: escala confirmada en espacio TYPE (.1012)"
                    stats["resolved_conflicts"] += 1
            stats["downgraded"] += 1

    findings.add({
        "trigger": "community_ingest",
        "family": family,
        "source": community["meta"].get("supersedes_partial") or "community",
        "oids": stats["added"] + stats["updated"],
        "downgraded": stats["downgraded"],
        "scale_resolved": scale_resolved,
        "catalog_action": "leaves de ONU + fórmula de índice; escala/estado reconciliados con el walk",
        "severity": "low",
    })
    return {"stats": stats, "index_spaces": spaces, "snmp": community["snmp"],
            "optical": optical, "scale_resolved": scale_resolved}
