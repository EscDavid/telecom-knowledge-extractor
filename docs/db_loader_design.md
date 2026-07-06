# Fase DB — Loader, autenticacion y tokens (diseno)

Spec conciso de como se carga el catalogo TKC a MySQL con doble autenticacion y
deteccion automatica de cambios. Estado: DISENO (pendiente de confirmar decisiones al final).

## 1. Arquitectura

- **DB aparte, misma instancia MySQL 8**: `ispm_tkc` separada de `isp_management`
  (operativa) y de `db_auth`. Referencia entre proyectos por dato blando
  (`olts.tkc_family_id INT`, sin FK cross-DB).
- **Instancia**: prod `157.137.210.239` (misma que `db_auth`/`isp_management`), porque el
  catalogo referencia `olts` y la network-api lo lee en vivo. Confirmado: acopla el output del
  pipeline a la instancia productiva (a cambio de que el runtime lo consuma directo).
- El catalogo es **referencia read-mostly, recargable por version**.
- **Grants (contenidos):** la app → `SELECT` en `ispm_tkc`. El Loader → `INSERT/UPDATE/DELETE`
  solo en `ispm_tkc.tkc_*` y `ispm_tkc.active_sessions`, y `SELECT` en `db_auth.users`.
  Nada mas (el token no da poder extra si los grants estan acotados).

## 2. Migration (delta sobre `database/ispm_tkc.sql`)

- Correr `ispm_tkc.sql` en `ispm_tkc` **sin** el `ALTER TABLE olts` final.
- `migration.sql` agrega:
  - `status` ENUM += `verified_walk`, `verified_community` (oids/entities/relations/alarms).
  - `access` ENUM += `read-create`, `write-only`, `accessible-for-notify`.
  - `tkc_oids` += `attribute`, `scale_formula`, `full_oid_template`, `empirical JSON`,
    `pending_validation JSON`.
  - `tkc_catalog_versions` += `content_hash CHAR(64)` (deteccion de cambios).
  - **nueva** `ispm_tkc.active_sessions(superadmin_id CHAR(36), token_hash CHAR(64),
    created_at, expires_at)` — sesion efimera del loader (NO va en `db_auth`, ver seccion 6).
- Todo lo demas ya sobrevive en `raw_json` (forward-compat).

## 3. Loader (fuente = JSON escritos, opcion A)

Lee `catalog/<vendor>/<family>/catalog-<version>/*.json` (desacoplado del pipeline).
Dos subcomandos:

```
python -m src.loader status                 # compara local vs DB, muestra tier + cambios
python -m src.loader load <familia> --authorize --user <superadmin>
```

Insercion en **orden de FK**, idempotente por version (borra+inserta esa version):
`catalog_versions → entities(+firmware,attrs,aliases) → commands(+params,output,fw) →
oids(+fw) → relations → alarms(+oid_refs,fw) → results`.
Refs sin FK (`command_ref`, `oid_ref`): el Loader valida existencia antes de insertar.

## 4. Readiness — 4 tiers (semaforo)

Por catalogo, combinando completitud (capas presentes + status) y confianza
(avg_overall, % inferred). El `status` recomienda subir el tier mas alto disponible.

| Tier | Nombre | Criterio |
|---|---|---|
| 1 | Incompleto (muy poca conf.) | falta >=1 capa **o** avg_overall < 0.5 |
| 2 | Algo completo (algo de conf.) | todas las capas, pero debiles; 0.5 <= avg < 0.75; muchos `inferred` |
| 3 | Faltantes menores (buena conf.) | avg >= 0.75; 0 entidades `inferred`; solo pendientes menores |
| 4 | Completo (conf. total) | avg >= 0.90; con evidencia empirica (walk); sin huerfanos/conflictos |

(El Tier 4 es casi inalcanzable — la recomendacion es "el mejor tier disponible", no "perfecto".)

## 5. Deteccion de cambios — hash raiz (Merkle) + version

La *version* es identidad humana; el *hash* detecta cambios de contenido (como git tag vs commit).

```
hoja  = sha256(json_canonico de cada artefacto, claves ordenadas, artefactos por id,
               SIN campos volatiles/per-run: generated_at, run-ids, timestamps)
grupo = sha256(concatenar hojas ordenadas)              # por archivo/tabla
raiz  = sha256(concatenar grupos en orden fijo:
               entities|commands|oids|relations|alarms)
```

**INCLUIR `status` en el hash**: que un OID pase de `documented` a `verified_walk` ES un cambio
de contenido que debe disparar recarga. Solo se excluyen campos volatiles por-corrida.

- Se guarda **solo la raiz** en `tkc_catalog_versions.content_hash`.
- Al cargar: `raiz_local == db` → sin cambios (no recarga); `!=` → cambios → recarga;
  inexistente → catalogo nuevo.
- Opcional (fase 2): hoja por fila para delta fino (que OIDs cambiaron).

## 6. Autenticacion doble + tokens (esquema real db_auth)

`db_auth` no tiene tabla `superadmins` ni columna `verified`: **superadmin es un ROL**.
No hay tabla de sesiones (el ISP usa JWT stateless) → la sesion efimera es **infra nueva en
`ispm_tkc`**, NO en `db_auth`. Passwords bcrypt (`$2b$`, varchar 255) → se validan con
`bcrypt.checkpw` en Python (lib `bcrypt`).

- **Factor 1 (app, lee `db_auth` read-only):** el Loader no inserta sin `--authorize` + credenciales.
  Valida el ROL y el estado, luego compara bcrypt:
  ```sql
  SELECT id, password FROM db_auth.users
  WHERE (email = ? OR username = ?)
    AND role_id = 'ed392bf3-272d-11f1-a6e3-42010a400002'   -- rol Super Admin (por ID, no por nombre)
    AND status = 'ACTIVO' AND deleted_at IS NULL;          -- equivalente a "verified"
  -- luego: bcrypt.checkpw(password_ingresado, row.password)
  ```
  Si OK, el Loader inserta una **sesion efimera en `ispm_tkc.active_sessions`**
  (`superadmin_id = users.id` como ref blanda CHAR(36), `token_hash = SHA2(token,256)`,
  `expires_at` corto). NO escribe en `db_auth`.
- **Factor 2 (trigger en `ispm_tkc`, tabla LOCAL):** en la misma conexion el Loader setea:
  ```sql
  SET @actor_id = '<users.id>';  SET @actor_token = '<token>';
  ```
  El trigger (BEFORE INSERT/UPDATE/DELETE en cada `tkc_*`) valida contra la tabla local
  (sin cross-DB en el path caliente):
  ```sql
  IF NOT EXISTS (SELECT 1 FROM active_sessions s
                 WHERE s.superadmin_id = @actor_id
                   AND s.token_hash = SHA2(@actor_token,256)
                   AND s.expires_at > NOW())
  THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No autorizado'; END IF;
  ```

Nota honesta: el trigger es **defensa-en-profundidad/auditoria**, no una frontera dura — quien
tenga los grants de escritura del loader + pueda insertar en `active_sessions` igual escribe. Su
valor es impedir escrituras directas/accidentales que no pasaron por la app. Por eso los grants
del loader estan acotados (seccion 1). **El trigger se escribe ahora pero se APLICA al final**.

## 7. UX (linea de verificacion)

```
$ python -m src.loader status
  zxa10-c300            Tier 3   [CAMBIOS]      local a1b2… != db 9f8e…
  zxa10-c320            Tier 3   [SIN SUBIR]    no existe en db
  zxa10-c320-validated  Tier 2   [SIN CAMBIOS]  hash coincide
  Recomendado: zxa10-c300

$ python -m src.loader load zxa10-c300 --authorize --user <superadmin>
  Password: ********        # oculto, NO en la linea (evita historial/process list)
  → credenciales OK contra auth DB (factor 1) → Tier 3, cambios → procede
  → SET @actor_id/@actor_token; INSERT; trigger re-valida (factor 2)
  → cargada version 1.0.0; content_hash = a1b2…
```

## 8. Plan de implementacion — 3 fases

### Fase 1 — Fundacion y lectura (read-only, sin auth)
- Setup DB: `ispm_tkc` + `ispm_tkc.sql` (sin ALTER olts) + `migration.sql` [HECHO].
- `src/loader/db.py` — conexion PyMySQL + transaccion (context manager). (+`PyMySQL` a requirements)
- `src/loader/hashing.py` — hash raiz Merkle (canonico, excluye volatiles, incluye `status`).
- `src/loader/readiness.py` — 4 tiers desde manifest + status distribution.
- `src/loader/__main__.py` — CLI `status`: compara hash local vs `tkc_catalog_versions.content_hash`,
  imprime tier + [CAMBIOS/SIN SUBIR/SIN CAMBIOS] + recomendacion.
- **Entregable:** `python -m src.loader status` (solo SELECT). **Verif:** unit tests de
  hashing/readiness sin DB; `status` contra un MySQL de prueba.

### Fase 2 — Carga autenticada (factor 1)
- `src/loader/auth.py` — factor 1: `SELECT db_auth.users WHERE role_id='ed392bf3…' AND
  status='ACTIVO' AND deleted_at IS NULL` + `bcrypt.checkpw`; `getpass`/`--password-env`;
  crea fila en `active_sessions` (token + expires). (+`bcrypt` a requirements)
- `src/loader/loader.py` — `load`: lee JSON → INSERT en orden de FK, idempotente por version
  (delete+insert por `catalog_version_id`), mapea campos Fase 2 (enums, scale_formula/attribute/
  empirical/pending_validation, raw_json), escribe `content_hash`. Setea `@actor_id/@actor_token`
  (listo para el trigger; inocuo sin el).
- **Entregable:** `python -m src.loader load <familia> --authorize --user X`. **Verif:** cargar un
  catalogo; re-correr → "sin cambios"; cambiar un OID → recarga.

### Fase 3 — Blindaje en DB (factor 2) — AL FINAL
- `database/triggers.sql` — BEFORE INSERT/UPDATE/DELETE en cada `tkc_*` validando
  `@actor_id/@actor_token` contra `active_sessions` (SIGNAL 45000 si invalido).
- `database/grants.sql` — grants acotados del loader (INSERT `tkc_*`+`active_sessions`,
  SELECT `db_auth.users`).
- Se aplica **al final** para no bloquearte durante el desarrollo.
- **Entregable:** doble-auth activo; escrituras directas bloqueadas. **Verif:** INSERT sin
  session var → rechazado; via loader → permitido.

## Decisiones (RESUELTAS con el esquema real)

1. **db_auth:** superadmin = ROL (`role_id = 'ed392bf3-272d-11f1-a6e3-42010a400002'`), no tabla.
   "verified" = `status='ACTIVO' AND deleted_at IS NULL`. Sin tabla de sesiones (JWT stateless);
   `active_sessions` es NUEVA y vive en `ispm_tkc`. Password bcrypt → `bcrypt.checkpw`.
2. **Password:** `getpass` (prompt oculto) por defecto; `--password-env NOMBRE_VAR` para CI.
3. **Fuente del Loader:** JSON de `catalog/` (opcion A) — confirmado.
4. **Hash:** raiz Merkle, JSON canonico, excluye volatiles per-run, **incluye `status`** — confirmado.

Correcciones aplicadas: (A) `active_sessions` en `ispm_tkc`, no en db_auth; (B) `db_auth.`
(no `auth.`); (C) rol por ID, no por nombre (roles con mojibake de encoding).
