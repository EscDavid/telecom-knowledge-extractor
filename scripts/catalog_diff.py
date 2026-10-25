"""Compara dos directorios de catálogo (catalog/<vendor>/<familia>/catalog-<v>) y resume lo añadido, quitado y cambiado.
Uso:  python scripts/catalog_diff.py <dir_antiguo> <dir_nuevo> [--md salida.md] [--examples N]
Solo lee archivos; no toca nada. Campos volátiles (generated_at, raw hashes) se ignoran."""
import argparse
import collections
import glob
import json
import sys
from pathlib import Path

IGNORE = {"generated_at"}


def load(base: Path):
    out = {"oids": {}, "commands": {}, "entities": {}, "alarms": {}, "relations": {}}
    for f in sorted(glob.glob(str(base / "oids/*.json"))):
        g = json.load(open(f))
        for o in g["oids"]:
            out["oids"][o["id"]] = {**o, "_firmware_group": g.get("firmware"), "_entity_group": g.get("entity_ref")}
    for f in sorted(glob.glob(str(base / "commands/*/*.json"))):
        c = json.load(open(f)); out["commands"][c["id"]] = c
    for f in sorted(glob.glob(str(base / "entities/*.json"))):
        e = json.load(open(f)); out["entities"][e["id"]] = e
    for f in sorted(glob.glob(str(base / "alarms/*.json"))):
        for a in json.load(open(f))["alarms"]:
            out["alarms"][a["id"]] = a
    for f in sorted(glob.glob(str(base / "relations/*.json"))):
        for r in json.load(open(f))["relations"]:
            out["relations"][r["id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old"); ap.add_argument("new"); ap.add_argument("--md"); ap.add_argument("--examples", type=int, default=3)
    a = ap.parse_args()
    old, new = load(Path(a.old)), load(Path(a.new))
    lines = [f"# Diferencias de catálogo\n\n`{a.old}` → `{a.new}`\n"]
    breaking = []
    for kind in old:
        o, n = old[kind], new[kind]
        added, removed = sorted(set(n) - set(o)), sorted(set(o) - set(n))
        fchg = collections.defaultdict(list)
        for k in set(o) & set(n):
            for fld in (set(o[k]) | set(n[k])) - IGNORE:
                if o[k].get(fld) != n[k].get(fld):
                    fchg[fld].append((k, o[k].get(fld), n[k].get(fld)))
        lines.append(f"## {kind}: {len(o)} → {len(n)}  (+{len(added)} / −{len(removed)} / {sum(len({k for k,_,_ in v}) for v in fchg.values()) and len({k for v in fchg.values() for k,_,_ in v})} con cambios)\n")
        if removed:
            breaking.append(f"{kind}: {len(removed)} id(s) quitados")
            lines.append("- **Quitados:** " + ", ".join(f"`{x}`" for x in removed[:20]) + (" …" if len(removed) > 20 else ""))
        if added:
            lines.append("- **Añadidos:** " + ", ".join(f"`{x.split('.', 3)[-1]}`" for x in added[:12]) + (f" … (+{len(added) - 12})" if len(added) > 12 else ""))
        for fld, items in sorted(fchg.items(), key=lambda x: -len(x[1])):
            lines.append(f"- campo `{fld}`: {len(items)} cambios; p. ej. " + "; ".join(
                f"`{k.split('.', 3)[-1]}`: {str(x)[:40]} → {str(y)[:40]}" for k, x, y in items[:a.examples]))
            if fld in ("scale", "unit", "firmware", "oid", "access", "enumeration", "syntax", "index", "_firmware_group", "attribute", "signed_bits") and kind == "oids":
                breaking.append(f"oids.{fld}: {len(items)} cambios")
        lines.append("")
    lines.append("## Posibles cambios incompatibles\n")
    lines += [f"- {b}" for b in breaking] or ["- ninguno (solo adiciones)"]
    text = "\n".join(lines) + "\n"
    if a.md:
        Path(a.md).write_text(text, encoding="utf-8")
    print(text[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
