"""Conexion a MySQL (ispm_tkc) + transaccion. PyMySQL se importa lazy: este
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
        "database": db.get("name", "ispm_tkc"),
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
           "WHERE v.name = %s AND f.name = %s AND cv.version_label = %s")
    with conn.cursor() as cur:
        cur.execute(sql, (vendor, family, version))
        row = cur.fetchone()
    return row["content_hash"] if row else None


def fetch_active_version(conn, vendor: str, family: str):
    """La version vigente de una familia: mayor tier y, a igual tier, la mas nueva
    (version_num mas alto). No hace falta una columna de estado: version_num ya es
    correlativo por construccion (ver loader._version)."""
    sql = ("SELECT cv.version_label, cv.tier FROM tkc_catalog_versions cv "
           "JOIN tkc_vendors v  ON v.id = cv.vendor_id "
           "JOIN tkc_families f ON f.id = cv.family_id "
           "WHERE v.name = %s AND f.name = %s "
           "ORDER BY cv.tier DESC, cv.version_num DESC LIMIT 1")
    with conn.cursor() as cur:
        cur.execute(sql, (vendor, family))
        return cur.fetchone()


def deprecate_version(conn, vendor: str, family: str, version_label: str, tier: int = 1):
    """'Deprecar' una version vieja (ej. hardware retirado) es bajarle el tier para que
    deje de competir en la seleccion automatica (tier DESC, version_num DESC). No borra
    nada; requiere sesion de superadmin (el trigger de tkc_catalog_versions lo exige)."""
    sql = ("UPDATE tkc_catalog_versions cv "
           "JOIN tkc_vendors v  ON v.id = cv.vendor_id "
           "JOIN tkc_families f ON f.id = cv.family_id "
           "SET cv.tier = %s "
           "WHERE v.name = %s AND f.name = %s AND cv.version_label = %s")
    with conn.cursor() as cur:
        cur.execute(sql, (tier, vendor, family, version_label))
        return cur.rowcount
