-- =============================================================================
-- ispm_tkc — esquema COMPLETO e INTEGRADO (base v3 + Fase 2 + versiones inmutables)
-- Motor: MySQL 8.0+   Prefijo: tkc_   Global: sin company_id (catalogo compartido)
--
-- VERSIONES INMUTABLES: las tablas de artefactos tienen PK COMPUESTA
-- (id, catalog_version_id): cada version guarda su propia instantanea del elemento,
-- habilitando auditoria, rollback y deltas. Las FK se propagan con catalog_version_id.
-- SELECCION AUTOMATICA: tkc_catalog_versions.tier (1..4); el backend toma el mayor.
--
-- Un solo archivo desplegable. NO incluye el puente con olts (bridge_isp_management.sql,
-- en isp_management). El trigger (Fase 3) va en triggers.sql, al final.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS ispm_tkc CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ispm_tkc;

SET FOREIGN_KEY_CHECKS = 0;
SET @OLD_SQL_MODE = @@SQL_MODE;
SET SQL_MODE = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION';

DROP TABLE IF EXISTS active_sessions;
DROP TABLE IF EXISTS tkc_completeness_reports;
DROP TABLE IF EXISTS tkc_results;
DROP TABLE IF EXISTS tkc_delta_runs;
DROP TABLE IF EXISTS tkc_alarm_firmware;
DROP TABLE IF EXISTS tkc_alarm_oid_refs;
DROP TABLE IF EXISTS tkc_alarms;
DROP TABLE IF EXISTS tkc_relations;
DROP TABLE IF EXISTS tkc_oid_firmware;
DROP TABLE IF EXISTS tkc_oids;
DROP TABLE IF EXISTS tkc_command_firmware;
DROP TABLE IF EXISTS tkc_command_output_fields;
DROP TABLE IF EXISTS tkc_command_params;
DROP TABLE IF EXISTS tkc_commands;
DROP TABLE IF EXISTS tkc_aliases;
DROP TABLE IF EXISTS tkc_entity_attributes;
DROP TABLE IF EXISTS tkc_entity_firmware;
DROP TABLE IF EXISTS tkc_entities;
DROP TABLE IF EXISTS tkc_catalog_versions;
DROP TABLE IF EXISTS tkc_documents;
DROP TABLE IF EXISTS tkc_firmwares;
DROP TABLE IF EXISTS tkc_families;
DROP TABLE IF EXISTS tkc_vendors;
SET FOREIGN_KEY_CHECKS = 1;

-- --- BLOQUE 1: Taxonomia -----------------------------------------------------
CREATE TABLE tkc_vendors (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    oid_prefix  VARCHAR(100) NULL,
    notes       TEXT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_families (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    vendor_id   INT NOT NULL,
    name        VARCHAR(100) NOT NULL,
    technology  VARCHAR(50)  NOT NULL,
    notes       TEXT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_families_vendor FOREIGN KEY (vendor_id) REFERENCES tkc_vendors(id),
    UNIQUE KEY uq_family (vendor_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_firmwares (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    family_id    INT NOT NULL,
    version      VARCHAR(50) NOT NULL,
    release_date DATE NULL,
    is_current   BOOLEAN NOT NULL DEFAULT FALSE,
    notes        TEXT NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_firmwares_family FOREIGN KEY (family_id) REFERENCES tkc_families(id),
    UNIQUE KEY uq_firmware (family_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 2: Documentos ----------------------------------------------------
CREATE TABLE tkc_documents (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    vendor_id         INT NOT NULL,
    family_id         INT NOT NULL,
    firmware_id       INT NULL,
    doc_type          ENUM('mib_file','mib_specification','command_reference',
                           'initial_configuration','product_catalog','alarm_reference',
                           'hardware_description') NOT NULL,
    hash              VARCHAR(64)  NOT NULL,
    status            ENUM('classified','partial','unclassified') NOT NULL DEFAULT 'unclassified',
    classifier_output JSON NULL,
    processed_at      DATETIME NULL,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_documents_vendor   FOREIGN KEY (vendor_id)   REFERENCES tkc_vendors(id),
    CONSTRAINT fk_documents_family   FOREIGN KEY (family_id)   REFERENCES tkc_families(id),
    CONSTRAINT fk_documents_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id),
    UNIQUE KEY uq_document (vendor_id, family_id, doc_type, hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 3: Versiones del catalogo  (+ content_hash + tier) ----------------
CREATE TABLE tkc_catalog_versions (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    vendor_id          INT NOT NULL,
    family_id          INT NOT NULL,
    version_num        INT UNSIGNED NOT NULL,     -- correlativo por (vendor,family): historia/orden
    version_label      VARCHAR(20)  NOT NULL,     -- etiqueta humana (del dir: 1.0.0, 1.0.0-validated)
    previous_version   VARCHAR(20)  NULL,
    generated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tier               TINYINT UNSIGNED NOT NULL DEFAULT 1,  -- 1..4 madurez; backend elige el mayor
    -- vigencia: version_num ya es correlativo (mayor = mas nueva), asi que "la vigente" para un
    -- tier dado es MAX(version_num). No hace falta una columna de estado aparte: deprecar una
    -- version vieja (ej. hardware retirado) es bajarle el tier a mano para que deje de competir.
    breaking_changes   BOOLEAN NOT NULL DEFAULT FALSE,
    migration_required BOOLEAN NOT NULL DEFAULT FALSE,
    changelog          JSON NULL,
    dist_path          VARCHAR(500) NULL,
    content_hash       CHAR(64) NULL,                        -- raiz Merkle del contenido
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_catalog_vendor FOREIGN KEY (vendor_id) REFERENCES tkc_vendors(id),
    CONSTRAINT fk_catalog_family FOREIGN KEY (family_id) REFERENCES tkc_families(id),
    UNIQUE KEY uq_catalog_label (vendor_id, family_id, version_label),
    KEY idx_catalog_vnum (vendor_id, family_id, version_num, tier)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 4: Entidades  (PK compuesta id+version) --------------------------
CREATE TABLE tkc_entities (
    id                      VARCHAR(150) NOT NULL,
    catalog_version_id      INT NOT NULL,
    canonical_name          VARCHAR(150) NOT NULL,
    vendor_id               INT NOT NULL,
    family_id               INT NOT NULL,
    technology              VARCHAR(50)  NOT NULL,
    entity_type             ENUM('device','port','logical','hardware','profile','protocol') NOT NULL,
    description             TEXT NULL,
    is_critical             BOOLEAN NOT NULL DEFAULT FALSE,
    confidence_extraction   DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall      DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                  ENUM('verified','documented','observed','inferred','deprecated',
                                 'conflicted','orphan','verified_walk','verified_community')
                                NOT NULL DEFAULT 'observed',
    lifecycle_introduced_in INT NULL,
    lifecycle_deprecated_in INT NULL,
    lifecycle_removed_in    INT NULL,
    lifecycle_status        ENUM('introduced','stable','modified','deprecated','removed')
                                NOT NULL DEFAULT 'introduced',
    replacement_id          VARCHAR(150) NULL,
    raw_json                JSON NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id, catalog_version_id),
    CONSTRAINT fk_entities_vendor   FOREIGN KEY (vendor_id)               REFERENCES tkc_vendors(id),
    CONSTRAINT fk_entities_family   FOREIGN KEY (family_id)               REFERENCES tkc_families(id),
    CONSTRAINT fk_entities_catalog  FOREIGN KEY (catalog_version_id)      REFERENCES tkc_catalog_versions(id),
    CONSTRAINT fk_entities_intro    FOREIGN KEY (lifecycle_introduced_in) REFERENCES tkc_firmwares(id),
    CONSTRAINT fk_entities_depr     FOREIGN KEY (lifecycle_deprecated_in) REFERENCES tkc_firmwares(id),
    CONSTRAINT fk_entities_removed  FOREIGN KEY (lifecycle_removed_in)    REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_entity_firmware (
    entity_id          VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    firmware_id        INT NOT NULL,
    PRIMARY KEY (entity_id, catalog_version_id, firmware_id),
    CONSTRAINT fk_ef_entity   FOREIGN KEY (entity_id, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_ef_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_entity_attributes (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    entity_id          VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    name               VARCHAR(100) NOT NULL,
    attr_type          VARCHAR(50)  NOT NULL,
    range_def          VARCHAR(100) NULL,
    required           BOOLEAN NOT NULL DEFAULT FALSE,
    source_doc_type    VARCHAR(50)  NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ea_entity FOREIGN KEY (entity_id, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 5: Aliases -------------------------------------------------------
CREATE TABLE tkc_aliases (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    entity_ref              VARCHAR(150) NULL,
    catalog_version_id      INT NOT NULL,
    alias                   VARCHAR(150) NOT NULL,
    source_doc_type         VARCHAR(50)  NOT NULL,
    firmware_scope          VARCHAR(20)  NOT NULL DEFAULT 'all',
    status                  ENUM('assigned','ambiguous','cross_vendor') NOT NULL DEFAULT 'assigned',
    candidates              JSON NULL,
    cross_vendor_entity     VARCHAR(150) NULL,
    cross_vendor_confidence DECIMAL(4,3) NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_aliases_entity FOREIGN KEY (entity_ref, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 6: Comandos  (PK compuesta) --------------------------------------
CREATE TABLE tkc_commands (
    id                     VARCHAR(150) NOT NULL,
    catalog_version_id     INT NOT NULL,
    canonical_name         VARCHAR(200) NOT NULL,
    vendor_id              INT NOT NULL,
    family_id              INT NOT NULL,
    technology             VARCHAR(50)  NOT NULL,
    category               ENUM('show','create','delete','modify','enable','disable','reset','diagnose') NOT NULL,
    cli_mode               ENUM('user_exec','privileged_exec','global_config','interface_config','pon_config') NOT NULL,
    entity_ref             VARCHAR(150) NULL,
    description            TEXT NULL,
    syntax                 VARCHAR(500) NULL,
    confidence_extraction  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall     DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                 ENUM('verified','documented','observed','inferred','deprecated',
                                'conflicted','orphan','verified_walk','verified_community')
                               NOT NULL DEFAULT 'documented',
    lifecycle_status       ENUM('introduced','stable','modified','deprecated','removed') NOT NULL DEFAULT 'stable',
    raw_json               JSON NULL,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id, catalog_version_id),
    CONSTRAINT fk_commands_vendor  FOREIGN KEY (vendor_id)          REFERENCES tkc_vendors(id),
    CONSTRAINT fk_commands_family  FOREIGN KEY (family_id)          REFERENCES tkc_families(id),
    CONSTRAINT fk_commands_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id),
    CONSTRAINT fk_commands_entity  FOREIGN KEY (entity_ref, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_command_params (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    command_id         VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    name               VARCHAR(100) NOT NULL,
    param_type         VARCHAR(50)  NOT NULL,
    pattern            VARCHAR(200) NULL,
    range_def          VARCHAR(100) NULL,
    required           BOOLEAN NOT NULL DEFAULT FALSE,
    description        TEXT NULL,
    example            VARCHAR(200) NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_cp_command FOREIGN KEY (command_id, catalog_version_id)
        REFERENCES tkc_commands(id, catalog_version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_command_output_fields (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    command_id         VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    name               VARCHAR(100) NOT NULL,
    field_type         VARCHAR(50)  NOT NULL,
    unit               VARCHAR(30)  NULL,
    oid_ref            VARCHAR(150) NULL,          -- sin FK: loader valida existencia
    oid_status         ENUM('mapped','not_mapped','inferred') NOT NULL DEFAULT 'not_mapped',
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_cof_command FOREIGN KEY (command_id, catalog_version_id)
        REFERENCES tkc_commands(id, catalog_version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_command_firmware (
    command_id         VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    firmware_id        INT NOT NULL,
    PRIMARY KEY (command_id, catalog_version_id, firmware_id),
    CONSTRAINT fk_cmdf_command  FOREIGN KEY (command_id, catalog_version_id)
        REFERENCES tkc_commands(id, catalog_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_cmdf_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 7: OIDs  (PK compuesta, + columnas Fase 2) -----------------------
CREATE TABLE tkc_oids (
    id                     VARCHAR(150) NOT NULL,
    catalog_version_id     INT NOT NULL,
    oid_string             VARCHAR(200) NOT NULL,
    name                   VARCHAR(200) NOT NULL,
    mib_table              VARCHAR(200) NULL,
    entity_ref             VARCHAR(150) NOT NULL,
    command_ref            VARCHAR(150) NULL,          -- sin FK: loader valida
    syntax                 VARCHAR(255) NOT NULL,
    unit                   VARCHAR(30)  NULL,
    scale                  DECIMAL(10,6) NULL,
    access                 ENUM('read-only','read-write','read-create','write-only',
                                'not-accessible','accessible-for-notify') NOT NULL DEFAULT 'read-only',
    index_type             ENUM('simple','composite') NOT NULL DEFAULT 'simple',
    bit_calculation        BOOLEAN NOT NULL DEFAULT FALSE,
    index_def              JSON NULL,
    enumeration            JSON NULL,
    description            TEXT NULL,
    attribute              VARCHAR(100) NULL,          -- Fase 2
    scale_formula          VARCHAR(64)  NULL,
    full_oid_template      VARCHAR(300) NULL,
    empirical              JSON NULL,
    pending_validation     JSON NULL,
    confidence_extraction  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall     DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                 ENUM('verified','documented','observed','inferred','deprecated',
                                'conflicted','orphan','verified_walk','verified_community')
                               NOT NULL DEFAULT 'observed',
    lifecycle_status       ENUM('introduced','stable','modified','deprecated','removed') NOT NULL DEFAULT 'stable',
    raw_json               JSON NULL,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id, catalog_version_id),
    CONSTRAINT fk_oids_entity  FOREIGN KEY (entity_ref, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id),
    CONSTRAINT fk_oids_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_oid_firmware (
    oid_id             VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    firmware_id        INT NOT NULL,
    PRIMARY KEY (oid_id, catalog_version_id, firmware_id),
    CONSTRAINT fk_oidf_oid      FOREIGN KEY (oid_id, catalog_version_id)
        REFERENCES tkc_oids(id, catalog_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_oidf_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 8: Relaciones  (PK compuesta) ------------------------------------
CREATE TABLE tkc_relations (
    id                     VARCHAR(200) NOT NULL,
    catalog_version_id     INT NOT NULL,
    source_entity          VARCHAR(150) NOT NULL,
    relation_type          ENUM('belongs_to','uses','has','depends_on','maps_to','triggers') NOT NULL,
    target_entity          VARCHAR(150) NOT NULL,
    cardinality            ENUM('one_to_one','one_to_many','many_to_one','many_to_many') NOT NULL,
    required               BOOLEAN NOT NULL DEFAULT FALSE,
    prerequisite           BOOLEAN NOT NULL DEFAULT FALSE,
    creation_order         INT NULL,
    description            TEXT NULL,
    confidence_extraction  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall     DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                 ENUM('verified','documented','observed','inferred','deprecated',
                                'conflicted','verified_walk','verified_community')
                               NOT NULL DEFAULT 'documented',
    raw_json               JSON NULL,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id, catalog_version_id),
    CONSTRAINT fk_rel_source  FOREIGN KEY (source_entity, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id),
    CONSTRAINT fk_rel_target  FOREIGN KEY (target_entity, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id),
    CONSTRAINT fk_rel_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 9: Alarmas  (PK compuesta) ---------------------------------------
CREATE TABLE tkc_alarms (
    id                      VARCHAR(150) NOT NULL,
    catalog_version_id      INT NOT NULL,
    code                    VARCHAR(50)  NOT NULL,
    name                    VARCHAR(100) NOT NULL,
    canonical_name          VARCHAR(200) NOT NULL,
    entity_ref              VARCHAR(150) NOT NULL,
    severity                ENUM('warning','major','critical') NOT NULL,
    alarm_type              ENUM('optical','hardware','power','security','traffic','protocol','environmental') NOT NULL,
    description             TEXT NULL,
    oid_trap                VARCHAR(200) NULL,
    auto_clear              BOOLEAN NOT NULL DEFAULT FALSE,
    clear_condition         TEXT NULL,
    threshold_metric        VARCHAR(100) NULL,
    threshold_operator      ENUM('gt','lt','eq','gte','lte') NULL,
    threshold_value         DECIMAL(10,4) NULL,
    threshold_unit          VARCHAR(30)  NULL,
    escalation_warning_min  INT NULL,
    escalation_major_min    INT NULL,
    escalation_critical_min INT NULL,
    probable_causes         JSON NULL,
    remediation             JSON NULL,
    confidence_extraction   DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall      DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                  ENUM('verified','documented','observed','inferred','deprecated',
                                 'conflicted','verified_walk','verified_community')
                                NOT NULL DEFAULT 'documented',
    raw_json                JSON NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id, catalog_version_id),
    CONSTRAINT fk_alarms_entity  FOREIGN KEY (entity_ref, catalog_version_id)
        REFERENCES tkc_entities(id, catalog_version_id),
    CONSTRAINT fk_alarms_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id),
    UNIQUE KEY uq_alarm (entity_ref, code, catalog_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_alarm_oid_refs (
    alarm_id           VARCHAR(150) NOT NULL,
    oid_id             VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    PRIMARY KEY (alarm_id, oid_id, catalog_version_id),
    CONSTRAINT fk_aor_alarm FOREIGN KEY (alarm_id, catalog_version_id)
        REFERENCES tkc_alarms(id, catalog_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_aor_oid   FOREIGN KEY (oid_id, catalog_version_id)
        REFERENCES tkc_oids(id, catalog_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_alarm_firmware (
    alarm_id           VARCHAR(150) NOT NULL,
    catalog_version_id INT NOT NULL,
    firmware_id        INT NOT NULL,
    PRIMARY KEY (alarm_id, catalog_version_id, firmware_id),
    CONSTRAINT fk_af_alarm    FOREIGN KEY (alarm_id, catalog_version_id)
        REFERENCES tkc_alarms(id, catalog_version_id) ON DELETE CASCADE,
    CONSTRAINT fk_af_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 10-12: Results / delta / completeness ----------------------------
CREATE TABLE tkc_results (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    result_type        ENUM('conflict','orphan','delta','variant') NOT NULL,
    artifact_type      ENUM('entity','command','oid','relation','alarm') NOT NULL,
    artifact_id        VARCHAR(200) NOT NULL,          -- sin FK (polimorfico): loader valida
    vendor_id          INT NOT NULL,
    catalog_version_id INT NOT NULL,
    resolved           BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at        DATETIME NULL,
    payload            JSON NOT NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_results_vendor  FOREIGN KEY (vendor_id)          REFERENCES tkc_vendors(id),
    CONSTRAINT fk_results_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_delta_runs (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    catalog_version_id      INT NOT NULL,
    triggered_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    trigger_type            ENUM('new_doc','modified_doc','deleted_doc','manual') NOT NULL,
    documents_unchanged     INT NOT NULL DEFAULT 0,
    documents_modified      INT NOT NULL DEFAULT 0,
    documents_new           INT NOT NULL DEFAULT 0,
    documents_deleted       INT NOT NULL DEFAULT 0,
    artifacts_reprocessed   INT NOT NULL DEFAULT 0,
    artifacts_added         INT NOT NULL DEFAULT 0,
    artifacts_modified      INT NOT NULL DEFAULT 0,
    artifacts_orphaned      INT NOT NULL DEFAULT 0,
    processing_time_seconds INT NULL,
    status                  ENUM('completed','partial','failed') NOT NULL DEFAULT 'completed',
    error_message           TEXT NULL,
    CONSTRAINT fk_dr_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_completeness_reports (
    id                        INT AUTO_INCREMENT PRIMARY KEY,
    catalog_version_id        INT NOT NULL,
    evaluated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level_1_doc_complete      BOOLEAN NOT NULL DEFAULT FALSE,
    level_2_artifact_complete BOOLEAN NOT NULL DEFAULT FALSE,
    level_3_production_ready  BOOLEAN NOT NULL DEFAULT FALSE,
    score_entities            DECIMAL(4,3) NULL,
    score_commands            DECIMAL(4,3) NULL,
    score_oids                DECIMAL(4,3) NULL,
    score_relations           DECIMAL(4,3) NULL,
    score_alarms              DECIMAL(4,3) NULL,
    score_global              DECIMAL(4,3) NULL,
    avg_confidence            DECIMAL(4,3) NULL,
    min_confidence            DECIMAL(4,3) NULL,
    critical_conflicts_open   INT NOT NULL DEFAULT 0,
    total_conflicts_open      INT NOT NULL DEFAULT 0,
    ambiguous_aliases         INT NOT NULL DEFAULT 0,
    orphans_pending           INT NOT NULL DEFAULT 0,
    blockers                  JSON NULL,
    scores_detail             JSON NULL,
    CONSTRAINT fk_cr_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 13: Seguridad — sesion efimera del Loader (Fase 2/3) -------------
-- superadmin_id = db_auth.users.id como REFERENCIA BLANDA (sin FK cross-DB).
CREATE TABLE active_sessions (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    superadmin_id CHAR(36)  NOT NULL,
    token_hash    CHAR(64)  NOT NULL,
    created_at    DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at    DATETIME  NOT NULL,
    UNIQUE KEY uq_session_token (token_hash),
    KEY idx_session_admin (superadmin_id),
    KEY idx_session_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --- BLOQUE 14: Indices ------------------------------------------------------
CREATE INDEX idx_catalog_tier_lookup ON tkc_catalog_versions(vendor_id, family_id, tier);
CREATE INDEX idx_tkc_catalog_hash    ON tkc_catalog_versions(content_hash);
CREATE INDEX idx_tkc_aliases_alias     ON tkc_aliases(alias);
CREATE INDEX idx_tkc_aliases_entity    ON tkc_aliases(entity_ref);
CREATE INDEX idx_tkc_aliases_status    ON tkc_aliases(status);
CREATE INDEX idx_tkc_entities_vendor   ON tkc_entities(vendor_id, catalog_version_id);
CREATE INDEX idx_tkc_entities_type     ON tkc_entities(entity_type);
CREATE INDEX idx_tkc_entities_conf     ON tkc_entities(confidence_overall);
CREATE INDEX idx_tkc_entities_status   ON tkc_entities(status);
CREATE INDEX idx_tkc_entities_critical ON tkc_entities(is_critical);
CREATE INDEX idx_tkc_commands_entity   ON tkc_commands(entity_ref);
CREATE INDEX idx_tkc_commands_category ON tkc_commands(category);
CREATE INDEX idx_tkc_commands_version  ON tkc_commands(catalog_version_id);
CREATE INDEX idx_tkc_oids_entity       ON tkc_oids(entity_ref);
CREATE INDEX idx_tkc_oids_status       ON tkc_oids(status);
CREATE INDEX idx_tkc_oids_bitcalc      ON tkc_oids(bit_calculation);
CREATE INDEX idx_tkc_oids_attribute    ON tkc_oids(attribute);
CREATE INDEX idx_tkc_relations_source  ON tkc_relations(source_entity);
CREATE INDEX idx_tkc_relations_target  ON tkc_relations(target_entity);
CREATE INDEX idx_tkc_relations_prereq  ON tkc_relations(prerequisite);
CREATE INDEX idx_tkc_alarms_code       ON tkc_alarms(code);
CREATE INDEX idx_tkc_alarms_severity   ON tkc_alarms(severity);
CREATE INDEX idx_tkc_documents_vendor  ON tkc_documents(vendor_id, family_id);
CREATE INDEX idx_tkc_documents_type    ON tkc_documents(doc_type);
CREATE INDEX idx_tkc_documents_status  ON tkc_documents(status);
CREATE INDEX idx_tkc_documents_hash    ON tkc_documents(hash);
CREATE INDEX idx_tkc_results_type      ON tkc_results(result_type);
CREATE INDEX idx_tkc_results_art       ON tkc_results(artifact_type, artifact_id);
CREATE INDEX idx_tkc_results_vendor    ON tkc_results(vendor_id, catalog_version_id);
CREATE INDEX idx_tkc_results_resolved  ON tkc_results(resolved);
CREATE INDEX idx_tkc_delta_catalog     ON tkc_delta_runs(catalog_version_id);
CREATE INDEX idx_tkc_delta_status      ON tkc_delta_runs(status);

-- --- BLOQUE 15: Seeds --------------------------------------------------------
INSERT IGNORE INTO tkc_vendors (name, oid_prefix, notes) VALUES
('ZTE',    '1.3.6.1.4.1.3902',  'Indices compuestos; bit_calculation / formula community'),
('Huawei', '1.3.6.1.4.1.2011',  'Prefijo enterprise 2011.6.128.*'),
('VSOL',   '1.3.6.1.4.1.34592', 'SNMP bloqueado por defecto, SSH2 primario');

INSERT IGNORE INTO tkc_families (vendor_id, name, technology, notes)
SELECT id, 'ZXA10 C300', 'gpon', 'OLT ZTE serie C300'  FROM tkc_vendors WHERE name = 'ZTE'    UNION ALL
SELECT id, 'ZXA10 C320', 'gpon', 'OLT ZTE serie C320'  FROM tkc_vendors WHERE name = 'ZTE'    UNION ALL
SELECT id, 'MA5608T',    'gpon', 'OLT Huawei MA5600'    FROM tkc_vendors WHERE name = 'Huawei' UNION ALL
SELECT id, 'V1600G',     'gpon', 'OLT VSOL V1600'       FROM tkc_vendors WHERE name = 'VSOL'   UNION ALL
SELECT id, 'V1600GS',    'gpon', 'OLT VSOL V1600GS'     FROM tkc_vendors WHERE name = 'VSOL';

INSERT IGNORE INTO tkc_firmwares (family_id, version, is_current)
SELECT id, '2.0', FALSE FROM tkc_families WHERE name = 'ZXA10 C320' UNION ALL
SELECT id, '2.1', TRUE  FROM tkc_families WHERE name = 'ZXA10 C320' UNION ALL
SELECT id, '2.0', FALSE FROM tkc_families WHERE name = 'ZXA10 C300' UNION ALL
SELECT id, '2.1', TRUE  FROM tkc_families WHERE name = 'ZXA10 C300';

SET SQL_MODE = @OLD_SQL_MODE;

-- ############################################################################
-- FASE 3 — SEGURIDAD: triggers de autorizacion (factor 2).
-- Se aplican al final del mismo deploy. Si preferis probar la carga ANTES de
-- activarlos, comenta de aqui hacia abajo y correlo despues.
-- ############################################################################

-- --- Funcion de chequeo: hay una sesion viva para @actor_id/@actor_token? -----
DROP FUNCTION IF EXISTS tkc_is_authorized;

DELIMITER $$
CREATE FUNCTION tkc_is_authorized() RETURNS BOOLEAN
DETERMINISTIC READS SQL DATA
BEGIN
    -- @actor_id/@actor_token toman la collation por defecto de la conexion
    -- (utf8mb4_0900_ai_ci en MySQL 8), distinta de la del esquema
    -- (utf8mb4_unicode_ci): sin el COLLATE explicito, MySQL rechaza el '='
    -- con "Illegal mix of collations".
    RETURN EXISTS (
        SELECT 1 FROM active_sessions s
        WHERE @actor_id    IS NOT NULL
          AND @actor_token IS NOT NULL
          AND s.superadmin_id = @actor_id    COLLATE utf8mb4_unicode_ci
          AND s.token_hash    = SHA2(@actor_token, 256) COLLATE utf8mb4_unicode_ci
          AND s.expires_at    > NOW()
    );
END$$
DELIMITER ;

-- --- Generador de triggers ---------------------------------------------------
-- Por cada tabla protegida se crean 3 triggers (BEFORE INSERT/UPDATE/DELETE) que
-- llaman a tkc_is_authorized(). Un trigger corre con privilegios de su DEFINER
-- (admin), asi que puede leer active_sessions aunque el actor sea tkc_loader.

DELIMITER $$

-- ===== tkc_catalog_versions =====
DROP TRIGGER IF EXISTS trg_versions_bi$$
CREATE TRIGGER trg_versions_bi BEFORE INSERT ON tkc_catalog_versions FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada (sesion invalida)';
END IF; END$$
DROP TRIGGER IF EXISTS trg_versions_bu$$
CREATE TRIGGER trg_versions_bu BEFORE UPDATE ON tkc_catalog_versions FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada (sesion invalida)';
END IF; END$$
DROP TRIGGER IF EXISTS trg_versions_bd$$
CREATE TRIGGER trg_versions_bd BEFORE DELETE ON tkc_catalog_versions FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada (sesion invalida)';
END IF; END$$

-- ===== tkc_entities =====
DROP TRIGGER IF EXISTS trg_entities_bi$$
CREATE TRIGGER trg_entities_bi BEFORE INSERT ON tkc_entities FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_entities_bu$$
CREATE TRIGGER trg_entities_bu BEFORE UPDATE ON tkc_entities FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_entities_bd$$
CREATE TRIGGER trg_entities_bd BEFORE DELETE ON tkc_entities FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_entity_firmware =====
DROP TRIGGER IF EXISTS trg_ef_bi$$
CREATE TRIGGER trg_ef_bi BEFORE INSERT ON tkc_entity_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_ef_bu$$
CREATE TRIGGER trg_ef_bu BEFORE UPDATE ON tkc_entity_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_ef_bd$$
CREATE TRIGGER trg_ef_bd BEFORE DELETE ON tkc_entity_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_entity_attributes =====
DROP TRIGGER IF EXISTS trg_ea_bi$$
CREATE TRIGGER trg_ea_bi BEFORE INSERT ON tkc_entity_attributes FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_ea_bu$$
CREATE TRIGGER trg_ea_bu BEFORE UPDATE ON tkc_entity_attributes FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_ea_bd$$
CREATE TRIGGER trg_ea_bd BEFORE DELETE ON tkc_entity_attributes FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_aliases =====
DROP TRIGGER IF EXISTS trg_aliases_bi$$
CREATE TRIGGER trg_aliases_bi BEFORE INSERT ON tkc_aliases FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_aliases_bu$$
CREATE TRIGGER trg_aliases_bu BEFORE UPDATE ON tkc_aliases FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_aliases_bd$$
CREATE TRIGGER trg_aliases_bd BEFORE DELETE ON tkc_aliases FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_commands =====
DROP TRIGGER IF EXISTS trg_commands_bi$$
CREATE TRIGGER trg_commands_bi BEFORE INSERT ON tkc_commands FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_commands_bu$$
CREATE TRIGGER trg_commands_bu BEFORE UPDATE ON tkc_commands FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_commands_bd$$
CREATE TRIGGER trg_commands_bd BEFORE DELETE ON tkc_commands FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_command_params =====
DROP TRIGGER IF EXISTS trg_cp_bi$$
CREATE TRIGGER trg_cp_bi BEFORE INSERT ON tkc_command_params FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_cp_bu$$
CREATE TRIGGER trg_cp_bu BEFORE UPDATE ON tkc_command_params FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_cp_bd$$
CREATE TRIGGER trg_cp_bd BEFORE DELETE ON tkc_command_params FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_command_output_fields =====
DROP TRIGGER IF EXISTS trg_cof_bi$$
CREATE TRIGGER trg_cof_bi BEFORE INSERT ON tkc_command_output_fields FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_cof_bu$$
CREATE TRIGGER trg_cof_bu BEFORE UPDATE ON tkc_command_output_fields FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_cof_bd$$
CREATE TRIGGER trg_cof_bd BEFORE DELETE ON tkc_command_output_fields FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_command_firmware =====
DROP TRIGGER IF EXISTS trg_cmdf_bi$$
CREATE TRIGGER trg_cmdf_bi BEFORE INSERT ON tkc_command_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_cmdf_bu$$
CREATE TRIGGER trg_cmdf_bu BEFORE UPDATE ON tkc_command_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_cmdf_bd$$
CREATE TRIGGER trg_cmdf_bd BEFORE DELETE ON tkc_command_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_oids =====
DROP TRIGGER IF EXISTS trg_oids_bi$$
CREATE TRIGGER trg_oids_bi BEFORE INSERT ON tkc_oids FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_oids_bu$$
CREATE TRIGGER trg_oids_bu BEFORE UPDATE ON tkc_oids FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_oids_bd$$
CREATE TRIGGER trg_oids_bd BEFORE DELETE ON tkc_oids FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_oid_firmware =====
DROP TRIGGER IF EXISTS trg_oidf_bi$$
CREATE TRIGGER trg_oidf_bi BEFORE INSERT ON tkc_oid_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_oidf_bu$$
CREATE TRIGGER trg_oidf_bu BEFORE UPDATE ON tkc_oid_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_oidf_bd$$
CREATE TRIGGER trg_oidf_bd BEFORE DELETE ON tkc_oid_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_relations =====
DROP TRIGGER IF EXISTS trg_rel_bi$$
CREATE TRIGGER trg_rel_bi BEFORE INSERT ON tkc_relations FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_rel_bu$$
CREATE TRIGGER trg_rel_bu BEFORE UPDATE ON tkc_relations FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_rel_bd$$
CREATE TRIGGER trg_rel_bd BEFORE DELETE ON tkc_relations FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_alarms =====
DROP TRIGGER IF EXISTS trg_alarms_bi$$
CREATE TRIGGER trg_alarms_bi BEFORE INSERT ON tkc_alarms FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_alarms_bu$$
CREATE TRIGGER trg_alarms_bu BEFORE UPDATE ON tkc_alarms FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_alarms_bd$$
CREATE TRIGGER trg_alarms_bd BEFORE DELETE ON tkc_alarms FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_alarm_oid_refs =====
DROP TRIGGER IF EXISTS trg_aor_bi$$
CREATE TRIGGER trg_aor_bi BEFORE INSERT ON tkc_alarm_oid_refs FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_aor_bu$$
CREATE TRIGGER trg_aor_bu BEFORE UPDATE ON tkc_alarm_oid_refs FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_aor_bd$$
CREATE TRIGGER trg_aor_bd BEFORE DELETE ON tkc_alarm_oid_refs FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_alarm_firmware =====
DROP TRIGGER IF EXISTS trg_af_bi$$
CREATE TRIGGER trg_af_bi BEFORE INSERT ON tkc_alarm_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_af_bu$$
CREATE TRIGGER trg_af_bu BEFORE UPDATE ON tkc_alarm_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_af_bd$$
CREATE TRIGGER trg_af_bd BEFORE DELETE ON tkc_alarm_firmware FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

-- ===== tkc_results =====
DROP TRIGGER IF EXISTS trg_results_bi$$
CREATE TRIGGER trg_results_bi BEFORE INSERT ON tkc_results FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_results_bu$$
CREATE TRIGGER trg_results_bu BEFORE UPDATE ON tkc_results FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$
DROP TRIGGER IF EXISTS trg_results_bd$$
CREATE TRIGGER trg_results_bd BEFORE DELETE ON tkc_results FOR EACH ROW
BEGIN IF NOT tkc_is_authorized() THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ispm_tkc: escritura no autorizada'; END IF; END$$

DELIMITER ;

-- Verificar:   SHOW TRIGGERS FROM ispm_tkc;
-- Quitar todo: DROP FUNCTION tkc_is_authorized;  y  DROP TRIGGER cada trg_*;
