# Hallazgos CLI y SNMP — ZTE C600 / C620 / clásicas (2026-10-09)

Fuentes: scripts de solo lectura corridos por Juan David (`verificar-olts.ts`, `recolectar-c600.ts`), lecturas/escrituras de la C620 de esta sesión y la captura del 2026-10-01/02 (otro repo, recolector de walks). Nada de esto se probó en escritura sobre la C600.

## 1. CLI

### Sintaxis por plataforma (confirmada)
| | classic (C300/C320) | C6 (C600 y C620) |
|---|---|---|
| ONU / puerto | `gpon-onu_1/1/1:1` / `gpon-olt_1/1/1` | `gpon_onu-1/1/1:1` / `gpon_olt-1/1/1` |
| versión | `show version` | `show software 1` (`show version` NO existe) |
| ONU sin autorizar | `show gpon onu uncfg` | `show pon onu uncfg` |
| fase de un puerto | `show gpon onu state gpon-olt_P` | `show gpon onu state gpon_olt-P` (y `show gpon onu state` = todas) |
- Prompt `ZXAN#`; en config `ZXAN(config)#`, `…(config-if-gpon_onu-1/1/1:17)#`, `…(config-gpon-onu-mng)#` (sin índice).
- C600 = firmware `V1.2.2_RZ` (build 2021/03/19), C620 = `V1.2.2`. Misma sintaxis C6 salvo lo marcado abajo.
- La cuenta de lectura ve `Name`/`Description` de ONU enmascarados (`********`): hay que traerlos de la BD/SmartOLT.

### C600: comandos que la OLT acepta (26 de 27 probados)
`show clock`, `show software 1`, `show card`, `show vlan summary`, `show qos traffic-profile`, `show gpon profile tcont`, `show onu-type gpon`, `show pon onu uncfg`, `show gpon onu state`; por ONU: `show running-config-interface gpon_onu-I` y `vport-P.N:1`, `show gpon onu detail-info|distance`, `show service-port interface`, `show mac interface`, `show pon onu information`, `show pon power attenuation|olt-rx|onu-rx|onu-tx`, `show gpon remote-onu equip|capability|service|sys-attr|interface eth|interface video`.
- **Rechazado:** `show gpon remote-onu wifi-info` → `%Error 140303 Invalid input`. La sintaxis correcta (ya en el código) es `wifi info` (también `ssid info`, `interface wifi`). Estas tres, corregidas, quedan por probar en C600.
- Datos de la C600 «Netmax»: 7 tarjetas (2× GFBT de 16 puertos en servicio, 2× SFUC con una STANDBY, 2× PRVR, 1× FCVDE-I); 22 VLAN (`1,10-27,35,100-101`); **0 ONU sin autorizar**; 29 tipos de ONU definidos; las ONU no tienen `hardware_model_id` en la BD.
- Escrituras en C600: **sin probar** (no hay ONU en espera); la plataforma responde 501 (`cliWrite:'none'`).
- Comparación C620 vs C600 (informe 2026-10-02): 152 comandos, 136 idénticos, 16 distintos (14 por módulos que solo tiene una).

### C620 (probado en vivo en esta sesión)
- Alta: `interface gpon_olt-P` → `onu N type T sn S`; `interface gpon_onu-I` (name/description/tcont/gemport/vport-map) ; `interface vport-P.N:1` → `service-port 1 user-vlan V vlan V ingress <PERFIL-UP> egress <PERFIL-DOWN>` (**los perfiles de velocidad viven en el service-port**, no en gpon_onu); `pon-onu-mng gpon_onu-I` → `service vlanV gemport 1 vlan V`, `veip 1`. Baja: `interface gpon_olt-P` → `no onu N`.
- Plantilla real de una ONU: `tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON`, `gemport 1 name internet tcont 1`, `vport-map 1 1 vlan V`.
- `admin enable|disable` corta/restablece; el corte se verifica con fase ≠ `working`. `write` responde `......[OK].`.
- `traffic-limit` existe, pero con perfiles `SMARTOLT-xxM` da `%Error 223981`; `real-speed gpon` da `%Error 230240` (dejó una ONU a medias en una prueba).
- Cambio de tipo (`type <t>`) pide `[yes/no]`; con `yes` falló (`222366 Modify ONU type failed`) en la prueba de 2026-10-02. `reboot` en `pon-onu-mng` pregunta `Confirm to reboot? [yes/no]:`.
- VLAN 100 = IPoE (~19 ONU), 101 = PPPoE (~260). Una ONU que no funcionaba con la 100 funcionó al pasarla a la 101.
- Lectura de diagnóstico: `show logfile brief` (comandos, ~14 h), `show logging alarm` (~48 min; líneas `A notification … occurred at <fecha> … port P onu N alarm <id> alarm|restore`). `LOSi` = pérdida de señal de esa ONU; `DyingGasp` = corte de energía. `Config state: fail` es el estado habitual en esta OLT.
- `show gpon onu detail-info` da Type, Admin state, Phase state, Config state, Online Duration; `show pon power attenuation` da `up Rx : -x.x`.

### Clásicas (C300/C320) — hallazgos de la verificación
- CLI de solo lectura OK en las 5 (versión y uncfg: 2–6 ONU sin autorizar en unas, 0 en otras).
- Padilla (C300) y las C320 por SNMP: la configuración se marca «sin guardar» tras cada SET; ahora se agenda `write` automático (10 s) — **no probado en hardware clásico**.

## 2. SNMP

### C600
- `sysDescr` = `ZXA10 C600, ZTE ZXA10 Software Version: V1.2.2_RZ`. Accesible por puerto SNMP 2161 / telnet 2123 (reenvío), no 161/1123. Índice de ONU `<ifIndex PON>.<n>` (potencias con `.1` final).
- Rama `1.3.6.1.4.1.3902.3.6000` (capturada hoy, 3705 filas en 90 s con bulk de 4): **sistema/gestión, sin datos de ONU**. `1.1.*` = modelo (`…1082.1001.600.1.1`), MAC, versiones, fechas de build, nombre del `.set`, rutas de disco, uptime; `5.3.1`, `52.1.4`, `101.4.1`, `160.2.1`, `204.1.1`, `500.1.1`, `500.2.4`, `500.2.9`, `503/504`, `511.2.1`: contadores y tablas de estado (mayoría 0/INTEGER pequeños).
- Rama `1.3.6.1.4.1.3902.1082.70`: **enorme y lenta**; en 10 min llegó a `…82.2.2.1.48.<a>.<b>` (tabla por ONU/servicio). Sin capturar aún: el script ya guarda página a página y reanuda con `--start-after`.
- Huecos de la captura anterior: `3.6000` (cerrado hoy) y `1082.70` (pendiente).

### Comportamiento SNMP observado en clásicas (verificación de hoy)
- Lectura de puertos PON: 41–78 s por OLT; ONU en modo light: 2–64 s.
- Páginas que no responden (`Request timed out` / `GeneralError`) con 10 filas → se reintenta con 5: columnas `1012.3.50.11.2.1.8`, `1012.3.50.12.1.1.10` y `…1.14`. Una respuesta de 2922 B superó el límite de fragmentación de 1300 B de GCP (aviso de `watchResponseSize`).
- Referencias previas (otro repo/memoria): columna `1082.500.20.2.1.25` responde a ~3 s por fila; `3.305` = bitácora de comandos de la OLT; `3.302` = hojas de alarmas; tarjetas de la C300 en `1082.10.1.2.4`; salud de chasis en `1082.10`; en C620 los puertos PON salen de IF-MIB (`ifOperStatus`+`ifType`+`ifName`), la VLAN se recorre con páginas de 4 filas (respuesta de 20 filas ≈ 2216 B se pierde en GCP) y el catálogo de velocidades se lee en lotes de 16.

### Seguridad (hallazgos, equipo de seguridad)
- **La community de lectura de la C600 permite leer la tabla de usuarios** (`3902.3.6000.51.2.1`): usuarios `smartoltusr` y `zte` con su contraseña codificada (`*21*…`, reversible). Rotar contraseñas y restringir la vista SNMP RO para excluir `3902.3.6000`.
- **El HTTP de la C600 es alcanzable desde internet**: el registro `51.2.3` guarda una petición `GET / HTTP/1.1` de un escáner (`Infrawatch/1.0`). Cerrar o filtrar el servicio web.
- La clave de la OLT C620 sigue pegada en chat/historial: rotarla.

## 3. Datos operativos que afectan al código
- Dos pares de OLT en la BD apuntan al mismo equipo (misma IP:puertos, distinta empresa): PruebaCasa↔PRIMAVERA y padilla↔«Prueba primer cliente». El usuario decidió borrar «OLT PruebaCasa» y «Prueba primer cliente» (0 ONU con cliente) por el flujo escalonado (7 días de gracia).
- «Último contacto» y «sin guardar» salían ~5 h de menos por el desfase MySQL(UTC)↔Node(Bogotá); el script ya calcula en MySQL.
- 116 ONU en la BD no aparecen en el equipo (1 COMFENALCO, 48 Net max, 14 PruebaCasa, 39 Unete Popular, 14 PRIMAVERA): informar, nunca retirar solas.

## 4. Pendiente
Capturar `1082.70` completa; probar `wifi info`/`ssid info`/`interface wifi` en C600; sintaxis de escritura de la C600 (ONU en espera + ciclo alta/borrado); `traffic-limit` aceptado; `write` automático en clásicas; sintaxis CLI de apagar ONU en clásicas (Padilla).

Archivos: `network-api/scripts/{verificar-olts,recolectar-c600}.ts`; salida cruda (con seriales/MAC, no subir) en `network-api/recoleccion-c600-*/`; fixtures C600 anonimizadas en `network-api/tests/fixtures/zte-c620/c600-20261002/`.
