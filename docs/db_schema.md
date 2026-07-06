# Esquema `ispm_tkc` + Fase 2 del Loader (mapeo JSON → tablas)

Referencia consolidada de la DB que vamos a crear y de que hace exactamente el Loader
en la Fase 2. El SQL vive en `database/ispm_tkc.sql` (base v3) + `database/migration.sql`
(delta Fase 2). Este doc es la vista legible + el contrato de carga.

## Despliegue (orden)

```sql
CREATE DATABASE ispm_tkc CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ispm_tkc;
-- source ispm_tkc.sql   ← SIN el bloque final "ALTER TABLE olts ..." (olts vive en isp_management)
-- source migration.sql    ← ENUMs Fase2 + columnas tkc_oids + content_hash + active_sessions
-- source triggers.sql     ← AL FINAL (Fase 3)
```

## Estructura (22 tablas `tkc_` + `active_sessions`)

**Taxonomia** — `tkc_vendors` → `tkc_families` → `tkc_firmwares` (seeds ya en el schema).
**Documentos/versiones** — `tkc_documents` (hash por doc, delta), `tkc_catalog_versions`
(1 fila por catalogo compilado; **`content_hash`** = raiz Merkle para detectar cambios).

**Artefactos del catalogo** (todos con `confidence_*`, `status`, `raw_json`, y FK a
`catalog_version_id`):

| Tabla | Qué guarda | Tablas hijas (arrays descompuestos) |
|---|---|---|
| `tkc_entities` | onu, olt, pon_port, card, vlan… | `tkc_entity_firmware`, `tkc_entity_attributes`, `tkc_aliases` |
| `tkc_commands` | comandos CLI reales | `tkc_command_params`, `tkc_command_output_fields`, `tkc_command_firmware` |
| `tkc_oids` | OIDs SNMP (+ campos Fase 2) | `tkc_oid_firmware` |
| `tkc_relations` | aristas entre entidades | — |
| `tkc_alarms` | alarmas (NOTIFICATION-TYPE + KB) | `tkc_alarm_oid_refs`, `tkc_alarm_firmware` |

**Análisis/operación** — `tkc_results` (conflictos/huérfanos/deltas), `tkc_delta_runs`,
`tkc_completeness_reports`.

**Seguridad (Fase 2/3)** — `active_sessions(superadmin_id CHAR(36), token_hash, expires_at)`
en `ispm_tkc` (ref blanda a `db_auth.users.id`). El trigger (Fase 3) valida contra ella.

### Adiciones de Fase 2 (migration.sql)
- `status` ENUM += `verified_walk`, `verified_community` (oids/entities/commands/relations/alarms).
- `access` ENUM += `read-create`, `write-only`, `accessible-for-notify`.
- `tkc_oids` += `attribute`, `scale_formula`, `full_oid_template`, `empirical` JSON, `pending_validation` JSON.
- `tkc_catalog_versions` += `content_hash CHAR(64)`.

## Mapeo JSON del catálogo → tablas

Cada `catalog/<vendor>/<family>/catalog-<version>/`:

| Archivo JSON | Tabla primaria | Columnas clave / descomposición |
|---|---|---|
| `manifest.json` | `tkc_catalog_versions` | version (del dir), generated_at, **content_hash** (calculado por el loader) |
| `entities/<e>.json` | `tkc_entities` | id, canonical_name, entity_type=`type`, is_critical, confidence_*, status, lifecycle_*, description; `firmware[]`→`tkc_entity_firmware`; `attributes[]`→`tkc_entity_attributes`; `aliases[]`→`tkc_aliases`; todo→`raw_json` |
| `commands/<cat>/<c>.json` | `tkc_commands` | id, canonical_name, category, cli_mode, entity_ref, syntax, confidence_*, status; `parameters[]`→`tkc_command_params`; `output_fields[]`→`tkc_command_output_fields` (con `oid_ref`/`oid_status`); `firmware[]`→`tkc_command_firmware`; `prerequisites[]`→`tkc_relations`(depends_on) |
| `oids/<e>.json` (grupo `.oids[]`) | `tkc_oids` | id, oid_string=`oid`, name, mib_table, entity_ref, syntax, unit, scale, access, index_type/bit_calculation/`index_def`=`index`, `enumeration`, confidence_*, status; **Fase2**: `attribute`, `scale_formula`, `full_oid_template`, `empirical`, `pending_validation`; `firmware[]`→`tkc_oid_firmware`; todo→`raw_json` |
| `relations/<e>.json` (grupo `.relations[]`) | `tkc_relations` | id, source_entity, relation_type=`type`, target_entity=`target`, cardinality, required, confidence_*, status |
| `alarms/<e>.json` (grupo `.alarms[]`) | `tkc_alarms` | id, code, name, canonical_name, entity_ref, severity, alarm_type=`type`, description, `probable_causes` JSON, `remediation` JSON, oid_trap, threshold_*/escalation_* (si hay), confidence_*, status; `oid_refs[]`→`tkc_alarm_oid_refs`; `firmware[]`→`tkc_alarm_firmware` |
| `results.json` | `tkc_results` | result_type, artifact_type, artifact_id, payload JSON, resolved |

Refs sin FK (`command_ref` en oids, `oid_ref` en output_fields, `artifact_id` en results):
el loader **valida existencia** antes de insertar (el schema las dejó sin FK a propósito).

## Fase 2 — que hace el Loader, en concreto

Comando: `python -m src.loader load <familia> --authorize --user <superadmin>`

### Paso 1 — Factor 1 (auth contra db_auth, read-only)
```sql
SELECT id, password FROM db_auth.users
WHERE (email = :u OR username = :u)
  AND role_id = 'ed392bf3-272d-11f1-a6e3-42010a400002'   -- Super Admin (por id)
  AND status = 'ACTIVO' AND deleted_at IS NULL;
```
`bcrypt.checkpw(password_ingresado, row.password)`. Si OK → inserta sesión efímera en
`active_sessions` (token aleatorio, `token_hash=SHA2(token,256)`, `expires_at`=+5min) y setea
`SET @actor_id, @actor_token` en la conexión (listos para el trigger de Fase 3).

### Paso 2 — Readiness + hash (reusa Fase 1)
- Calcula `rank_key`/tier; avisa si el tier es bajo.
- `content_hash` local vs `tkc_catalog_versions.content_hash`: si **SIN CAMBIOS**, no recarga.

### Paso 3 — Carga idempotente por versión (una transacción)
1. Upsert taxonomía: `tkc_vendors`/`families`/`firmwares` (INSERT IGNORE por nombre).
2. Upsert `tkc_catalog_versions` (obtiene `catalog_version_id`).
3. **Replace por versión**: DELETE de artefactos con ese `catalog_version_id` en orden inverso
   de FK, luego INSERT en orden de FK:
   `entities(+ef,ea,aliases) → commands(+params,output,cf) → oids(+of) → relations →
    alarms(+aor,af) → results`.
4. Escribe `content_hash` en la fila de versión; marca `is_latest`.
5. `commit` (o `rollback` ante cualquier fallo — todo o nada).

### Verificación
- Cargar `zxa10-c320` (validated) → filas en todas las `tkc_*` con el `catalog_version_id`.
- Re-correr → "SIN CAMBIOS" (hash igual), no duplica.
- Cambiar un OID a `verified_walk` → hash distinto → recarga esa versión.
- `status` refleja `SIN CAMBIOS` tras la carga.

### Módulos Fase 2
- `src/loader/auth.py` — factor 1 (query + bcrypt + crea sesión/token).
- `src/loader/loader.py` — lectura JSON, orden de FK, idempotencia, descomposición de arrays,
  validación de refs blandas, escritura de `content_hash`.
- CLI `load` en `src/loader/__main__.py` (getpass / `--password-env`).
