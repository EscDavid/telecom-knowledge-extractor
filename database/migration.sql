-- =============================================================================
-- TKC — migration 001: delta de Fase 2 sobre tkc_schema.sql (v3)
-- Motor: MySQL 8.0+   DB objetivo: isp_catalog
-- Aplica DESPUES de crear isp_catalog y correr tkc_schema.sql SIN el ALTER TABLE olts.
-- MIGRACION RUN-ONCE: MySQL NO soporta IF NOT EXISTS en ADD COLUMN / CREATE INDEX
-- (eso es MariaDB). Los MODIFY ENUM y CREATE TABLE IF NOT EXISTS si son re-ejecutables;
-- el resto correr una sola vez. NO incluye el trigger (factor 2) — ese va al final.
-- =============================================================================

-- Ejecutar dentro de la base del catalogo:
--   CREATE DATABASE IF NOT EXISTS isp_catalog CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE isp_catalog;

-- -----------------------------------------------------------------------------
-- 1) status ENUM += verified_walk, verified_community  (estados empiricos Fase 2)
--    Se restatea NOT NULL DEFAULT para no perder el default de cada tabla.
-- -----------------------------------------------------------------------------
ALTER TABLE tkc_oids      MODIFY status ENUM(
    'verified','documented','observed','inferred','deprecated','conflicted','orphan',
    'verified_walk','verified_community') NOT NULL DEFAULT 'observed';

ALTER TABLE tkc_entities  MODIFY status ENUM(
    'verified','documented','observed','inferred','deprecated','conflicted','orphan',
    'verified_walk','verified_community') NOT NULL DEFAULT 'observed';

ALTER TABLE tkc_commands  MODIFY status ENUM(
    'verified','documented','observed','inferred','deprecated','conflicted','orphan',
    'verified_walk','verified_community') NOT NULL DEFAULT 'documented';

ALTER TABLE tkc_relations MODIFY status ENUM(
    'verified','documented','observed','inferred','deprecated','conflicted',
    'verified_walk','verified_community') NOT NULL DEFAULT 'documented';

ALTER TABLE tkc_alarms    MODIFY status ENUM(
    'verified','documented','observed','inferred','deprecated','conflicted',
    'verified_walk','verified_community') NOT NULL DEFAULT 'documented';

-- -----------------------------------------------------------------------------
-- 2) access ENUM += read-create, write-only, accessible-for-notify
--    (el catalogo real usa estos accesos SNMP; el schema v3 solo traia 3)
-- -----------------------------------------------------------------------------
ALTER TABLE tkc_oids MODIFY access ENUM(
    'read-only','read-write','read-create','write-only',
    'not-accessible','accessible-for-notify') NOT NULL DEFAULT 'read-only';

-- -----------------------------------------------------------------------------
-- 3) columnas nuevas de Fase 2 en tkc_oids (lo demas vive en raw_json)
-- -----------------------------------------------------------------------------
ALTER TABLE tkc_oids
    ADD COLUMN attribute          VARCHAR(100) NULL,   -- onu_rx_power, onu_status...
    ADD COLUMN scale_formula      VARCHAR(64)  NULL,   -- 'raw*0.002-30' (afin, no cabe en scale DECIMAL)
    ADD COLUMN full_oid_template  VARCHAR(300) NULL,   -- <prefix>.<suffix>.<onuID>[.1]
    ADD COLUMN empirical          JSON NULL,           -- bloque de evidencia walk
    ADD COLUMN pending_validation JSON NULL;           -- validacion diferida (ej. rama software)

CREATE INDEX idx_tkc_oids_attribute ON tkc_oids(attribute);

-- -----------------------------------------------------------------------------
-- 4) content_hash en las versiones del catalogo (deteccion de cambios / Merkle root)
-- -----------------------------------------------------------------------------
ALTER TABLE tkc_catalog_versions
    ADD COLUMN content_hash CHAR(64) NULL;

CREATE INDEX idx_tkc_catalog_hash ON tkc_catalog_versions(content_hash);

-- -----------------------------------------------------------------------------
-- 5) active_sessions — sesion efimera del Loader (factor 2).
--    Vive en isp_catalog (NO en db_auth). superadmin_id = db_auth.users.id como
--    referencia BLANDA (CHAR(36) UUID, sin FK cross-DB, patron de olts.tkc_family_id).
--    El trigger (a aplicar al final) valida contra ESTA tabla local.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS active_sessions (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    superadmin_id CHAR(36)  NOT NULL,            -- ref blanda a db_auth.users.id
    token_hash    CHAR(64)  NOT NULL,            -- SHA2(token,256)
    created_at    DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at    DATETIME  NOT NULL,
    UNIQUE KEY uq_session_token (token_hash),
    KEY idx_session_admin (superadmin_id),
    KEY idx_session_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Limpieza de sesiones vencidas (correr periodica o al inicio de cada load):
--   DELETE FROM active_sessions WHERE expires_at < NOW();
