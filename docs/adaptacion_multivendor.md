# Plan de adaptación multi-vendor (2026-10-13)

Objetivo: que el TKC genere catálogos para Huawei (MA5608T R015) y VSOL (V1600G/GS) con
la misma tubería que ZTE, sin que ningún valor de un vendor "se cuele" en otro.

## 1. Qué se hizo (des-hardcodeo de ZTE)

Todo lo específico de un fabricante vive ahora en [config/vendors.yaml](../config/vendors.yaml)
y se lee con [src/profiles.py](../src/profiles.py). El código no contiene OIDs, nombres de
interfaz ni fórmulas de ningún vendor.

| Antes (fijo a ZTE) | Ahora |
|---|---|
| `VENDOR_MAP` / `FAMILY_MAP` en walk_validator.py | `families:` por vendor; un token de modelo puede repetirse entre vendors |
| Semilla global `seed_from_family: ZXA10 C320` para cualquier walk | config (solo vendor del pipeline) > `seed_family` del perfil > la propia familia del walk |
| `single_shelf: true` global | por perfil; si es `null` **no se asume** (False) |
| Prefijos `3902.*` en std_tables / refinements | `software_branches`, `onu_count_source`, `sensitive_prefixes` del perfil |
| `entity.zte.gpon...` literal | derivado de `vendor` + `technology` |
| `285278208 + slot*256 + pon` para todo vendor | `pon_port_index`; sin fórmula en el perfil se emite índice `simple` y no se afirma ninguna |
| Índice bit-packed 32 bits en toda MIB compuesta (Fase 1) | solo si el perfil declara `bit_index` |
| ifType 250/6, keywords `pon/gei/xge…` | `iftype` y `ifname` del perfil |
| Refinamientos C6xx llamados siempre | hook `refinements:` del perfil (solo ZTE) |
| Poda de todo OID read-only no visto en el walk | `prune_mode: covered_branch`: solo dentro de ramas que el walk recorrió |

**Regla de oro:** un campo `null` significa "no se conoce" y la validación se OMITE. Nunca
se hereda un valor de otro vendor.

**Garantía de no regresión:** los 4 catálogos ZTE (C300, C320, C600, C620; 420 archivos)
se regeneraron antes y después y son idénticos byte a byte. La extracción de Fase 1 de
la C320 también (1992 OIDs, 23 con bit_calculation, componentes idénticos). Suite: 136 tests
(17 nuevos en `tests/test_profiles.py`).

Quedó a propósito sin tocar:

- Textos `"catálogo C300"` en `triggers.py`/`enricher.py` (cosmético, pero cambiarlos altera
  `results.json` y por tanto el `content_hash` que usa el loader). Se hace junto con la
  próxima regeneración completa de catálogos.
- `refinements.py`: sigue siendo un módulo ZTE C6xx, ahora aislado detrás del hook.
- `config/pipeline.yaml`: tiene cambios sin commitear tuyos; no lo toqué.
  Los perfiles se cargan desde `config/vendors.yaml` (o `paths.vendors` si lo agregas).

## 2. Modelo de evidencia (aplica a cualquier vendor)

| Nivel | Fuente | Estado máximo en catálogo |
|---|---|---|
| A | MIB oficial del fabricante | `documented` |
| B | Vista de terceros (Observium/LibreNMS: `scripts/observium_mib_extract.py`) | `documented`, marcada `third_party_rendering` |
| C | Walk real del equipo | `verified` / `verified_walk` |
| D | Comportamiento en hardware (CLI) | comandos verificados |

Nada de nivel A/B pasa a `verified` sin nivel C. Esto es lo que evita repetir el caso del
OID `uncfg` inventado.

## 3. Flujo para incorporar un vendor/modelo

1. **Identificar el equipo.** `sysDescr` (`1.3.6.1.2.1.1.1.0`), `sysObjectID` (`.1.2.0`) y
   `entPhysicalDescr`. El `sysObjectID` fija el enterprise y confirma el modelo.
2. **Perfil en DRAFT.** Agregar o completar el bloque en `config/vendors.yaml`: `enterprise_oid`,
   `families`. Todo lo demás en `null` o marcado `# DRAFT`.
3. **Walks** con la convención `<Vendor>_<Modelo>[_entities|_ifnames].txt` en `docs/walks/`:
   enterprise completo o por subárbol, `entPhysicalTable`, `ifTable`+`ifXTable`.
   `snmpbulkwalk -v2c -On -Cr20` (más de 20 repeticiones fragmenta datagramas y pierde filas).
   Solo lectura. Si el walk es por subárbol, usar `prune_mode: covered_branch`.
4. **Fase 1 (catálogo teórico).** Fuente nivel A si existe; si no, nivel B (ver §5).
   Configuración propia por vendor (`config/pipeline_<vendor>.yaml` con `pipeline.vendor`/`family`).
5. **Fase 2.** `python main.py --config config/pipeline_<vendor>.yaml` valida el walk contra
   la semilla; los hallazgos bloqueantes siguen pasando por `docs/walks/resolutions.json`.
6. **Cerrar el perfil.** Cada campo DRAFT se rellena con lo que el walk demuestre
   (formato de ifName, fórmula de ifIndex, tabla de ONUs, rama de software) y se quita la marca.
7. **Carga a BD.** El loader crea `tkc_vendors`/`tkc_families` si no existen (`_ensure`):
   no hay seeds que editar.

## 4. Preguntas que el primer walk debe contestar (por vendor)

Cada una cierra un campo del perfil:

| Campo del perfil | Qué buscar en el walk |
|---|---|
| `enterprise_oid` | `sysObjectID` |
| `ifname.regex` / keywords | forma real de `ifName` de puertos PON y uplink (¿`rack/slot/port`? ¿qué separadores?) |
| `iftype` | `ifType` de los puertos PON (¿250 gpon u otro?) y de uplink |
| `pon_port_index` | relación `ifIndex` ↔ (slot, puerto): decodificar con `derive_bit_layout`; si no es bit-packed, dejar `null` |
| `bit_index` | si la MIB usa índices compuestos de un solo entero; Huawei XPON indexa por `ifIndex` + `ontId` (enteros separados) |
| `onu_count_source` | tabla de ONUs con filas: prefijo de columna + posición de `port` y `onu` |
| `single_shelf` | cantidad de chasis/frames en `entPhysicalTable` |
| `software_branches` | si hay tabla de versiones; es opcional |
| `sensitive_prefixes` | ramas cuyo ÍNDICE sea texto (comunidades, cuentas, URLs): ver tabla de usuarios/SNMP |
| `prune_mode` | `all` solo si el walk cubre el enterprise completo |

## 5. Fase 1 sin MIB oficial (Huawei MA5608T)

Ya existen [HUAWEI-GPON-MIB.json](huawei/ma5608t/observium/HUAWEI-GPON-MIB.json)
(raíz `2011.5.100`, 1022 objetos) y [HUAWEI-XPON-MIB.json](huawei/ma5608t/observium/HUAWEI-XPON-MIB.json)
(raíz `2011.6.128`, 1549 objetos). El `MibExtractor` consume texto SMI, no estos JSON.

Opciones, de menor a mayor esfuerzo:

1. **Generar un `.mib` sintético** desde el JSON (un `OBJECT-TYPE` por columna) y dejar que la
   Fase 1 existente lo procese sin cambios. Cuidado: Observium solo expone `r/w`; el resto
   (`read-only`, `read-create`, `not-accessible`) es indistinguible. El generador debe emitir
   `MAX-ACCESS` **desconocido → conservador**: un OID de acceso desconocido no se poda por falta
   de respuesta (hoy `_KEEP_IF_UNCONFIRMED` solo protege los accesos conocidos).
2. Adaptador JSON → `Oid` directo en el `Extractor` (nuevo `doc_type: mib_json`). Más limpio,
   pero toca el clasificador y el modelo.
3. Conseguir el MIB oficial (paquete de MIBs de la versión de software) y no usar nada de esto.

Recomendación: opción 1 para destrabar el trabajo, con `access` desconocido protegido, y
reemplazarla en cuanto aparezca la fuente oficial.

Antes de generar nada, el walk decide cuál de los dos MIBs existe en la MA5608T R015: no
cargar ambos como si fueran verdad.

## 6. Plan inmediato — VSOL (equipo disponible)

Es el primer vendor sin ninguna fuente documental en el repo, así que el walk es la fuente.

1. `sysDescr`, `sysObjectID`, `sysName` (GET). Con eso se cierra `enterprise_oid`
   (hipótesis sin confirmar: `1.3.6.1.4.1.37950`) y el modelo exacto
   (`V1600G` vs `V1600GS`; si es otro, agregarlo a `families`).
2. Walks estándar: `1.3.6.1.2.1.2` (ifTable), `1.3.6.1.2.1.31.1.1.1` (ifXTable),
   `1.3.6.1.2.1.47.1.1.1.1` (entPhysicalTable; puede no existir en VSOL → anotarlo).
3. Walk del enterprise completo, **por subárbol**, con `-Cr20`. Primero un GETNEXT del
   enterprise para listar ramas hijas (el colector tiene `discovery.py` para esto).
4. Guardar como `VSOL_V1600G.txt`, `VSOL_V1600G_ifnames.txt`, `VSOL_V1600G_entities.txt`.
   Revisar PII (seriales, nombres de ONU, comunidades) antes de versionar: agregar el
   prefijo a `walk_collector.redaction.prefixes` y/o `.gitignore`, como en C620/C600.
5. Sin MIB: la Fase 1 queda vacía. Opciones: buscar el MIB de VSOL (soporte técnico o el
   propio firmware), o hacer el catálogo **walk-first** (ver §7, ítem 1).
6. Completar el perfil con lo que demuestre el walk (§4) y correr las pruebas.

## 7. Backlog ordenado

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 1 | **Modo walk-first** (hecho 2026-10-26) | ✅ `WalkValidator.run()` detecta semilla vacía (`not oid_groups and not entities`) y activa `walk_first`: `Enricher.materialize_observed_groups()` construye un grupo de OIDs `UNRESOLVED`/`status=observed` por tabla (misma heurística de `extract_table_prefix` que ya usaban los findings `observed_only`); `enrich_hardware_entities`/`enrich_port_entities`/`enrich_pon_operational` sintetizan la entidad que falte (`std_tables._ensure_entity`) en vez de descartar la confirmación. Probado con `config/pipeline_vsol.yaml` contra `VSOL_V1600G2B_*.txt`: 265 PON ports y 8 uplinks confirmados por `ifName` real (`status=verified`), 3 OIDs operativos `verified_walk`, 8 escalares `UNRESOLVED/observed` desde `_system.txt` — primer catálogo VSOL real, sin MIB. Nunca se activa si hay semilla (ZTE/Huawei sin cambios, 149 tests). De paso: `WALK_TYPE_MAP` ahora reconoce `_ifxfull`→`if_table` y `_system`→`enterprise` (antes esos walks ya capturados se descartaban silenciosamente con "no se pudo identificar"). |
| 2 | Generador `.mib` sintético desde JSON de Observium con acceso desconocido protegido | Fase 1 Huawei produce catálogo; ningún OID con acceso desconocido es podado |
| 3 | `access: unknown` explícito en el modelo y en el enricher | test: no se poda aunque la rama esté caminada |
| 4 | **Validación de `ifName`** (hecho 2026-10-26) | ✅ `enrich_port_entities` ya no descarta en silencio un `ifName` pon_port/uplink_port que no matchea `ifname.regex` (o el fallback de 3 números): `trigger_ifname_unparsed` (triggers.py) cuenta `unparsed/total` por tipo de puerto y guarda hasta 5 muestras. Confirmado contra VSOL real: `uplink_port` 8/8 (`GE0/1`… solo 2 números, el fallback genérico no les alcanza) y `pon_port` 28/265 (nombres de sitio sin 3er número) — severidad `high`/`medium` según si falla TODO el tipo o una porción. Huawei/ZTE: 0 hallazgos (ifName siempre con 3 números). No bloqueante. |
| 5 | **Trazabilidad del perfil** (hecho 2026-10-26) | ✅ `ProfileRegistry` guarda `source_path`/`source_sha256` de `config/vendors.yaml` (sha256 del archivo completo, calculado en `load_registry`). El `manifest.json` de Fase 2 trae `vendor_profile: {vendor, source, sha256}` — ruta relativa al cwd, portable entre dispositivos. Solo Fase 2 (donde el perfil realmente decide casi todo); Fase 1/`CatalogWriter` queda sin tocar — su manifest no referencia el perfil hoy, no era necesario para el criterio de aceptación. |
| 6 | **Texto "catálogo C300" unificado** (hecho 2026-10-26) | ✅ `trigger_documented_only` (triggers.py) recibe `family` opcional; `Enricher` lo guarda (`self.family`, seteado desde `family` del walk en curso) y lo pasa. `catalog_action` ahora dice "podado del catálogo \<FAMILIA REAL\>" (o "catálogo" genérico si no hay family) en vez de siempre "catálogo C300" sin importar qué vendor/familia se estuviera procesando. Diff acotado a `catalog_action`, como pedía el criterio de aceptación — nada más del finding cambió, así que no debería afectar al loader (que lee `pruned`/`oid_id`, no el texto). |
| 7 | **`walk_collector --vendor`** (hecho 2026-10-26) | ✅ `--vendor {ZTE,Huawei,VSOL}` (mutuamente excluyente con `--config`) resuelve a la config de ese vendor vía `VENDOR_CONFIG_FILES` (`src/walk_collector/config.py`) — `resolve_config_path()`, vendor desconocido → `ConfigError` claro. **No** se fusionó `expand`/`roots`/`redaction`/pacing dentro de `vendors.yaml`: esos valores están afinados por evidencia real distinta por equipo (ej. VSOL con `inter_request_delay_ms: 300` porque disparó el kill-switch de latencia a 150ms) y fusionarlos habría sido una refactorización de mayor riesgo sin ganancia real — se optó por el atajo de nombre, que es lo que pedía el criterio de aceptación. `config/collector_huawei.yaml`/`collector_vsol.yaml` se conservan como la fuente de verdad de cada vendor. 2 tests nuevos. |
| 8 | **Entidades hardware** (hecho 2026-10-26) | ✅ Respuesta a la pregunta: **sí**, `entPhysicalClass` es el enum estándar RFC 2737 y ya funcionaba igual para todos — no hacía falta tabla por vendor. Huawei real: class 3 chassis (1 fila) → `shelf`, class 9 module (7 filas: backplane GPON, control unit GE uplink, fuente AC, CPU) → `card`/`fan`/`power_supply` vía `_refine_module`. El bloqueo real era otro: `ENT_CLASS_TO_SHORT` clasificaba bien, pero la semilla de Huawei (Fase 1, solo XPON-MIB) nunca creó esas entidades — el hardware de chasis vive en HUAWEI-DEVICE-MIB, nunca ingerido. Nuevo flag de perfil `ent_synthesize_from_walk` (`config/vendors.yaml`, default `false`): si `true`, `enrich_hardware_entities` sintetiza la entidad que falte — SOLO respaldada por una clase SNMP real confirmada (no heurística de texto a ciegas), igual de seguro que `walk_first`. Activado para Huawei: 4 entidades nuevas `verified` (`card` 5 instancias con part numbers reales, `fan`, `power_supply`, `shelf`). VSOL: `entPhysicalTable` tiene **0 filas reales** (`rows:0` en el walk) — no es un problema de clasificación, el agente SNMP no la implementa; sigue en 0, correctamente, no hay nada que sintetizar. ZTE sin cambios (flag no seteado, ya tenía todo en la semilla). |
| 9 | `pytest.ini` con `testpaths = tests` (hecho) | `pytest` en la raíz no importa `scripts/*_test.py` |

## 8. Riesgos abiertos

- **Un MIB, dos raíces (Huawei).** `2011.5.100` y `2011.6.128` describen objetos parecidos;
  solo el walk dice cuál implementa la MA5608T R015. `covered_branch` evita podar lo que no se caminó.
- **Datos de terceros como fuente.** Observium puede estar desactualizado respecto a R015.
- **Índices no bit-packed.** El gate `bitcalc_validation` es de ZTE; para Huawei/VSOL no aplica
  y hoy simplemente no se ejecuta (sin `bit_index`). Falta un validador equivalente para
  índices `ifIndex.ontId` (comparar con `ifName`).
- **Scripts que ejecutan al importarse.** Los `scripts/*_test.py` abren telnet contra la OLT
  de `.env` y escriben logs; por eso `pytest.ini` ahora limita a `tests/`. Conviene renombrarlos
  (`*_probe.py`) y añadir `if __name__ == "__main__":`.
