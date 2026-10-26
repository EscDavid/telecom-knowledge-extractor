"""Verificador de contrato del catálogo (puerta antes de cargar a ispm_tkc).

Comprueba, por familia:
  1. Integridad: ids únicos, sin huérfanos (entity_ref, oid_ref, related_commands), firmware uniforme, sin nombres UNRESOLVED
     ni unidades con multiplicador embebido ("0.001 dBm").
  2. Contrato de consumo (docs/validation/consumer_contract.json): cada atributo que lee el importador existe, está verificado,
     su OID cubre las filas de la fixture real anonimizada y el valor se decodifica a algo plausible (serial, enum contra la
     verdad de terreno de la CLI, potencias en dBm, fechas...).
Uso:  [TKC_CATALOG_ROOT=staging/classic_build/catalog] python scripts/catalog_contract_check.py [c620|c600|c320|c300 ...]   (sale con código 1 si algo falla)"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OK_STATUS = {"verified", "verified_walk", "verified_community"}
fails, passes = [], 0


def check(cond, label, detail=""):
    global passes
    if cond:
        passes += 1
    else:
        fails.append(f"{label}: {detail}")
    return cond


def rows(path, prefix=None, match=None):
    out = []
    for l in open(path, errors="ignore"):
        m = re.match(r"^(\.?[\d.]+) = (\w[\w-]*): ?(.*)$", l.rstrip("\n"))
        if not m:
            continue
        oid = m.group(1).lstrip(".")
        if prefix and not oid.startswith(prefix + "."):
            continue
        if match and match not in "." + oid[len(prefix):] + ".":
            continue
        out.append((oid, m.group(2), m.group(3).strip()))
    return out


def val_str(v):
    return v.strip().strip('"')


def sql_enums():
    """ENUM por tabla/columna de database/ispm_tkc.sql."""
    txt = (ROOT / "database/ispm_tkc.sql").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\)\s*ENGINE", txt, re.S):
        for c in re.finditer(r"^\s*(\w+)\s+ENUM\(([^)]*)\)", m.group(2), re.M):
            out.setdefault(m.group(1), {})[c.group(1)] = set(re.findall(r"'([^']*)'", c.group(2)))
    return out


def sql_varchars():
    txt = (ROOT / "database/ispm_tkc.sql").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\)\s*ENGINE", txt, re.S):
        for c in re.finditer(r"^\s*(\w+)\s+VARCHAR\((\d+)\)", m.group(2), re.M):
            out.setdefault(m.group(1), {})[c.group(1)] = int(c.group(2))
    return out


def check_db_enums(fam, base):
    """Cada fila que construiría el loader debe respetar los ENUM de la base (si no, la carga falla a mitad)."""
    sys.path.insert(0, str(ROOT))
    from src.loader import loader as L
    enums = sql_enums()
    items = {
        "tkc_entities": [L.entity_row(json.load(open(f)), 1, 1, 1, {}) for f in glob.glob(str(base / "entities/*.json"))],
        "tkc_commands": [L.command_row(json.load(open(f)), 1, 1, 1) for f in glob.glob(str(base / "commands/*/*.json"))],
        "tkc_oids": [L.oid_row(o, 1) for f in glob.glob(str(base / "oids/*.json")) for o in json.load(open(f))["oids"]],
        "tkc_alarms": [L.alarm_row(a, 1) for a in L._load_group(base, "alarms", "alarms")],
        "tkc_relations": [L.relation_row(r, 1) for r in L._load_relations(base)],
    }
    varchars = sql_varchars()
    for table, rows_ in items.items():
        for col, n in varchars.get(table, {}).items():
            long_ = [r["id"] for r in rows_ if isinstance(r.get(col), str) and len(r[col]) > n]
            check(not long_, f"[{fam}] VARCHAR({n}) {table}.{col}", f"{len(long_)} valores más largos, p. ej. {long_[:2]}")
        for col, allowed in enums.get(table, {}).items():
            bad = sorted({str(r[col]) for r in rows_ if col in r and r[col] is not None and r[col] not in allowed})
            check(not bad, f"[{fam}] ENUM {table}.{col}", f"valores no permitidos {bad} (permitidos: {sorted(allowed)})")


def run(fam_key):
    fam = {"c620": "ZXA10 C620", "c600": "ZXA10 C600", "c320": "ZXA10 C320", "c300": "ZXA10 C300"}[fam_key]
    classic = fam_key in ("c320", "c300")
    FW = ["2.0", "2.1"] if classic else ["1.2.2"]
    contract = json.load(open(ROOT / "docs/validation/consumer_contract.json"))["families"][fam]
    base = Path(os.environ.get("TKC_CATALOG_ROOT", ROOT / "catalog")) / f"zte/zxa10-{fam_key}/catalog-{contract['version']}"
    if not check(base.exists(), f"[{fam}] directorio", str(base)):
        return
    oids, groups = {}, []
    for f in sorted(glob.glob(str(base / "oids/*.json"))):
        g = json.load(open(f)); groups.append(g)
        for o in g["oids"]:
            check(o["id"] not in oids, f"[{fam}] id duplicado", o["id"])
            oids[o["id"]] = {**o, "_group_entity": g.get("entity_ref"), "_group_fw": g.get("firmware")}
    ents = {json.load(open(f))["id"]: json.load(open(f)) for f in glob.glob(str(base / "entities/*.json"))}
    cmds = {}
    for f in glob.glob(str(base / "commands/*/*.json")):
        c = json.load(open(f)); cmds[c["id"]] = c
    # 1) integridad
    for o in oids.values():
        er = o.get("entity_ref") or o["_group_entity"]
        check(er in ents, f"[{fam}] entity_ref huérfano", f"{o['id']} -> {er}")
        check(o["name"] != "UNRESOLVED", f"[{fam}] nombre UNRESOLVED", o["id"])
        check(not re.match(r"^\s*0?\.\d", o.get("unit") or ""), f"[{fam}] unidad con multiplicador", f"{o['id']}: {o.get('unit')}")
        check(o["_group_fw"] == FW, f"[{fam}] firmware de OID", f"{o['id']}: {o['_group_fw']}")
    for c in cmds.values():
        check(c["firmware"] == FW, f"[{fam}] firmware de comando", c["id"])
        check(not c["entity_ref"] or c["entity_ref"] in ents, f"[{fam}] entity_ref de comando", c["id"])
        for r in c["related_commands"]:
            check(r in cmds, f"[{fam}] comando relacionado inexistente", f"{c['id']} -> {r}")
        for fld in c["output_fields"]:
            if fld.get("oid_ref"):
                check(fld["oid_ref"] in oids, f"[{fam}] oid_ref inexistente", f"{c['id']}.{fld['name']} -> {fld['oid_ref']}")
    check_db_enums(fam, base)
    sys.path.insert(0, str(ROOT))
    from src.profiles import default_registry
    sens = tuple(default_registry().get("ZTE").sensitive_prefixes)       # fuente única: config/vendors.yaml
    rf = base / "results.json"
    if rf.exists():
        leaked = [x for x in json.load(open(rf)).get("findings", [])
                  if any(str(x.get("tabla") or x.get("oid") or "").startswith(p) for p in sens)]
        check(not leaked, f"[{fam}] results.json con índices sensibles", f"{len(leaked)} hallazgos de comunidades/cuentas/peticiones web")
    # unicidad de atributo y metadatos que el consumidor necesita
    seen_attr = {}
    for o in oids.values():
        a = o.get("attribute")
        if a and not (classic and o["status"] not in OK_STATUS):      # clásicas: el gemelo degradado comparte atributo (superseded_by)
            check(a not in seen_attr, f"[{fam}] atributo repetido", f"{a}: {seen_attr.get(a)} y {o['id']}")
            seen_attr[a] = o["id"]
    for pid in (("oid.zte.gpon.onu.onu_rx_power_type", "oid.zte.gpon.onu.onu_tx_power_type") if classic else
                ("oid.zte.gpon.onu.onu_rx_power", "oid.zte.gpon.onu.onu_tx_power")):
        o = oids.get(pid, {})
        check(o.get("signed_bits") == 16 and o.get("sentinels") == [65535] and o.get("valid_range_dbm"),
              f"[{fam}] {pid} metadatos de signo/centinela", str({k: o.get(k) for k in ("signed_bits", "sentinels", "valid_range_dbm")}))
    for pid in ("oid.zte.gpon.onu.onu_name", "oid.zte.gpon.onu.onu_description"):
        check(oids.get(pid, {}).get("sensitivity") == "pii", f"[{fam}] {pid} sensitivity", "falta pii")
    al = [json.load(open(f))["alarms"] for f in glob.glob(str(base / "alarms/*.json"))]
    for a in [x for g in al for x in g if x["id"].startswith("alarm.zte.gpon.onu.offline_cause_")]:
        check(a.get("kind") == "historical", f"[{fam}] alarma histórica", a["id"])
    man = json.load(open(base / "manifest.json"))
    check(man["counts"]["oids_kept"] == len(oids), f"[{fam}] manifest oids_kept", f"{man['counts']['oids_kept']} != {len(oids)}")
    if classic:
        check(not [o["id"] for o in oids.values() if o["status"] == "verified_community"], f"[{fam}] verified_community sin filas",
              "quedan OID community sin verificar en el equipo")
        check(all(o.get("superseded_by") in oids for o in oids.values() if o.get("community_status_was") and o["status"] != "documented") and
              all(o.get("superseded_by") in oids for o in oids.values() if o.get("superseded_by")), f"[{fam}] superseded_by", "apunta a un OID inexistente")
        bad = [c["id"] for c in cmds.values() if c["status"] == "verified" and all(s.get("doc_type") == "command_reference" for s in c["sources"])]
        check(not bad, f"[{fam}] comandos 'verified' sin ejecución en hardware", str(bad[:3]))
        st = oids.get("oid.zte.gpon.onu.onu_status_type", {})
        check(bool((st.get("enumeration_meta") or {}).get("observed")), f"[{fam}] onu_status_type enumeration_meta", "falta")
        check(oids.get("oid.zte.gpon.onu.onu_serial_number_type", {}).get("serial_format") == "binary-8", f"[{fam}] serial_format", "falta")
        check(bool(man.get("not_exposed_attributes")), f"[{fam}] manifest not_exposed_attributes", "falta")
        ver = cmds.get("command.zte.gpon.global.show.version", {})
        check(ver.get("syntax") == "show version-running", f"[{fam}] comando de versión", str(ver.get("syntax")))
        want_st = "verified" if fam_key == "c300" else "observed"
        check(sum(c["status"] == want_st for c in cmds.values()) >= 35, f"[{fam}] comandos {want_st} por la sonda", "menos de 35")
        check(not [e for e in ents.values() if e.get("status") == "inferred" and not e.get("attributes")], f"[{fam}] entidades cascarón inferred", "bajan el tier")
        for c in cmds.values():
            check(bool(c.get("syntax")) and "gpon_olt-" not in c["syntax"] and "gpon_onu-" not in c["syntax"] and c["syntax"] != "show version",
                  f"[{fam}] sintaxis de clásicas", f"{c['id']}: {c.get('syntax')}")
        clidir = ROOT / contract.get("cli_fixtures", "")
        check(clidir.is_dir() and any((clidir / "cli").glob("show_version-running.txt")), f"[{fam}] fixtures de CLI", str(clidir))
    else:
        check("index_layout_final" in man, f"[{fam}] manifest index_layout_final", "falta")
        st = oids.get("oid.zte.gpon.onu.onu_status", {})
        check(bool((st.get("enumeration_meta") or {}).get("not_observed")), f"[{fam}] onu_status enumeration_meta", "falta")
        check(sum(bool(c.get("errors")) for c in cmds.values()) >= 20, f"[{fam}] errors[] en comandos", "menos de 20 comandos con errores")
    # 2) contrato
    fx = ROOT / contract["fixtures"]
    truth = json.load(open(fx / "ground_truth.json")) if (fx / "ground_truth.json").exists() else {}
    for attr, spec in contract["attributes"].items():
        want = spec.get("attribute", attr)
        cands = [o for o in oids.values() if o.get("attribute") == want or (spec.get("oid_exact") and o["oid"] == spec["oid_exact"])]
        if not check(cands, f"[{fam}] atributo {attr}", "no existe en el catálogo"):
            continue
        o = sorted(cands, key=lambda x: x["status"] not in OK_STATUS)[0]
        if spec["kind"] == "absent":     # atributo que NO debe leerse por SNMP en esta familia
            check(all(x["status"] not in OK_STATUS for x in cands), f"[{fam}] {attr} no expuesto", str([x["status"] for x in cands]))
            continue
        check(o["status"] in OK_STATUS, f"[{fam}] {attr} estado", o["status"])
        if not spec.get("fixture"):
            continue
        fixture = fx / "snmp" / spec["fixture"]
        if not check(fixture.exists(), f"[{fam}] fixture {attr}", str(fixture)):
            continue
        prefix = spec.get("oid_exact") or o["oid"]
        rs = rows(fixture, prefix, spec.get("column_match"))
        if not check(rs, f"[{fam}] {attr} cubre la fixture", f"ninguna fila de {fixture.name} cuelga de {prefix}"):
            continue
        kind = spec["kind"]
        if kind == "serial_text":
            check(all(re.fullmatch(r"\d*,?[A-Z0-9]{12}", val_str(v)) for _, _, v in rs), f"[{fam}] {attr} serial", rs[0][2])
        elif kind == "serial_hex":
            b = [int(x, 16) for x in rs[0][2].split()]
            check(len(b) == 8 and re.fullmatch(r"[A-Z0-9]{4}", bytes(b[:4]).decode("ascii", "replace")), f"[{fam}] {attr} serial hex", rs[0][2])
        elif kind == "text":
            check(any(val_str(v) for _, _, v in rs), f"[{fam}] {attr} texto", "todo vacío")
        elif kind == "int_range":
            lo, hi = spec["range"]
            check(all(lo <= int(v) <= hi for _, _, v in rs), f"[{fam}] {attr} rango", f"{lo}..{hi}")
        elif kind == "dbm_formula":
            m = re.fullmatch(r"raw\*([\d.]+)([+-][\d.]+)", o.get("scale_formula") or "")
            if check(m, f"[{fam}] {attr} fórmula", str(o.get("scale_formula"))):
                k, off = float(m.group(1)), float(m.group(2))
                vals = [int(v) * k + off for _, _, v in rs if int(v) != (o.get("sentinel") and 65535 or -1)]
                lo, hi = spec["range"]
                check(vals and all(lo <= x <= hi for x in vals), f"[{fam}] {attr} dBm plausible", f"{min(vals):.1f}..{max(vals):.1f}")
            check(o.get("unit") == "dBm", f"[{fam}] {attr} unidad", str(o.get("unit")))
        elif kind == "dbm_signed_all":      # 16 bits con signo y 65535 = sin señal
            lo, hi = spec["range"]
            vals = [((int(v) - 65536) if int(v) >= 32768 else int(v)) * 0.002 - 30 for _, _, v in rs
                    if int(v) != 65535 and str(int(v)) not in (o.get("suspect_values") or {})]
            check(vals and all(lo <= x <= hi for x in vals), f"[{fam}] {attr} dBm plausible (con signo)", f"{min(vals):.1f}..{max(vals):.1f}")
            check(o.get("signed_bits") == 16 and o.get("unit") == "dBm", f"[{fam}] {attr} signed_bits/unidad", str((o.get("signed_bits"), o.get("unit"))))
        elif kind == "dbm_signed":
            lo, hi = spec["range"]
            truth_pw = {x["snmp_index"]: x["rx_dbm_cli"] for x in truth.get(spec.get("ground_truth"), [])}
            neg = [(oid[len(prefix) + 1:][:-2], int(v)) for oid, _, v in rs if 32768 <= int(v) < 65535]   # índice sin el ".1" final
            check(neg, f"[{fam}] {attr} fixture con raw >= 32768", "sin filas con signo")
            for i, v in neg:
                dbm = (v - 65536) * 0.002 - 30
                check(lo <= dbm <= hi, f"[{fam}] {attr} dBm con signo plausible", f"{i}: {dbm:.3f}")
                if i in truth_pw:
                    check(abs(dbm - truth_pw[i]) < 0.01, f"[{fam}] {attr} contra la CLI", f"{i}: {dbm:.3f} vs {truth_pw[i]}")
        elif kind == "enum":
            en = {k for k in (o.get("enumeration") or {}) if k != "default"}
            check(all(v in en for _, _, v in rs), f"[{fam}] {attr} enum",
                  f"valores {sorted({v for _, _, v in rs})} fuera de {sorted(en)}")
            if spec.get("ground_truth") and truth:
                labels = {k.lower(): v for k, v in (o.get("enumeration") or {}).items()}
                byidx = {oid[len(prefix) + 1:]: v for oid, _, v in rs}
                bad = []
                for s in truth.get("onu_samples", []):
                    v = byidx.get(s["snmp_index"])
                    if v is not None and labels.get(v, "").lower() != s["phase_state"].lower():
                        bad.append((s["snmp_index"], labels.get(v), s["phase_state"]))
                check(not bad, f"[{fam}] {attr} contra la CLI (ground_truth)", str(bad[:3]))
        elif kind == "datetime_hex":
            b = [int(x, 16) for x in rs[0][2].split()]
            check(len(b) == 8 and 2000 <= (b[0] << 8 | b[1]) <= 2100 and 1 <= b[2] <= 12, f"[{fam}] {attr} fecha", rs[0][2])


if __name__ == "__main__":
    targets = sys.argv[1:] or ["c620", "c600", "c320", "c300"]
    for t in targets:
        run(t)
    print(f"{passes} comprobaciones correctas, {len(fails)} fallos")
    for f in fails[:60]:
        print("  FALLO", f)
    sys.exit(1 if fails else 0)
