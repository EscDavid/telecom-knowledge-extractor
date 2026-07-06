"""CLI del Loader.

    python -m src.loader status                         # local vs ispm_tkc (read-only)
    python -m src.loader load <familia> --authorize --user <superadmin> [--version V]
                                                        # carga autenticada (factor 1)

El `.env` (raiz del repo) provee TKC_DB_PASSWORD (password del usuario MySQL del loader).
El password del SUPERADMIN se pide oculto por prompt (o --password-env VAR).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()                    # carga .env de la raiz si existe
except Exception:                    # dotenv opcional
    pass

from . import auth, db, hashing, loader, readiness


def _catalogs(catalog_base: Path):
    for manifest in sorted(catalog_base.glob("*/*/catalog-*/manifest.json")):
        cdir = manifest.parent
        m = json.loads(manifest.read_text(encoding="utf-8"))
        yield cdir, m.get("vendor", ""), m.get("family", ""), cdir.name.replace("catalog-", "")


def cmd_status(config: dict) -> int:
    base = Path(config["paths"]["catalog"])
    conn = None
    try:
        conn = db.connect(config)
    except Exception as exc:
        print(f"(DB no accesible: {exc})\n  -> estado local; el campo estado sera '?'\n")

    print(f"{'catalogo':30} {'tier':6} {'estado':12} {'vigente':9} hash")
    print("-" * 80)
    best = None
    for cdir, vendor, family, version in _catalogs(base):
        local = hashing.catalog_root_hash(cdir)
        tier, tname, m = readiness.readiness(cdir)
        state, vigente = "?", "-"
        if conn is not None:
            try:
                dbhash = db.fetch_content_hash(conn, vendor, family, version)
                state = "SIN SUBIR" if dbhash is None else (
                    "SIN CAMBIOS" if dbhash == local else "CAMBIOS")
                if dbhash is not None:
                    active = db.fetch_active_version(conn, vendor, family)
                    vigente = "si" if active and active["version_label"] == version else "no"
            except Exception:
                state = "?"
        wk = f"walk:{m['verified_walk']}" if m["verified_walk"] else ""
        print(f"{family+' '+version:30} T{tier:<5} {state:12} {vigente:9} {local[:10]}... {wk}")
        if state != "SIN CAMBIOS" and (best is None or m["rank_key"] > best[1]):
            best = (f"{family} {version}", m["rank_key"], tname)
    print(f"\nRecomendado subir: {best[0]}  ({best[2]})" if best else "\nTodo sincronizado.")
    if conn is not None:
        conn.close()
    return 0


def cmd_load(config: dict, family_slug: str, version, user: str,
             password_env, authorize: bool) -> int:
    if not authorize:
        print("ERROR: la carga requiere --authorize (autorizacion explicita del operador).")
        return 2
    base = Path(config["paths"]["catalog"])
    cands = [(cdir, v, f, ver) for cdir, v, f, ver in _catalogs(base)
             if family_slug.lower() in cdir.parent.name.lower()
             and (version is None or ver == version)]
    if not cands:
        print(f"No hay catalogo para '{family_slug}'" + (f" v{version}" if version else ""))
        return 1
    cdir, vendor, family, ver = max(cands, key=lambda c: readiness.readiness(c[0])[2]["rank_key"])
    tier, tname, m = readiness.readiness(cdir)
    local = hashing.catalog_root_hash(cdir)
    print(f"Catalogo: {family} {ver}  (T{tier} {tname}, verified_walk={m['verified_walk']})")

    if password_env:
        password = os.environ.get(password_env, "")
        if not password:
            print(f"ERROR: la variable {password_env} esta vacia.")
            return 2
    else:
        import getpass
        password = getpass.getpass(f"Password de {user} (superadmin): ")

    conn = db.connect(config)
    try:
        superadmin_id = auth.authenticate(conn, config, user, password)
        if not superadmin_id:
            print("ERROR: credenciales invalidas o el usuario no es superadmin ACTIVO.")
            return 3
        try:
            dbhash = db.fetch_content_hash(conn, vendor, family, ver)
        except Exception:
            dbhash = None
        if dbhash == local:
            print("SIN CAMBIOS (hash igual al de ispm_tkc). No se recarga.")
            return 0
        technology = config.get("pipeline", {}).get("technology", "gpon")
        with db.transaction(conn):
            auth.open_session(conn, superadmin_id)      # factor 2 listo (trigger en Fase 3)
            stats = loader.Loader(conn).load(cdir, vendor, family, technology, ver, local, tier)
        print(f"OK — cargado {family} {ver} (tier {tier}): {stats}")
        return 0
    finally:
        conn.close()


def cmd_deprecate(config: dict, vendor: str, family: str, version_label: str, tier: int,
                   user: str, password_env, authorize: bool) -> int:
    if not authorize:
        print("ERROR: deprecar requiere --authorize (autorizacion explicita del operador).")
        return 2
    if password_env:
        password = os.environ.get(password_env, "")
        if not password:
            print(f"ERROR: la variable {password_env} esta vacia.")
            return 2
    else:
        import getpass
        password = getpass.getpass(f"Password de {user} (superadmin): ")

    conn = db.connect(config)
    try:
        superadmin_id = auth.authenticate(conn, config, user, password)
        if not superadmin_id:
            print("ERROR: credenciales invalidas o el usuario no es superadmin ACTIVO.")
            return 3
        with db.transaction(conn):
            auth.open_session(conn, superadmin_id)
            n = db.deprecate_version(conn, vendor, family, version_label, tier)
        if n:
            print(f"OK — {vendor} {family} {version_label} bajada a tier {tier} (retirada).")
        else:
            print(f"No se encontro {vendor} {family} {version_label}.")
        return 0 if n else 1
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.loader")
    parser.add_argument("--config", default="config/pipeline.yaml")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="estado local vs ispm_tkc")
    ld = sub.add_parser("load", help="carga autenticada de un catalogo")
    ld.add_argument("family", help="slug de familia (ej. zxa10-c320)")
    ld.add_argument("--version", default=None)
    ld.add_argument("--user", required=True, help="email o username del superadmin")
    ld.add_argument("--password-env", default=None, help="variable de entorno con el password (CI)")
    ld.add_argument("--authorize", action="store_true", help="autorizacion explicita (obligatoria)")

    dep = sub.add_parser("deprecate", help="retira una version bajandole el tier (deja de ser la vigente)")
    dep.add_argument("vendor")
    dep.add_argument("family")
    dep.add_argument("version_label")
    dep.add_argument("--tier", type=int, default=1, help="tier al que se baja (default 1)")
    dep.add_argument("--user", required=True, help="email o username del superadmin")
    dep.add_argument("--password-env", default=None)
    dep.add_argument("--authorize", action="store_true")
    args = parser.parse_args(argv)

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if args.cmd == "status":
        return cmd_status(config)
    if args.cmd == "load":
        return cmd_load(config, args.family, args.version, args.user,
                        args.password_env, args.authorize)
    if args.cmd == "deprecate":
        return cmd_deprecate(config, args.vendor, args.family, args.version_label, args.tier,
                             args.user, args.password_env, args.authorize)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
