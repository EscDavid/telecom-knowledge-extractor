-- =============================================================================
-- Puente isp_management.olts  →  isp_catalog.tkc_families  (REFERENCIA BLANDA)
-- Correr EN isp_management (NO en isp_catalog).
-- Sin FK cross-DB (a proposito): desacopla backups/drops entre las dos DBs y
-- evita acoplar la DB operativa al ciclo de recarga del catalogo. La app valida
-- la referencia; el valor es isp_catalog.tkc_families.id.
-- =============================================================================

USE isp_management;

ALTER TABLE olts
    ADD COLUMN tkc_family_id INT NULL;

CREATE INDEX idx_olts_tkc_family ON olts(tkc_family_id);

-- Nota: si en el futuro se quiere integridad dura, MySQL permite FK cross-DB en la
-- misma instancia; pero para "evitar problemas" se deja como referencia blanda.
