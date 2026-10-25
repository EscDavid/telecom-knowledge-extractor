"""Comprueba con GETNEXT (solo lectura) las columnas `absent_in_populated_table` del catálogo.
Si el siguiente OID devuelto cuelga de la columna, existe; si no, el equipo no la expone.
Uso: python scripts/check_absent_columns.py <c620|c600>   (host/puerto/community de .env: TKC_SNMP_*)"""
import glob, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
fam = sys.argv[1] if len(sys.argv) > 1 else "c620"
env = {}
for l in open(ROOT / ".env"):
    if "=" in l and l.startswith("TKC_SNMP_"):
        k, v = l.split("=", 1); env[k] = v.strip().strip("\"'")
target = f"{env['TKC_SNMP_HOST']}:{env.get('TKC_SNMP_PORT', '161')}"
cols = [(o["id"], o["oid"]) for f in glob.glob(str(ROOT / f"catalog/zte/zxa10-{fam}/catalog-1.1.0/oids/*.json"))
        for o in json.load(open(f))["oids"] if (o.get("pending_validation") or {}).get("category") == "absent_in_populated_table"]
res = {}
for oid_id, oid in sorted(cols):
    r = subprocess.run(["snmpgetnext", "-v2c", "-On", "-c", env["TKC_SNMP_COMMUNITY"], "-t", "10", "-r", "2", target, oid],
                       capture_output=True, text=True)
    out = (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "(sin respuesta)"
    nxt = out.split(" = ")[0].lstrip(".")
    state = "EXISTE" if nxt.startswith(oid + ".") or nxt == oid else "NO EXPUESTA"
    res[oid_id] = {"oid": oid, "estado": state, "siguiente": nxt[:70]}
    print(f"{state:12} {oid_id.split('.', 3)[-1]:48} -> {nxt[:70]}")
json.dump({"checked": __import__("datetime").date.today().isoformat(), "method": "snmpgetnext de solo lectura sobre cada columna", "firmware": "1.2.2",
           "family": f"ZXA10 {fam.upper()}", "columns": {v["oid"]: v["estado"] for v in res.values()}},
          open(ROOT / f"docs/validation/absent_columns_{fam}.json", "w"), indent=1)
