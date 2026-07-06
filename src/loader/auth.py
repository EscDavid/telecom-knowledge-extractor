"""Factor 1 — autenticacion del superadmin contra db_auth.users (read-only) y
creacion de la sesion efimera en ispm_tkc.active_sessions.

- superadmin = ROL (role_id pineado en config), estado ACTIVO, no borrado.
- password bcrypt ($2b$) validado con bcrypt.checkpw.
- La sesion (token) queda en active_sessions y se expone via @actor_id/@actor_token
  para que el trigger (Fase 3) la re-valide.
"""
from __future__ import annotations

import hashlib
import secrets


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def authenticate(conn, config: dict, username: str, password: str) -> str | None:
    """Devuelve db_auth.users.id si (usuario, password) es un superadmin activo; si no, None."""
    import bcrypt
    auth = config.get("auth_database", {}) or {}
    dbname = auth.get("name", "db_auth")
    role_id = auth.get("superadmin_role_id")
    sql = (f"SELECT id, password FROM {dbname}.users "
           "WHERE (email = %s OR username = %s) AND role_id = %s "
           "AND status = 'ACTIVO' AND deleted_at IS NULL LIMIT 1")
    with conn.cursor() as cur:
        cur.execute(sql, (username, username, role_id))
        row = cur.fetchone()
    if not row:
        return None
    stored = row["password"]
    stored_b = stored.encode("utf-8") if isinstance(stored, str) else stored
    try:
        if bcrypt.checkpw(password.encode("utf-8"), stored_b):
            return row["id"]
    except ValueError:
        return None            # hash almacenado invalido
    return None


def open_session(conn, superadmin_id: str, ttl_minutes: int = 5) -> str:
    """Crea la sesion efimera y setea @actor_id/@actor_token en la conexion. Devuelve el token.

    expires_at se calcula con NOW() del propio servidor (no datetime.now() del
    cliente): el trigger compara expires_at contra NOW() en MySQL, y un cliente en
    otra zona horaria dejaria la sesion "expirada" desde el momento en que se crea.
    """
    token = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM active_sessions WHERE expires_at < NOW()")
        cur.execute("INSERT INTO active_sessions (superadmin_id, token_hash, expires_at) "
                    "VALUES (%s, %s, NOW() + INTERVAL %s MINUTE)",
                    (superadmin_id, _sha256(token), ttl_minutes))
        cur.execute("SET @actor_id = %s", (superadmin_id,))
        cur.execute("SET @actor_token = %s", (token,))
    return token
