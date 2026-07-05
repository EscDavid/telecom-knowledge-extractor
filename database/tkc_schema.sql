-- =============================================================================
-- Telecom Knowledge Compiler (TKC) — Schema SQL v3
-- Motor: MySQL 8.0+
-- Prefijo: tkc_
-- Global: sin company_id — catálogo compartido por todos los ISPs
-- Puente con proyecto: olts.tkc_family_id → tkc_families.id
-- =============================================================================

SET FOREIGN_KEY_CHECKS = 0;
SET @OLD_SQL_MODE = @@SQL_MODE;
SET SQL_MODE = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION';

-- -----------------------------------------------------------------------------
-- LIMPIEZA — orden inverso de dependencias
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- BLOQUE 1 — Taxonomía base
-- tkc_vendors es la tabla maestra de vendors conocidos
-- Los INSERTs de families y firmwares referencian por WHERE name=
-- nunca por ID hardcodeado
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- BLOQUE 2 — Metadata de documentos procesados
-- No guarda contenido binario ni rutas
-- Solo hash + tipo para que el Delta Processor detecte cambios entre runs
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_documents (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    vendor_id             INT NOT NULL,
    family_id             INT NOT NULL,
    firmware_id           INT NULL,
    doc_type              ENUM(
                              'mib_file',
                              'mib_specification',
                              'command_reference',
                              'initial_configuration',
                              'product_catalog',
                              'alarm_reference',
                              'hardware_description'
                          ) NOT NULL,
    hash                  VARCHAR(64)  NOT NULL,
    status                ENUM('classified','partial','unclassified') NOT NULL DEFAULT 'unclassified',
    classifier_output     JSON NULL,
    processed_at          DATETIME NULL,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_documents_vendor   FOREIGN KEY (vendor_id)   REFERENCES tkc_vendors(id),
    CONSTRAINT fk_documents_family   FOREIGN KEY (family_id)   REFERENCES tkc_families(id),
    CONSTRAINT fk_documents_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id),
    UNIQUE KEY uq_document (vendor_id, family_id, doc_type, hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 3 — Versiones del catálogo
-- Cada compilación genera una versión inmutable
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_catalog_versions (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    vendor_id          INT NOT NULL,
    family_id          INT NOT NULL,
    version            VARCHAR(20) NOT NULL,
    previous_version   VARCHAR(20) NULL,
    generated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_latest          BOOLEAN NOT NULL DEFAULT FALSE,
    breaking_changes   BOOLEAN NOT NULL DEFAULT FALSE,
    migration_required BOOLEAN NOT NULL DEFAULT FALSE,
    changelog          JSON NULL,
    dist_path          VARCHAR(500) NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_catalog_vendor FOREIGN KEY (vendor_id) REFERENCES tkc_vendors(id),
    CONSTRAINT fk_catalog_family FOREIGN KEY (family_id) REFERENCES tkc_families(id),
    UNIQUE KEY uq_catalog_version (vendor_id, family_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 4 — Entidades
-- Conceptos gestionables: ONU, OLT, GEM Port, VLAN, Card, etc.
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_entities (
    id                      VARCHAR(150) PRIMARY KEY,
    canonical_name          VARCHAR(150) NOT NULL,
    vendor_id               INT NOT NULL,
    family_id               INT NOT NULL,
    catalog_version_id      INT NOT NULL,
    technology              VARCHAR(50)  NOT NULL,
    entity_type             ENUM(
                                'device',
                                'port',
                                'logical',
                                'hardware',
                                'profile',
                                'protocol'
                            ) NOT NULL,
    description             TEXT NULL,
    is_critical             BOOLEAN NOT NULL DEFAULT FALSE,
    confidence_extraction   DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall      DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                  ENUM(
                                'verified',
                                'documented',
                                'observed',
                                'inferred',
                                'deprecated',
                                'conflicted',
                                'orphan'
                            ) NOT NULL DEFAULT 'observed',
    lifecycle_introduced_in INT NULL,
    lifecycle_deprecated_in INT NULL,
    lifecycle_removed_in    INT NULL,
    lifecycle_status        ENUM(
                                'introduced',
                                'stable',
                                'modified',
                                'deprecated',
                                'removed'
                            ) NOT NULL DEFAULT 'introduced',
    replacement_id          VARCHAR(150) NULL,
    raw_json                JSON NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_entities_vendor   FOREIGN KEY (vendor_id)               REFERENCES tkc_vendors(id),
    CONSTRAINT fk_entities_family   FOREIGN KEY (family_id)               REFERENCES tkc_families(id),
    CONSTRAINT fk_entities_catalog  FOREIGN KEY (catalog_version_id)      REFERENCES tkc_catalog_versions(id),
    CONSTRAINT fk_entities_intro    FOREIGN KEY (lifecycle_introduced_in) REFERENCES tkc_firmwares(id),
    CONSTRAINT fk_entities_depr     FOREIGN KEY (lifecycle_deprecated_in) REFERENCES tkc_firmwares(id),
    CONSTRAINT fk_entities_removed  FOREIGN KEY (lifecycle_removed_in)    REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_entity_firmware (
    entity_id   VARCHAR(150) NOT NULL,
    firmware_id INT NOT NULL,
    PRIMARY KEY (entity_id, firmware_id),
    CONSTRAINT fk_ef_entity   FOREIGN KEY (entity_id)   REFERENCES tkc_entities(id),
    CONSTRAINT fk_ef_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_entity_attributes (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    entity_id       VARCHAR(150) NOT NULL,
    name            VARCHAR(100) NOT NULL,
    attr_type       VARCHAR(50)  NOT NULL,
    range_def       VARCHAR(100) NULL,
    required        BOOLEAN NOT NULL DEFAULT FALSE,
    source_doc_type VARCHAR(50)  NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ea_entity FOREIGN KEY (entity_id) REFERENCES tkc_entities(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 5 — Aliases
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_aliases (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    entity_ref              VARCHAR(150) NULL,
    alias                   VARCHAR(150) NOT NULL,
    source_doc_type         VARCHAR(50)  NOT NULL,
    firmware_scope          VARCHAR(20)  NOT NULL DEFAULT 'all',
    status                  ENUM(
                                'assigned',
                                'ambiguous',
                                'cross_vendor'
                            ) NOT NULL DEFAULT 'assigned',
    candidates              JSON NULL,
    cross_vendor_entity     VARCHAR(150) NULL,
    cross_vendor_confidence DECIMAL(4,3) NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_aliases_entity FOREIGN KEY (entity_ref) REFERENCES tkc_entities(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 6 — Comandos CLI
-- entity_ref es NULL para comandos globales (save, enable, reload)
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_commands (
    id                     VARCHAR(150) PRIMARY KEY,
    canonical_name         VARCHAR(200) NOT NULL,
    vendor_id              INT NOT NULL,
    family_id              INT NOT NULL,
    catalog_version_id     INT NOT NULL,
    technology             VARCHAR(50)  NOT NULL,
    category               ENUM(
                               'show',
                               'create',
                               'delete',
                               'modify',
                               'enable',
                               'disable',
                               'reset',
                               'diagnose'
                           ) NOT NULL,
    cli_mode               ENUM(
                               'user_exec',
                               'privileged_exec',
                               'global_config',
                               'interface_config',
                               'pon_config'
                           ) NOT NULL,
    entity_ref             VARCHAR(150) NULL,
    description            TEXT NULL,
    syntax                 VARCHAR(500) NULL,
    confidence_extraction  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall     DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                 ENUM(
                               'verified',
                               'documented',
                               'observed',
                               'inferred',
                               'deprecated',
                               'conflicted',
                               'orphan'
                           ) NOT NULL DEFAULT 'documented',
    lifecycle_status       ENUM(
                               'introduced',
                               'stable',
                               'modified',
                               'deprecated',
                               'removed'
                           ) NOT NULL DEFAULT 'stable',
    raw_json               JSON NULL,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_commands_vendor  FOREIGN KEY (vendor_id)          REFERENCES tkc_vendors(id),
    CONSTRAINT fk_commands_family  FOREIGN KEY (family_id)          REFERENCES tkc_families(id),
    CONSTRAINT fk_commands_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id),
    CONSTRAINT fk_commands_entity  FOREIGN KEY (entity_ref)         REFERENCES tkc_entities(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_command_params (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    command_id  VARCHAR(150) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    param_type  VARCHAR(50)  NOT NULL,
    pattern     VARCHAR(200) NULL,
    range_def   VARCHAR(100) NULL,
    required    BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT NULL,
    example     VARCHAR(200) NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_cp_command FOREIGN KEY (command_id) REFERENCES tkc_commands(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- oid_ref sin FK para evitar ciclo commands↔oids
-- Loader valida existencia antes de insertar
CREATE TABLE tkc_command_output_fields (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    command_id VARCHAR(150) NOT NULL,
    name       VARCHAR(100) NOT NULL,
    field_type VARCHAR(50)  NOT NULL,
    unit       VARCHAR(30)  NULL,
    oid_ref    VARCHAR(150) NULL,
    oid_status ENUM('mapped','not_mapped','inferred') NOT NULL DEFAULT 'not_mapped',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_cof_command FOREIGN KEY (command_id) REFERENCES tkc_commands(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_command_firmware (
    command_id  VARCHAR(150) NOT NULL,
    firmware_id INT NOT NULL,
    PRIMARY KEY (command_id, firmware_id),
    CONSTRAINT fk_cmdf_command  FOREIGN KEY (command_id)  REFERENCES tkc_commands(id),
    CONSTRAINT fk_cmdf_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 7 — OIDs SNMP
-- command_ref sin FK para evitar ciclo commands↔oids
-- Loader valida existencia antes de insertar
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_oids (
    id                     VARCHAR(150) PRIMARY KEY,
    oid_string             VARCHAR(200) NOT NULL,
    name                   VARCHAR(200) NOT NULL,
    mib_table              VARCHAR(200) NULL,
    entity_ref             VARCHAR(150) NOT NULL,
    command_ref            VARCHAR(150) NULL,
    catalog_version_id     INT NOT NULL,
    syntax                 VARCHAR(50)  NOT NULL,
    unit                   VARCHAR(30)  NULL,
    scale                  DECIMAL(10,6) NULL,
    access                 ENUM(
                               'read-only',
                               'read-write',
                               'not-accessible'
                           ) NOT NULL DEFAULT 'read-only',
    index_type             ENUM('simple','composite') NOT NULL DEFAULT 'simple',
    bit_calculation        BOOLEAN NOT NULL DEFAULT FALSE,
    index_def              JSON NULL,
    enumeration            JSON NULL,
    description            TEXT NULL,
    confidence_extraction  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall     DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                 ENUM(
                               'verified',
                               'documented',
                               'observed',
                               'inferred',
                               'deprecated',
                               'conflicted',
                               'orphan'
                           ) NOT NULL DEFAULT 'observed',
    lifecycle_status       ENUM(
                               'introduced',
                               'stable',
                               'modified',
                               'deprecated',
                               'removed'
                           ) NOT NULL DEFAULT 'stable',
    raw_json               JSON NULL,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_oids_entity  FOREIGN KEY (entity_ref)         REFERENCES tkc_entities(id),
    CONSTRAINT fk_oids_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_oid_firmware (
    oid_id      VARCHAR(150) NOT NULL,
    firmware_id INT NOT NULL,
    PRIMARY KEY (oid_id, firmware_id),
    CONSTRAINT fk_oidf_oid      FOREIGN KEY (oid_id)      REFERENCES tkc_oids(id),
    CONSTRAINT fk_oidf_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 8 — Relaciones entre entidades
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_relations (
    id                     VARCHAR(200) PRIMARY KEY,
    source_entity          VARCHAR(150) NOT NULL,
    relation_type          ENUM(
                               'belongs_to',
                               'uses',
                               'has',
                               'depends_on',
                               'maps_to',
                               'triggers'
                           ) NOT NULL,
    target_entity          VARCHAR(150) NOT NULL,
    cardinality            ENUM(
                               'one_to_one',
                               'one_to_many',
                               'many_to_one',
                               'many_to_many'
                           ) NOT NULL,
    required               BOOLEAN NOT NULL DEFAULT FALSE,
    prerequisite           BOOLEAN NOT NULL DEFAULT FALSE,
    creation_order         INT NULL,
    catalog_version_id     INT NOT NULL,
    description            TEXT NULL,
    confidence_extraction  DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_correlation DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    confidence_overall     DECIMAL(4,3) NOT NULL DEFAULT 0.000,
    status                 ENUM(
                               'verified',
                               'documented',
                               'observed',
                               'inferred',
                               'deprecated',
                               'conflicted'
                           ) NOT NULL DEFAULT 'documented',
    raw_json               JSON NULL,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_rel_source  FOREIGN KEY (source_entity)      REFERENCES tkc_entities(id),
    CONSTRAINT fk_rel_target  FOREIGN KEY (target_entity)      REFERENCES tkc_entities(id),
    CONSTRAINT fk_rel_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 9 — Alarmas
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_alarms (
    id                      VARCHAR(150) PRIMARY KEY,
    code                    VARCHAR(50)  NOT NULL,
    name                    VARCHAR(100) NOT NULL,
    canonical_name          VARCHAR(200) NOT NULL,
    entity_ref              VARCHAR(150) NOT NULL,
    catalog_version_id      INT NOT NULL,
    severity                ENUM('warning','major','critical') NOT NULL,
    alarm_type              ENUM(
                                'optical',
                                'hardware',
                                'power',
                                'security',
                                'traffic',
                                'protocol',
                                'environmental'
                            ) NOT NULL,
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
    status                  ENUM(
                                'verified',
                                'documented',
                                'observed',
                                'inferred',
                                'deprecated',
                                'conflicted'
                            ) NOT NULL DEFAULT 'documented',
    raw_json                JSON NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_alarms_entity  FOREIGN KEY (entity_ref)         REFERENCES tkc_entities(id),
    CONSTRAINT fk_alarms_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id),
    UNIQUE KEY uq_alarm (entity_ref, code, catalog_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_alarm_oid_refs (
    alarm_id VARCHAR(150) NOT NULL,
    oid_id   VARCHAR(150) NOT NULL,
    PRIMARY KEY (alarm_id, oid_id),
    CONSTRAINT fk_aor_alarm FOREIGN KEY (alarm_id) REFERENCES tkc_alarms(id),
    CONSTRAINT fk_aor_oid   FOREIGN KEY (oid_id)   REFERENCES tkc_oids(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tkc_alarm_firmware (
    alarm_id    VARCHAR(150) NOT NULL,
    firmware_id INT NOT NULL,
    PRIMARY KEY (alarm_id, firmware_id),
    CONSTRAINT fk_af_alarm    FOREIGN KEY (alarm_id)    REFERENCES tkc_alarms(id),
    CONSTRAINT fk_af_firmware FOREIGN KEY (firmware_id) REFERENCES tkc_firmwares(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 10 — Results
-- Tabla unificada para análisis e investigación del Compiler
-- No usada por el backend en producción
-- artifact_type + artifact_id forman puntero lógico al artefacto afectado
-- artifact_id sin FK por polimorfismo — Loader valida existencia antes de insertar
--
-- result_type:
--   conflict → dos fuentes dicen cosas distintas sobre el mismo campo
--   orphan   → artefacto sin fuente que lo respalde
--   delta    → registro de cambios entre runs del Compiler
--   variant  → mismo artefacto con datos distintos entre firmwares
-- -----------------------------------------------------------------------------

CREATE TABLE tkc_results (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    result_type        ENUM('conflict','orphan','delta','variant') NOT NULL,
    artifact_type      ENUM('entity','command','oid','relation','alarm') NOT NULL,
    artifact_id        VARCHAR(200) NOT NULL,
    vendor_id          INT NOT NULL,
    catalog_version_id INT NOT NULL,
    resolved           BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at        DATETIME NULL,
    payload            JSON NOT NULL,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_results_vendor  FOREIGN KEY (vendor_id)          REFERENCES tkc_vendors(id),
    CONSTRAINT fk_results_catalog FOREIGN KEY (catalog_version_id) REFERENCES tkc_catalog_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- BLOQUE 11 — Delta runs
-- Registro de cada ejecución del Compiler
-- Los artefactos afectados van en tkc_results con result_type = 'delta'
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- BLOQUE 12 — Completeness reports
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- BLOQUE 13 — Índices de performance
-- Derivados de QUERY_SPEC.md
-- -----------------------------------------------------------------------------

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
CREATE INDEX idx_tkc_oids_version      ON tkc_oids(catalog_version_id);

CREATE INDEX idx_tkc_relations_source  ON tkc_relations(source_entity);
CREATE INDEX idx_tkc_relations_target  ON tkc_relations(target_entity);
CREATE INDEX idx_tkc_relations_prereq  ON tkc_relations(prerequisite);
CREATE INDEX idx_tkc_relations_version ON tkc_relations(catalog_version_id);

CREATE INDEX idx_tkc_alarms_entity     ON tkc_alarms(entity_ref);
CREATE INDEX idx_tkc_alarms_code       ON tkc_alarms(code);
CREATE INDEX idx_tkc_alarms_severity   ON tkc_alarms(severity);
CREATE INDEX idx_tkc_alarms_version    ON tkc_alarms(catalog_version_id);

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

-- -----------------------------------------------------------------------------
-- BLOQUE 14 — Setup inicial
-- INSERT IGNORE evita error en ejecuciones repetidas
-- Families y firmwares referencian por WHERE name= nunca por ID hardcodeado
-- -----------------------------------------------------------------------------

INSERT IGNORE INTO tkc_vendors (name, oid_prefix, notes) VALUES
('ZTE',    '1.3.6.1.4.1.3902',  'Índices compuestos de 32 bits, bit_calculation requerido'),
('Huawei', '1.3.6.1.4.1.2011',  'Prefijo enterprise 2011.6.128.*'),
('VSOL',   '1.3.6.1.4.1.34592', 'SNMP bloqueado por defecto, SSH2 como protocolo primario');

INSERT IGNORE INTO tkc_families (vendor_id, name, technology, notes)
SELECT id, 'ZXA10 C320', 'gpon', 'OLT ZTE serie C300/C320'  FROM tkc_vendors WHERE name = 'ZTE'    UNION ALL
SELECT id, 'MA5608T',    'gpon', 'OLT Huawei serie MA5600'   FROM tkc_vendors WHERE name = 'Huawei' UNION ALL
SELECT id, 'V1600G',     'gpon', 'OLT VSOL serie V1600'      FROM tkc_vendors WHERE name = 'VSOL'   UNION ALL
SELECT id, 'V1600GS',    'gpon', 'OLT VSOL serie V1600GS'    FROM tkc_vendors WHERE name = 'VSOL';

INSERT IGNORE INTO tkc_firmwares (family_id, version, is_current)
SELECT id, '2.0', FALSE FROM tkc_families WHERE name = 'ZXA10 C320' UNION ALL
SELECT id, '2.1', TRUE  FROM tkc_families WHERE name = 'ZXA10 C320';

-- -----------------------------------------------------------------------------
-- BLOQUE 15 — Puente con tabla olts del proyecto
-- El puente NO va aqui: `olts` vive en isp_management, no en isp_catalog, y el
-- diseno usa REFERENCIA BLANDA (sin FK cross-DB). Correr por separado, en
-- isp_management, el script `database/bridge_isp_management.sql`.
-- -----------------------------------------------------------------------------

SET SQL_MODE = @OLD_SQL_MODE;
