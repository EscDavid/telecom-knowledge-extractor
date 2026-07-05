"""CLI del Loader — Fase 1: `status`.

    python -m src.loader status [--config config/pipeline.yaml]

Compara cada catalogo local (hash raiz) contra `isp_catalog` y muestra tier +
[SIN SUBIR | CAMBIOS | SIN CAMBIOS], con una recomendacion. Read-only (solo SELECT);
si la DB no es accesible, muestra el estado local igual.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from . import db, hashing, readiness


def _catalogs(catalog_base: Path):
    """Cada catalog-<version>/ con identidad (vendor, family, version) del manifest."""
    for manifest in sorted(catalog_base.glob("*/*/catalog-*/manifest.json")):
        cdir = manifest.parent
        m = json.loads(manifest.read_text(encoding="utf-8"))
        version = cdir.name.replace("catalog-", "")
        yield cdir, m.get("vendor", ""), m.get("family", ""), version


def cmd_status(config: dict) -> int:
    base = Path(config["paths"]["catalog"])
    conn = None
    try:
        conn = db.connect(config)
    except Exception as exc:                      # DB opcional para status
        print(f"(DB no accesible: {exc})\n  -> mostrando estado local; el campo estado sera '?'\n")

    print(f"{'catalogo':30} {'tier':6} {'estado':12} hash")
    print("-" * 70)
    best = None
    for cdir, vendor, family, version in _catalogs(base):
        local = hashing.catalog_root_hash(cdir)
        tier, tname, m = readiness.readiness(cdir)
        state = "?"
        if conn is not None:
            try:
                dbhash = db.fetch_content_hash(conn, vendor, family, version)
                state = "SIN SUBIR" if dbhash is None else (
                    "SIN CAMBIOS" if dbhash == local else "CAMBIOS")
            except Exception:
                state = "?"
        wk = f"walk:{m['verified_walk']}" if m["verified_walk"] else ""
        print(f"{family+' '+version:30} T{tier:<5} {state:12} {local[:10]}... {wk}")
        # desempata por rank_key (tier, verified_walk, avg, -inferred)
        if state != "SIN CAMBIOS" and (best is None or m["rank_key"] > best[1]):
            best = (f"{family} {version}", m["rank_key"], tname)

    if best:
        print(f"\nRecomendado subir: {best[0]}  ({best[2]})")
    else:
        print("\nTodo sincronizado (sin cambios).")
    if conn is not None:
        conn.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.loader")
    sub = parser.add_subparsers(dest="cmd")
    st = sub.add_parser("status", help="estado local vs isp_catalog")
    st.add_argument("--config", default="config/pipeline.yaml")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        with open(args.config, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return cmd_status(config)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
