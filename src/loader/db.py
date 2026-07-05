"""Conexion a MySQL (isp_catalog) + transaccion. PyMySQL se importa lazy: este
modulo se puede importar sin la lib instalada; solo se necesita al conectar.

Config en config/pipeline.yaml -> `database:` (password por variable de entorno).
"""
from __future__ import annotations

import os
from contextlib import contextmanager


def _params(config: dict) -> dict:
    db = config.get("database", {}) or {}
    pwd_env = db.get("password_env")
    password = os.environ.get(pwd_env, "") if pwd_env else db.get("password", "")
    return {
        "host": db.get("host", "127.0.0.1"),
        "port": int(db.get("port", 3306)),
        "user": db.get("user", ""),
        "password": password,
        "database": db.get("name", "isp_catalog"),
        "charset": "utf8mb4",
    }


def connect(config: dict):
    """Abre una conexion PyMySQL (autocommit off; usar `transaction`)."""
    import pymysql          # lazy: no requerido para hashing/readiness
    import pymysql.cursors
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor,
                           autocommit=False, **_params(config))


@contextmanager
def transaction(conn):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def fetch_content_hash(conn, vendor: str, family: str, version: str):
    """content_hash de una version del catalogo, o None si no esta cargada."""
    sql = ("SELECT cv.content_hash FROM tkc_catalog_versions cv "
           "JOIN tkc_vendors v  ON v.id = cv.vendor_id "
           "JOIN tkc_families f ON f.id = cv.family_id "
           "WHERE v.name = %s AND f.name = %s AND cv.version = %s")
    with conn.cursor() as cur:
        cur.execute(sql, (vendor, family, version))
        row = cur.fetchone()
    return row["content_hash"] if row else None
