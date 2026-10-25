"""Elimina de `ispm_tkc.tkc_results` los hallazgos que codifican nombres de comunidades SNMP, cuentas y peticiones web de la OLT
(ramas de `sensitive_prefixes` en config/vendors.yaml: C6 3902.3.6000.101.2.3, 3902.3.6000.51.2, 3902.3.101.7.5 y clásicas
3902.1082.20.5.2.1) presentes en versiones de catálogo cargadas antes de sanearlas.

Pide la contraseña del superadmin por prompt oculto y usa una sesión autorizada (los triggers de tkc_results la exigen).
Sin --apply solo cuenta; con --apply borra dentro de una transacción.
Uso:  .venv/bin/python scripts/purge_sensitive_results.py --user <superadmin> [--apply]"""
import argparse
import getpass
import sys
from pathlib import Path

import yaml

try:
    from dotenv import load_dotenv
except Exception:                    # dotenv opcional
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.loader import auth, db  # noqa: E402

from src.profiles import default_registry  # noqa: E402

PREFIXES = tuple(default_registry().get("ZTE").sensitive_prefixes)       # fuente única: config/vendors.yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config/pipeline.yaml"))
    a = ap.parse_args()
    if load_dotenv:
        load_dotenv(ROOT / ".env")            # TKC_DB_PASSWORD (como hace src.loader)
    config = yaml.safe_load(open(a.config, encoding="utf-8"))
    pwd = getpass.getpass(f"Password de {a.user} (superadmin): ")
    conn = db.connect(config)
    try:
        uid = auth.authenticate(conn, config, a.user, pwd)
        if not uid:
            print("ERROR: credenciales invalidas o el usuario no es superadmin ACTIVO.")
            return 3
        where = " OR ".join(["payload LIKE %s"] * len(PREFIXES))
        args = [f"%{p}%" for p in PREFIXES]
        with conn.cursor() as cur:
            cur.execute("SELECT cv.id, cv.version_label, COUNT(*) n FROM tkc_results r "
                        "JOIN tkc_catalog_versions cv ON cv.id = r.catalog_version_id "
                        f"WHERE {where} GROUP BY cv.id, cv.version_label ORDER BY cv.id", args)
            rows = cur.fetchall()
        if not rows:
            print("Sin hallazgos sensibles en tkc_results.")
            return 0
        for r in rows:
            print(f"  version id {r['id']} ({r['version_label']}): {r['n']} hallazgos sensibles")
        if not a.apply:
            print("Simulacion: nada borrado. Repite con --apply para eliminarlos.")
            return 0
        with db.transaction(conn):
            auth.open_session(conn, uid)
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM tkc_results WHERE {where}", args)
                print(f"OK - eliminadas {cur.rowcount} filas de tkc_results.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
