# Cambios del catálogo TKC (ZTE ZXA10 C620 / C600 / C320 / C300)

## Política de versiones
- **Parche (1.2.x):** correcciones de datos que no cambian ids, unidades, escalas, firmware ni formato (p. ej. una descripción).
- **Menor (1.x.0):** se añaden ids (OID, comandos, entidades, alarmas, relaciones) o se corrigen valores existentes; un consumidor puede necesitar leer de nuevo escala, unidad o firmware. Se publica **siempre** con versión nueva y no se modifica una versión ya cargada en `ispm_tkc`.
- **Mayor (x.0.0):** se quitan o renombran ids, o cambia el significado de un atributo.
- Antes de cargar: `python scripts/catalog_contract_check.py` (lo ejecuta el loader; `--skip-contract` lo omite) y `python scripts/catalog_diff.py <anterior> <nuevo>` para ver el detalle.

## 1.3.0 — 2026-10-26 (C320 y C300, clásicas)
Sustituye a la 1.2.0 de clásicas. Mismos OID (C320 1003, C300 952), ningún id quitado ni renombrado; +37 comandos. Procede de la sonda de solo lectura
del 2026-10-26 en una **ZXA10 C300 V2.1.0** (103 ONU; `show system-group`: `C300 Version V2.1.0`; la OLT que se creía C320 era un C300). Informe: secciones BJ y BK.

### Cambios que un consumidor debe revisar
- **Versión por CLI: `show version-running`.** `show version` es ambiguo (`%Error 20204`) y `show software 1` no existe en clásicas. La 1.2.0 daba `show version` como `observed` (error mío, tomado del informe del importador sin ejecutarlo):
  el id `command.zte.gpon.global.show.version` se conserva y ahora describe `show version-running`. La versión también sale de `show system-group` (sysDescr y uptime por CLI).
- **Sintaxis de clásicas:** `gpon-olt_<rack>/<slot>/<puerto>` y `gpon-onu_<rack>/<slot>/<puerto>:<n>`. La de C6 (`gpon_olt-…`, `gpon_onu-…`) da `Invalid input`.
  `show running-config interface <iface>` lleva espacio (`show running-config-interface` no existe).
- **Comandos de lectura:** 37 `verified` en C300 (ejecutados) y `observed` en C320 (misma plataforma y firmware, no ejecutados): `clock`, `version-running`, `system-group`, `card`, `card-temperature`, `card-power`, `gpon onu state|baseinfo|uncfg|detail-info|distance|by sn`,
  `pon onu information`, `pon power attenuation|onu-rx|onu-tx|olt-rx|olt-tx`, `interface gpon-olt`, `service-port interface`, `mac gpon onu`, `running-config interface` (puerto y ONU), `onu running config`, `gpon remote-onu equip|capability|interface eth|sys-attr`,
  `onu-type`, `vlan summary`, `gpon profile tcont|traffic`, `gpon onu profile vlan|traffic`, `logging alarm`, `alarm pool|counter`. Con `errors[]` (20200, 20202, 20203, 20204, 62310, 64040; los dos últimos son lecturas vacías, `severity: info`).
  No existen en esta versión: `show logfile brief`, `show alarm current|history`, `show mac interface`, `show qos traffic-profile`, `show pon olt-tx`, `show gpon onu tcont|gemport|vport`, `show version-saved`/`show pon version` (incompletos). Detalle en `docs/validation/commands/zte_classic_cli_behavior.json`.
- **PII por CLI:** en clásicas la cuenta de lectura ve `Name` y `Description` de la ONU **en claro** (detail-info y running-config). En C6 salen enmascarados. No registrar esas salidas.
- **Plantilla de aprovisionamiento observada** (7 comandos `observed`, no ejecutados por TKC): `onu <n> type <tipo> sn <serial>` en el puerto; en la ONU `name`, `description`, `tcont <n> profile <subida>`, `gemport <n> tcont <m>`,
  `gemport <n> traffic-limit downstream <bajada>` y `service-port <n> vport <v> user-vlan <v> vlan <v>`. Diferencia con C6: el perfil de bajada va en el `gemport`, no en el service-port.
- **`show pon power attenuation`:** `up Rx` es la potencia recibida por la OLT (la de `onu_rx_power_type`, rama `1012.3.50.12.1.1.10`; correspondencia `inferred` hasta leer ese OID de la misma ONU) y puede ser menor de -30 dBm (caso con signo).

### Quitado (sin ids de OID/comando afectados)
- 4 entidades cascarón (`protocol.dba`, `protocol.igmp`, `profile.line_profile`, `profile.service_profile`): `inferred`, confianza 0,07, sin atributos, OID ni relaciones. Aparecieron al regenerar la semilla y bajaban el tier de 4 a 2.
  Regla en `refinements.py`; el contrato ahora falla si vuelven.

### Puerta de contrato y fixtures
- Fixtures de CLI anonimizadas: `docs/fixtures/zte-real/c300-cli-20261026` (29 salidas, `ground_truth.json`), generadas con `scripts/build_classic_cli_fixtures.py` (comprueba que no queda ningún serial, MAC ni nombre).
- Reglas nuevas para clásicas: comando de versión, ≥ 35 comandos `verified`/`observed`, sin entidades cascarón, sin sintaxis de C6, fixtures de CLI presentes.

## 1.2.0 — 2026-10-23 (C320 y C300, clásicas)
Primera reparación de las clásicas; sustituye a `1.1.0-validated` (C320) y `1.1.0` (C300). Mismo número de OID (C320 1003, C300 952): ningún id quitado ni renombrado.
Se genera con `scripts/build_classic_catalog.py` (en una copia, comparada con `catalog_diff.py`) y pasa la puerta de contrato (fixtures `docs/fixtures/zte-real/c320-20261001`, `c300-20261001`).

### Cambios que un consumidor debe revisar
- **10 OID `verified_community` pasan a `documented`** (`community_status_was` conserva el estado anterior): `onu_name`, `onu_description`, `onu_serial_number`, `onu_status`, `onu_rx_power`,
  `onu_last_online_time`, `onu_last_offline_time`, `onu_last_offline_reason`, `onu_gpon_optical_distance` (rama `1082.500`) y `onu_ip_address` (`1012.3.50.16`). No tienen NINGUNA fila en el walk de la familia
  (C320 1572 ONU, C300 1008), así que nunca devolvían dato. Tres tienen gemelo con filas: `superseded_by` apunta a `onu_serial_number_type`, `onu_status_type` y `onu_rx_power_type` (rama `1012.3.50`).
  Quien indexe por `attribute` debe quedarse con el OID `verified*`. Nombre y descripción de ONU no tienen fuente SNMP en clásicas (traerlos de la BD/SmartOLT); manifiesto `not_exposed_attributes`.
- **Potencia de ONU (`onu_rx_power_type`, `onu_tx_power_type`):** `signed_bits: 16`, `sentinels: [65535]`, `valid_range_dbm: [-45, 10]`, `unit: dBm`. C320: 4 ONU con raw ≥ 32768 y ≠ 65535 (p. ej. 65052 → −34,0 dBm); C300: 7.
  `suspect_values: {"0": …}`: raw 0 (−30,0 dBm) en ONU con status Online (C320 5 de 1573, C300 8 de 1008) no es una medición.
- **Unidades y escalas:** 16 unidades con multiplicador embebido (`0.001Volts`, `0.001W`, `0.00001 degree`…) pasan a `V`/`W`/`degree` con `scale` 0,001/0,00001 (15 en C320, 14 en C300).
- **26 nombres `UNRESOLVED` → el atributo** (p. ej. `onu_name`, `if_type`, `oper_status`). `scale_formula` y los ids no cambian.
- **`onu_name`/`onu_description`: `sensitivity: pii`.** `serial_format: binary-8` (8 bytes: 4 de fabricante + 4; la forma `STRING` del walk son bytes imprimibles, no otro formato).
- **`onu_status_type`:** `enumeration_meta` (rama `1012.3.50.11.2.1.8`, valores {1 Online, 2 Offline, 65535}, coincide con el equipo).
- **Comandos:** los 18 de la semilla (manual del C320, confianza 0,4, nunca ejecutados) estaban como `verified`; pasan a `documented` con aviso. `show gpon onu uncfg` y `show gpon onu state gpon-olt_{pon}` pasan a `observed`
  y se añade `show version` (`observed`): los ejecutó el importador en 5 OLT clásicas (`reports/hallazgos-cli-snmp-zte-2026-10-09.md`), TKC no. La CLI real de clásicas usa `gpon-onu_1/1/1:1` y `no onu N`: no escribir con los comandos `documented`.
- 770 (C320) / 826 (C300) OID `documented` llevan `pending_validation` (por qué no aparecen en el walk). Atributos de entidad: `onu` y `pon_port`. Manifiesto: `observed_software` (C320: V2.1.0, de sysDescr), `status_distribution` y `oids_kept` recalculados.

### Sin cambios (a propósito)
- Firmware de grupo `["2.0","2.1"]` (la OLT C320 informa V2.1.0; el C300 no tiene sysDescr guardado). Alarmas, relaciones y entidades de perfiles de C6 no se trasladan: salen de la CLI de C6.
- Walk C320 de octubre: mismos 1003 OID que la 1.1.0-validated (el diff solo trae cambios de calidad).

### Seguridad
- **Nueva rama sensible `1082.20.5.2.1`** (`sensitive_prefixes`): en C320 (4 filas) y C300 (2) el índice son cadenas de 12 caracteres con acceso 1/2 y estado 0; **probables comunidades SNMP** (no se pudo confirmar con la MIB).
  Los hallazgos `ascii_index` de esa tabla se omiten de `results.json` y las cadenas se quitan de `observed_firmware_strings`. Walks y diagnósticos se redactaron con `scripts/redact_sensitive_local.py`.
  Las cadenas del C300 estaban en el historial de git (walk y `context.md` del primer commit, repositorio público): **rotar esas comunidades**. Las versiones anteriores cargadas en `ispm_tkc` las conservan en `tkc_results`: `scripts/purge_sensitive_results.py`.

## 1.3.0 — 2026-10-09 (C620 y C600)
Sustituye a la 1.2.0. Ningún id quitado ni renombrado (diff: +1 OID, 0 −). Procede del análisis contra el diagnóstico del consumidor
(`reports/analisis_catalogos_vs_diagnostico_2026-10-09.md`).

### Cambios que un consumidor debe revisar
- **`uplink_port`: los 16 atributos pasan a llevar prefijo `uplink_`** (`uplink_oper_status`, `uplink_hc_in_octets`…). Antes repetían los nombres de `pon_port`/`onu`
  (`oper_status`…), y un consumidor que indexe por `attribute` se quedaba con una u otra. `oper_status` ahora es solo el de `pon_port`.
- **Potencia óptica de ONU (`onu_rx_power`, `onu_tx_power`):** nuevos `signed_bits: 16`, `sentinels: [65535]`, `valid_range_dbm: [-45, 10]`.
  Un valor raw ≥ 32768 y ≠ 65535 es negativo: `(raw − 65536) × 0,002 − 30`. Verificado en la C620: raw 63547 → −33,978 dBm (CLI idéntico).
- **`onu_status`:** `enumeration_meta` con la rama (`1082.500.10.2.3.8.1.4`), los valores observados y los no observados en C6 (1 Logging, 3 Synchronization, 6 AuthFailed).
  `enumeration` no cambia. LOS(2) incluye las ONU deshabilitadas por administración (causa 10 = DeactiveSucc); no equivale a corte de fibra.
- **Alarmas `offline_cause_*`:** `kind: historical` (reflejan la última baja, no el estado actual; hay ONU `working` con causa 2/3/9).

### Añadido
- **Alias `onu_type`** (mismo OID que `onu_type_name`, `alias_of`), para consumidores que buscan ese nombre.
- **`errors[]` por comando** (código, significado, `severity: info|error`, `retry`): 30 comandos de C620 y los equivalentes de C600. 224040, 230285 y 90 son `info` (lecturas vacías o `no` sin nada que borrar).
  El código 230240 (`real-speed gpon`) **sigue sin comando**: la sintaxis y el contexto no están verificados; solo consta en `cli_behavior.json`. La nota de la 1.2.0 que lo daba por añadido era incorrecta.
- **`serial_format`:** `ascii-pon-prefixed` (`<n>,<SERIAL>`) en `onu_serial_number`, `binary-8` en `uncfg_onu_serial`.
- **Manifiesto:** `counts.oids_kept` coincide con los archivos, `status_distribution` recalculado, `index_layout_final`, `not_exposed_attributes` (`onu_ip_address`).

### Corregido
- **Receta de perfiles de bajada:** CBS = PBS = CIR/80 (KB), no «128 KB» fijo (10240 → 128, 52480 → 656, 104960 → 1312; 9 perfiles C620 y 5 C600).
- `onu_name`/`onu_description`: `sensitivity: pii` (ya desde 1.2.0) y mención en la descripción.

### Seguridad
- **`results.json` ya no lleva índices de comunidades SNMP, cuentas ni peticiones web** (ramas `3902.3.6000.101.2.3`, `3902.3.6000.51.2`, `3902.3.101.7.5`):
  los hallazgos `ascii_index` de esas tablas contenían el nombre decodificado (incluidas comunidades de lectura y escritura) y el propio OID lo codifica.
  Se sustituyen por un único hallazgo `sensitive_branch_redacted`. Las versiones anteriores cargadas en `ispm_tkc` (1.1.0 y 1.2.0) conservan esos datos en `tkc_results.payload`:
  limpiar con `scripts/purge_sensitive_results.py` y rotar las comunidades.

### Puerta de contrato
Reglas nuevas: `results.json` sin ramas sensibles y ensayo de carga completo (`scripts/loader_dry_run.py`: ejecuta el Loader contra un cursor falso y valida cada INSERT contra el esquema); atributos únicos por familia, metadatos de signo/centinela, `pii`, alarmas históricas, `oids_kept` = archivos, `errors[]` presentes, y fixture de potencia con
signo contrastada con la CLI. El contrato de C600 pasa de 6 a 14 atributos.

## 1.2.0 — 2026-10-09 (C620 y C600)
Sustituye a la 1.1.0 (2026-10-02). Los ids existentes se conservan: 0 quitados, 0 renombrados.

### Cambios que un consumidor debe revisar
- **Firmware** de OID, entidades, alarmas y relaciones: `["2.0","2.1"]` → `["1.2.2"]` (igual que los comandos).
- **Escala y unidad:** 37 OID (C620) / 38 (C600) traían la unidad con el multiplicador ("0.001 dBm") y `scale` nulo; ahora `scale = 0.001` y `unit = dBm`. Valor real = `raw * scale`. Tensión óptica: `scale` 0.01 → 0.001 (3317 = 3,317 V). `pon_rx_power_detect_period`: sin escala (segundos). `2147483647` en potencias rx del módulo óptico = sin lectura.
- **Potencia rx/tx de ONU:** `scale_formula = raw*0.002-30` (sin cambios), ahora con `unit = dBm`; `65535` = sin señal.
- **Índice:** 17 OID escalares o IF-MIB (`sys_*`, `hc_*`, errores) con `onu_id_append = false`.
- **Nombres:** 43 hojas de la comunidad con `name = attribute` (antes "UNRESOLVED").

### Añadido
- **ONU sin autorizar por SNMP (solo C620):** `uncfg_onu_serial`, `_password`, `_type`, `_firmware`, `_detected`, `_last_found` en `1082.500.2.2.11.2.1.<col>.<ifIndexPON>.<n>`. Corrige la nota anterior «solo CLI».
- **uplink_port:** 16 OID IF-MIB para los uplinks xgei (ifType 6).
- **Entidades:** `tcont_profile`, `traffic_profile`, `onu_traffic_profile`; 75 atributos de entidad.
- **Relaciones** con orden de creación verificado (onu → pon_port, tcont_profile, gem_port, service_port) y service_port → traffic_profile.
- **Alarmas de ONU** por causa de baja: LOS, LOSi, DyingGasp, DeactiveSucc.
- **Comandos:** `show logfile brief`, `show logging alarm` (C620: 78; C600: 76); parámetros, comandos relacionados y prerrequisitos; rollback de `splitter`; error 230240 solo en `cli_behavior.json` (no llegó a `commands/`; corregido en 1.3.0).
- **Enlace OID ↔ comandos:** 21 campos de salida con `oid_ref` y 17 OID con `command_ref`.
- **Anotación de los 625 OID `documented`** (`pending_validation`: estructura, tabla vacía, notificación o columna no expuesta; las 17 no expuestas están confirmadas por GETNEXT en C620 y C600).

### Verificado y documentado
- Walks residuales de ambas OLT (inspector `3.6000.51.2.3.7`, perfiles `1082.70.67.2.3.1`); columnas 26-29 de `1082.500.20.2.1` no existen.
- `ssid info` solo existe en la C620.

### Notas
- La C600 y la C620 comparten casi todos los OID, pero el índice de puerto difiere: slot en los bits 10-8 (C620) y 11-8 (C600).
- Las contraseñas de la tabla de usuarios del equipo (`3902.3.6000.51.2.1`) se redactan en los walks nuevos y se sustituyeron en los locales.
