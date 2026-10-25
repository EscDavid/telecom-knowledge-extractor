# Análisis de los catálogos TKC contra el diagnóstico del consumidor (2026-10-09)

Referencia: `reports/diagnostico-catalogo-tkc-zte-2026-10-09.md` (network-api). Cada hallazgo se contrastó con los catálogos locales
(`catalog/zte/zxa10-c300/catalog-1.1.0`, `zxa10-c320/catalog-1.1.0-validated`, `zxa10-c600|c620/catalog-1.2.0`), los walks de `docs/walks/` y,
cuando hizo falta, una lectura CLI de solo lectura en la C620 (2026-10-09). Solo análisis: no se modificó ningún catálogo.

## 1. Veredicto por hallazgo del diagnóstico

| ID | Veredicto | Evidencia propia | Acción propuesta |
|---|---|---|---|
| D-01 | **Confirmado** | C300 y C320: 10 OID `verified_community` (rama `1082.500`), **0 filas** en el walk de su familia. Los `verified` tienen filas 110/110 y 217/217; `documented`: 0 con filas. | Degradar a `observed` (o acotar a C6) cuando la familia no tenga walk; regla en `community.py`. Requiere versión nueva de C300/C320. |
| D-02 | **Confirmado y resuelto con evidencia CLI** | Walks: C620 rx 3 valores en 32768–65534 (63547, 65308), C600 3 (65052, 65308×2); tx ninguno. CLI en vivo (C620): ONU 1/1/1:28 raw **63547 → −33,978 dBm** y 1/1/2:31 raw 63547 → −33,978 dBm = `(63547−65536)·0,002−30`. **Es entero de 16 bits con signo.** `65535` = sin señal (ONU en LOS/OffLine/DyingGasp). | Añadir a rx/tx de ONU: `signed_bits: 16`, `sentinels: [65535]`, `valid_range_dbm: [-45, 10]`; ampliar el contrato de consumo con una fixture de raw ≥ 32768. |
| D-03 | **Confirmado** | Mismo `attribute: onu_status` con 3 enums: `1012…8` {1 Online, 2 Offline, 65535}, `1082…8.1.4` clásicas {1 Logging … 4 Online … 7 Offline} y `1082…8.1.4` C6 {2 LOS, 4 Working, 5 DyingGasp, 7 OffLine}. El enum de clásicas es un superconjunto compatible con lo observado en C6, así que 1/3/6 se pueden declarar «no observados en C6». | Enum por (atributo, rama) con `branch` explícito; en C6 añadir 1/3/6 con `observed: false`. |
| D-04 | **Confirmado** | `uncfg_*`: C300/C320 7 atributos (`500.10.2.2.5`), C620 6 (`500.2.2.11`), C600 **ninguno**. | Probar `500.2.2.11.2.1` en la C600 con una ONU en espera; declarar la ruta por familia en el manifiesto. |
| D-05 | **Confirmado** | `onu_type`/`onu_ip_address` existen en C300/C320 y no en C6; C6 trae `onu_type_name` y `onu_model`. | Alias real: fila adicional `onu_type` con el mismo OID que `onu_type_name`, añadida en `refinements.py` (el intento anterior por la ingesta comunitaria renombraba un id y se descartó). `onu_ip_address` no tiene fuente SNMP en C6: documentarlo como `not_exposed`. |
| D-06 | **Parcialmente incorrecto** | El valor `1` **sí está** catalogado (`1: None`, «sin bajas registradas») en C600 y C620. Cruce estado×causa: C620 working con causa 1 = 138, OffLine con causa 1 = 22; C600 OffLine con causa 1 = 6. Es coherente: nunca cayó. Sí es correcto que es la **última** causa: 374 working con causa 2/3/9. | Mantener el 1; **corregir mi error**: las 4 alarmas `alarm.zte.gpon.onu.offline_cause_*` no marcan que son históricas → añadir `kind: historical`. Documentar que LOS(2) + causa 10 (DeactiveSucc) = ONU deshabilitada por administración (10/10 en C620). |
| D-07 | **Confirmado (parcial)** | Log CLI de la C620: `XPON alarm general event` ×53 (todos `alarm 723961 restore`), `GPON alarm link olt dgi` ×6, `losi` ×2. Hoy solo catalogamos el comando `show logging alarm`, no sus eventos. | Catálogo de eventos del log CLI (tipos y códigos 72395x/72396x, par alarm/restore) con la muestra de C620 y C600. |
| D-08 | **Confirmado y es culpa mía** | 223981, 224040, 230285 y 230240 están en `docs/validation/commands/zte_c6xx_cli_behavior.json`, que **ningún proceso carga** (el loader solo toma `catalog/`). En los 78 comandos de C620 solo aparece 224040 una vez. El CHANGELOG decía «añadido» sin que llegara a `commands/`. | Campo `errors[] {code, meaning, severity}` por comando (viaja en `raw_json` sin tocar la base) + `severity: info` para 224040/230285. Corregir el CHANGELOG. |
| D-09 | **Confirmado** | C600: 24 `documented` + 12 `observed` + 1 `verified` entre los comandos de escritura (ninguno probado: no hay ONU en espera). **Además, nuestra receta está desactualizada:** `provisioning_recipes.json` dice «CBS=PBS=128 KB»; las 9 filas de `traffic_profiles.txt` (C620) y las 5 de C600 dan **CBS = PBS = CIR/80** (p. ej. 104960 → 1312; 524032 → 6550). El consumidor tiene razón. | Corregir la receta; `verified_on: [familias]` por comando y sección `rules` (perfiles en el service-port, `traffic-limit` no admite perfiles SMARTOLT, CBS=rate/80). |
| D-10 | **Resuelto en C6, abierto en clásicas** | C600/C620 llevan `sensitivity: pii`; C300/C320 no. | Marcar `onu_name`/`onu_description` de C300/C320 como `pii`. |
| D-11 | **Confirmado en esencia** | `fan` 26 OID todos `documented` (21 `table_empty`, 5 `structure_node`), `sensor` 24 `documented`, `power_supply` 6 `not_exposed`; idéntico en C600 y C620. La anotación existe por OID, pero no hay un resumen por capacidad. | `exposed` por entidad en el manifiesto (fans/temperatura/CPU/memoria = no publicado en C600) y listar los 6 sensores que sí publica la C600. |
| D-12 | **Confirmado y lo introduje yo** | 16 atributos repetidos entre `onu`/`pon_port` y `uplink_port` (los 16 OID IF-MIB que añadí a `uplink_port` reutilizan los nombres: `oper_status`, `hc_in_octets`…). `oper_status`: C620 ambas `verified_walk`; C600 `inferred` en uplink. | Prefijar los de uplink (`uplink_oper_status`, `uplink_hc_in_octets`…) y regla en la puerta de contrato: un `attribute` no se repite dentro de una familia salvo que difiera la rama. |
| D-13 | **Confirmado** | `oids_kept` = 1772 (C600) / 1778 (C620) frente a 1788 / 1794 archivos; `catalog_map` del manifiesto sigue siendo el layout semilla (31-28/27-24). | Recalcular contadores al final de `refine_catalog` y guardar `layout_final` por familia. |
| D-14 | **Confirmado** | C320 tiene `1.0.0`, `1.0.0-mib-refinement`, `1.0.0-validated`, `1.1.0`, `1.1.0-validated`; C300 `1.0.0`/`1.1.0`. | Una sola línea por familia y `content_hash` en el manifiesto; archivar el resto fuera de `catalog/`. |
| D-15 | **Confirmado** | C6: `STRING "pon,SERIAL"`; clásicas: Hex-STRING de 8 bytes. | `serial_format` por familia en la entidad ONU. |
| D-16 | **No reproducido** | Con los walks principales: `documented` con filas = 0 en C300 y C320 (el diagnóstico dice 41 en C300). Puede salir de `diagnostics/*_uncfg.txt`. | Repetir incluyendo los walks de diagnóstico antes de promover nada. |
| D-17 | **De acuerdo** | Las ramas PM (todos 0) y `3.6000.51.*` quedan fuera; contraseñas redactadas en los walks. | Añadir `sensitive: true` a cualquier OID futuro de `3.6000.51`. |

## 2. Hallazgos propios (no figuran en el diagnóstico)

| # | Hallazgo | Detalle |
|---|---|---|
| P-1 | **C300/C320 no recibieron los refinamientos de C6** | 26 nombres `UNRESOLVED`, 16 unidades con multiplicador embebido (14–15 sin `scale`) y firmware `2.0/2.1` frente a `1.2.2` en C6; 0 `pending_validation`. `refine_catalog` solo actúa sobre C600/C620. Las clásicas son las que producen más lecturas en producción. |
| P-2 | **El comportamiento del CLI no está en el catálogo cargable** | `cli_behavior.json` (errores, confirmaciones, límites, prompts) y `provisioning_recipes.json` solo existen en `docs/validation/`. El consumidor nunca los ve (D-08, D-09). |
| P-3 | **Hojas IF-MIB con ids `onu.*`** | `hc_in_*`, `high_speed`, `sys_*` tienen id `oid.zte.gpon.onu.*` pero `entity_ref` pon_port/olt. Un id no se puede renombrar sin romper consumidores: proponer atributos con el nombre correcto y mantener el id. |
| P-4 | **Contrato de consumo asimétrico** | 16 atributos en C620 y 6 en C600 aunque las fixtures de C600 cubren también `onu_type_name`, modelo, causa de baja y perfiles. Tampoco prueba raw ≥ 32768 ni unicidad de atributos. |
| P-5 | **C600 comparte los mismos 1788 OID que la C620** | Misma estructura, pero la C600 tiene 32 PON (6 arriba, 26 abajo) y su tabla de entidades estándar viene vacía: tarjetas y puertos solo por CLI (`show card`), sin poblar. |
| P-6 | **21 comandos de C600 sin parámetros y 1771 OID sin `command_ref`** | Los 17 enlaces OID↔comando de la 1.2.0 son solo de lectura de ONU; faltan perfiles, VLAN y tarjetas. |
| P-7 | **Semántica de LOS no documentada** | En C620, las 10 ONU en LOS con causa 10 son las deshabilitadas por administración (verdad de terreno: `admin disable` → LOS). El consumidor las leería como corte de fibra. |

## 3. Orden propuesto (todo de mi lado, salvo lo marcado)

1. **Versión 1.3.0 de C600/C620** (cambios incompatibles de nombres, así que versión nueva):
   D-02 metadatos de potencia, D-03 enums por rama, D-05 alias `onu_type`, D-06 `kind: historical`, D-08 `errors[]`, D-12 prefijos de uplink, D-13 contadores, D-15 `serial_format`, P-4 contrato ampliado y regla de unicidad, corrección de la receta CBS (D-09).
2. **Versión 1.2.0 de C300/C320** (primera reparación de las clásicas): D-01, D-10, P-1, D-03. Se regenera en una copia y se compara con `catalog_diff.py` antes de publicar.
3. **Después:** eventos del log CLI (D-07), `exposed` por entidad (D-11), tarjetas de la C600 desde `show card` (P-5), versionado único (D-14).
4. **Necesitan algo tuyo o del consumidor:** D-04 en C600 (una ONU en espera), D-09 `verified_on` real en C600 (OLT de pruebas), D-16 (revisar con sus walks de diagnóstico).

Recordatorio: toda publicación nueva exige recargar en `ispm_tkc` con tu contraseña por prompt oculto; la puerta de contrato bloquea si algo falla.
