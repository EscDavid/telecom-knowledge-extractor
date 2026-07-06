"""Loader — inserta un catalogo JSON en ispm_tkc, idempotente por version.

Los mappers (`*_row`) son funciones puras JSON->columnas (testeables sin DB). La
clase `Loader` hace la IO: taxonomia, version, replace por catalog_version_id y los
INSERT en orden de FK. `raw_json` guarda el artefacto completo (red de seguridad).
Refs sin FK (command_ref, oid_ref, alarm oid_refs) se validan contra lo cargado.
"""
from __future__ import annotations

import json
from pathlib import Path


def _J(x):
    return json.dumps(x, ensure_ascii=False) if x is not None else None


def _conf(a):
    c = a.get("confidence", {}) or {}
    return (c.get("extraction", 0) or 0, c.get("correlation", 0) or 0, c.get("overall", 0) or 0)


# --- mappers puros (JSON -> dict de columnas) --------------------------------
def entity_row(e, vid, fid, cvid, fw):
    ex, co, ov = _conf(e)
    lc = e.get("lifecycle", {}) or {}
    return {
        "id": e["id"], "canonical_name": (e.get("canonical_name") or "")[:150],
        "vendor_id": vid, "family_id": fid, "catalog_version_id": cvid,
        "technology": e.get("technology", "gpon"), "entity_type": e.get("type", "logical"),
        "description": e.get("description"), "is_critical": bool(e.get("is_critical")),
        "confidence_extraction": ex, "confidence_correlation": co, "confidence_overall": ov,
        "status": e.get("status", "observed"),
        "lifecycle_introduced_in": fw.get(lc.get("introduced_in")),
        "lifecycle_deprecated_in": fw.get(lc.get("deprecated_in")),
        "lifecycle_removed_in": fw.get(lc.get("removed_in")),
        "lifecycle_status": lc.get("status", "introduced"),
        "replacement_id": e.get("replacement_id"), "raw_json": _J(e),
    }


def command_row(c, vid, fid, cvid):
    ex, co, ov = _conf(c)
    return {
        "id": c["id"], "canonical_name": (c.get("canonical_name") or "")[:200],
        "vendor_id": vid, "family_id": fid, "catalog_version_id": cvid,
        "technology": c.get("technology", "gpon"), "category": c.get("category", "show"),
        "cli_mode": c.get("cli_mode", "privileged_exec"), "entity_ref": c.get("entity_ref"),
        "description": c.get("description"), "syntax": (c.get("syntax") or "")[:500],
        "confidence_extraction": ex, "confidence_correlation": co, "confidence_overall": ov,
        "status": c.get("status", "documented"), "lifecycle_status": "stable", "raw_json": _J(c),
    }


def oid_row(o, cvid):
    ex, co, ov = _conf(o)
    idx = o.get("index", {}) or {}
    return {
        "id": o["id"], "oid_string": (o.get("oid") or "")[:200], "name": (o.get("name") or "")[:200],
        "mib_table": o.get("mib_table"), "entity_ref": o.get("entity_ref"),
        "command_ref": o.get("command_ref"), "catalog_version_id": cvid,
        "syntax": (o.get("syntax") or "")[:255], "unit": (o.get("unit") or None) and o["unit"][:30],
        "scale": o.get("scale"), "access": o.get("access", "read-only"),
        "index_type": idx.get("type", "simple"), "bit_calculation": bool(idx.get("bit_calculation")),
        "index_def": _J(idx) if idx else None,
        "enumeration": _J(o.get("enumeration")) if o.get("enumeration") else None,
        "description": o.get("description"), "attribute": (o.get("attribute") or None),
        "scale_formula": (o.get("scale_formula") or None), "full_oid_template": o.get("full_oid_template"),
        "empirical": _J(o.get("empirical")) if o.get("empirical") else None,
        "pending_validation": _J(o.get("pending_validation")) if o.get("pending_validation") else None,
        "confidence_extraction": ex, "confidence_correlation": co, "confidence_overall": ov,
        "status": o.get("status", "observed"), "lifecycle_status": "stable", "raw_json": _J(o),
    }


def relation_row(r, cvid):
    ex, co, ov = _conf(r)
    return {
        "id": r["id"], "source_entity": r["source_entity"], "relation_type": r.get("type"),
        "target_entity": r.get("target"), "cardinality": r.get("cardinality", "many_to_one"),
        "required": bool(r.get("required")), "prerequisite": bool(r.get("prerequisite")),
        "creation_order": r.get("creation_order"), "catalog_version_id": cvid,
        "description": r.get("description"),
        "confidence_extraction": ex, "confidence_correlation": co, "confidence_overall": ov,
        "status": r.get("status", "documented"), "raw_json": _J(r),
    }


def alarm_row(a, cvid):
    ex, co, ov = _conf(a)
    th = a.get("threshold") or {}
    es = a.get("escalation") or {}
    th = th if isinstance(th, dict) else {}
    es = es if isinstance(es, dict) else {}
    return {
        "id": a["id"], "code": (a.get("code") or "")[:50], "name": (a.get("name") or "")[:100],
        "canonical_name": (a.get("canonical_name") or "")[:200], "entity_ref": a.get("entity_ref"),
        "catalog_version_id": cvid, "severity": a.get("severity", "warning"),
        "alarm_type": a.get("type", "protocol"), "description": a.get("description"),
        "oid_trap": a.get("oid_trap"), "auto_clear": bool(a.get("auto_clear")),
        "clear_condition": a.get("clear_condition"),
        "threshold_metric": th.get("metric"), "threshold_operator": th.get("operator"),
        "threshold_value": th.get("value"), "threshold_unit": th.get("unit"),
        "escalation_warning_min": es.get("warning_min"), "escalation_major_min": es.get("major_min"),
        "escalation_critical_min": es.get("critical_min"),
        "probable_causes": _J(a.get("probable_causes") or []),
        "remediation": _J(a.get("remediation") or []),
        "confidence_extraction": ex, "confidence_correlation": co, "confidence_overall": ov,
        "status": a.get("status", "documented"), "raw_json": _J(a),
    }


# --- IO ----------------------------------------------------------------------
def _load_group(catalog_dir: Path, name: str, key):
    items = []
    d = catalog_dir / name
    if d.exists():
        for f in sorted(d.rglob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            items += data.get(key, []) if key else [data]
    return items


def _load_relations(catalog_dir: Path):
    """Cada archivo de relations/ agrupa varias relaciones bajo un `entity_ref` comun
    (la entidad origen); los items de la lista no lo repiten, asi que hay que
    propagarlo como `source_entity` de cada relacion."""
    items = []
    d = catalog_dir / "relations"
    if d.exists():
        for f in sorted(d.rglob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            source = data.get("entity_ref")
            for r in data.get("relations", []) or []:
                r.setdefault("source_entity", source)
                items.append(r)
    return items


class Loader:
    def __init__(self, conn):
        self.conn = conn

    # ---- taxonomia / version ----
    def _ensure(self, cur, table, key_cols, key_vals, extra=None):
        cols = list(key_cols) + list((extra or {}).keys())
        vals = list(key_vals) + list((extra or {}).values())
        ph = ",".join(["%s"] * len(cols))
        cur.execute(f"INSERT IGNORE INTO {table} ({','.join(cols)}) VALUES ({ph})", vals)
        where = " AND ".join(f"{c}=%s" for c in key_cols)
        cur.execute(f"SELECT id FROM {table} WHERE {where}", key_vals)
        return cur.fetchone()["id"]

    def _version(self, cur, vid, fid, version_label, content_hash, tier):
        # idempotente por version_label: recargar la misma etiqueta reemplaza su fila;
        # una etiqueta NUEVA obtiene un version_num correlativo (historia inmutable).
        cur.execute("SELECT id FROM tkc_catalog_versions WHERE vendor_id=%s AND family_id=%s "
                    "AND version_label=%s", (vid, fid, version_label))
        row = cur.fetchone()
        if row:
            cvid = row["id"]
            cur.execute("UPDATE tkc_catalog_versions SET content_hash=%s, tier=%s WHERE id=%s",
                        (content_hash, tier, cvid))
        else:
            cur.execute("SELECT COALESCE(MAX(version_num),0)+1 AS n FROM tkc_catalog_versions "
                        "WHERE vendor_id=%s AND family_id=%s", (vid, fid))
            vnum = cur.fetchone()["n"]
            cur.execute("INSERT INTO tkc_catalog_versions (vendor_id,family_id,version_num,"
                        "version_label,content_hash,tier) VALUES (%s,%s,%s,%s,%s,%s)",
                        (vid, fid, vnum, version_label, content_hash, tier))
            cvid = cur.lastrowid
        return cvid

    def _wipe_version(self, cur, cvid):
        """Borra los artefactos de esa version (los hijos caen por ON DELETE CASCADE)."""
        for table in ("tkc_results", "tkc_alarms", "tkc_relations", "tkc_oids",
                      "tkc_commands", "tkc_entities"):
            cur.execute(f"DELETE FROM {table} WHERE catalog_version_id=%s", (cvid,))

    @staticmethod
    def _insert(cur, table, row):
        cols = list(row.keys())
        ph = ",".join(["%s"] * len(cols))
        cur.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})",
                    [row[c] for c in cols])

    def load(self, catalog_dir, vendor, family, technology, version, content_hash, tier=1) -> dict:
        catalog_dir = Path(catalog_dir)
        entities = _load_group(catalog_dir, "entities", None)
        commands = _load_group(catalog_dir, "commands", None)
        oids = _load_group(catalog_dir, "oids", "oids")
        relations = _load_relations(catalog_dir)
        alarms = _load_group(catalog_dir, "alarms", "alarms")
        results = []
        rf = catalog_dir / "results.json"
        if rf.exists():
            data = json.loads(rf.read_text(encoding="utf-8"))
            results = data if isinstance(data, list) else data.get("findings", [])

        ent_ids = {e["id"] for e in entities}
        oid_ids = {o["id"] for o in oids}
        cmd_ids = {c["id"] for c in commands}

        cur = self.conn.cursor()
        vid = self._ensure(cur, "tkc_vendors", ["name"], [vendor])
        fid = self._ensure(cur, "tkc_families", ["vendor_id", "name"], [vid, family],
                           {"technology": technology})
        # firmwares presentes en los artefactos -> {version: id}
        fw_versions = set()
        for coll in (entities, commands):
            for a in coll:
                fw_versions.update(a.get("firmware", []) or [])
        for g in _iter_groups(catalog_dir):
            fw_versions.update(g.get("firmware", []) or [])
        fw = {}
        for v in sorted(x for x in fw_versions if x):
            fw[v] = self._ensure(cur, "tkc_firmwares", ["family_id", "version"], [fid, v])

        cvid = self._version(cur, vid, fid, version, content_hash, tier)
        self._wipe_version(cur, cvid)

        # 1) entidades (+ hijos)
        for e in entities:
            self._insert(cur, "tkc_entities", entity_row(e, vid, fid, cvid, fw))
            for v in e.get("firmware", []) or []:
                if v in fw:
                    self._insert(cur, "tkc_entity_firmware",
                                 {"entity_id": e["id"], "catalog_version_id": cvid, "firmware_id": fw[v]})
            for al in e.get("aliases", []) or []:
                self._insert(cur, "tkc_aliases", {
                    "entity_ref": e["id"], "catalog_version_id": cvid,
                    "alias": (al.get("name") or "")[:150],
                    "source_doc_type": (al.get("source") or "mib_file")[:50], "status": "assigned"})
            for at in e.get("attributes", []) or []:
                if isinstance(at, dict) and at.get("name"):
                    self._insert(cur, "tkc_entity_attributes", {
                        "entity_id": e["id"], "catalog_version_id": cvid, "name": at["name"][:100],
                        "attr_type": (at.get("type") or "string")[:50],
                        "range_def": at.get("range"), "required": bool(at.get("required")),
                        "source_doc_type": at.get("source")})
        # 2) comandos (+ hijos)
        for c in commands:
            if c.get("entity_ref") and c["entity_ref"] not in ent_ids:
                c = {**c, "entity_ref": None}
            self._insert(cur, "tkc_commands", command_row(c, vid, fid, cvid))
            for p in c.get("parameters", []) or []:
                self._insert(cur, "tkc_command_params", {
                    "command_id": c["id"], "catalog_version_id": cvid,
                    "name": (p.get("name") or "")[:100],
                    "param_type": (p.get("type") or "string")[:50], "pattern": p.get("pattern"),
                    "range_def": p.get("range"), "required": bool(p.get("required")),
                    "description": p.get("description"), "example": p.get("example")})
            for of in c.get("output_fields", []) or []:
                ref = of.get("oid_ref")
                self._insert(cur, "tkc_command_output_fields", {
                    "command_id": c["id"], "catalog_version_id": cvid,
                    "name": (of.get("name") or "")[:100],
                    "field_type": (of.get("type") or "string")[:50], "unit": of.get("unit"),
                    "oid_ref": ref if ref in oid_ids else None,
                    "oid_status": of.get("oid_status", "not_mapped")})
            for v in c.get("firmware", []) or []:
                if v in fw:
                    self._insert(cur, "tkc_command_firmware",
                                 {"command_id": c["id"], "catalog_version_id": cvid, "firmware_id": fw[v]})
        # 3) OIDs (+ firmware). command_ref soft-validado. entity_ref viene del grupo
        # (el archivo agrupa varios OIDs bajo un entity_ref comun que no se repite
        # por item); se propaga aca igual que el source_entity de las relaciones.
        for grp in _iter_groups(catalog_dir):
            gfw = grp.get("firmware", []) or []
            gentity = grp.get("entity_ref")
            for o in grp.get("oids", []):
                o = {**o, "entity_ref": o.get("entity_ref") or gentity}
                if o["entity_ref"] not in ent_ids:
                    continue                    # FK entity_ref NOT NULL: skip huerfano
                if o.get("command_ref") and o["command_ref"] not in cmd_ids:
                    o["command_ref"] = None
                self._insert(cur, "tkc_oids", oid_row(o, cvid))
                for v in gfw:
                    if v in fw:
                        self._insert(cur, "tkc_oid_firmware",
                                     {"oid_id": o["id"], "catalog_version_id": cvid, "firmware_id": fw[v]})
        # 4) relaciones (source/target deben existir)
        for r in relations:
            if r.get("source_entity") in ent_ids and r.get("target") in ent_ids:
                self._insert(cur, "tkc_relations", relation_row(r, cvid))
        # 5) alarmas (+ oid_refs validados, firmware)
        for a in alarms:
            if a.get("entity_ref") and a["entity_ref"] not in ent_ids:
                continue                    # FK entity_ref NOT NULL: skip huerfana
            self._insert(cur, "tkc_alarms", alarm_row(a, cvid))
            for ref in a.get("oid_refs", []) or []:
                if ref in oid_ids:
                    self._insert(cur, "tkc_alarm_oid_refs",
                                 {"alarm_id": a["id"], "oid_id": ref, "catalog_version_id": cvid})
            for v in a.get("firmware", []) or []:
                if v in fw:
                    self._insert(cur, "tkc_alarm_firmware",
                                 {"alarm_id": a["id"], "catalog_version_id": cvid, "firmware_id": fw[v]})
        # 6) results
        art_ids = ent_ids | oid_ids | cmd_ids | {r["id"] for r in relations} | {a["id"] for a in alarms}
        for res in results:
            aid = res.get("artifact_id", "")
            self._insert(cur, "tkc_results", {
                "result_type": res.get("result_type", "orphan"),
                "artifact_type": res.get("artifact_type", "oid"),
                "artifact_id": aid[:200], "vendor_id": vid, "catalog_version_id": cvid,
                "resolved": bool(res.get("resolved")), "payload": _J(res.get("payload", res))})

        cur.close()
        return {"entities": len(entities), "commands": len(commands), "oids": len(oids),
                "relations": len(relations), "alarms": len(alarms), "catalog_version_id": cvid}


def _iter_groups(catalog_dir: Path):
    d = catalog_dir / "oids"
    if d.exists():
        for f in sorted(d.rglob("*.json")):
            yield json.loads(f.read_text(encoding="utf-8"))
