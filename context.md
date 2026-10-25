# Contexto de catalogos ZTE C300 y C320

Este archivo resume el estado actual de los catalogos generados para futuras
referencias dentro del proyecto Telecom Knowledge Compiler (TKC).

## Mapa rapido

- Catalogo semilla/documental (teorico): `catalog/zte/zxa10-c320/catalog-1.0.0/`
- Catalogo C300 validado por walk: `catalog/zte/zxa10-c300/catalog-1.0.0/`
- Catalogo C320 validado por walk (no pisa la base): `catalog/zte/zxa10-c320/catalog-1.0.0-validated/`
- Documentos fuente C320: `docs/zte/zxa10-c320/`
- Walks reales: `docs/walks/ZTE_C300*.txt` y `docs/walks/ZTE_C320*.txt`
  (`.txt` enterprise, `_entities.txt` entPhysicalTable, `_ifnames.txt` ifName + ifTable).
- Fuentes de validacion community: `docs/validation/community/*.txt`
- Solicitudes de walk dirigido: `docs/validation/requests/*.txt`
- Resoluciones operativas de hallazgos bloqueantes: `docs/walks/resolutions.json`
- Reportes de revision: `reports/walk_review/`

El pipeline vigente trabaja en tres capas:

1. Fase 1: C320 se genera desde documentacion/MIBs como catalogo teorico.
2. Fase 2 (walk validation): C300 y C320 se validan con walks reales. Confirma OIDs,
   poda OIDs read-only no observados, confirma entidades fisicas, valida indices
   compuestos contra `ifName`, y detiene el procesado ante hallazgos bloqueantes
   hasta accept/reject.
3. Fase 2 (community): ingiere extractos curados validados contra hardware
   (`docs/validation/community/`) que agregan leaves de ONU, la formula de indice
   y enums, reconciliando estado/escala contra el walk.

Nota: el modelo capturado como "C600" es en realidad C320 (mismo arbol MIB, mismo
encoding `285278208 + slot*256 + pon` y misma convencion ifType). Se trata como C320.

## ZXA10 C320

Rol: catalogo base para ZTE GPON. La configuracion principal apunta a esta
familia:

- `vendor`: `ZTE`
- `family`: `ZXA10 C320`
- `technology`: `gpon`
- `firmware`: `2.0`, `2.1`
- `current_firmware`: `2.1`
- `catalog_version`: `1.0.0`
- Prefijo enterprise ZTE observado/documentado: `1.3.6.1.4.1.3902`

Fuentes relevantes en `docs/zte/zxa10-c320/`:

- MIBs ZTE AN/GPON/chassis/interface/service/optical/vlan/envmon/alarm.
- `hardware_description.pdf`
- `command_reference.pdf`

Resumen del `manifest.json` generado el `2026-07-04T16:16:54`:

- Entidades: 13; 5 `verified`, 8 `documented`, 0 `inferred` (todas con descripcion curada).
- Comandos: 16 reales (curados en `command_reference_cli.txt`), categorizados y ligados a
  entidad; el PDF de output de mantenimiento ya NO produce comandos basura.
- OIDs: 1992 total; 1974 `documented`, 18 `verified`.
- Relaciones: 7, todas `inferred` (capa aun por reforzar).
- Alarmas: 117 total, todas `documented`, tipadas y **117/117 con probable_causes y
  remediation** (KB por tipo: optical/hardware/power/environmental/security/traffic/protocol).
- Conflictos: 0.
- Confianza promedio: `~0.85`.

Nota (capa semantica reforzada, 2026-07-05): entidades ancladas en OIDs reales del MIB se
elevan a `documented`/`verified` (antes `inferred`); las alarmas cascadean a `documented` por
propagacion; los comandos se curan (el `command_reference.pdf` era output de mantenimiento, no
sintaxis). El extractor de comandos filtra lineas de output (sin `{param}` y con `:`).

Entidades presentes:

- `card`
- `fan`
- `gem_port`
- `olt`
- `onu`
- `optical_module`
- `pon_port`
- `power_supply`
- `sensor`
- `service_port`
- `shelf`
- `uplink_port`
- `vlan`

Grupos de OIDs presentes:

- `card`
- `fan`
- `gem_port`
- `olt`
- `onu`
- `optical_module`
- `pon_port`
- `power_supply`
- `sensor`
- `service_port`
- `shelf`
- `vlan`

Relaciones presentes:

- `card`
- `gem_port`
- `onu`
- `pon_port`
- `service_port`

Comandos extraidos actualmente:

- `commands/show/config_type.json`
- `commands/show/disable_shutdown_port.json`
- `commands/show/ping_response_true.json`
- `commands/modify/config_state.json`

Nota: los fixtures de prueba para C320 incluyen comandos de ejemplo como
`show onu {interface} {onu-id} [detail]`, `create onu {interface} {onu-id}
profile {line-profile}`, `show gpon-onu-state {interface}` y `save`, ademas de
alarmas de ONU (`ONU_LOS`, `ONU_DYING_GASP`) y OIDs opticos ONU de ejemplo.

## ZXA10 C300

Rol: catalogo especializado empiricamente desde la semilla `ZXA10 C320`.

Walks usados:

- `ZTE_C300.txt`: rama enterprise/vendor.
- `ZTE_C300_entities.txt`: `entPhysicalTable`, inventario fisico real.
- `ZTE_C300_ifnames.txt`: `ifXTable ifName`, interfaces reales e indices
  compuestos.

Resumen del `manifest.json` generado el `2026-07-04T16:16:59`:

- OIDs conservados: 926.
- OIDs podados: 1066.
- Entidades confirmadas: 5.
- OIDs conservados por estado: 816 `documented`, 110 `verified`.
- Entidades por estado: 5 `verified`, 8 `inferred`.

Entidades confirmadas por evidencia real:

- `shelf`: 1 instancia via `entPhysicalTable`.
- `power_supply`: 2 instancias via `entPhysicalTable`.
- `card`: 6 instancias via `entPhysicalTable`.
- `pon_port`: 32 instancias via `ifXTable`.
- `uplink_port`: 8 instancias via `ifXTable`.

Triggers encontrados en C300:

- `oid_not_increasing`: 8.
- `ascii_index`: 15.
- `documented_only`: 1882.
- `scale_detected`: 2.
- `observed_only`: 30.
- `entity_confirmed`: 5.
- `bitcalc_validation`: 1.

Hallazgo critico de indices compuestos:

- El mapa teorico C320 usaba `shelf: 31-28`, `slot: 27-24`.
- Contra 40 `ifIndex` reales de C300 hubo 0 coincidencias y 40 desacuerdos.
- Ejemplo: `ifIndex=285278721`, `ifName=gpon_1/2/1`; el decode teorico daba
  `shelf=1`, `slot=1`, pero el nombre real indica rack/slot/port `1/2/1`.
- Layout derivado desde walk:
  - `shelf`: constante observada `1` en alcance single-shelf.
  - `slot`: bits `12-8`.
  - `port`: bits `4-0`.
- `docs/walks/resolutions.json` contiene actualmente:
  `{ "ZXA10 C300": { "bitcalc_validation": "accept" } }`
- Por tanto, el catalogo C300 generado acepta la correccion empirica.

Escalas detectadas empiricamente en C300:

- `1.3.6.1.4.1.3902.1082.10.10.2.1.5.1.8`: valor crudo `52893`,
  escala `0.001`, valor escalado `52.893`, unidad `volts`.
- `1.3.6.1.4.1.3902.1082.10.10.2.4.10.1.22`: valor crudo `52893`,
  escala `0.001`, valor escalado `52.893`, unidad `volts`.

Indices ASCII / cadenas observadas:

- (2 cadenas de 12 caracteres omitidas: probables comunidades SNMP; ver `sensitive_prefixes` en config/vendors.yaml)
- `default`
- `gtghg.bt`
- `gtghg.fw`
- `gtghg.mvr`
- `gtxk.mvr`
- `hutq.mvr`
- `hutqb.bt`
- `hutqb.fw`
- `hutqb.mvr`
- `scxm1.mvr`

## Capa de validacion community (fuentes curadas)

Ubicacion: `docs/validation/community/`. Se ingieren en Fase 2 (`src/walk_validator/community.py`)
y aplican a cada familia listada en su `meta.families`. `docs/validation/` esta excluido del
Classifier de Fase 1. Estados propios: `verified_walk` (confirmado por el walk) y
`verified_community` (confirmado por implementacion en hardware).

Fuentes actuales:

- `snmp-olt-zte_reference_extract.txt`: 12 leaves de ONU + formula del indice compuesto
  (2 espacios: ONU-ID en `.1082`, TYPE en `.1012`) + enums (status 1-7, offline_reason 1-13).
- `snmp-olt-zte_walk_reconciliation.txt`: reconcilia contra el walk real.
- `snmp-olt-zte_status_serial_columns.txt`: mapea las columnas de status y serial (derivadas
  por correlacion contra el walk).

### Hallazgo clave: divergencia .1082 vs .1012

El walk real NO puebla la rama `.1082` (espacio ONU-ID). Toda la data operativa de ONU de este
hardware/firmware vive en el espacio TYPE `.1012.3.50.11/12`. Por eso los 9 leaves `.1082` se
degradan a `verified_community` (variante), y los OIDs reales del espacio TYPE quedan
`verified_walk`. La formula community reemplaza el bit-map como decoder de indice.

### Set MVP verificado contra hardware (verified_walk)

Datos del hot-path que el network-api necesita, todos confirmados en C300 y C320:

- Formula de indice TYPE: `suffix = 268435456 + slot*65536 + pon*256`, mas `<onuID>`.
- `onu_type`: `.1.3.6.1.4.1.3902.1012.3.50.11.2.1.17`
- `onu_rx_power`: `.1.3.6.1.4.1.3902.1012.3.50.12.1.1.10`, escala `raw*0.002-30` (RX lleva `.1` extra).
- `onu_tx_power`: `.1.3.6.1.4.1.3902.1012.3.50.12.1.1.14`
- `onu_vendor_id`: `.1.3.6.1.4.1.3902.1012.3.50.11.2.1.1` (prefijo de 4 chars)
- `onu_status`: `.1.3.6.1.4.1.3902.1012.3.50.11.2.1.8` (columna .8, enum derivado
  `1=Online, 2=Offline, 65535=Unknown`; correlaciona 1:1 con presencia de RX).
- `onu_serial_number` (completo): `.1.3.6.1.4.1.3902.1012.3.50.11.2.1.3`
  (Hex-STRING: 4 bytes ASCII vendor + 4 bytes unicos, ej. `43 44 54 43 1D DB 9E B4` = `CDTC1DDB9EB4`).

Escala optica: RESUELTA a `dBm = raw*0.002 - 30.0` (la hipotesis `÷100` queda descartada).

## Estado de consultas del network-api (MVP)

- `getCards()`: LISTO. Entidad `card` verified via entPhysicalTable (6 instancias), 103 OIDs.
- `getPonPorts()`: CERRADO. `pon_port` verified_walk:
  - oper via `ifOperStatus` (ifTable `.1.3.6.1.2.1.2.2.1.8`, `1=up/2=down`); PON ports se
    identifican por `ifType=250` (uplinks por `ifType=6`).
  - OIDs operativos agregados como verified_walk: `oper_status` (.8), `admin_status` (.7),
    `if_type` (.3), sin tocar los 189 OIDs del MIB.
  - `onu_count` por puerto: DERIVADO de la tabla ONU (`.1012.3.50.11.2.1`) sin OID nuevo.
    C300: 1008 ONUs en 28 puertos (1..81/puerto). C320: 1572 ONUs en 32 puertos (max 105).
- La rama pon-port documentada del MIB (`.1082.500.21`, zxAnGponOP) NO existe en ningun firmware
  (confirmado con "No Such Object"); no usarla.
- Solicitud de walk dirigido de OLT: `docs/validation/requests/snmp-olt-zte_OLT_ponport_walk_request.txt`.

## Pendientes

- Mapeo de rama de software: los 11 indices ASCII de software/parche del catalogo estan en
  `.1082.20.30` (ausente en el walk); el equipo expone el software en `.1012` (ver `3902.1015`).
  Marcados `pending_validation` en el catalogo. No bloquea el MVP.
- Caveat de conteo C320: el ifTable capturado tiene 16 PON ports pero el walk enterprise tiene
  32 puertos con ONUs (capturas de distinto momento/scope). Una recaptura simultanea alinearia.

## Diferencias clave entre C320 y C300

- C320 es el catalogo documental completo: conserva todos los OIDs de MIBs y
  documentacion aunque no haya validacion de walk para esa familia.
- C300 es una especializacion empirica: mantiene solo lo respaldado por walk o
  lo que no debe podarse por ser writable/read-create/estructural.
- C300 tiene muchas menos entradas de OID que C320 porque se podaron 1066 OIDs
  read-only no confirmados.
- C300 mejora la confianza de OIDs confirmados y entidades reales agregando
  bloques `empirical`.
- C300 corrige el layout de bits de indices compuestos para el caso observado
  single-shelf.

## Reglas operativas para futuras referencias

- Si se necesita una referencia teorica amplia de ZTE GPON, usar C320.
- Si se necesita lo observado en produccion para C300, usar C300.
- No asumir que un OID documentado en C320 existe en C300: validar contra
  `catalog/zte/zxa10-c300/catalog-1.0.0/oids/`.
- No revertir la correccion de bits de C300 sin evidencia nueva de `ifName`.
- La validacion `shelf=1` es de alcance single-shelf; si aparece un equipo
  multi-shelf, repetir validacion con walks nuevos.
- Los OIDs `read-only` no observados en C300 se podan; los
  `read-write`, `read-create`, `write-only`, `not-accessible` y
  `accessible-for-notify` se conservan como `documented`.
- Los indices ASCII deben tratarse como indices textuales, especialmente en
  tablas de firmware/version/configuracion.
- Ante hallazgos bloqueantes nuevos, revisar `reports/walk_review/` y resolver
  en `docs/walks/resolutions.json` con `accept` o `reject` antes de confiar en
  el catalogo derivado.
- Para la data operativa de ONU/PON de este hardware usar el espacio TYPE `.1012`,
  NO `.1082` (esa rama no esta poblada por el firmware). El indice es de 2 niveles
  `suffixTYPE.onuID` (RX lleva `.1` extra).
- El network-api debe consumir los OIDs `verified_walk` del set MVP; el OID numerico es
  la clave estable (`mib_name: UNRESOLVED` hasta correlacion MIB).
- Nuevas fuentes de validacion van a `docs/validation/community/` con `doc_type: community`;
  soportan `status`/`note` por OID, `optical_scale`, `downgrade_status` y enums arbitrarios.
- Cuando el modelo del walk == familia semilla (C320), el catalogo validado se escribe en
  `catalog-<v>-validated` para no pisar la base teorica de Fase 1.

## Walk dirigido PON ports C320 (2026-07-28) — gap ifOperStatus cerrado

Contra el OLT real "MARROQUIN" (`190.14.224.10:161`, `C320 Version V2.1.0 Software`):

- `ifOperStatus` (`.1.3.6.1.2.1.2.2.1.8`) **capturado por primera vez**: 36 valores reales
  → `docs/walks/ZTE_C320_ifTable.txt`. Antes de esto, 0 coincidencias en todos los walks
  existentes; era el gap original que motivo el walk dirigido de PON ports.
- `zxAnGponOP` (`.1.3.6.1.4.1.3902.1082.500.21.2.1`): confirmado `No Such Object` por walk
  real → `docs/walks/ZTE_C320_gponOP.txt`. Antes solo habia una nota documental de ausencia
  (`docs/validation/requests/snmp-olt-zte_OLT_ponport_walk_request.txt`); ahora es evidencia
  empirica.
- `entPhysicalTable` reintentado con mas retries/timeout: 86 lineas (antes 1 sola, walk
  parcial/incompleto) → `docs/walks/ZTE_C320_entities_retry.txt`. Revela: shelf, 2 tarjetas
  de linea GPON de 16 puertos, tarjeta de poder general, tarjeta de gestion/switch tipo A.
- Rama ambiental `.1.3.6.1.4.1.3902.1082.10.10.3`: `No Such Object` → `docs/walks/ZTE_C320_env.txt`.
  Esperado: esa rama son definiciones de trap (notificaciones), no tabla de lectura viva;
  las alarmas de temperatura (`zxAnEnvHighTempAlm` etc.) solo llegarian por trap real, nunca
  por polling/GET.

**RESUELTO 2026-07-29 — catalogo C320 re-enriquecido con la nueva evidencia.** Contenido de
`ZTE_C320_ifTable.txt` fusionado en `ZTE_C320_ifnames.txt` y `ZTE_C320_entities_retry.txt` en
`ZTE_C320_entities.txt` (para que el WalkValidator los reconozca por sufijo `_ifnames`/
`_entities`). Se corrio `WalkValidator` SOLO para C320 (reusando la semilla Fase 1 ya
existente, sin tocar C300/C600 que ya estan finalizados y cargados en BD). Resultado en
`catalog/zte/zxa10-c320/catalog-1.1.0-validated/`:
- Trigger `pon_operational` disparado: entidad `pon_port` ahora `empirical.oper_via:
  "ifTable (ifType=250)"`, `pon_ports: 32`, `oper_up: 32`, `oper_down: 0`.
- 3 OIDs nuevos en `oids/pon_port.json` como `verified_walk`: `oper_status` (`.2.2.1.8`,
  IF-MIB ifOperStatus), `admin_status` (`.2.2.1.7`), `if_type` (`.2.2.1.3`) — con
  `full_oid_template: ".<oid>.<ifIndex>"` usando la formula de indice ya confirmada
  (`suffix = 285278208 + slot*256 + pon`, shelf=1).
- `entities_confirmed` subio de 4 a 5 (2 entidades hardware confirmadas via entPhysicalTable
  con el retry, antes 0 por el walk incompleto).
- Sin hallazgos bloqueantes nuevos (no hubo `WalkHalt`); `bitcalc_validation: null` porque
  C320 es la familia semilla (no aplica revalidacion de bits, esa logica es solo para
  familias derivadas como C300/C600).

**AUTOCORRECCION 2026-07-29** — la primera fusion por `cat >>` genero un falso positivo:
`ZTE_C320_ifnames.txt` YA contenia casi toda la tabla ifTable (columnas 1-22, incluida
ifPhysAddress), no solo ifName; pegar el walk nuevo duplico ~350 lineas identicas de columnas
ya presentes, y el checker de secuencia (`oid_not_increasing`, que asume una unica corrida
`snmpbulkwalk` continua por archivo) marco esto como `severity: high` / `status=conflicted`
en la tabla ifIndex estandar. Verificado que NO llego a corromper el catalogo (esa tabla
MIB-2 no forma parte del catalogo vendor ZTE, y las 3 columnas nuevas que si importan
-.3/.7/.8- no coinciden con la columna afectada -.1-), pero igual se corrigio: deduplicar por
OID + ordenar antes de reprocesar. Leccion para futuras fusiones de walks: **nunca concatenar
dumps `snmpbulkwalk` de corridas distintas con `cat >>` sin deduplicar+ordenar por OID
primero** — el parser asume una sola secuencia estrictamente creciente por archivo.

## Hallazgo mayor 2026-07-29 — `ZTE_C320.txt` NUNCA tuvo la rama enterprise real

Investigando por que 9 OIDs de indice ASCII (rama `1082.20.30`) daban `ascii_branch_absent`,
se descubrio que **`docs/walks/ZTE_C320.txt` (794550 lineas, nombrado como walk "enterprise")
contenia el 100% de su contenido bajo `.1012.*` (espacio operativo TYPE/ONU) y CERO lineas
bajo `.1082.*`** (la rama propia del vendor ZTE, donde vive casi todo el catalogo). El archivo
terminaba en errores `snmpbulkwalk: Failure in sendto (Network is unreachable)`, señal de que
la corrida se corto por red — pero el corte fue DESPUES de completar solo `.1012`, la rama
`.1082` nunca se intento (a diferencia de `ZTE_C300.txt`, que si tiene ambas: 396243 lineas
`.1012` + 2500 `.1082` — el problema es especifico de este archivo, no del pipeline).

Impacto real: el `WalkValidator` usa este archivo (tipo `enterprise`) para decidir que OIDs de
`.1082.*` podar por "no observados". Como nunca tuvo NADA de `.1082`, los ~1100 OIDs podados y
~1990 `documented_only` del catalogo `1.1.0-validated` **nunca fueron realmente contrastados
contra el equipo real** — no es que el equipo no los soporte, es que faltaba la evidencia.

**Corregido**: se capturo un walk real de `1.3.6.1.4.1.3902.1082` contra el C320 real
(`190.14.224.10:161`), segmentado por rama de segundo nivel para evitar timeouts (una subrama,
`1082.20.20`, tiene una tabla gigante de descripciones OSPF que corta la conexion si se camina
completa — se evito caminando `1082.20.30` de forma acotada en vez de `1082.20` entero). Fusion
final en `ZTE_C320.txt` (deduplicado + ordenado por OID, ahora 830288 lineas). Resultado tras
reprocesar:
- `verified` subio de 0 a 217 OIDs (antes ninguno tenia confirmacion `.1082` real).
- `oids_kept` 909→1001, `oids_pruned` 1107→1015.
- De los 9 OIDs ASCII de software (`1082.20.30.*`): **4 confirmados con datos reales**
  (`zxanswimagefilename`, `zxanswpatchname`, `zxanswcardpatchname`, `zxanswpatchpkgname`) y
  **5 confirmados como genuinamente ausentes** (`No Such Object` limpio, walkeados uno por uno
  sin error) — ya no es incertidumbre, es evidencia dura en ambos sentidos.
- Tambien se confirmo (via `3902.1015.2.1.2.4`, igual que en el hallazgo de C300) que el
  inventario real de software vive ahi tambien para C320, mismo patron que
  [[pending-software-branch-mapping]] documento para C300 — el `validate_ascii_indices` del
  codigo aun NO implementa esa correspondencia `1082.20.30 → 1015.2.1.2.4` (queda igual de
  pendiente que antes, ahora confirmado que aplica a ambas familias).

Leccion adicional: `timeout N` de shell mata el proceso SIN que `snmpbulkwalk` imprima ningun
error — una verificacion que solo busca "Timeout"/"Network unreachable" dentro del archivo de
salida puede dar falso negativo si el corte fue por `timeout` del shell, no por el propio
cliente SNMP. Siempre verificar tambien que la ULTIMA rama capturada corresponda a donde
deberia terminar el walk, no asumir por ausencia de mensajes de error.

## Comandos utiles

Generar o regenerar catalogos:

```bash
python main.py --config config/pipeline.yaml
```

Ejecutar pruebas:

```bash
python -m pytest -q
```

Ver manifiestos:

```bash
jq . catalog/zte/zxa10-c320/catalog-1.0.0/manifest.json            # C320 teorico
jq . catalog/zte/zxa10-c320/catalog-1.0.0-validated/manifest.json  # C320 validado
jq . catalog/zte/zxa10-c300/catalog-1.0.0/manifest.json            # C300 validado
```

Ver hallazgos y el set MVP verified_walk:

```bash
jq . catalog/zte/zxa10-c300/catalog-1.0.0/results.json
jq '.oids[] | select(.status=="verified_walk") | {attribute, oid}' \
   catalog/zte/zxa10-c300/catalog-1.0.0/oids/onu.json
```
