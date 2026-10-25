"""Inventario de OID presentes en el walk enterprise que NO están en el catálogo (sin definición MIB de referencia).
No lo carga el loader: es material de trabajo para catalogarlos (contrastar con CLI) y priorizar.
Uso:  python scripts/build_observed_inventory.py ZXA10_C620"""
import collections
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fam = sys.argv[1] if len(sys.argv) > 1 else "ZXA10_C620"
stem = fam.split("_")[-1]
cat = set()
for f in glob.glob(str(ROOT / f"catalog/zte/{fam.lower().replace('_', '-')}/catalog-1.1.0/oids/*.json")):
    cat |= {o["oid"] for o in json.load(open(f))["oids"]}
rows, types, sample, inst = collections.Counter(), collections.defaultdict(collections.Counter), {}, {}
rx = re.compile(r"\.?(1\.3\.6\.1\.4\.1\.3902\.1082\.[\d.]+?) = (\w[\w-]*): ?(.*)")
for line in open(ROOT / f"docs/walks/ZTE_{stem}.txt", errors="ignore"):
    m = rx.match(line)
    if not m:
        continue
    p = m.group(1).split(".")
    if any(".".join(p[:n]) in cat for n in range(len(p), 9, -1)):
        continue
    k = ".".join(p[:14])                                           # subárbol tabla.entrada.columna
    rows[k] += 1; types[k][m.group(2)] += 1
    sample.setdefault(k, (m.group(1), m.group(3)[:40])); inst[k] = max(inst.get(k, 0), len(p) - 14)
out = [{"subtree": k, "rows": n, "types": dict(types[k]), "index_depth": inst[k], "sample_oid": sample[k][0], "sample_value": sample[k][1]}
       for k, n in rows.most_common()]
dst = ROOT / f"docs/validation/observed_uncataloged_{stem.lower()}.json"
dst.write_text(json.dumps({"family": fam, "subtrees": len(out), "rows": sum(rows.values()), "items": out}, ensure_ascii=False, indent=1))
print(dst.name, len(out), "subárboles", sum(rows.values()), "filas")
