# Traspaso: cargar el catálogo TKC 1.4.0 de ZTE C300 y C320 (clásicas)

Fecha: 2026-11-03. De: la sesión de ISP Management (network-api). Para: la sesión del pipeline TKC que ejecuta el Loader.
Quien verifica después de la carga: la sesión de ISP Management, leyendo `ispm_tkc` en solo lectura.

## 1. Qué hay que hacer

Cargar a `ispm_tkc` el catálogo **1.4.0** de dos familias, que ya está generado, promovido a `catalog/` y validado:

| Familia | Slug | Ruta |
|---|---|---|
| ZXA10 C300 | `zxa10-c300` | `catalog/zte/zxa10-c300/catalog-1.4.0/` |
| ZXA10 C320 | `zxa10-c320` | `catalog/zte/zxa10-c320/catalog-1.4.0/` |

**No cargar ninguna otra familia ni versión.** No modificar `catalog-1.3.0` ni ninguna carpeta existente.

## 2. Qué trae la 1.4.0 (frente a la 1.3.0)

- **OID:** iguales (C300 952, C320 1003). Ningún id quitado ni renombrado. `catalog_diff.py` da "solo adiciones, ningún cambio incompatible".
- **Comandos:** 56 → **81** por familia: **68 `verified`, 12 `documented` (heredados de la semilla), 1 `observed`**.
  - **+25 comandos de escritura**, certificados en vivo el 2026-11-03 en dos OLT reales con firmware V2.1.0 (OLT Unete Popular = C300, OLT PRIMAVERA = C320).
  - **7 comandos pasan de `observed` a `verified`** (`onu_create`, `onu_name`, `onu_description`, `onu_tcont`, `onu_gemport`, `onu_gemport_traffic_limit`, `onu_service_port`), ahora con `rollback`.
  - `observed` que quedan (1 por familia, intencional): `dhcp-ip ethuni` en C300 (la ONU de prueba no lo tenía) y `wifi {enable|disable}` en C320 (la ONU de prueba lo rechazó con `unknown ME`; depende del modelo de ONU).
- **No catalogado a propósito:** `traffic-limit eth_0/N cir` (rechazado por 4 de 4 ONU). Está explicado en el changelog.
- **Evidencia enmascarada** (sin datos de clientes): `docs/fixtures/zte-real/classic-write-20261103/` (10 JSON + README). Cada entrada de comando cita en `evidence` la OLT, el modelo, el firmware y la fecha.
- **Changelog:** `docs/CHANGELOG_catalog.md`, sección 1.4.0.

## 3. Estado actual de `ispm_tkc` (leído hoy, solo lectura)

Las dos familias ya tienen la **1.3.0** cargada: C300 `version_num` 4 y C320 `version_num` 4, ambas **tier 4**, con 56 comandos (37 verificados) cada una.
La 1.4.0 entrará como `version_num` 5. Como el proveedor de la app (`oid-catalog.provider.ts`) elige "mayor tier, luego mayor `version_num`", **la 1.4.0 pasará a ser la vigente automáticamente si el Loader le asigna tier 4**. Si le asigna un tier menor que 4, NO será la vigente; en ese caso no la fuerces, avisa.

## 4. Antes de cargar (ya corrido por mí; vuelve a correrlo si quieres confirmarlo)

Desde la raíz de `telecom-knowledge-extractor`, con `.venv`:

```
.venv/bin/python scripts/catalog_contract_check.py c320 c300      # esperado: 10530 comprobaciones correctas, 0 fallos
.venv/bin/python scripts/loader_dry_run.py c320 c300              # esperado: "OK: todas las filas caben en el esquema"
.venv/bin/python -m pytest -q                                     # esperado: 151 passed
```

Cifras esperadas del ensayo de carga: C320 **6042 filas** y C300 **5351 filas** en 16 tablas, con **81** `tkc_commands` y **162** `tkc_command_firmware` en cada una.

## 5. Carga

El Loader pide la clave de superadmin de forma interactiva (no la escribas en archivos ni en el chat). Primero el estado:

```
.venv/bin/python -m src.loader status
```

Debe mostrar para C300 y C320 la 1.4.0 como pendiente (nueva) y la 1.3.0 como ya cargada. Luego, **una familia a la vez**:

```
.venv/bin/python -m src.loader load zxa10-c300 --version 1.4.0 --authorize --user <superadmin>
.venv/bin/python -m src.loader load zxa10-c320 --version 1.4.0 --authorize --user <superadmin>
```

Si el contrato o el ensayo fallan, el Loader se detiene: no uses `--skip-contract`.

## 6. Qué reportar de vuelta (copiar y pegar)

1. La salida completa de `status` antes de cargar.
2. La salida de cada `load` (`version_num`, `tier` asignado, `content_hash`, filas por tabla).
3. Cualquier advertencia o rechazo de los triggers.
4. Si algo no coincide con las cifras de la sección 4.

## 7. Lo que verifico yo después (lectura de `ispm_tkc`)

- Versiones: C300 y C320 con `1.4.0` en `version_num` 5, el tier asignado y `content_hash` no nulo; la 1.3.0 sin cambios.
- Comandos de la 1.4.0: 81 por familia; estados 68 / 12 / 1; ningún `inferred`.
- Que los 25 ids nuevos existan (p. ej. `onu_delete`, `onu_reboot`, `vlan_create`, `pon_shutdown`, `write`, `profile_tcont_create`, `onu_type_create`) y que los 7 antes `observed` ahora sean `verified` con `rollback`.
- Parámetros y salidas: `tkc_command_params` 48 y `tkc_command_output_fields` 53 por familia.
- Que el catálogo vigente que leería la app sea la 1.4.0 (mayor tier y luego mayor `version_num`).
- Que `network-api` siga resolviendo sin error los OID de ONU (lectura de prueba).

## 8. Cosas que NO hay que tocar ni asumir

- Este repo tiene **trabajo sin commit de antes** (47 archivos de `catalog-1.3.0`, fixtures y scripts del 27-oct). No lo mezcles con la 1.4.0 ni lo reviertas. El commit de la 1.4.0 lo decide el usuario.
- No cargues el JSON `docs/validation/commands/zte_classic_verified_commands.json` directamente: es entrada del generador, no del Loader.
- El `status` de los comandos de la 1.4.0 es evidencia de **ejecución en una OLT por familia y una o dos ONU**, no de compatibilidad con todos los modelos de ONU.

## 9. Si hay que deshacer

El Loader es idempotente por versión (borra e inserta esa versión). Para retirar la 1.4.0 sin borrar, bajarle el tier a mano hace que deje de competir con la 1.3.0 (ver `db_loader_design.md`). Hazlo solo con aprobación del usuario.
