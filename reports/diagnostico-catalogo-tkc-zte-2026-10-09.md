# Diagnóstico del catálogo TKC — ZTE C300 / C320 / C600 / C620 (2026-10-09)

**Para:** quien mantiene el generador (`telecom-knowledge-extractor`). **De:** el consumidor (`network-api`).
**Alcance:** lo que el catálogo cargado en `ispm_tkc` declara y el equipo real NO respalda, o que falla/engaña al consumirlo. Lo confiable está al final para no regresarlo.

## 0. Qué versión se evaluó
| Familia | Cargado en `ispm_tkc` | Origen en el repo del generador | OID |
|---|---|---|---|
| C300 | id 7, v2 | `zxa10-c300/catalog-1.1.0` | 952 |
| C320 | id 9, v2 | `zxa10-c320/catalog-1.1.0-validated` | 1003 |
| C600 | id 14, v2 | `zxa10-c600/catalog-1.2.0` | 1788 |
| C620 | id 13, v2 | `zxa10-c620/catalog-1.2.0` | 1794 |

El consumidor elige la versión por mayor `tier` y luego mayor `version_num`, y una fila por `(entity_ref, attribute)` por estado (`verified_walk` > `verified_community` > `verified` > `documented` > `observed` > `inferred`) y confianza.

## 1. Evidencia usada (qué se contrastó contra qué)
- **C300/C320:** walks guardados (`docs/walks/ZTE_C300.txt` 1008 ONU; `ZTE_C320.txt` 1572 ONU; ifnames; `diagnostics/*_uncfg.txt`) reproducidos contra el adaptador real con el catálogo resuelto como el proveedor.
- **C600:** recolección de solo lectura del 2026-10-09 a la OLT en producción (390 ONU, todas las tablas de ONU, perfiles, VLAN, tarjetas, entorno; 277 comandos CLI). Estado SNMP contrastado ONU por ONU con `show gpon onu state`.
- **C620:** uso en producción y la verificación de lectura previa; no se recapturó hoy.
- **Producción:** lectura SNMP por las 5 OLT clásicas contra la BD (0 ONU del equipo ausentes de la BD).

## 2. Hallazgos (ordenados por impacto)

### D-01 · ALTO — `verified_community` de la rama `1082.500` en C300 y C320: 0 filas en el equipo
- **Qué:** 10 OID marcados `verified_community` (0,85) en C300 y en C320 no tienen NINGUNA fila en los walks reales de esos modelos: `onu_name` (`…10.2.3.3.1.2`), `onu_description` (`…3.1.3`), `onu_serial_number` (`…3.1.18`), `onu_status` (`…8.1.4`), `onu_last_online_time/offline_time/offline_reason` (`…8.1.5/.6/.7`), `onu_gpon_optical_distance` (`…10.1.2`), `onu_rx_power` (`1082.500.20.2.2.2.1.10`) y `onu_ip_address` (`1012.3.50.16.1.1.10`).
- **Evidencia:** C300 → 0/10 con filas; C320 → 0/10. En cambio TODOS los `verified` (110 / 217) y `verified_walk` (16 / 16) de esas familias sí tienen filas.
- **Causa probable:** evidencia de comunidad (plataforma C6) promovida a `verified_community` sin walk de la propia familia.
- **Consecuencia:** el consumidor camina `onu_name`/`onu_description` en clásicas y siempre recibe vacío; la IP de gestión por SNMP nunca devuelve dato.
- **Pedido al generador:** no asignar `verified_*` a una familia sin un walk de esa familia; degradar a `observed` o acotar el OID a `families: [C600, C620]`.

### D-02 · ALTO — Potencia óptica: valores crudos ~64000–65308 sin metadato de signo ni centinela
- **Qué:** ONU en línea devuelven RX crudo 64031–65308 (fórmula `raw*0.002-30` → ~100 dBm). Aparece en las tres plataformas: C300 7/1008, C320 4/1573, C600 3/390. Interpretados como entero de 16 bits con signo serían −33…−30,5 dBm (señal muy débil).
- **Catálogo:** solo trae `scale_formula` y `unit`; ni `signed`, ni lista de centinelas (65535), ni rango válido.
- **Consecuencia:** el consumidor descarta todo lo fuera de [−40, 10] dBm y esas ONU, las de peor señal, quedan SIN lectura y no disparan `low_signal`.
- **Estado:** hipótesis pendiente de confirmar con `show pon power attenuation gpon_onu-<idx>` en una de esas ONU (solo lectura). Una vez confirmada, añadir al OID: `signed_bits: 16`, `sentinels: [65535]`, `valid_range_dbm`.

### D-03 · ALTO — Dos enums distintos de `onu_status` bajo el mismo atributo, y `1` significa cosas opuestas
- **Clásicas `1012.3.50.11.2.1.8`:** `{1 Online, 2 Offline, 65535 Unknown}` (coincide con el equipo).
- **Rama `1082.500.10.2.3.8.1.4` (community, C300/C320):** `{1 Logging, 2 LOS, 3 Synchronization, 4 Online, 5 DyingGasp, 6 AuthFailed, 7 Offline}`.
- **C600/C620 verificado:** `{2 LOS, 4 Working, 5 DyingGasp, 7 OffLine}`; contraste 390/390 en la C600 (4→working 374, 5→DyingGasp 10, 7→OffLine 6).
- **Problema:** el mismo `attribute` tiene enums incompatibles y el valor 1 es «Online» en una rama y «Logging» en otra; además `Offline` vs `OffLine`, `Online` vs `Working`.
- **Pedido:** una enumeración por (atributo, rama) con identificador de rama, y `1/3/6` documentados como «no observados» en C6 hasta verlos.
- **Nota para el consumidor (no del generador):** `mapOnuStatus` mapea `1`→online para todas las familias; en C6 el `1` sería «Logging». No se observó en la C600/C620 (solo 4/5/7). Latente.

### D-04 · MEDIO — Ruta de ONU sin autorizar distinta por familia y ausente en C600
- C300/C320: `1082.500.10.2.2.5.1.*` con filas reales (18 en cada diagnóstico de julio).
- C620: `1082.500.2.2.11.2.1.<col>` (otra rama, agregada en 1.2.0).
- C600: sin `uncfg_*`; `1082.500.10.2.2.5` respondió `Request timed out` a los 69 s (0 filas) y la OLT no tenía ONU sin autorizar (`show pon onu uncfg` vacío).
- **Pedido:** probar `1082.500.2.2.11.2.1` en la C600 cuando haya una ONU sin autorizar; documentar en el manifiesto que la ruta depende de la familia.

### D-05 · MEDIO — Atributos que el consumidor usa y no existen en C6
- `onu_type` ausente en C600 y C620 (existen `onu_type_name` `…3.1.1` y `onu_model` `…20.2.1.2.1.2`, ambos verificados 12/12 contra `detail-info` y `remote-onu equip`). El consumidor busca `onu_type`.
- `onu_ip_address` ausente en C600 y C620.
- **Pedido:** alias `onu_type → onu_type_name` en las familias C6, o contrato único de nombres de atributo entre familias (`consumer_contract.json` cubre 17 atributos en C620 y solo 6 en C600).

### D-06 · MEDIO — Causa de baja: valor 1 sin catalogar; semántica de «última causa»
- Catálogo: `offline_cause` 2 LOS, 3 LOSi, 9 DyingGasp, 10 DeactiveSucc. Observado en la C600 (`…8.1.7`): 9 (297 ONU), 3 (46), 2 (37), **1 (10)**; el 1 no existe en el catálogo.
- 374 ONU están `working` y aun así tienen causa 2/3/9: es la **última** causa de baja, no el estado actual. Los `alarm.zte.gpon.onu.offline_cause_*` como alarmas activas dispararían sobre ONU sanas.
- Coincide: las 10 ONU en DyingGasp traen causa 9 (10/10) y las 6 OffLine traen causa 1 (6/6).
- **Pedido:** catalogar el 1 (parece «sin evento / OffLine»), y marcar estas alarmas como `kind: historical` en vez de estado.

### D-07 · MEDIO — Eventos del `show logging alarm` sin mapear
- 626 eventos en ~13,7 h en la C600: `XPON alarm general event` ×580 (códigos `723961` ×214 pares alarm/restore, `723956` ×76 pares), `GPON notify Uncfg ONU` ×4, `GPON alarm link olt losi` ×2, `dgi` ×2, `GPON ONU first-online event` ×2, `SNMP entity authentication failure` ×1.
- Los códigos `723961`/`723956` solo figuran como texto de ejemplo dentro de `notificationAlmDescription`; no hay alarma catalogada para ellos.
- **Pedido:** catalogar los tipos de evento del log CLI y qué significa cada código `72395x/72396x` (par alarm/restore); hoy un consumidor no puede clasificarlos.

### D-08 · MEDIO — Errores de CLI sin catalogar o mal clasificados
- `%Error 224040` y `%Error 230285` («No related information to show») son **informativos**, no fallos (ONU sin puerto WiFi o de video). El catálogo trae 224040 en un solo comando y 230285 en ninguno.
- `%Error 140303 Invalid input` aparece con `show gpon remote-onu wifi-info` y con `ssid info` en C600 (12/12 ONU). La sintaxis correcta es `wifi info`; `ssid info` solo existe en C620 (así lo dice el CHANGELOG, y se confirmó).
- Vistos en producción y **ausentes** de `commands/`: `%Error 223981` (`traffic-limit` con perfiles `SMARTOLT-xxM`) y `%Error 230240` (`real-speed gpon`). El CHANGELOG 1.2.0 dice que 230240 se añadió; no aparece en `commands/` de C600 ni C620.
- **Pedido:** campo `errors[]` por comando con `{code, meaning, severity: info|error}`.

### D-09 · MEDIO — Comandos de escritura: estado y reglas aprendidas
- 16 `modify`, 10 `create`, 6 `delete` y los `reset`/`enable`/`disable` están `documented` u `observed`; ninguno se probó en la C600 (no hay ONU en espera).
- Falta lo aprendido en producción: `traffic-limit` rechaza los perfiles de velocidad de SmartOLT; en C620 los perfiles de velocidad usan CBS = PBS = rate/80 KB; los perfiles viven en el `service-port` (`ingress`/`egress`) y no en `gpon_onu`.
- **Pedido:** campo `verified_on: [familias]` por comando de escritura y una sección `rules` con las anteriores.

### D-10 · MEDIO — Datos personales expuestos por SNMP y sin clasificar
- C600: `onu_name` (`…3.1.2`) y `onu_description` (`…3.1.3`) llenos en las 390 ONU, con valores distintos (389/388) y forma de nombre de persona y dirección. La CLI de la cuenta de lectura los enmascara (`********`) pero SNMP los entrega.
- **Pedido:** campo `pii: true` por atributo y por familia. El consumidor ya omite estos atributos en C620 y los camina en C600 y clásicas.

### D-11 · MEDIO — Entorno del chasis: el catálogo promete lo que la OLT no publica
- C600/C620: `fan` 26 OID (todos `documented`), `sensor` 35 (24 `documented`, 11 `verified`), `power_supply` 15 (4 `verified`).
- La C600 publica en `1082.10.10`: 6 sensores con nombre (`2nd-Power-Monitor`, `Input-Fan-Monitor`, `Heat-Exchager`, `Distribution-Frame`, `Gate-Sensor`, `Smoke-Sensor`) con estado; **sin temperatura, CPU, memoria ni ventiladores**.
- **Pedido:** marcar como `not_exposed` por familia lo que la OLT no publica (como ya se hizo con las 17 columnas no expuestas), para que el consumidor no lo busque.

### D-12 · BAJO — `oper_status` duplicado entre entidades
- Un mismo OID (`1.3.6.1.2.1.2.2.1.8`) aparece como `pon_port` (espacio `ONU-ID`) y `uplink_port` (espacio `ifIndex`). En C620 ambas son `verified_walk`; en C600 la de uplink es `inferred`.
- El consumidor indexa por `attribute` y se queda con la última fila: depende del orden de la consulta.
- **Pedido:** atributos únicos por entidad (`pon_oper_status`, `uplink_oper_status`).

### D-13 · BAJO — Metadatos del manifiesto inconsistentes
- `bitcalc_validation`: 24 de 40 puertos NO coinciden con `catalog_map {"shelf":"31-28","slot":"27-24"}`; veredicto «accepted (layout derivado aplicado)». La fórmula real es `285278208 + slot*256 + pon` (bits 8+), y el CHANGELOG habla de bits 10-8 (C620) / 11-8 (C600).
- `oids_kept` del manifiesto: C600 1772 y C620 1778; los archivos tienen 1788 y 1794 (diferencia de 16 = los OID IF-MIB de `uplink_port` añadidos después).
- **Pedido:** una sola descripción del índice y contadores que coincidan con los archivos.

### D-14 · BAJO — Nombres de versión ambiguos
- C320 tiene dos catálogos «1.1.0»: el de 1992 OID todos `documented` y el `1.1.0-validated` de 1003 (el cargado). C300 v2 = `1.1.0` (952). C600/C620 pasaron de 1788/1788 a 1788/1794.
- **Pedido:** versionado único por contenido (`content_hash` ya existe) y que el nombre cargado coincida con el directorio.

### D-15 · BAJO — Serial: formato mezclado en clásicas
- C300: 989 seriales como `Hex-STRING` y 19 como `STRING`; C320: 1521 y 51. Un walk en texto pierde bytes no imprimibles de los STRING (p. ej. `XPON#…`), así que se ven repetidos.
- C600/C620: ASCII con prefijo `<pon>,` (`serial_text`).
- **Pedido:** declarar `serial_format` por familia (`binary-8` vs `ascii-pon-prefixed`) y que los walks se exporten con tipo explícito.

### D-16 · INFO — `documented` con filas reales (candidatos a promover)
- C300: 41 OID `documented` tienen filas en el equipo. C320: 0.
- C600/C620: de los 625 `documented`, 118 caen en ramas que se recapturaron hoy sin filas (nodos estructurales; correcto que sigan `documented`).

### D-17 · INFO — Ramas del equipo fuera del catálogo (bien así)
- `1082.70.82.2.2.1.*`: 44 columnas × 390 ONU de contadores PM, **todos 0** (la OLT no puebla PM). `10.2.*`: umbrales con centinelas `2147483646/2147483647`. `3902.3.6000.51.*`: tabla de usuarios del equipo con contraseñas codificadas y registro de peticiones web (no catalogado; se redactó en los walks nuevos según el CHANGELOG).
- **Pedido:** mantenerlas fuera, y añadir `sensitive: true` a cualquier OID futuro de `3.6000.51`.

## 3. Lo que SÍ es confiable (no regresar)
| Dato | Familias | Evidencia |
|---|---|---|
| `onu_serial_number`, `onu_status`, `onu_rx_power`, `onu_tx_power`, `onu_type`, `onu_vendor_id` en `1012.3.50.*` | C300, C320 | 1008 / 1572 filas; 0 ONU del equipo ausentes de la BD en 5 OLT |
| Fórmula `raw*0.002-30` | C300, C320, C600, C620 | 11/12 ONU a <0,15 dB de `show pon power attenuation` (C600) |
| Enum de estado `{2,4,5,7}` | C600, C620 | 390/390 en la C600 |
| `onu_gpon_optical_distance` / `onu_distance` (m) | C600, C620 | 12/12 contra `show gpon onu distance` |
| `onu_type_name`, `onu_model` | C600, C620 | 12/12 contra `detail-info` / `remote-onu equip` |
| `service_port_ingress/egress_profile` | C600, C620 | 390 filas; 2 columnas por perfil |
| `oper_status` = ifOperStatus | todas | mismo OID en las cuatro |
| Los `verified` y `verified_walk` en las ramas recapturadas | C600 | 116 con filas, 0 sin ellas |
| 28 de 30 `show` verificados | C600 | corrieron sin rechazo |
| Causa de baja 9 = DyingGasp | C600 | 10/10 |

## 4. Orden sugerido para revisarlo con el generador
1. D-01 y D-03 (evidencia por familia y enums por rama): son los que hacen que el catálogo afirme algo falso.
2. D-02 (signo/centinelas): confirmar con una lectura CLI y añadir metadatos.
3. D-05, D-04, D-10 (nombres comunes, ruta de uncfg, PII).
4. D-06, D-07, D-08, D-09 (alarmas, errores y escritura).
5. El resto (metadatos y versionado).

*Datos crudos (con seriales/MAC, no subir a git): `network-api/recoleccion-c600-2026-10-09T*/`. Reproducción del contraste clásico: `network-api/scripts/probar-catalogo-clasicas.ts`.*
