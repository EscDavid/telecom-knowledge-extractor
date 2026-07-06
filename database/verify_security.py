#!/usr/bin/env python3
"""Prueba de seguridad del Loader/triggers contra ispm_tkc (DB real).

Valida las dos mitades del factor 2, de forma NO destructiva (todo con ROLLBACK):

  TEST 1 — INSERT sin sesion   -> debe ser RECHAZADO por el trigger (SQLSTATE 45000).
  TEST 2 — INSERT con sesion   -> debe ser ACEPTADO (sesion valida en active_sessions).

Uso:
    python -m database.verify_security         # o: python database/verify_security.py
Requiere: conexion a ispm_tkc (config + .env) y, para que TEST 1 falle, que los
triggers de database/ispm_tkc.sql (BLOQUE FASE 3) esten aplicados.
"""
from __future__ import annotations

import hashlib
import secrets
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from src.loader import db

TRIGGER_MARK = ("45000", "no autorizada", "1644")


def _seed_ids(conn):
    with conn.cursor() as c:
        c.execute("SELECT id, vendor_id FROM tkc_families LIMIT 1")
        row = c.fetchone()
    if not row:
        raise SystemExit("No hay familias sembradas; corre database/ispm_tkc.sql primero.")
    return row["vendor_id"], row["id"]


def _try_insert_version(conn, vendor_id, family_id, label):
    with conn.cursor() as c:
        c.execute("INSERT INTO tkc_catalog_versions (vendor_id, family_id, version_num, "
                  "version_label, tier) VALUES (%s, %s, 999, %s, 1)",
                  (vendor_id, family_id, label))


def main() -> int:
    cfg = yaml.safe_load(open("config/pipeline.yaml", encoding="utf-8"))
    conn = db.connect(cfg)
    print("Conectado a ispm_tkc ✓")
    vendor_id, family_id = _seed_ids(conn)
    passed = True

    # --- TEST 1: sin sesion -> debe RECHAZAR --------------------------------
    try:
        with conn.cursor() as c:
            c.execute("SET @actor_id = NULL")
            c.execute("SET @actor_token = NULL")
        _try_insert_version(conn, vendor_id, family_id, "TEST_NOSESSION")
        print("TEST 1 (INSERT sin sesion): ACEPTADO  ✗  -> el trigger NO esta aplicado/protegiendo")
        passed = False
    except Exception as exc:
        if any(m in str(exc) for m in TRIGGER_MARK):
            print("TEST 1 (INSERT sin sesion): RECHAZADO por trigger  ✓")
        else:
            print(f"TEST 1: fallo por otra causa (no el trigger): {str(exc)[:140]}")
            passed = False
    finally:
        conn.rollback()

    # --- TEST 2: con sesion valida -> debe ACEPTAR --------------------------
    try:
        token = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with conn.cursor() as c:
            # expires_at con NOW() del servidor (no datetime.now() del cliente): evita
            # que un desfase de zona horaria cliente/servidor deje la sesion "expirada".
            c.execute("INSERT INTO active_sessions (superadmin_id, token_hash, expires_at) "
                      "VALUES (%s, %s, NOW() + INTERVAL 5 MINUTE)",
                      ("00000000-test-actor", token_hash))
            c.execute("SET @actor_id = %s", ("00000000-test-actor",))
            c.execute("SET @actor_token = %s", (token,))
        _try_insert_version(conn, vendor_id, family_id, "TEST_SESSION")
        print("TEST 2 (INSERT con sesion): ACEPTADO  ✓")
    except Exception as exc:
        print(f"TEST 2 (INSERT con sesion): RECHAZADO  ✗  -> inesperado: {str(exc)[:140]}")
        passed = False
    finally:
        conn.rollback()          # no persiste nada

    conn.close()
    print("\nRESULTADO:", "OK — la doble auth funciona" if passed else
          "PENDIENTE — revisar (¿triggers aplicados?)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
