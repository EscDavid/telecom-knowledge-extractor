# Verificación de comandos CLI — ZXA10 C620 y C600 (2026-10-02)

Solo lecturas (`show`) y **ayuda con `?`**. No se ejecutó ningún comando de configuración.
Ambas OLT son de producción; en modo config solo se entró a sub-modos (sin Enter sobre ningún
comando de escritura) con la ONU sin datos `1/1/1:17` (C620) y `1/1/1:34` (C600).
Guardas del script: `scripts/telnet_help_probe.py` rechaza antes de conectar cualquier línea que no
sea `show …`, entrada de sub-modo, `end`/`exit` o termine en `?`.

Evidencia cruda (con seriales; en `.gitignore`): `docs/walks/diagnostics/ZTE_C620_cli_reads_*.txt`
y `ZTE_C600_cli_reads_*.txt`. 152 comandos comparados entre las dos OLT: **136 idénticos, 16
distintos** (14 son de módulos presentes solo en una de las dos; las diferencias de sintaxis
reales están al final).

- C620: `ZXA10 C620`, Software V1.2.2 · C600: `ZXA10 C600`, Software V1.2.2_RZ.
- Prompt `ZXAN#`. En config: `ZXAN(config)#`, `ZXAN(config-if-gpon_olt-1/1/5)#`,
  `ZXAN(config-if-gpon_onu-1/1/1:17)#`, `ZXAN(config-if-vport-1/1/1.17:1)#`,
  `ZXAN(config-gpon-onu-mng)#` (**sin índice**), `ZXAN(config-gpon)#`, `ZXAN(config-pon)#`.


## Contexto de la conversación (resumen para quien retome este trabajo)

**Objetivo.** Preparar el catálogo de OIDs y el conocimiento de la CLI de dos OLT ZTE de la familia C6xx para que un
importador (repositorio `network-api`, aparte de este) pueda leerlas y, más adelante, aprovisionarlas: una **ZXA10 C620**
(prioridad del usuario, OLT "COMFENALCO") y una **ZXA10 C600** ("MARROQUIN"). Ambas son de **producción**.

**Cronología (2026-10-01 y 2026-10-02).**
1. *Walks SNMP.* Con el recolector `src.walk_collector` se capturaron la rama `3902`, `ifTable`/`ifName` y, después, `system` e
   `ifXTable` de las dos OLT. Hubo que resolver trampas operativas: puerto SNMP (UDP 161/2161; el 1123/2123 es Telnet), una
   columna que responde a 3 s por fila (`…1082.500.20.2.1.25`), lotes de bulk que agotan la memoria del agente, `--max-runtime`
   acumulativo y el límite de 2 h de los procesos en segundo plano. Quedan huecos conocidos (`3.6000`, `1082.70`).
2. *Comparación y catálogo.* Se comparó C620 vs C600 (≈99 % de estructura idéntica) y C600 nueva vs la de julio; se identificaron
   ramas con los MIB de `docs/zte/`; se vio que las hojas de alarmas (`3.302`) se habían **podado por falta de walk**, no por un
   fallo del extractor. Se regeneraron los catálogos (C600 y C620, 1.1.0) con documentos de validación `docs/validation/community/`
   (serial, tipo, nombre, descripción, estado con su enum, potencias Rx/**Tx**, distancia, historial de altas/bajas, contadores
   IF-MIB y `system`), todos contrastados contra la CLI. La carga a la DB la hace el usuario (`python -m src.loader load …`).
3. *CLI por Telnet.* Primero lecturas `show`; después ayuda `?` (sin ejecutar) en modo exec y modo config; luego plantilla real de
   aprovisionamiento leída de 52 ONU configuradas. Se descubrió que **la ayuda no es exhaustiva** (`traffic-profile` funciona y no
   aparece) y que la rama SNMP `3902.3.305` es la **bitácora de comandos** de la OLT, de donde salieron los comandos reales de
   SmartOLT para crear/borrar perfiles de velocidad.
4. *Escrituras de prueba (autorizadas por el usuario, con rollback).* Perfil `TKCTEST-DEL` (creado y borrado por mí); ciclo de ONU
   en espera ejecutado por el usuario con scripts míos: alta, aprovisionamiento completo, relectura y `no onu N` (3 corridas),
   y diálogo de `reboot`. El índice 250 no registra en GPON; con el índice 3 la ONU llega a `syncMib` pero oscila y no alcanza `working`.

**Restricciones y decisiones.**
- No se ejecutó `write`, ni se modificó ningún perfil o ONU de cliente. Todo cambio de prueba se deshizo y se verificó.
- El clasificador de seguridad de Claude Code **bloqueó** dos ejecuciones mías (escritura sobre un perfil existente y el ciclo de ONU);
  por eso el ciclo lo corrió el usuario con los scripts `scripts/c620_onu_lifecycle_test.py` y `scripts/c620_onu_write_battery_test.py`.
- La carga a la DB (`ispm_tkc`) requiere credenciales de superadmin; no se piden por el chat.
- Credenciales y comunidades SNMP compartidas durante la sesión **no se guardaron en el proyecto**, pero quedaron visibles en la
  conversación: **conviene rotarlas** (Telnet y comunidades de lectura/escritura de ambas OLT).
- Los walks y las capturas con seriales y nombres de abonados están en `.gitignore` (`docs/walks/*C6*`, `diagnostics`, `staging/`).

**Entregables en el repositorio.** Catálogos `catalog/zte/zxa10-c600|c620/catalog-1.1.0`; documentos `docs/validation/community/
snmp-olt-zte_c600_onu.txt`, `…_c620_onu.txt`, `…_c6xx_onu_events.txt`, `…_c6xx_std_mib.txt`; informes `reports/alarm_mib_gap_c600_c620.json`
y este archivo; scripts `scripts/telnet_read_probe.py`, `telnet_help_probe.py`, `c620_onu_lifecycle_test.py`, `c620_onu_write_battery_test.py`;
evidencia cruda (con datos personales) en `docs/walks/diagnostics/` y `staging/`; notas de memoria del proyecto.

**Pendiente.** (C620 cerrada: secciones Q–Y; `write` y `reboot` en línea ya probados.) Residuales sin impacto (`portid`, `no vport-map`, `domain`, `video_0/1`, `splitter`); efecto de `reboot` en una ONU en línea (decisión del
usuario); misma ronda de escrituras en la C600 (no tiene ONU en espera); recapturar C300/C320 (sus catálogos siguen sin la rama `3.*`);
subir a la DB la última versión de los catálogos; y el trabajo del importador en `network-api` (función única de plataforma, mapa de lecturas,
parsers con fixtures anonimizadas).

---

## Registro de avances (se actualiza con cada resultado analizado)
| # | Resultado analizado | Avance | Sección |
|---|---|---|---|
| 1 | Sondas de lectura y ayuda en C620/C600 | Sintaxis de lectura y ayuda idéntica en ambas; equivalentes de los comandos rechazados | A–E |
| 2 | Plantilla real (52 ONU) + ayuda del último nivel | Plantilla de aprovisionamiento y sintaxis de escritura completas | F–I |
| 3 | Bitácora SNMP `3.305` tras crear/borrar perfil en SmartOLT | Comandos `traffic-profile`/`profile tcont` (la ayuda `?` no es exhaustiva); creación y borrado probados | J–K |
| 4 | Matriz verificado/faltante | Lista de pendientes por modelo | L |
| 5 | Ciclo de ONU, índice 250 | Aprovisionamiento y rollback OK; el índice 250 no registra | M |
| 6 | Ciclo de ONU, índice 3 (dos ONU) | Aprovisionamiento relleído idéntico y rollback OK; la ONU oscila sin llegar a `working` | N–O |
| 7 | Diálogo de `reboot` | Texto `Confirm to reboot? [yes/no]:`; `no` cancela, `yes` silencioso | P |
| 8 | Batería 1 de escrituras | 25/28 comandos OK (T-CONT/GEM extra, admin, eth, security-mgmt, dhcp-ip, video, `profile tcont`) | Q |
| 9 | Batería 2, primera ejecución | Tipos de ONU crear/borrar OK; el script se cortó por un fallo mío (corregido) | R |
| 10 | Batería 2 completa | T-CONT tipos 1–4, `vlan port … mode tag` y `wan-ip … vlan-profile` OK; pendientes: `vlan … vlan`, `ping-response host`, cambio de tipo/WiFi | S |
| 11 | Batería 2, segunda corrida | `vlan port … mode tag vlan 101` OK; `type <tipo>` pide confirmación `[yes/no]` (el script no contestó); `ping-response enable` exige `traceroute-response`; WiFi sigue sin UNI | T |
| 12 | Batería 2, tercera corrida | Cambio de tipo con `yes` falla (`222366 Modify ONU type failed`); `ping-response` es válido pero exige un `wan-ip` previo; WiFi sigue sin UNI. Siguiente: alta directa con el tipo que tiene `wifi_0/1` | U |
| 13 | Batería 2, cuarta corrida (alta con tipo WiFi) | **Todo OK**: WiFi/SSID, `wan-ip`+`ping-response`, `vlan port … mode tag vlan`; el WiFi exige que la ONU se dé de alta con un tipo que tenga `wifi_0/1` | V |
| 14 | Batería final (87 comandos) + `write` | 63 OK / 24 ERR; `write` OK con la config idéntica; hallado el comando de perfiles de límite de tasa (`gpon` → `onu profile traffic`); causas de casi todos los ERR | W |
| 15 | Ronda 2 (sintaxis corregida) | Perfil `onu profile traffic` crear/leer/usar/borrar OK; `gemport/switchport traffic-limit` OK; `tcont name … profile`, `arc … arc-interval`, `blacklist sn` OK; 4 ERR residuales sin impacto operativo | X |
| 16 | Ronda 2 + reinicio de ONU en línea (`1/1/5:1`) | `reboot` en línea verificado: `working` → `LOS` (~30 s) → `syncMib` → `working`, ~53 s de corte; ronda 2 idéntica a la anterior | Y |
| 17 | Catálogo de comandos y SNMP de la C620 | 74 comandos verificados en el catálogo (72 verified + 2 documented), +6 OIDs de perfiles de velocidad; hook `docs/validation/commands/` en el validador | Z |
| 18 | Revisión del importador (network-api) contra nuestros datos | Respuesta punto por punto con evidencia (VLAN, tarjetas, uplinks, perfil por ONU, índice, sysObjectID, huecos del walk); nuevo doc `snmp-olt-zte_c6xx_onu_profiles.txt`; carga a DB: C620 subida, C600 pendiente | AA |
| 19 | Carga a la DB de la C620 | `loader load zxa10-c620`: 13 entidades, 74 comandos, 1.772 OIDs, 7 relaciones, 117 alarmas, tier 4, `catalog_version_id=10`; C600 pendiente de recarga | AB |
| 20 | Plan del importador (otro agente) vs TKC | Faltaban del lado TKC: errores/prompts, recetas de aprovisionamiento y límites; generados (`zte_c6xx_cli_behavior.json`, `zte_c6xx_provisioning_recipes.json`); pendientes: fixtures anonimizadas y rango real de ONU | AC |
| 21 | Fixtures anonimizadas (`docs/fixtures/zte-real/c620-20261002`, `c600-20261002`) | 34/38 salidas CLI + 20 SNMP por modelo, `ground_truth.json`, 0 fugas de serial, OID íntegros | AD |
| 22 | Informe del agente de scripts residuales | Causas de los 5 residuales identificadas con la ayuda `?`; script `c620_pending_cli_test.py` listo (sin ejecutar) | AE |
| 23 | Script del rango real de ONU por puerto | `scripts/c620_onu_range_test.py` listo (sin ejecutar): prueba índices 64–256 con la ONU de prueba y rollback por índice | AF |
| 24 | Script de residuales (secciones 2–5), primera ejecución | CATV = `rf_0/1` confirmado (video_0/1, video-ani_0/1 y catv_0/1 rechazados incluso en un tipo mínimo); `show onu-type-if` verificado; secciones 2, 3 y 5 NO se ejecutaron (alta rechazada `222320 sn already exists` por solaparse con el script del rango) | AG |
| 25 | Script de residuales (secciones 2,3,5), segunda ejecución | Otra vez solapado con el script del rango (ONU de prueba autorizada en el índice 128): `222320`; sin información nueva; rollback OK, config idéntica. Parcial del rango en curso: 64, 96 y 127 registran | AH |
| 26 | Rango real de ONU por puerto (script del rango, ejecutado por el usuario) | **Registran los índices 1–128**; 129, 130, 192, 255 y 256 se autorizan sin error pero no registran; rollback OK, config idéntica | AI |
| 27 | Residuales (secciones 2, 3 y 5) | `no vport-map` = `<v> <g> vlan <V>`; `wifi enable` = work-mode → domain → channel (`bra` solo con 802.11b); `splitter` = niveles numéricos `1-2-3`; 4 de los 5 residuales cerrados (queda `portid`, que exige `resource mode2`) | AJ |
| 28 | Prueba de `gemport … portid` en un puerto vacío | Script `c620_gemport_portid_test.py` listo (sin ejecutar): `resource mode2` en un puerto PON sin ONU (1/1/4, 1/1/13, 1/1/15 y 1/1/16 están vacíos) | AK |
| 29 | `gemport … portid` con `resource mode2` en un puerto vacío (1/1/16) | `resource mode2` se acepta y se revierte limpio; `portid 300`/`allocid 300` → fuera de rango (230405/230404); en mode2 la config muestra los ids (1024); no es necesario para provisionar | AL |
| 30 | VLAN por SNMP en C620 (Q-BRIDGE vs. tabla de service-port ZTE) | Q-BRIDGE no sirve (bitmaps vacíos, dot1dBasePortIfIndex solo 9 puertos); VLAN por ONU en `…1082.110.5.2.2.1.8` (BeginVid) y `.18` (Vlan): coincide 26/26 con CLI `service-port … user-vlan V vlan V`; VLAN→uplink solo por CLI `show vlan <id>` | AM |
| 31 | Repetición de gemport/tcont `portid`/`allocid` 1025/1026 en mode2 (1/1/16) | Con ids ≥1024 se aceptan (OK); 300 → 230405/230404; en mode2 la config muestra `resource-id-assign-mode mode2` y asigna `allocid 1024`/`portid 1024` al primer tcont/gemport; rollback limpio, config del puerto idéntica | AN |
| 32 | `splitter` valor guardado y cambio de tipo (`type`) a tipo equivalente (C620, ONU 1/1/5:3 de prueba) | `splitter 1-2-3` se guarda literal (detail-info `Splitter: 1-2-3` y config `splitter 1-2-3`); `no splitter` lo borra. `type ZTE-F600` pide [yes/no] y con `yes` falla 222366 incluso a un tipo equivalente y con la ONU nunca en línea: el tipo no cambia; la vía es `no onu` + alta de nuevo. Rollback limpio | AO |
| 33 | Revisión exhaustiva del catálogo C620 1.1.0 | 9 errores (escala tensión óptica, firmware 2.0/2.1 vs 1.2.2, 43 nombres UNRESOLVED, onu_id_append en escalares…) y 12 mejoras (293 subárboles del walk sin catalogar, uplink_port sin OID, atributos de entidad vacíos…) | ver `reports/catalog_review_c620_2026-10-02.md` |
| 34 | Correcciones y mejoras del catálogo C620/C600 (módulo `src/walk_validator/refinements.py`) | 0 ids quitados o renombrados; +16 OID uplink_port, +3 entidades de perfiles, +4 alarmas de ONU, relaciones con orden verificado, escalas/unidades corregidas, firmware 1.2.2, comandos con parámetros/relacionados/prerrequisitos | AP |
| 35 | Decisión del importador: tipos de ONU de la C620 (capacidad `onuTypesByCli`) | No la crea por ahora; los tipos son solo CLI (`show onu-type`, `show onu-type-if`); el TKC no cambia nada | — |
| 36 | Walks residuales de la C600 (ejecutado por el usuario) | Columnas 26-29 de `1082.500.20.2.1` no existen (el siguiente OID es la columna 30); tabla inspector `3.6000.51.2.3.7` completa (3000 filas, +2168 nuevas) y perfiles `1082.70.67.2.3.1` completos (1330 filas, +378 nuevas); anexadas a `docs/walks/ZTE_C600.txt` y catálogo C600 regenerado | AQ |
| 37 | Análisis de `reports/hallazgos-cli-snmp-zte-2026-10-09.md` (sesión del importador) | Coincide con lo verificado; nuevos `show logfile brief` y `show logging alarm` (verificados en la C620 hoy); error 230240 de `real-speed gpon`; hallazgo de seguridad: la tabla de usuarios SNMP `3902.3.6000.51.2.1` está en nuestros walks (redacción activada para futuros walks) | AR |
| 38 | Walks residuales de la C620 (inspector y perfiles por defecto) | Inspector 3016 filas (4 columnas × 754) y perfiles 1330 filas (7 columnas × 190), completos; +2558 filas nuevas anexadas a `docs/walks/ZTE_C620.txt`; catálogos regenerados con `show logfile brief` y `show logging alarm` (C620: 78 comandos) | AS |
| 39 | Enlace OID ↔ comandos CLI | 21 campos de salida de 7 comandos apuntan a su OID (`oid_ref`, `oid_status: mapped`) y 17 OID llevan `command_ref`; sin referencias huérfanas; resto de campos = solo CLI | AT |
| 40 | Clasificación de los 625 OID `documented` contra el walk | Ninguno tiene filas en el walk: 311 nodos estructurales, 287 objetos de configuración de tablas vacías, 10 notificaciones y 17 columnas que faltan en tablas con filas (posiblemente no soportadas en 1.2.2); anotados en `pending_validation`, estado sin cambios | AU |
| 41 | GETNEXT de las 17 columnas ausentes en tablas con filas (C620, solo lectura) | Las 17 no están expuestas por el equipo (V1.2.2): categoría `not_exposed` en la C620; en la C600 siguen `absent_in_populated_table` hasta comprobarlas | AV |
| 42 | Comprobaciones opcionales en la C600 (ejecutado por el usuario) | Las 17 columnas tampoco están expuestas (`not_exposed`); `ssid info` no aparece en la ayuda de `show gpon remote-onu` (consistente con el catálogo); `show logfile brief` y `show logging alarm` se aceptan → verified en C600 (76 comandos) | AW |
| 43 | Tabla SNMP de ONU sin autorizar en C620 (corrige «solo CLI») | `1082.500.2.2.11.2.1.<col>.<ifIndexPON>.<n>`: serial (2), PW (3), modelo (8), firmware (10), primer/último hallazgo (12/13); coincide con `show pon onu uncfg` (seriales, modelos, horas); 6 OID nuevos `uncfg_onu_*` + fixture | AX |
| 44 | Publicación 1.2.0, comparador de versiones y puerta de contrato | Catálogos C620/C600 pasan a `catalog-1.2.0` (config `walk_validator.release_versions`); `scripts/catalog_diff.py`, `scripts/catalog_contract_check.py` (18 526 comprobaciones, 0 fallos) y `docs/validation/consumer_contract.json`; el loader ejecuta la puerta antes de cargar; `docs/CHANGELOG_catalog.md`; el diff detectó que las 4 alarmas de ONU no se estaban escribiendo (corregido) | AY |
| 45 | Fallos de carga a `ispm_tkc` y su corrección | (1) bloqueo 1205 por un segundo loader abierto; (2) 1644 por caducar la sesión efímera de 5 min → el loader renueva la sesión cada 200 inserciones; (3) 1265 `alarm_type` por mis alarmas de ONU con tipo `equipment`/severidad `info` fuera de los ENUM → corregidas y la puerta valida ahora ENUM y longitudes de VARCHAR contra `database/ispm_tkc.sql`; enum de estado C600 con LOS=2; `sensitivity: pii` en nombre/descripción de ONU | AZ |
| 46 | Carga de la 1.2.0 a `ispm_tkc` (ejecutada por el usuario) | C620 (catalog_version_id 13): 16 entidades, 78 comandos, 1794 OID, 9 relaciones, 121 alarmas. C600 (id 14): 16, 76, 1788, 9, 121. Puerta de contrato: 9358 y 9266 comprobaciones, 0 fallos | BA |
| 47 | Análisis de los 4 catálogos contra el diagnóstico del consumidor | 17 hallazgos contrastados: 10 confirmados, 3 parciales, 1 no reproducido; el signo de 16 bits de la potencia óptica se confirmó por CLI en la C620 (raw 63547 → −33,978 dBm); 7 hallazgos propios (receta CBS=rate/80, alarmas históricas, atributos de uplink repetidos, errores solo en el doc de comportamiento, clásicas sin refinamientos…) | BB |
| 48 | Catálogos C620/C600 1.3.0 (correcciones del análisis contra el diagnóstico del consumidor) | +1 OID (alias `onu_type`), 0 ids quitados; atributos de uplink con prefijo `uplink_`; potencia con `signed_bits`/`sentinels`/rango; `errors[]` en comandos; `kind: historical` en alarmas; `enumeration_meta` en `onu_status`; manifiesto coherente; receta CBS=CIR/80; contrato de C600 de 6 a 14 atributos; puerta 18 841 comprobaciones, 0 fallos | BC |
| 49 | Reanálisis final previo a la carga de la 1.3.0 | Hallazgo crítico: `results.json` (1.1.0, 1.2.0 y la 1.3.0 sin corregir) codificaba 4 nombres de comunidad SNMP por OLT (incluida la de escritura) y 2 cuentas; ya redactado en 1.3.0 (7701 y 9490 hallazgos), con regla en la puerta; ensayo de carga completo (`scripts/loader_dry_run.py`): 11 895 y 13 649 filas caben en el esquema; 18 843 comprobaciones, 0 fallos; 119 pruebas; script `purge_sensitive_results.py` para limpiar 1.1.0/1.2.0 en la base | BD |
| 50 | Carga de la 1.3.0 y purga de resultados sensibles (ejecutadas por el usuario; verificadas en solo lectura) | C620 1.3.0 (id 15) y C600 1.3.0 (id 16) cargadas y `SIN CAMBIOS`; 0 hallazgos sensibles en `tkc_results` de las 10 versiones de catálogo (incl. 1.1.0 y 1.2.0 ya depuradas) | BE |
| 51 | Catálogo 1.2.0 de las clásicas (C320 y C300) y hallazgo de seguridad en la rama `1082.20.5.2.1` | 10 OID community sin filas → `documented`, potencia con signo, unidades, 26 nombres, pii, 18 comandos de la semilla degradados, 3 lecturas `observed`; puerta C300/C320 con fixtures; cadenas probables de comunidades SNMP en walks, DB e historial git (C300) | BF |
| 52 | Carga de la 1.2.0 de C320 y C300 y purga (ejecutadas por el usuario; verificadas en solo lectura) | C320 1.2.0 (id 17) y C300 1.2.0 (id 18) en T4, SIN CAMBIOS y vigentes; versiones antiguas limpias; solo queda el marcador `sensitive_branch_redacted` (sin cadenas) | BG |
| 53 | Contexto de la conversación (aprovisionamiento C620/C600, qué falta para la C320, purga vs recarga) y pendiente de la C320 | Estado comparado C620/C600; plan de la C320 en 3 pasos (lecturas CLI, escritura con rollback, huecos del walk) | BH |
| 54 | Sonda de solo lectura para la C320 preparada (`scripts/c320_readonly_probe.py`), no ejecutada | Lista cerrada (`show`, `terminal length 0`, ayuda `?`), prompt oculto, salida con datos de ONU fuera de git, resumen sin datos sensibles; paso 1 del plan de la C320 | BI |

**Regla de trabajo:** cada vez que se analice un resultado nuevo se añade aquí una fila y su sección de detalle.

---
## A. Lecturas rechazadas por la clásica → equivalente encontrado

| Comando clásico | Equivalente en C620 y C600 | Estado |
|---|---|---|
| `show gpon onu uncfg [gpon-olt_X]` | `show pon onu uncfg [gpon_olt-1/1/5]` (acepta puerto y filtros `model`, `pw`, `mac`, `first-find-time`…) | ✔ ambas |
| `show running-config interface gpon-onu_X` | `show running-config-interface gpon_onu-<idx>` | ✔ ambas |
| `show running-config interface gpon-olt_X` (ONUs ocupadas) | `show running-config-interface gpon_olt-<pon>` → líneas `onu N type T sn SN` (igual que la clásica) | ✔ ambas |
| `show onu running config …` | No existe: `show onu` es **ambiguo** (`show onu-type`, `show onu-compat`). El bloque `pon-onu-mng` sale dentro de `show running-config-interface gpon_onu-<idx>` (verificado con 26 ONU configuradas por OLT; corrige una lectura mía anterior que decía "parcial") | ✔ ambas |
| `show gpon profile traffic` | No existe (`show gpon profile ?` solo da `tcont`). **Los planes de velocidad están en `show qos traffic-profile [name <X>]`** (lista de nombres y, por nombre, CIR/PIR en kbps). `show gpon onu profile traffic` existe pero está vacío | ✔ ambas |
| `show mac gpon onu <tok>` | `show mac interface gpon_onu-<idx>` o `show mac interface vport-<pon>.<n>:1` → MAC, VLAN, tipo, vport. (`show mac table interface …` NO existe; `show gpon remote-onu mac <tok>` da "Incomplete command") | ✔ ambas |
| `show running-config pon-onu-mng …` | No existe; ver fila anterior. El service-port se lee con `show running-config-interface vport-<pon>.<n>:1` | ✔ ambas |
| `show gpon remote-onu traffic-limit <tok>` | No existe. El límite de tasa se configura (no se lee) con `switchport ethuni eth_0/N traffic-limit` / `gemport traffic-limit` en `pon-onu-mng` | ✔ (sin lectura) |
| `show version` | `show software 1` (versión, imagen, uptime del sistema y paquetes por slot). C620: slots `<1-7>`; C600: `<1-21>` | ✔ ambas |

Lecturas nuevas útiles, probadas en ambas: `show gpon onu distance <tok>`, `show pon power
onu-rx|onu-tx|olt-rx <tok>` (`olt-tx` no existe por ONU), `show pon onu information <tok>`,
`show gpon remote-onu service|sys-attr <tok>`, `show gpon onu baseinfo gpon_olt-<pon>`.

## B. Lecturas con salida vacía
- `show gpon remote-onu interface wifi` / `ssid info`, 26 ONU de 31 modelos distintos en la C620:
  **todas** devuelven "No related information". `wifi info` sí devuelve datos (`Admin status`).
- **C600**: `show gpon remote-onu ssid info` **no existe** (Invalid input), confirmando la doc.
  `show gpon remote-onu interface wifi` devuelve datos en 15 de 26 ONU (`wifi_0/1`, `wifi_0/2`,
  `Admin status`, `ARC`). Primera evidencia real de WiFi en C600.

## C. Lecturas confirmadas: formato idéntico entre C620 y C600
`detail-info`, `remote-onu equip|capability|interface eth|video`, `service-port interface`,
`gpon onu by sn`, `gpon onu state`, `onu-type` (+ `onu-type gpon`), `gpon profile tcont`,
`pon onu uncfg`: misma estructura de salida en las dos OLT (136/152 comandos idénticos).
`detail-info` trae además el historial de las últimas 10 altas/bajas (`Authpass Time`,
`OfflineTime`, `Cause`) y `ONU Distance`; `Name` y `Description` salen como `********`
(la OLT los enmascara para esta cuenta). Los parsers hay que compararlos contra estas salidas
crudas (no se revisó el código del importador).

## D. Sintaxis de escritura descubierta con `?` (NO ejecutada)

| Función (clásica) | C620 y C600 |
|---|---|
| Entrar a modo | `configure terminal` · `interface gpon_olt-<pon>` · `interface gpon_onu-<idx>` · `interface vport-<pon>.<n>:<v>` · `pon-onu-mng gpon_onu-<idx>` · `gpon` · `pon` · `end`/`exit` |
| Alta de ONU | En `interface gpon_olt-X`: `onu <1-256> type <TIPO> {sn\|sn+pw\|loid\|loid+loidpw\|…} <valor>` — **igual que la clásica** |
| Baja de ONU | En `interface gpon_olt-X`: `no onu <1-256>` |
| Nombre / descripción | En `interface gpon_onu-X`: `name <WORD>`, `description <WORD>` |
| T-CONT y GEM | En `interface gpon_onu-X`: `tcont <1-255> profile <WORD>` (también `allocid`, `gap`, `name`); `gemport <1-255> tcont <N> [queue …]` (también `name`, `portid`) |
| Service-port | **Cambia.** Ya no está en la interfaz de la ONU: `vport <1-128> map-type {vlan\|1:1\|cos\|cos+vlan}` en `gpon_onu-X`, y `service-port <1-128> user-vlan {<1-4094>\|untagged} …` dentro de `interface vport-<pon>.<n>:<v>` (opciones: `description disable enable expand multi-cos other-all user-begin-vlan`) |
| Perfil de bajada | `gemport traffic-limit <1-255> …` y `gemport down-queue <1-255> …` dentro de `pon-onu-mng` (sintaxis completa sin descubrir) |
| Bloque `pon-onu-mng` | **Cambia.** `flow`, `flow mode`, `switchport-bind`, `vlan-filter-mode`, `vlan-filter`, `ip-host` **no existen**. Equivalentes: `service <nombre> gemport <1-255> {vlan V\|untag\|cos\|ethuni\|veip}`, `switchport {ethuni <if>\|veip <1-255>} …`, `vlan {port <if>\|gemport <n>\|gemport-mcast} …`, `veip <1-255> {inter-domain\|port\|state}`, `wan-ip <1-255> {ipv4\|ipv6} {mode\|ping-response}`, `dhcp-ip ethuni <if> {forbidden\|from-internet\|from-onu\|no-ctrl}`, `security-mgmt <1-255> {ingress-type\|mode\|protocol\|start-src-ip\|state}` |
| CATV | `interface video video_0/<n> {arc\|power-control\|state}` |
| Ethernet | `interface eth eth_0/<n> {arc\|l2l3\|loop\|mtu\|pause-time\|power-control\|pppoe-filter\|speed\|state\|type\|wiring}` |
| WiFi | `interface wifi wifi_0/<n> {arc\|state}` en ambas. **Solo C620**: `wifi {enable\|disable\|5g}` y `ssid ctrl wifi_0/<n> {name\|hide\|max-users\|user-isolation}` y `ssid auth`. En C600 no existen `ssid` ni `wifi`. |
| Límite de tasa | `switchport ethuni eth_0/<n> traffic-limit …` (C620). En C600 no hay `traffic-limit` propio |
| Perfiles en la OLT | Modo `gpon`: `profile tcont …` (único). No hay `profile traffic` |
| Tipos de ONU | Modo `pon`: `onu-type <WORD> …` y `onu-type-if …` |
| Reinicio | `reboot` (`<cr>`) dentro de `pon-onu-mng` |
| Guardar | `write` no se probó (no es ayuda de modo config ni lectura) |

Esta tabla se completó con el último nivel de ayuda: ver las secciones F y G más abajo.
Ejecutar cualquier plantilla requiere una ONU de prueba y una OLT que no sea de producción.

## E. Otros
- `show vlan [<id>]`: ✔ ambas (`show vlan summary` lista los VLAN creados; `show vlan 100` da el detalle).
- `terminal length 0`: ✔ **apaga el paginador** en la C620 (la misma salida de 218 líneas sin `--More--`; antes se cortaba a 25 líneas con `--More--`). Se acepta sin salida.
- `show clock`: ✔ (prueba de conexión).
- Prompt del sub-modo `pon-onu-mng`: `ZXAN(config-gpon-onu-mng)#` (sin índice), como indica la doc. Los demás sub-modos sí llevan el índice.


## F. Plantilla real de aprovisionamiento (leída de 26 ONU configuradas por OLT, 52 en total)
Todas siguen la misma plantilla (salida de `show running-config-interface gpon_onu-<idx>` y
`… vport-<pon>.<n>:1`). Es la que hay que reproducir al escribir:

```
interface gpon_olt-<pon>
  onu <N> type <TIPO> sn <SERIAL>
interface gpon_onu-<idx>
  real-speed gpon
  name <txt>
  description <txt>
  vport-mode manual
  tcont 1 profile <PERFIL_TCONT>
  gemport 1 name <nombre> tcont 1
  vport 1 map-type vlan
  vport-map 1 1 vlan <V>            (una línea por VLAN; en 17 ONU hay dos, p. ej. 100 y 101)
pon-onu-mng gpon_onu-<idx>
  service vlan<V> gemport 1 vlan <V>
  veip 1
interface vport-<pon>.<n>:1
  service-port 1 user-vlan <V> vlan <V> ingress <PERFIL_UP> egress <PERFIL_DOWN>
```
- Los perfiles de velocidad son nombres de `show qos traffic-profile` (`SMARTOLT-<vel>-UP` / `-DOWN`:
  1G, 50M, 100M…500M, más `VOIPMNG-10M` e `IPTV-50M-DOWN`); `show qos traffic-profile name <X>` da
  CIR y PIR en kbps (p. ej. 200M = 209664 kbps). El T-CONT es de `show gpon profile tcont`.
- CATV (4 ONU de la C600): `interface video video_0/1 state lock` e `interface video-ani state lock`
  (+ `interface video-ani optical-thresh lower -9.5 upper 2.5` en 1 ONU de cada OLT) en `pon-onu-mng`.
- **No existen** en la plantilla real `flow …`, `switchport-bind`, `vlan-filter*` ni `ip-host`.

## G. Último nivel de ayuda de las escrituras (solo `?`; idéntico en C620 y C600, 62 de 62)

| Función | Sintaxis completa descubierta |
|---|---|
| Alta de ONU | `interface gpon_olt-<pon>` → `onu <1-256> type <TIPO> {sn\|sn+pw\|sn+hpw\|sn+rid\|sn+hrid\|pw\|hpw\|rid\|hrid\|loid\|loid+loidpw\|loid+loidhpw\|psk} <valor>` |
| Baja | `no onu <1-256>` (modo `gpon_olt-`) |
| Nombre / desc. | `name <WORD>`, `description <WORD>` (modo `gpon_onu-`) |
| T-CONT | `tcont <1-255> profile <WORD>` (también `allocid`, `gap`, `name`); quitar: `no tcont` |
| GEM | `gemport <1-255> name <WORD> tcont <1-255> [queue …]` (también `portid`); quitar: `no gemport` |
| Vport | `vport-mode {gemport\|manual}`, `vport <1-128> map-type {vlan\|1:1\|cos\|cos+vlan}`, `vport-map <v> <gem> vlan {<1-4094>\|untag} [cos …]`; quitar: `no vport`, `no vport-map` |
| Service-port | modo `interface vport-<pon>.<n>:<v>`: `service-port <1-128> user-vlan {<1-4094>\|untagged} vlan <1-4094> [user-priority\|user-etype\|user-svlan …] [ingress <PERFIL> [egress <PERFIL>]] [car-threshold …] [new-cos\|svlan …]`; quitar: `no service-port <1-128>` |
| Velocidad (CPE/gem) | en `pon-onu-mng`: `gemport traffic-limit <1-255> {upstream\|downstream} <PERFIL>`; en puerto Ethernet: `switchport ethuni eth_0/<n> traffic-limit {in\|out} …` |
| Bloque de servicio | `service <nombre> gemport <1-255> {vlan <V>\|untag\|cos …\|ethuni <if>\|veip …}`; `veip <1-255> {inter-domain\|port\|state}`; `vlan port <if> {mode\|translate\|vlan {<V>\|all}}`; `vlan gemport <1-255> …`; `switchport {ethuni <if>\|veip <1-255>} …` |
| WAN / gestión | `wan-ip <1-255> ipv4 mode {dhcp [id\|vlan-profile …]\|inner\|pppoe\|static}`, `…ping-response`; `dhcp-ip ethuni <if> {forbidden\|from-internet\|from-onu\|no-ctrl}`; `security-mgmt <1-255> state {enable [mode {discard\|forward} ingress-type {iphost\|lan\|wan} protocol {ftp\|https\|snmp\|ssh\|telnet\|tr069\|web} [start-src-ip …]]\|disable\|enable-action}` |
| CATV / Ethernet / WiFi | `interface video video_0/<n> state {lock\|unlock}`; `interface eth eth_0/<n> {state {lock\|unlock}\|speed {auto\|full-10\|full-100\|full-1000\|full-10000\|half-10\|half-100}\|mtu\|type\|…}`; `interface wifi wifi_0/<n> state {lock\|unlock}`; `ssid ctrl wifi_0/<n> name <WORD>` (solo C620); `wifi enable [channel\|tx-power-percent\|work-mode\|…]` |
| Perfil T-CONT en OLT | modo `gpon`: `profile tcont <WORD> type {1\|2\|3\|4\|5} …` (en el tipo 5 sigue `fixed …`) |
| Tipo de ONU | modo `pon`: `onu-type <WORD> {gpon\|epon} [description <WORD>\|max-tcont\|max-gemport\|max-veip\|max-iphost\|service-ability\|…]`; `onu-type-if <WORD> <if> …` |
| Perfil de velocidad | **No se crea desde `qos traffic-profile` en modo config** (no existe ahí); el comando de creación no se descubrió con este nivel de ayuda |
| Reinicio | `reboot` (`<cr>`) en `pon-onu-mng` |

Siguen **sin descubrir** (necesitan otra ronda de `?` o un manual): la creación de perfiles de
velocidad (`traffic-profile`), el resto de parámetros de `profile tcont … type 5 fixed …`,
`onu-type … max-*`, `switchport ethuni … traffic-limit {in|out} …` y `write`.

## H. Los cinco pendientes (solo `?` y lecturas; idéntico en C620 y C600)

**1. Crear perfiles de velocidad (`traffic-profile`): NO encontrado.** La lectura existe
(`show qos traffic-profile [name <X>]`) pero el comando de creación no aparece con la ayuda de
esta cuenta. Se buscó en: la lista completa de modo config (207 comandos; solo `flow-profile`,
`resource-profile` y `security-service-profile` contienen "profile"), `qos ?` (lista de perfiles de
cola/CoS, sin `traffic-profile`), los prefijos `tr?`, `tra?`, `traffic?` (solo `traffic-limit
in …`, que es por ACL), `ca?`/`car?` y `hqos` (inexistente), y el `qos ?` dentro de las interfaces
`vport-`, `gpon_olt-` y `xgei-` (solo enlazan perfiles ya existentes). `show running-config all |
include …` quedó sin salida utilizable y es pesado para una OLT de producción (no se repitió).
Hipótesis a descartar con el fabricante: comando restringido por nivel de privilegio, o los perfiles
`SMARTOLT-*` los crea la propia plataforma de gestión por otra vía.

**2. `profile tcont` (modo `gpon`)**: el perfil se identifica por **nombre** (`<WORD>`), no por
número como en la clásica. Rango de velocidades 64–9.953.280 kbps:

| Tipo | Sintaxis |
|---|---|
| 1 | `profile tcont <WORD> type 1 fixed <v>` |
| 2 | `profile tcont <WORD> type 2 assured <v>` |
| 3 | `profile tcont <WORD> type 3 assured <v> maximum <v>` |
| 4 | `profile tcont <WORD> type 4 maximum <v> [priority <1-4> [weight …]]` |
| 5 | `profile tcont <WORD> type 5 fixed <v> assured <v> maximum <v> [priority <1-4> [weight …]]` |

**3. `onu-type <WORD> gpon …` (modo `pon`)**, todos opcionales y encadenables:
`max-tcont <1-255>`, `max-gemport <1-255>`, `max-veip <0-255>`, `max-iphost <0-127>`,
`max-ipv6-host <0-127>`, `max-switch-perslot <1-255>`, `max-flow-perswitch <1-255>`,
`service-ability N:1`, `omci-send-mode {async|sync}`, `mgc-cfg-mode {both|itu-t|zte}`,
`ex-omci {enable|disable}`, `default-multicast-range {all-inclusive|none}`,
`location {enable|disable}`, `description <WORD>`. Interfaces del tipo: `onu-type-if <tipo> eth_0/<n>`.

**4. Límite de tasa**: se aplica con el **nombre de un perfil** (de `show qos traffic-profile`), no
con un valor en kbps: `switchport ethuni eth_0/<n> traffic-limit {in|out} <PERFIL>` y
`gemport traffic-limit <gem> {upstream|downstream} <PERFIL>` (en `pon-onu-mng`). El `traffic-limit in`
del modo config global es por ACL y es otra cosa.

**5. `write`**: existe solo en modo **exec** (tras `end`), sin argumentos (`write ?` → `<cr>`); en
modo config da "Invalid input". No se ejecutó.

## I. Parámetros restantes de la C620 (solo `?`; esta ronda NO se repitió en la C600)

**`interface gpon_olt-<pon>`:** `onu-sn {enable|disable}`, `bind-onu <1-256>`, `shutdown`,
`uncfg-onu-aging-time <2-3600>`, `description <LINE>`, `blacklist sn …`, `fiber-distance <0-400>`,
`no onu <N>` (`<cr>`).

**`interface gpon_onu-<idx>`:** `tcont <1-255> {profile <WORD>|name <WORD>|allocid <256-4095>|gap
{default|mode0|mode1|mode2|mode3}}`; `gemport <1-255> {name <WORD>|portid <129-4095>|tcont <N> queue
<0-7>}`; `no {tcont|gemport} <1-255>`; `no {vport|vport-map} <1-128>`; `no splitter`; `deregister`;
`reset`; `admin {enable|disable}`; `auth-id {sn|pw|loid|rid|hpw|hrid|psk} …`; `authpass-control <0-10>`;
`auto-replace {enable|disable}`; `sn-bind {sn|both}`; `fec {auto|default|enable|disable}`;
`omcc-bandwidth <WORD>`; `encrypt <1-255>`; `link-test test-times …`; `real-speed gpon` (`<cr>`).

**`pon-onu-mng gpon_onu-<idx>`:**
- `service <nombre> gemport <1-255> {vlan <V>|untag|cos <0-7>|ethuni <WORD>|veip <1-255>}`
- `vlan port <if> {mode {hybrid|tag|transparent|trunk}|translate vlan …|vlan {<V>|all}}`; `vlan gemport <n> {mode|translate|vlan} …`
- `veip <1-255> {state {lock|unlock}|port <1-65535> {tcp|udp}|inter-domain <WORD>}`
- `wan-ip <1-255> ipv4 {mode {dhcp [id <WORD>|vlan-profile <WORD>]|inner|pppoe|static}|ping-response {enable|disable}}`; `wan-ip <1-255> ipv6 {mode|rs} …`
- `interface eth eth_0/<n> {state {lock|unlock}|speed {auto|full-10|full-100|full-1000|full-10000|half-10|half-100}|arc|loop|power-control|pppoe-filter {enable|disable}|l2l3 {either|l2|l3}|mtu <64-12288>|pause-time <0-65535>|type <0-255>|wiring {dce|dte}}`
- `interface video video_0/<n> {state {lock|unlock}|arc|power-control {enable|disable}}`;
  `interface video-ani {state {lock|unlock}|arc|agc-mode|pilot-frequency|optical-thresh lower <dBm> upper <dBm>}`
- `interface wifi wifi_0/<n> {state {lock|unlock}|arc {enable|disable}}`
- WiFi (solo C620): `wifi enable [channel <0-13>] [domain {bra|can|chn|…|usa}] [qos-type {disable|ssid|wmm}]
  [radio-measure …] [ssid-isolate …] [tx-power-percent {20|40|60|80|100}] [tx-rate {auto|1|2|5.5|6|9|11|12|18|24|36|48|54}]
  [work-mode {802.11b|802.11g|802.11n|802.11b-11g|802.11b-11g-11n}]`, `wifi disable …`, `wifi 5g {enable|disable}`;
  `ssid ctrl wifi_0/<n> {name <WORD>|hide {enable|disable}|max-users <1-32>|user-isolation {enable|disable}}`; `ssid auth {wep|wpa} …`
- `security-mgmt <1-255> state {enable [mode {discard|forward}] [ingress-type {iphost|lan|wan}] [protocol {ftp|https|snmp|ssh|telnet|tr069|web}] [start-src-ip A.B.C.D]|disable|enable-action …}`
- `dhcp-ip ethuni <if> {forbidden|from-internet|from-onu|no-ctrl}`; `mac-filter ethuni <if> …`; `ip route A.B.C.D …`; `reboot`

**Modo `pon`:** `onu-type-if <tipo> {eth_0/<n>|pots_0/<n>|video_0/<n>|wifi_0/<n>}` (`<cr>`).

**Corrección:** la creación de perfiles de velocidad sí se encontró (sección K): `traffic-profile …`.
Lo único sin comprobar es Tampoco se pudo comprobar, sin ejecutarlo, el texto de confirmación de `reboot`
(la doc dice `Confirm to reboot? [yes/no]`) ni el efecto de `write`.

## J. Perfiles de velocidad por SNMP y bitácora de comandos de la OLT (C620)

**Tabla de perfiles en SNMP** (rama `…1082.50.2.2.1.1.<col>.<len>.<nombre ASCII>`; el índice es el
nombre con prefijo de longitud). 16 filas = los 16 de `show qos traffic-profile`. Columnas: `.2` CIR
(kbps), `.3` CBS (kbytes), `.4` PIR, `.5` PBS, `.6` tipo básico (1 = ip), `.7`, `.8`, `.9` (modo de descarte,
modo de color, tipo de policer; valores 2/1/1 en todas), `.50` RowStatus (1 = activo). Coincide con
`show qos traffic-profile name …` (p. ej. 209664 kbps / 2620 kbytes para 200M). Los perfiles se **leen** por
SNMP sin necesidad de CLI.

**Intento de crear/borrar un perfil de prueba por SNMP** (comunidad de escritura de la C620, que responde):
`TKCTEST-DEL`, 5 `SET` atómicos (RowStatus `4`/createAndGo con y sin las demás columnas, con el RowStatus
primero y último, y `5`/createAndWait). **Todos rechazados con `wrongValue`** sobre el propio RowStatus; no se
creó ni modificó nada (el estado SNMP y `show qos traffic-profile` siguen en 16 perfiles). Conclusión: el agente
no admite crear filas con los valores estándar de RowStatus; hace falta el MIB de ZTE de esta tabla
(`zxAnQos…`) o el comando de CLI. No se tocó ningún perfil existente.

**Bitácora de comandos en SNMP** (`…3902.3.305.2.1.3.<n>`, 1135 filas): historial de la propia OLT con
inicios de sesión Telnet y cada comando ejecutado. Muestra los comandos reales de operación de la plataforma
de gestión, incluidos los de reversa: `no onu <N>`, `no service vlan<V>`, `no service-port <N>`,
`no qos traffic-policy direction {ingress|egress}`, `veip 1 state unlock`,
`interface video video_0/<n> state {lock|unlock}`, `interface video-ani state {lock|unlock}`,
`write` (18 veces), `copy sftp vrf mng root: … startrun.dat`, `terminal length 0`, `conf t`/`end`.
La creación de perfiles de velocidad no aparece en esa ventana de historial.

## K. Creación y borrado de perfiles de velocidad (comandos reales, C620)
Origen: la bitácora SNMP (`…3902.3.305.2.1.3`) tras crear y borrar un perfil desde SmartOLT v3.60.0.
Comandos exactos recibidos por la OLT (cada uno en su propia sesión Telnet: `terminal length 0`, `conf t`, comando, `end`, `exit`):

| Qué | Comando |
|---|---|
| Perfil de bajada (traffic-profile) | `traffic-profile <NOMBRE> cir <kbps> cbs <KB> pir <kbps> pbs <KB>` (modo config) |
| Borrar perfil de bajada | `no traffic-profile <NOMBRE>` (modo config) |
| Perfil de subida (T-CONT) | `gpon` → `profile tcont <NOMBRE> type 5 fixed 64 assured 64 maximum <kbps>` |
| Borrar perfil de subida | `gpon` → `no profile tcont <NOMBRE>` |

Ejemplo observado: `traffic-profile SMARTOLT-TKC-PRUEBA-30M-DOWN cir 10240 cbs 128 pir 10240 pbs 128` y
`profile tcont SMARTOLT-TKC-PRUEBA-30M-UP type 5 fixed 64 assured 64 maximum 102400`.
SmartOLT redondea la velocidad (10220 kbps → 10240; 102220 → 102400), usa CBS = PBS = 128 KB para un
burst de 100 ms (la interfaz lo muestra como 127 KB para C6xx, pero el comando enviado fue 128; rango
aceptado por la OLT 0–131072 KB), y el nombre lleva el prefijo `SMARTOLT-` y el sufijo `-UP`/`-DOWN`.
El comando de bajada se envió dos veces (posible reintento de la plataforma).

**Verificado por mí en la C620** (autorizado): `traffic-profile TKCTEST-DEL cir 1024 cbs 128 pir 1024 pbs 128`
creó el perfil (aparece en `show qos traffic-profile name TKCTEST-DEL` con CIR 1024 kbps, CBS/PBS 128 kbytes,
tipo ip) y `no traffic-profile TKCTEST-DEL` lo eliminó (la lista volvió a 16 perfiles). No se ejecutó `write`.

**Importante:** `traffic-profile` **no aparece en la ayuda `?`** del modo config (`tr?` solo lista
`trace`, `traffic-limit`, `traffic-stat-reset`) aunque el comando existe: la ayuda no es exhaustiva.
Para descubrir comandos de trabajo hay que apoyarse también en la bitácora de la OLT.

## L. Matriz final: verificado vs. faltante (C620 prioridad, C600)
Leyenda: **E** ejecutado por mí con éxito · **L** ejecutado por SmartOLT, visto en la bitácora SNMP (C620) · **H** sintaxis solo por `?` · **—** sin verificar.

| Comando / función | C620 | C600 |
|---|---|---|
| Lecturas `show` (state, baseinfo, detail-info, by sn, uncfg, onu-type, tcont, vlan, mac interface, distance, pon power, service-port, remote-onu equip/capability/eth/video/wifi/service/sys-attr, running-config-interface onu/olt/vport, software, card, qos traffic-profile [name]) | E | E |
| `show interface <puerto>` (contadores) | E | E |
| `show gpon remote-onu ssid info` / `wifi enable…` / `ssid ctrl…` | E / H | no existe |
| `terminal length 0` apaga paginador | E | aceptado (efecto sin medir) |
| `conf t`, `end`, `exit`, entrar a sub-modos | E | E |
| `traffic-profile … cir cbs pir pbs` y `no traffic-profile` | **E** | — (no ejecutado) |
| `profile tcont … type 5 …` y `no profile tcont` (modo `gpon`) | L | H |
| `onu N type T sn S`, `no onu N` | L | H |
| `name`, `description`, `vport-mode`, `tcont`, `gemport`, `vport`, `vport-map` | L | H (aparecen en la config real) |
| `pon-onu-mng`: `service vlanV gemport 1 vlan V`, `veip 1`, `veip 1 state unlock`, `no service vlanV` | L | H |
| `service-port … ingress … egress …`, `no service-port N` | L | H |
| CATV `interface video / video-ani state lock|unlock` | L | H |
| `reboot` (+ confirmación `[yes/no]`) | H | H |
| `write` | L (18 veces) | — |
| Ethernet, WAN (`wan-ip`), `security-mgmt`, `dhcp-ip`, `vlan port`, WiFi, `onu-type`, `onu-type-if`, `no tcont/gemport/vport` | H | H (sin WiFi) |
| `show gpon remote-onu mac <tok>` | requiere subopción `ethuni`/`wifiuni` (solo ayuda) | igual |
| `show gpon onu config-fail|tcont|gemport`, `show pon onu offline|online`, `show alarm {class|current|history|…}` | H | H |

**Faltantes (en orden):** 1) ciclo completo en una ONU: autorizar → aprovisionar → reiniciar → borrar
(**bloqueado**: el clasificador de seguridad denegó ejecutarlo; script listo en
`scripts/c620_onu_lifecycle_test.py`, ONU en espera `DF30A601103C` del puerto `1/1/5`, índice 250, con
rollback `no onu 250`); 2) texto real de confirmación de `reboot` y efecto de `write`; 3) crear/borrar
`traffic-profile` y `tcont` en la C600; 4) ejecutar (no solo `?`) WiFi, Ethernet, WAN y `security-mgmt`;
5) lecturas `show alarm …`, `config-fail`, `pon onu offline/online`; 6) C600: sin ONU en espera para probar alta.
La ronda de parámetros (86 comandos) en la C600 salió idéntica a la C620 salvo `wifi`/`ssid` y `enable-action`.

## M. Ciclo de ONU en la C620: primer intento (índice 250)
Ejecutado por el usuario con `scripts/c620_onu_lifecycle_test.py`. **Aprovisionamiento: OK** — la OLT aceptó sin
`%Error` y con los prompts correctos cada comando: `onu 250 type LATIC sn <SN>`, `name`, `description`,
`vport-mode manual`, `tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON`, `gemport 1 name internet tcont 1`,
`vport 1 map-type vlan`, `vport-map 1 1 vlan 101`, `pon-onu-mng` + `service vlan101 gemport 1 vlan 101` + `veip 1`,
`interface vport-1/1/5.250:1` + `service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN`
(en pantalla, las líneas largas salen recortadas con `$` por el ancho del terminal; no son errores).
La ONU apareció en `show gpon onu state` (Admin enable). **Rollback: OK** — `no onu 250` la eliminó con todo su
aprovisionamiento (el vport y el detail-info dan "Invalid input" = no queda residuo) y la ONU física volvió a la lista de espera.
**No llegó a `working`**: 4 min en `OffLine` / OMCC `disable`, aunque la ONU física sigue activa (vista a las 17:53 de hoy,
`Auth fail reason: Others`, igual que las otras dos). Sin alarmas para `onu 250`. Hipótesis principal: el índice 250 no es viable
en GPON (ONU-ID limitado; las ONU reales usan 1–28). Por eso la reiniciada (`reboot`) no se pudo probar. Siguiente intento con índice 3.

## N. Ciclo de ONU en la C620: segundo intento (índice 3)
Con el índice 3 la ONU **sí se registra** (confirma que el 250 era inviable): `OffLine` → `syncMib` (OMCC/MIB) y luego
oscila 4 min entre `syncMib`, `LOS` y `Logging` sin llegar a `working` (la ONU `HG102WT DF30A601103C` pierde la señal
y vuelve a registrarse; parece un problema de esa ONU/fibra, no de la configuración). **Releído de la OLT antes del rollback:**
`show running-config-interface gpon_onu-1/1/5:3` muestra exactamente `name`, `description` (enmascarados), `vport-mode manual`,
`tcont 1 profile SMARTOLT_DEFAULT_TCONT_GPON`, `gemport 1 name internet tcont 1`, `vport 1 map-type vlan`,
`vport-map 1 1 vlan 101` y el bloque `pon-onu-mng gpon_onu-1/1/5:3` con `service vlan101 gemport 1 vlan 101` y `veip 1`; y
`…vport-1/1/5.3:1` el `service-port 1 user-vlan 101 vlan 101 ingress SMARTOLT-50M-UP egress SMARTOLT-50M-DOWN`.
**Alta + aprovisionamiento completo + relectura + rollback: verificados (2 corridas).** `reboot` sigue sin probar (la ONU no llegó a `working`).
Estados nuevos de fase observados: `syncMib`, `Logging`. Siguiente: repetir con otra ONU en espera
(`python scripts/c620_onu_lifecycle_test.py DF306B41EDB0`).

## O. Ciclo de ONU en la C620: tercer intento (otra ONU, `SML-702XW-AX-C`, índice 3)
Mismo resultado que con `HG102WT`: aprovisionamiento relleído idéntico (nombre/descripción enmascarados, tcont, gemport,
vport-map, `pon-onu-mng service/veip`, service-port) y rollback correcto, pero la ONU oscila ~4 min entre `syncMib`, `LOS` y
`Logging` sin llegar a `working` (ciclo de ~40–50 s). Dos ONU distintas con el mismo patrón apuntan a algo común a las
ONU en espera de este puerto (las tres llevan días en la lista de espera, `Auth fail reason: Others`, primera vez vistas el
26-sep), no a una ONU concreta. Causa sin determinar. Autorizar, aprovisionar, leer y borrar quedan verificados 3 veces;
`reboot` se prueba ahora sobre la ONU de prueba aunque no esté `working` (cancelando con `no` y luego confirmando con `yes`).

## P. `reboot`: diálogo verificado (C620)
Sobre la ONU de prueba (en `syncMib`, no `working`): `reboot` en `pon-onu-mng` muestra exactamente
`Confirm to reboot? [yes/no]:`; responder `no` cancela y devuelve el prompt `ZXAN(config-gpon-onu-mng)#` sin mensaje;
responder `yes` también devuelve el prompt sin mensaje ni error (el reinicio es silencioso). **No se observó el efecto sobre una
ONU en línea** (la de prueba nunca llegó a `working`). Rollback correcto (3.ª vez). Hallazgo lateral: los perfiles `SMARTOLT-*-UP`
figuran también en `show gpon profile tcont` (son perfiles T-CONT de subida), además de en `show qos traffic-profile`.

## Q. Batería de escrituras sobre la ONU de prueba (C620, ejecutada por el usuario)
ONU `SML-702XW-AX-C` en el índice 3 (no activa, sin clientes). 28 comandos; **25 aceptados, 3 con error**; todo deshecho y verificado.

| Aceptado y ejecutado (OK) | Notas |
|---|---|
| `tcont 2 profile SMARTOLT-50M-UP`, `gemport 2 name tkctest tcont 2` | y su borrado `no gemport 2`, `no tcont 2` (verificado: no quedan en la configuración) |
| `admin disable` / `admin enable`, `name TKCTEST2` | `name` queda enmascarado en la lectura |
| `veip 1 state unlock`, `interface eth eth_0/1 state unlock`, `… speed auto` | valores por defecto: se aceptan pero **no se guardan** en la configuración |
| `interface eth eth_0/1 mtu 1500` | guardado en `pon-onu-mng` |
| `security-mgmt 1 state enable mode forward ingress-type lan protocol web` | guardado |
| `dhcp-ip ethuni eth_0/1 from-onu` | guardado |
| `interface video video_0/1 state lock` | guardado |
| `profile tcont TKCTEST-T type 5 fixed 64 assured 64 maximum 2048` (modo `gpon`) | aparece en `show gpon profile tcont` como tipo 5, FBW 64 / ABW 64 / MBW 2048; `no profile tcont TKCTEST-T` lo elimina (verificado) |

| Con error | Causa |
|---|---|
| `interface wifi wifi_0/1 state unlock` y `ssid ctrl wifi_0/1 name …` | `%Error 223845: UNI does not exist` — esa ONU/tipo no tiene UNI WiFi (hace falta una ONU con WiFi o un tipo con `onu-type-if … wifi_0/1`) |
| `vlan port eth_0/1 vlan 101` | `%Error 223983: Port mode error` — el puerto debe tener antes un modo (`vlan port eth_0/1 mode {hybrid|tag|transparent|trunk}`) |

**Efecto del rollback:** `no onu 3` retiró la ONU y todo su aprovisionamiento; el contador de uso de `SMARTOLT_DEFAULT_TCONT_GPON`
bajó de 279 a 278 (la ONU de prueba dejó de usarlo) y el perfil `TKCTEST-T` desapareció de la lista. La configuración guardada tras la batería muestra
además `real-speed gpon` en la ONU (aparece al sincronizar la MIB).

## R. Batería 2 (C620): ejecución parcial (error mío en el script)
Verificado: ayuda dentro de `pon-onu-mng` (`vlan port eth_0/1 mode tag ?` → `pri`, `vlan`, `<cr>`; `vlan port eth_0/1 vlan 101 ?` → `<cr>`;
`wan-ip 1 ipv4 mode dhcp ?` → `id`, `vlan-profile <WORD 1-64>`); **tipos de ONU**: `onu-type TKCTEST-TYPE gpon description TKCTEST max-tcont 8 max-gemport 32 max-veip 1`
creado y visible en `show onu-type gpon` (Max T-CONT 8, GEM 32, VEIP 1; los tipos nuevos nacen con `Max switch per slot`/`Max flow per switch` = 255);
`onu-type-if TKCTEST-TYPE eth_0/1` y `… wifi_0/1` aceptados; `no onu-type TKCTEST-TYPE` lo elimina (verificado en la lista). `no onu-type-if <tipo>` sin
interfaz da `%Error 140305: Incomplete command` (requiere el nombre de la interfaz; no hace falta para el rollback). El script se detuvo tras crear el tipo porque
olvidé volver a modo config (`conf t`) antes de entrar a la interfaz de la ONU; el rollback fue correcto (`rollback_ok: true`, sin residuo). **Sin ejecutar por ese fallo:**
cambio de tipo de la ONU a `TKCTEST-TYPE`, WiFi/SSID con tipo que tiene `wifi_0/1`, escritura de `vlan port … mode tag` + `vlan`, `wan-ip … vlan-profile`, T-CONT tipos 1–4.
Script corregido (seguimiento del modo config; sin `no onu-type-if`).

## S. Batería 2 completa (C620, ejecutada por el usuario; rollback verificado)
**T-CONT tipos 1–4: OK.** `profile tcont TKCT1 type 1 fixed 64`, `TKCT2 type 2 assured 64`, `TKCT3 type 3 assured 64 maximum 128`, `TKCT4 type 4 maximum 128` se crean
(`show gpon profile tcont` los muestra con FBW/ABW/MBW 64/0/0, 0/64/0, 0/64/128 y 0/0/128) y `no profile tcont <nombre>` los elimina (verificado).
**`vlan port eth_0/1 mode tag`: OK** (queda guardado como `vlan port eth_0/1 mode tag`), pero `vlan port eth_0/1 vlan 101` sigue dando `%Error 223983: Port mode error`
(la ayuda de `mode tag ?` ofrece `pri` y `vlan`: la VLAN se pasa dentro del mismo comando, `vlan port eth_0/1 mode tag vlan 101`, sin probar).
**`wan-ip 1 ipv4 mode dhcp vlan-profile SMARTOLT_VLAN_101`: OK** — se guarda normalizado como `wan-ip ipv4 mode dhcp vlan-profile SMARTOLT_VLAN_101 host 1`.
`wan-ip 1 ipv4 ping-response enable` da `Incomplete command` (probablemente exige `host <n>` al final, como la forma guardada).
**`type TKCTEST-TYPE force` en la interfaz de la ONU: `Invalid input` en `force`** (la forma sin `force` no se ejecutó), por lo que el cambio de tipo no se probó y el WiFi
siguió dando `UNI does not exist`. Rollback correcto: `no onu 3`, `no onu-type TKCTEST-TYPE` y los cuatro perfiles T-CONT (la lista volvió a 11 perfiles y los tipos a los originales).
El script quedó ajustado (`type TKCTEST-TYPE` sin `force`, `mode tag vlan 101`, `ping-response … host 1`, ayuda de esas formas) para repetir solo lo pendiente.

## T. Batería 2, segunda corrida (C620, ejecutada por el usuario; rollback verificado)
- **`vlan port eth_0/1 mode tag vlan 101`: OK** — es la forma correcta (la VLAN va dentro del mismo comando; la ayuda ofrece además `pri`). Se guarda tal cual en `pon-onu-mng`. Explica el `Port mode error` anterior (`vlan port … vlan 101` suelto no es válido).
- **Cambio de tipo de la ONU (`type <tipo>` en `interface gpon_onu-…`)**: existe sin `force` y pide `Need to restore ONU after modification, confirm to modify? [yes/no]:` (reinicia/restaura la ONU). El script no respondió, por lo que el cambio **no se aplicó** (el siguiente comando recibió `%Error 99: Invalid character(s). Please enter yes/no.`; sin efecto). Por eso WiFi/SSID siguió con `223845 UNI does not exist`. Corregido: el script ahora responde `yes` (solo sobre la ONU de prueba).
- **`wan-ip 1 ipv4 ping-response enable`**: la ayuda solo ofrece `traceroute-response` (no `<cr>`), así que la forma completa es `wan-ip 1 ipv4 ping-response enable traceroute-response {enable|disable}` (coincide con la plantilla de `ip-host … ping-response enable traceroute-response enable` de la doc original). El `host 1` que probé no es válido.
- Rollback: `no onu 3`, `no onu-type TKCTEST-TYPE` verificados; los `no profile tcont TKCT*` dieron `Profile does not exist` (ya no se crean en esta batería, esperado). La lista de perfiles T-CONT y de tipos quedó como al inicio.

## U. Batería 2, tercera corrida (C620, ejecutada por el usuario; rollback verificado)
- **`type TKCTEST-TYPE` + `yes`: `%Error 222366: Modify ONU type failed.`** — la OLT no permite cambiar el tipo de una ONU ya registrada a `TKCTEST-TYPE` (causa sin confirmar; la ONU de prueba no está en línea, y el tipo nuevo difiere en interfaces/capacidades). Sin efecto: la configuración no cambió.
- **`wan-ip 1 ipv4 ping-response enable traceroute-response enable`: `%Error 224011: This wan-ip does not exist`.** La sintaxis es **válida** (ya no hay `Invalid input`); falla porque el `wan-ip 1` no existía en esta corrida (en la anterior se había creado con `wan-ip 1 ipv4 mode dhcp vlan-profile …`). Dependencia confirmada: primero `wan-ip … mode …`, luego `ping-response`.
- **`vlan port eth_0/1 mode tag vlan 101`: OK** (se repite y se guarda igual).
- **WiFi/SSID:** `223845 UNI does not exist` otra vez, porque el tipo no cambió.
- Rollback: correcto (ONU y tipo de prueba eliminados; perfiles T-CONT y tipos como al inicio).
**Siguiente prueba (script ajustado):** crear primero `TKCTEST-TYPE` (con `eth_0/1` y `wifi_0/1`) y **autorizar la ONU directamente con ese tipo** (`onu 3 type TKCTEST-TYPE sn …`) en vez de cambiarlo después; crear el `wan-ip` antes del `ping-response`; luego WiFi/SSID.

## V. Batería 2, cuarta corrida: éxito completo (C620, ejecutada por el usuario; rollback verificado)
Dando de alta la ONU **directamente con un tipo que tiene `wifi_0/1`** (`onu 3 type TKCTEST-TYPE sn …`, tras crear el tipo con `onu-type-if … eth_0/1` y `wifi_0/1`):
- **Alta con tipo WiFi: OK.** Se resuelve el `UNI does not exist`: la interfaz WiFi existe solo si el tipo de la ONU la declara. El tipo no se puede cambiar después (`222366`).
- **`interface wifi wifi_0/1 state unlock`, `ssid ctrl wifi_0/1 name TKCTEST`, `ssid ctrl wifi_0/1 hide disable`: OK.**
- **`wan-ip 1 ipv4 mode dhcp vlan-profile SMARTOLT_VLAN_101` y luego `wan-ip 1 ipv4 ping-response enable traceroute-response enable`: OK** (orden obligatorio). La ayuda de `… traceroute-response ?` ofrece `enable|disable`.
- **`vlan port eth_0/1 mode tag vlan 101`: OK.**
- **Configuración guardada** (`show running-config-interface gpon_onu-1/1/5:3`), bloque `pon-onu-mng`:
  `interface wifi wifi_0/1 arc disable arc-interval 0 state unlock`, `service vlan101 gemport 1 vlan 101`, `veip 1`, `wan-ip ipv4 mode dhcp vlan-profile SMARTOLT_VLAN_101 host 1`,
  `wan-ip ipv4 ping-response enable traceroute-response enable`, `vlan port eth_0/1 mode tag vlan 101`, `ssid ctrl wifi_0/1 name TKCTEST`. (`hide disable` es el valor por defecto y no se guarda.)
  Nota: sin `real-speed gpon` en el bloque de la ONU porque esta vez nunca sincronizó la MIB.
- **Rollback: OK** (`no onu 3`, `no onu-type TKCTEST-TYPE`); perfiles T-CONT y tipos como al inicio.
**Estado de escrituras de la C620:** todas las de trabajo están ejecutadas y verificadas salvo `write` y el efecto de `reboot` en una ONU en línea.

## W. Batería final + `write` (C620, ejecutada por el usuario; rollback verificado)
**Seguridad:** rollback OK (ONU, tipo, perfil T-CONT y perfil de velocidad de prueba eliminados), configuración del puerto `1/1/5` **idéntica** a la inicial,
la ONU física volvió a la lista de espera. **`write` se ejecutó con éxito** (`......[OK].`) y guardó esa configuración idéntica. No se probó el reinicio de una ONU en línea (opción no usada).

**Aceptados (OK), sobre la ONU de prueba:** `description <txt>` en el puerto PON (y `no description`), `security-mgmt … state enable|disable`, `dhcp-ip … from-onu|forbidden|no-ctrl`,
Ethernet (`state`, `speed`, `mtu`, `pppoe-filter`, `loop`, `power-control`, `l2l3`, `pause-time`), `interface video-ani state lock|unlock`, WiFi (`state`, `ssid name|hide|max-users|user-isolation`,
`wifi enable channel|tx-power-percent|work-mode`, `wifi 5g disable`), `vlan port … mode tag vlan`, `wan-ip …`, `veip state`, `no service-port 1` + recrear, `no service vlan101`,
`tcont 2 profile`, `tcont 2 gap default`, `gemport 2 … queue 1`, `no vport 2`, `no gemport 2`, `no tcont 2`, `no splitter`, `sn-bind enable sn`, `fec enable|default`, `authpass-control 5`,
`auto-replace disable`, `admin`, `name`, `reset`, `deregister`, `onu-type-if … pots_0/1`, `onu-type-if … wifi_0/1`, `traffic-profile`, `profile tcont`. `reset` y `deregister` no piden confirmación.
**Efectos guardados** (`show running-config-interface`): `interface eth eth_0/1 loop|mtu|pause-time|l2l3|pppoe-filter|power-control`, `interface video-ani optical-thresh lower -9.5 upper 2.5` (aparece al tocar `video-ani`),
`security-mgmt 1 mode forward ingress-type lan protocol web` (sin `state enable`), `wifi enable work-mode … channel 6 tx-power-percent 80`, `wifi 5g disable work-mode 802.11a-11ac-11n`,
`ssid ctrl wifi_0/1 name TKCTEST max-users 8`.

**Con error (ERR) y qué dice la ayuda para corregirlos:**
| Comando probado | Error | Corrección según la ayuda (`?`) |
|---|---|---|
| `tcont 2 name TKCNAME` | `Incomplete command` | tras `name <WORD>` siguen `allocid <256-4095>`, `gap`, `profile` → `tcont 2 name <N> profile <P>` |
| `gemport 2 portid 300` | `Incomplete command` | tras `portid <129-4095>` sigue `tcont` → `gemport 2 portid 300 tcont 2` |
| `no vport-map 2` | `Incomplete command` | `no vport-map <1-128> <1-255>` (vport y gem) |
| `vport-map 2 1 vlan 102` | `222357 Port-id has been used` | el GEM 1 ya está mapeado al vport 1; usar otro GEM |
| `interface eth|wifi|video … arc enable` | `Incomplete command` | `arc enable arc-interval <n>` (se guarda como `arc disable arc-interval 0`) |
| `gemport traffic-limit 1 upstream|downstream <PERFIL>` | `223876 Parameter error` | **no usa los perfiles de `show qos traffic-profile`** sino los de ONU: `gpon` → `onu profile traffic <WORD> sir <kbps> pir <kbps> [cbs|colour-mode|meter-type…]` (borrar: `no onu profile traffic <WORD>`; leer: `show gpon onu profile traffic [<WORD>]`). Hoy no hay ninguno creado |
| `switchport ethuni … traffic-limit in|out <PERFIL>` | `223981 Profile does not exist` | mismo origen: el perfil debe existir en `onu profile traffic` |
| `onu-type-if <tipo> video_0/1` | `230263 Parameter error` | la ayuda lo da por válido (`<cr>`); causa sin determinar (los tipos CATV reales usan `interface video video_0/1` pero esta ONU de prueba no admite video) |
| `interface video video_0/1 state …` | `UNI does not exist` | consecuencia de lo anterior (el tipo de prueba no pudo declarar `video_0/1`) |
| `blacklist sn TKCBL0000001` | `141000 Common error` | sintaxis `blacklist sn <WORD>`; falló con ese SN ficticio (¿formato/longitud o prefijo de fabricante?). Sin determinar |
| `wifi enable domain bra` | `230263 Parameter error` | la ayuda de `domain bra ?` ofrece `channel|qos-type|tx-power-percent|tx-rate`; sin determinar |
| `splitter TKCSPL` | `230263 Parameter error` | `splitter <WORD>`; probablemente exige un splitter ya definido. Sin determinar |

**Nuevo descubrimiento (ayuda):** `onu profile ?` (modo `gpon`) lista `dial-plan dscp filter-rule igmp ip mgc schedule sip snmp tdm traffic treat vlan voip-accesscode voip-appsrv voip-media`;
`onu profile vlan <WORD> tag-mode …` es el origen de `SMARTOLT_VLAN_*`. `show pon onu-profile gpon ?` → `line`, `service` (otro tipo de perfil).
**Pendiente de verificar tras esta corrida:** rehacer las 5 correcciones de sintaxis (tcont name, gemport portid, no vport-map, arc, perfil `onu profile traffic` + `gemport/switchport traffic-limit`); resolver video_0/1, blacklist, domain, splitter; reinicio de una ONU en línea.

## X. Ronda 2 (C620, ejecutada por el usuario SIN `--reboot-online`; rollback verificado)
Rollback OK, configuración del puerto idéntica, ONU de prueba de vuelta en la lista de espera; no se ejecutó `write` (no hacía falta). **El reinicio de una ONU en línea NO se probó** (no se pasó la opción).
**Resuelto (OK):**
- **Perfil de límite de tasa de ONU:** en modo `gpon`, `onu profile traffic TKCTEST-OP sir 1024 pir 1024` lo crea; `show gpon onu profile traffic <nombre>` lo muestra (SIR/PIR 1024 kbps, CBS/PBS 0 bytes, `Colour mode: colour-blind`, `Ingress/Egress colour marking: no-marking`, `Meter type: not-specified`); `no onu profile traffic <nombre>` lo borra (la lista vuelve a "No related information").
- **Uso del perfil:** `gemport traffic-limit 1 upstream|downstream <perfil>` y `switchport ethuni eth_0/1 traffic-limit in|out <perfil>` en `pon-onu-mng`: OK. Se guardan como `gemport traffic-limit 1 downstream <P> upstream <P>`, `switchport ethuni eth_0/1 traffic-limit in <P>` y `… out <P>`.
- `tcont 2 name TKCNAME profile SMARTOLT-50M-UP`: OK. `gemport 2 name tkctest tcont 2`, `vport 2 map-type vlan`, `vport-map 2 2 vlan 102`: OK. `no vport 2`, `no gemport 2`, `no tcont 2`: OK (`no vport 2` deja la ONU limpia).
- `interface eth eth_0/1 arc enable arc-interval 5` e `interface wifi wifi_0/1 arc enable arc-interval 5`: OK (se guardan igual).
- `blacklist sn ZTEGC0000001` y su `no`: OK (el serial de la ronda anterior, `TKCBL0000001`, dio `141000`: el SN necesita un formato válido, p. ej. prefijo de fabricante de 4 letras + 8 caracteres).
**Errores residuales (sin impacto operativo):** `gemport 2 portid 300 tcont 2` → `222370 Not support this operation` (asignar `portid` manual no se admite); `no vport-map 2 2` → `222386 Vport Map param input error` (la forma de borrado de un mapeo concreto no coincide; `no vport <n>` lo elimina entero); `wifi enable domain bra channel 6` → `230263 Parameter error` (por segunda vez: `domain` no se acepta en esta ONU/radio). Siguen sin determinar `onu-type-if … video_0/1` y `splitter`.

## Y. Ronda 2 repetida + reinicio de una ONU EN LÍNEA (C620, ejecutada por el usuario con `--reboot-online 1/1/5:1`)
**Batería:** resultado idéntico a la sección X (mismos OK y mismos 3 ERR: `gemport … portid`, `no vport-map 2 2`, `wifi enable domain`), rollback OK, configuración del puerto idéntica.
**Reinicio en línea (ONU `1/1/5:1`, cliente real, estado previo `working`):** `reboot` → `Confirm to reboot? [yes/no]:` → `yes` (sin mensaje). Secuencia observada (muestreo cada ~10 s, segundos desde el `yes`):
`10 s working` (aún no aplicado) → `21 s LOS` → `31 s LOS` → `42 s LOS` → `52 s syncMib` → `63 s working`. El contador de ONU activas bajó de 13/19 a 12/19 durante el reinicio y volvió a 13/19.
**Conclusión:** el reinicio es efectivo y silencioso; el servicio de la ONU se corta **~45–55 s** (entre ~15 s y ~63 s tras el `yes`) y se recupera solo, pasando por `LOS` (no `OffLine`) y `syncMib`; `Admin state` se mantiene `enable`, `OMCC state` pasa a `disable` y vuelve a `enable`.
No hubo efecto sobre las demás ONU (las `DyingGasp` 1/1/5:16 y :19 y la `LOS` :27 ya estaban así antes).

### Estado final de la C620 (resumen)
- **Lecturas:** todas verificadas (secciones A–E, J, K).
- **Escrituras de trabajo:** alta/baja de ONU, aprovisionamiento completo, `pon-onu-mng` (servicio, VLAN, WAN, WiFi, Ethernet, CATV, `security-mgmt`, `dhcp-ip`), tipos de ONU, T-CONT 1–5, perfiles `traffic-profile` y `onu profile traffic`, límites de tasa, `reboot` (en prueba y en línea), `reset`, `deregister`, `blacklist`, `write`: **ejecutadas y verificadas** con rollback (secciones K–Y).
- **Residuales sin impacto operativo:** `gemport … portid` (no soportado), `no vport-map <v> <g>`, `wifi enable domain`, `onu-type-if … video_0/1`, `splitter`.

## Z. Inventario final de la C620: qué tenemos por CLI y por SNMP, y qué no
### Catálogo generado (local; falta cargarlo a la DB)
- **Comandos:** `catalog/zte/zxa10-c620/catalog-1.1.0/commands/` → **74 comandos** (72 `verified`, 2 `documented`) con sintaxis, parámetros, modo, contexto, rollback y notas; para la C600 72 (29 `verified`, 13 `observed`, 30 `documented`).
  Fuente: `scripts/build_c620_command_catalog.py` → `docs/validation/commands/zte_c6xx_verified_commands.json`; el `walk_validator` los aplica (hook `_apply_command_sources`, `replace_seed`) en lugar de los 18 heredados del manual C320 (sintaxis incorrecta para C6xx).
- **OIDs:** 1.770 (39 `verified_walk` contrastados con la CLI, 1.106 `verified` por walk/MIB, 625 `documented`).
### SNMP — lo que SÍ tenemos (C620, contrastado con la CLI salvo donde se indica)
ONU (`.1082.500.*`): serial, tipo configurado, modelo, prefijo de fabricante, **nombre y descripción** (datos personales; sin contraste CLI, enmascarados), estado (2 LOS · 4 Working · 5 DyingGasp · 7 OffLine), **Rx y Tx** de la ONU (raw*0.002-30), **distancia**, última autenticación, última baja y causa (1 ninguna · 2 LOS · 3 LOSi · 9 DyingGasp · 10 DeactiveSucc). Puertos: `ifType`, admin/oper, `ifName`, contadores `ifHC*` de 64 bits (octetos y paquetes unicast/multicast/broadcast), `ifHighSpeed`, errores y descartes. Equipo: `sysDescr`, `sysObjectID`, `sysUpTime`, `sysName`. Alarmas: tablas actuales, histórico y notificaciones (`zxr10AlarmMIB`, 92 hojas confirmadas con 5.000/361 filas). **Perfiles de velocidad** (`.1082.50.2.2.1.1`): nombre, CIR, CBS, PIR, PBS (legibles). Además ~1.100 OID de MIB presentes en el walk (PON perf, óptica, service-port, VLAN, chasis).
### SNMP — lo que NO tenemos
1. **Lista de ONU sin autorizar (uncfg)** y **tabla MAC** (`dot1qTpFdb` vacía): solo por CLI. 2. **Potencia de recepción del OLT por ONU (`olt-rx`)**: solo CLI. 3. **Escritura por SNMP**: la comunidad de escritura no puede crear perfiles de velocidad (RowStatus 4/5 → `wrongValue`); no se probó ninguna otra escritura SNMP, así que toda la configuración va por CLI. 4. `ENTITY-MIB` (vacía en C620 y C600). 5. Ramas sin MIB entregado (≈55 % de las filas del walk: tabla de ONU `1082.500.10/20`, QoS `1082.50.7`, multicast `1082.60`, seguridad `1082.70`, `3.104/3.305`, `1083.5`): parcialmente catalogadas. 6. Huecos del walk (25 rangos con OID no crecientes en `3.6000` y `1082.70`) y la columna lenta `…20.2.1.25` (3 s por fila; capturada aparte). 7. Nombre/descripción de ONU sin contraste con la CLI. 8. El walk de la C620 es `INCOMPLETE` (marcado) por esos huecos.
### CLI — lo que SÍ tenemos (C620)
Lecturas: reloj, versión (`show software`), tarjetas, estado/baseinfo/detalle/búsqueda de ONU, sin autorizar, tipos, perfiles T-CONT/velocidad/tráfico de ONU/VLAN, configuración de puerto/ONU/vport, service-ports, MAC, VLAN, distancia, potencias, información, `remote-onu` (equip, capability, interface, service, sys-attr, wifi, ssid, mac), estadísticas de puerto, alarmas. Escrituras (ejecutadas con rollback): alta/baja de ONU, aprovisionamiento completo, perfiles (T-CONT 1–5, `traffic-profile`, `onu profile traffic`), tipos de ONU, servicio/VLAN/WAN/WiFi/Ethernet/CATV/`security-mgmt`/`dhcp-ip`, límites de tasa, `admin`, `reset`, `deregister`, `reboot` (también en línea), `blacklist`, `write`.
### CLI — lo que NO tenemos
1. **Residuales sin resolver:** `gemport … portid` (no soportado), `no vport-map <v> <g>`, `wifi enable domain`, `onu-type-if … video_0/1`, `splitter` (hay un agente escribiendo scripts para esto, pendiente de ejecución por el usuario). 2. **C600:** escrituras solo con ayuda (`documented`) o vistas en la configuración (`observed`): no hay ONU en espera para probar; WiFi/SSID no existe. 3. **Fuera de alcance, no investigado:** EPON, VoIP/POTS (SIP, MGC), multicast/IGMP, ACL, colas QoS, LAG/smartgroup, DHCP relay, PPPoE, OTDR, rogue ONU, actualización de firmware de ONU, AAA, SNMP/trap, backup/restore. 4. `show running-config all` (pesado, no ejecutado). 5. Los `Name`/`Description` de ONU salen enmascarados con la cuenta de solo lectura. 6. Comportamiento con ONU en estados distintos de `working` para algunas lecturas.
### Activación en el sistema
Pendiente (tuyo): `python -m src.loader load zxa10-c620 --version 1.1.0 --user <u> --authorize` y lo mismo para `zxa10-c600` (estado actual: **CAMBIOS**). Importador (`network-api`): requiere la ruta del repo para el detector de plataforma (`/c6\d\d/i`), el mapa de lecturas (tokens `gpon_onu-`, `show pon onu uncfg`, `show running-config-interface …`, `show mac interface …`, `show software 1`) y parsers con fixtures anonimizadas.

## AA. Revisión del importador (análisis de la respuesta del otro agente) contra la evidencia
**Carga a la DB:** la C620 1.1.0 se subió (`SIN CAMBIOS` tras la carga). La C600 **no** estaba igual: `loader status` la marcaba `CAMBIOS` (hash local distinto del de la DB) porque el catálogo local ya traía 72 comandos y OID nuevos; tras añadir los perfiles por ONU ambas vuelven a `CAMBIOS` y hay que **recargar las dos**.
**Corrección de cifras:** los «72 verified» son 37 lecturas + 37 escrituras de comandos CLI (74 en total con 2 documentados), no 72 escrituras.

| Punto del otro agente | Evidencia nuestra |
|---|---|
| **VLAN** | SNMP: `…1082.40.50.2.1.2.1.<vlan>` (nombre; VLAN 1, 100, 101, 214) y Q-BRIDGE `dot1qVlanStaticName` (`.17.7.1.4.3.1.1`), PVID por ifIndex (`.17.7.1.4.5.1.1.<ifIndex>`). Relación VLAN–puerto: CLI `show vlan <id>` lista los puertos *tagged* (rangos `vport-1/1/1.11,16-17…:1` y uplinks `xgei-1/4/1`); `show vlan summary` lista los ID. Por SNMP el mapa VLAN–puerto (bitmap de egress de `dot1qVlanCurrentTable`, 84 filas) existe pero no se decodificó. |
| **Tarjetas** | SNMP `…1082.10.1.2.4.1.<col>.<shelf>.<slot>` (misma rama que C300): tipo (col 4: GFBT, FCSDA, SPUF, PRAF), nombre (42), puertos (7), HW (23), serial (14), oper (5), admin (6), standby (13: 2 = STANDBY, coincide con el slot 5 de `show card`). 5 tarjetas en C620 (slots 1, 3, 4, 5, 6). El catálogo ya trae esos OID verificados. |
| **Uplinks vs PON** | `ifType` 250 = `gpon_olt-` (PON) y 6 = `xgei-` (uplink). C620: 16 PON en slot 1 + 8 `xgei` (slots 4 y 5); C600: 32 PON (slots 1–2) + 8 `xgei` (slot 10). |
| **Perfil aplicado a cada ONU** | **Sí está por SNMP:** tabla de service-port `…1082.110.5.2.2.1.27.<ifIndexPON>.<spKey>` = perfil de **subida** y `…28` = perfil de **bajada**, con `spKey = (0x18<<24)\|(onu<<16)\|0x0100`; coincide **26 de 26** ONU con `show running-config-interface vport-<pon>.<n>:1`. Además T-CONT por ONU `…1082.500.10.2.3.4.1.3.<ifIndexPON>.<onu>.<tcont>` y nombre de GEM `…3.5.1.2`. `show onu running config` no existe en C6xx (se usa `show running-config-interface gpon_onu-<idx>` y `…vport-…`). Añadido al catálogo en `snmp-olt-zte_c6xx_onu_profiles.txt`. |
| **ONU sin autorizar y MAC** | Solo CLI (`show pon onu uncfg [gpon_olt-<pon>]`, `show mac interface gpon_onu-<idx>`); `uncfg` sin argumento devuelve todos los puertos en una sola sesión (no hace falta una por puerto). |
| **Índice de ONU** | La ONU **no** usa un índice compuesto de 32 bits: la clave SNMP es `<ifIndexPON>.<nºONU>` (y `.1` extra en potencias). `ifIndexPON` = `0x1101xxxx` (C620: slot bits 10-8, puerto bits 4-0; C600: slot bits 11-8) y se resuelve con `ifName` (`gpon_olt-1/1/N`). Ejemplos reales: `…3.8.1.4.285278465.1` → `0x11010101` = `1/1/1:1`; `285278466.1` → `1/1/2:1`; `285278467.39` → `1/1/3:39`; `285278472.30` → `1/1/8:30`; `285278478.3` → `1/1/14:3`. Verificado en 277 ONU C620 (tipo 270/270, serial 269/270) y 375/375 C600. |
| **Reconocer el modelo** | C620: `sysDescr` = `ZXA10 C620, ZTE ZXA10 Software Version: V1.2.2`, `sysObjectID` = `.1.3.6.1.4.1.3902.1082.1001.620.1.1`. C600: `ZXA10 C600, ZTE ZXA10 Software Version: V1.2.2_RZ`, `.1.3.6.1.4.1.3902.1082.1001.600.1.1`. `show version` no existe (usar `show software 1`). Regex `/c6\d\d/i` sobre `sysDescr`. |
| **Huecos del walk** | 25 rangos: 4 en `3.6000.51.2` (tablas de operadores/usuarios), 21 en `1082.70.67.2` (perfiles de seguridad por nombre) y 1 de la columna lenta `…500.20.2.1.25` (ya capturada aparte). **Ninguno afecta a ONU (`1082.500.10`), VLAN (`1082.40.50`), tarjetas (`1082.10.1.2.4`), puertos ni perfiles de velocidad**: son ruido para el importador. |
| **C600 sin evidencia de escritura** | Correcto: solo ayuda/configuración vista, sin ONU en espera; crear perfiles o dar de alta debe responder 501 en C600. Las lecturas sí están verificadas (sección C y L). |
| **Código (otro repositorio)** | Sin acceso a `network-api`: reconocer C620 en el factory y en los sitios que distinguen C600, parsers con fixtures reales y token `gpon_onu-`. |
**Fixtures pedidas:** disponibles en crudo en `docs/walks/diagnostics/` (con seriales; sin anonimizar): lista de VLAN, `show card`, `show running-config-interface` de 26 ONU por OLT (incluye CATV en C600: `interface video video_0/1 state lock`), lista de ONU de un puerto (`show gpon onu state|baseinfo`) y `show pon onu uncfg`. Falta empaquetarlas **anonimizadas** (seriales, MAC, IP, nombres/direcciones de abonado) con el script del otro repo.

## AB. Carga de la C620 a `ispm_tkc` (ejecutada por el usuario)
`python -m src.loader load zxa10-c620 --version 1.1.0`: **OK**, versión 1.1.0 (tier 4, `verified_walk=45`), `catalog_version_id=10`. Filas cargadas: **13 entidades, 74 comandos, 1.772 OIDs, 7 relaciones y 117 alarmas**. Los 74 comandos nuevos (37 lecturas + 37 escrituras) entraron sin errores de enums ni longitudes. Pendiente: recargar la C600 (`zxa10-c600`) con el mismo comando.

## AC. Plan del importador (`docs/plans/zte-c620-plataforma-cli-2026-10-02.md`, otro repo) frente al TKC
**Veredicto sobre los 5 hallazgos del plan:** 1, 2 (código), 4 y 5 coinciden con nuestra evidencia. **3 (cambio de tipo = baja+alta) es la decisión segura pero no está probada como imposible:** la OLT sí ofrece la operación (`Need to restore ONU after modification, confirm to modify? [yes/no]`), y en nuestra prueba falló con `222366` en una ONU no activa cambiando a un tipo con otras interfaces; no se probó con una ONU en línea ni con un tipo equivalente. **D3 (velocidad en el service-port) coincide con lo observado en 52 ONU y verificado por SNMP (26/26).** `gemport traffic-limit` es otro mecanismo (perfiles `onu profile traffic`, verificado).
**Lo que el plan necesita y ahora existe en el TKC:** `docs/validation/commands/zte_c6xx_cli_behavior.json` (transporte, prompts con regex, confirmaciones `[yes/no]`, catálogo de 20 códigos `%Error` con significado y si son inocuos, límites SNMP/ONU, tiempos) y `docs/validation/commands/zte_c6xx_provisioning_recipes.json` (recetas con pasos, verificación y rollback: alta Internet, alta con WiFi, WAN DHCP, cambio de velocidad, crear perfil, baja, reinicio, guardar).
**Aún pendiente del lado TKC:** (a) fixtures anonimizadas; (b) ~~rango real de ONU por puerto~~ **resuelto en AI: 1–128**; (c) 5 comandos residuales (agente en segundo plano); (d) recarga de la C600.

## AD. Fixtures anonimizadas para el importador
`scripts/build_c6xx_fixtures.py` → `docs/fixtures/zte-real/c620-20261002/` y `c600-20261002/`: `cli/` (34 salidas en C620, 38 en C600: lecturas de ONU, estado, detalle, configuración de puerto/ONU/vport —incluye ONU con CATV en la C600—, service-port, MAC, VLAN, tarjetas, perfiles, potencias, `remote-onu`, alarmas, `show software`), `snmp/` (20 archivos: columnas por ONU de las 8 primeras ONU del puerto 1, perfiles de service-port, tarjetas, VLAN, perfiles de velocidad, `ifName`/`ifTable`, `ifX`, `system`), `ground_truth.json` (índice SNMP ↔ ubicación CLI y estado de cada ONU de muestra) y `README.md`. Anonimización determinista de seriales (se conserva el prefijo de fabricante), MAC e IPv4 en la salida CLI; se excluyen las columnas de nombre/descripción del abonado; las líneas SNMP conservan sus OID (se corrigió un fallo inicial que alteraba OID con forma de IPv4). Verificación: 0 coincidencias de seriales reales en ambos paquetes. Limitación: una sola OLT por modelo (no prueba otros firmwares).

## AE. Informe del agente de scripts para los residuales (hallazgos de la ayuda `?`, solo lectura)
Script: `scripts/c620_pending_cli_test.py` (81 comandos permitidos, ONU de prueba 1/1/5:3, `started`, rollback verificado, sin `write`); **no ejecutado**. Uso: `.venv/bin/python scripts/c620_pending_cli_test.py <SN en espera> [--sections 1,2,3,4,5] [--resource-mode2]` (`--resource-mode2` cambia un ajuste del puerto y está desactivado por defecto).
| Residual | Causa según la ayuda (por confirmar con el script) |
|---|---|
| `gemport … portid` (222370) | "Only supported when resource assign mode is mode2": `resource mode1` (por defecto, asignación automática) vs `resource mode2` (manual) en `interface gpon_olt-<pon>`; cambiarlo afecta a las ONU del puerto: solo en ventana de mantenimiento. |
| `no vport-map` (222386) | Sintaxis `no vport-map <vport> <gem> [cos\|vlan]`; hipótesis: hay que repetir el `vlan <V>` del alta. |
| `wifi enable domain` (230263) | `domain bra` solo con `work-mode 802.11b`; `domain` va antes de `channel`; canal 0-11 para CAN/USA; `tx-rate` con 802.11b solo auto/1/2/5.5/11. |
| `onu-type-if … video_0/1` (230263) | El CATV se declara como **`rf_0/1`** (tipos reales ZTE-F625/F628/F640, LATIC, PROFILE-DEFAULT); `show onu-type-if <tipo>` lista las interfaces de un tipo. |
| `splitter` (230263) | No hay tabla de splitters; `splitter <WORD>` es texto libre (≤32 caracteres, campo `Splitter:` de `detail-info`); hipótesis: el tipo necesita `location enable`. |
Otros: `type <WORD> [force]` aparece en la ayuda de `interface gpon_onu`; `onu-type … gpon` admite `speed-mode auto|gpon|xg-pon|xgs-pon`; `show gpon global config` funciona. Catálogo actualizado con estas notas y 2 comandos nuevos (`splitter`, `show onu-type-if`).
**Nota de proceso:** el agente entró en modo config sobre la ONU real `1/1/5:1` y sobre interfaces del puerto solo para pedir ayuda con `?` (sin Enter, sin cambios).

## AF. Script para medir el rango real de ONU por puerto (preparado, no ejecutado)
`scripts/c620_onu_range_test.py <SN en espera> [--indices 64,96,127,128,129,130,192,255,256] [--pon 1/1/5]`: para cada índice libre autoriza la ONU de prueba (`onu N type LATIC sn <SN>`), observa 90 s si registra (cualquier fase distinta de OffLine), hace `no onu N` y espera a que vuelva a la lista de espera; verifica configuración idéntica. Lee además `show gpon global config|olt|slot` por si la OLT informa su capacidad. Resultado clave: `max_indice_que_registra` y `min_indice_que_no_registra`. Hipótesis a contrastar: límite de 128 ONU por puerto (el 250 no registró; las ONU reales llegan a ~49).

## AG. Script de residuales (`c620_pending_cli_test.py --sections 2,3,4,5`), primera ejecución
**Hecho:** sección 4 completa. En un tipo con eth/wifi/rf (`TKCTEST-TYPE`) y en un tipo mínimo (`TKCTEST-MIN`): `onu-type-if … rf_0/1` **OK**; `video_0/1`, `video-ani_0/1` y `catv_0/1` → `230263 Parameter error`. **El CATV se declara únicamente como `rf_0/1`** (resuelve el residual `video_0/1`; en `pon-onu-mng` la configuración sigue siendo `interface video video_0/1 …`/`interface video-ani …`, que exige que el tipo tenga `rf_0/1`). `show onu-type-if <tipo>` verificado: lista `Interface list` con `eth_0/1`, `rf_0/1`, `wifi_0/1`. Rollback OK (tipos de prueba eliminados, configuración del puerto idéntica a la inicial).
**No ejecutado:** secciones 2 (`no vport-map`), 3 (`wifi domain`) y 5 (`splitter`): el alta de la ONU de prueba falló con `%Error 222320: GPON ONU sn already exists` porque el script del rango (`c620_onu_range_test.py`) tenía esa misma ONU autorizada en otro índice (se vio `onu 96 …` y después `onu 127 …` en la configuración del puerto) **mientras corría en paralelo**. No es un fallo de la OLT ni del script: los dos scripts comparten la ONU de prueba y no deben solaparse. Efecto colateral inocuo: la línea `onu 96` de esa foto formaba parte de la configuración «inicial» del script de residuales, que por eso no la tocó.
**Pendiente:** esperar a que el script del rango termine (limpia sus índices) y repetir `--sections 2,3,5`.

## AH. Segunda ejecución solapada del script de residuales
Mismo resultado que en AG: el alta en el índice 3 falló con `222320 sn already exists` porque el script del rango (aún en curso) tenía la ONU de prueba autorizada en el índice 128. Sin cambios en la OLT (rollback OK, configuración idéntica). Las secciones 2 (`no vport-map`), 3 (`wifi domain`) y 5 (`splitter`) siguen pendientes y **solo se pueden ejecutar cuando el script del rango termine** (comparten la ONU de prueba). Lectura parcial del registro del rango (solo lectura del archivo de salida): índices 64, 96 y 127 **registran** (fase distinta de OffLine; el 96 y el 127 tardan ~60 s en pasar de OffLine a syncMib, el 64 ~10 s); el 128 estaba en prueba.

## AI. Rango real de ONU por puerto (C620, puerto 1/1/5; ejecutado por el usuario con `c620_onu_range_test.py`)
`RESULTADO`: `max_indice_que_registra = 128`, `min_indice_que_no_registra = 129`, `rollback_ok = true`, `config_puerto_identica = true`, `back_in_uncfg = true`.
| Índice | Autorización | Resultado en 90 s |
|---|---|---|
| 64 | OK | registra (syncMib a los 10 s; oscila con LOS, como esta ONU de prueba) |
| 96 | OK | registra (OffLine ~50 s → syncMib → Logging) |
| 127 | OK | registra (igual que el 96) |
| **128** | OK | **registra** (syncMib a los 60 s) |
| 129, 130, 192, 255, 256 | OK (sin error) | **no registran**: OffLine con OMCC `disable` los 90 s (el 250 tampoco en 4 min) |
**Conclusión: el rango operativo es 1–128 ONU por puerto.** La sintaxis (`1-256`) y la OLT aceptan sin error la autorización de 129–256, pero la ONU nunca se pone en línea: el importador debe validar 1–128 (la OLT no lo avisa). Los índices altos tardan ~60 s en salir de OffLine (los bajos, ~10 s), de modo que 90 s es margen suficiente para el corte en 128/129 (los tres índices ≥129 más cercanos y el 250 de 4 min confirman que no es cuestión de espera). Efectos colaterales a tener en cuenta: con un índice ocupado, el mismo SN no puede autorizarse en otro (`222320`), y la ONU puede seguir listada en `show pon onu uncfg` mientras no esté registrada. Se resuelve la duda abierta del plan del importador (usar 1–128). `behavior.json`, recetas y catálogo de comandos actualizados.

## AJ. Residuales (secciones 2, 3 y 5 del script `c620_pending_cli_test.py`; C620, ejecutado por el usuario; rollback verificado)
Con el script del rango ya terminado: alta de la ONU de prueba OK, rollback OK, configuración del puerto idéntica.
- **`no vport-map` (S2): resuelto.** `no vport-map 2 2 vlan 102` **sí borra** el mapeo (verificado releyendo la configuración: `mapeo borrado: true`); `no vport-map 2 2`, `… cos 0`, `2 1` y `2 102` dan `222386`. Hay que **repetir el `vlan <V>` del alta**. `no vport <n>` sigue limpiando el vport completo.
- **`wifi enable domain` (S3): resuelto.** Orden obligatorio **work-mode → domain → channel** (`wifi enable channel 6 work-mode … domain …` da Invalid input). `domain bra` solo con `work-mode 802.11b` (sin él: `230263`): `wifi enable work-mode 802.11b domain bra channel 6 [tx-power-percent 80]` OK. Los demás países valen con cualquier modo o sin modo: `wifi enable domain usa channel 6`, `domain chn|esp`, `work-mode 802.11b-11g-11n domain ger|fra|uk|esp|chn|usa`; 5 GHz: `wifi 5g enable domain chn|usa channel 36` OK. Configuración guardada: `wifi enable work-mode 802.11b-11g-11n channel 6 tx-power-percent 80` y `wifi 5g enable work-mode 802.11a-11ac-11n domain usa channel 36` (el dominio por defecto del 2,4 GHz no se guarda). `wifi enable` sin parámetros OK.
- **`splitter` (S5): resuelto, y la hipótesis del agente era errónea.** El formato son **niveles numéricos separados por guion**: `splitter 1-2-3` OK; `TKCSPL` y `L1-L2-L3` → `230263`, tanto con `Location: disable` como intentando `enable`. `onu-type … gpon location enable` falló con `230296 Profile is being used` (un tipo en uso no se puede modificar), así que `location` no interviene. `no splitter` OK. (El campo `Splitter:` de `detail-info` salió vacío porque el script lo leyó después de `no splitter`; el valor guardado no se llegó a ver.)
- **Sigue sin probarse:** `gemport … portid` (exige `resource mode2` en el puerto PON; cambiar ese ajuste afecta a las ONU del puerto: no se ejecutó la sección 1 a propósito).
Catálogo (`splitter` pasa a `verified`, notas de `vport-map` y `wifi` corregidas) y `cli_behavior.json` (`230296`) actualizados.

## AK. `gemport … portid`: aclaración y prueba segura preparada
**El gemport del aprovisionamiento ya está verificado** (`gemport <n> name <x> tcont <m> [queue <0-7>]`, alta con 52 ONU reales y creación/borrado en la ONU de prueba). Lo único que falla es la **asignación manual del Port-ID** (`gemport … portid`, `222370`) y del Alloc-ID (`tcont … allocid`): la ayuda dice que solo se admiten con `resource mode2` en el puerto PON (por defecto la OLT asigna ambos automáticamente en `mode1`), por lo que **no es necesaria** para autorizar/aprovisionar.
**Puertos vacíos (lectura):** 1/1/4, 1/1/13, 1/1/15 y 1/1/16 no tienen ONU configuradas (ONU por puerto: 1:40, 2:43, 3:54, 5:19, 6:16, 7:1, 8:63, 9:15, 10:11, 11:6, 12:1, 14:9). Cambiar `resource` ahí no puede afectar a ningún cliente.
**Script:** `scripts/c620_gemport_portid_test.py <SN en espera> [--pon 1/1/16]`: comprueba que el puerto está vacío → `resource mode2` → alta de la ONU de prueba (solo configuración) → `gemport 2 name tkc portid 300 tcont 1`, `gemport 3 portid 301 tcont 1`, `tcont 2 allocid 300 profile …`, `tcont 3 name … allocid 301 profile …` → relee → rollback (`no onu 1`, `resource mode1`) comparando la configuración del puerto. Pendiente de ejecución por el usuario.

## AL. `gemport … portid` / `tcont … allocid` con `resource mode2` (C620, puerto vacío 1/1/16; ejecutado por el usuario)
Rollback OK; configuración del puerto **idéntica** a la inicial; sin `write`; ningún cliente afectado (puerto sin ONU).
- **`resource mode2`: OK** y reversible. En la configuración del puerto aparece como `resource-id-assign-mode mode2`; `resource mode1` elimina la línea y deja el puerto como estaba (en mode1, por defecto, la configuración no muestra ids).
- **Con mode2 la configuración de la ONU lista los ids asignados:** `tcont 1 allocid 1024 profile SMARTOLT_DEFAULT_TCONT_GPON` y `gemport 1 name internet portid 1024 tcont 1`. En mode1 (los 52 ONU reales) esas líneas van sin `allocid`/`portid`. **Los parsers deben aceptar ambas formas.**
- **Valores manuales rechazados:** `gemport … portid 300` → `%Error 230405: Port-id is out of range`; `tcont … allocid 300` → `%Error 230404: Alloc-id is out of range`, aunque la ayuda diga `129-4095`/`256-4095`. Los asignados automáticamente empiezan en **1024**, que es el rango plausible; no se probó un valor ≥1024 (el script quedó ajustado para probar 1025/1026).
- La ayuda confirma: `portid`/`allocid` «Only supported when resource assign mode is mode2»; `tcont` admite `allocid`, `gap`, `name`, `profile`.
- **Conclusión:** la asignación manual no es necesaria para autorizar/aprovisionar (la OLT la hace sola en mode1). Catálogo y `cli_behavior.json` actualizados (códigos 230404 y 230405, sección `resource_assign_mode`).

## Diferencias reales de sintaxis entre C620 y C600
1. `show gpon remote-onu ssid …`, `wifi {enable|disable|5g}`, `ssid auth|ctrl` y `wifi 5g`: **solo C620**.
2. `show gpon remote-onu mgmt-ip|wan|dhcp-client`: solo C620; `mgc-service|voip-ip|tr069-mgmt`: solo C600.
3. `show software` acepta slots `<1-7>` en C620 y `<1-21>` en C600 (el chasis de la C600 es mayor).
4. El resto son módulos opcionales del firmware (no afectan a la importación de ONU).

**Cómo detectar la plataforma:** ambas responden a `sysDescr` con `ZXA10 C6x0` y a `show software 1`
con `ZXA10 C620` / `ZXA10 C600` en la primera línea; la sintaxis de ONU, puerto PON y MAC es la misma,
así que un regex `/c6\d\d/i` es suficiente; `ssid`/`wifi` se activa solo si la ayuda de
`pon-onu-mng` lo ofrece.


## AM. VLAN por SNMP (C620, solo lectura)

- `dot1qVlanCurrentTable` (`.17.7.1.4.2.1`): 1 fila por columna y bitmaps egress/untagged en cero; `dot1qVlanStatic` (116 líneas) igual. `dot1dBasePortIfIndex`: 9 entradas. **La relación VLAN–puerto no se expone por Q-BRIDGE.**
- Tabla de service-port ZTE, fila `<ifIndexPON>.<spKey>`: col 8 = BeginVid, col 18 = Vlan, 27/28 = nombres de perfil ingress/egress. Comparado con CLI en 26 ONU: **26/26 coinciden**.
- Consecuencia para el importador: la VLAN de una ONU se lee por SNMP; qué VLAN llega a qué uplink/vport solo con CLI (`show vlan <id>`).
- Pendiente (sin ejecutar): `scripts/c620_retype_splitter_test.py` (valor guardado de `splitter` y cambio de tipo equivalente con [yes/no]); lo ejecuta el usuario.

## AN. Repetición portid/allocid (C620, puerto vacío 1/1/16; ejecutado por el usuario)

- `gemport 2 name tkc portid 1025 tcont 1`, `gemport 3 portid 1026 tcont 1`, `tcont 2 allocid 1025 …`, `tcont 3 name … allocid 1026 …`: **OK** en mode2. `portid 300` → 230405, `allocid 300` → 230404 (rango mínimo efectivo 1024).
- La ayuda confirma `portid`/`allocid`: «Only supported when resource assign mode is mode2».
- En la config el modo aparece como `resource-id-assign-mode mode2` (el comando de entrada es `resource mode2`); el flag `config_puerto_con_resource_mode2` del script salió false por buscar el texto equivocado (error del script, no de la OLT).
- Rollback (`no onu 1`, `resource mode1`): config del puerto idéntica, ONU de prueba sigue en espera.

## AO. `splitter` y cambio de tipo (C620; ejecutado por el usuario)

- `splitter 1-2-3` → OK; `show gpon onu detail-info` muestra `Splitter: 1-2-3` y la config `splitter 1-2-3`. `no splitter` → OK y el campo queda vacío.
- `type ZTE-F600` (desde LATIC): pide «Need to restore ONU after modification, confirm to modify? [yes/no]»; `yes` → `%Error 222366: Modify ONU type failed.` El tipo sigue LATIC y la config no cambia.
- Conclusión: no se puede cambiar el tipo en sitio (ni a uno equivalente, ni con la ONU nunca en línea); el flujo es borrar la ONU y autorizarla con el tipo correcto.
- Rollback (`no onu 3`): config del puerto idéntica, la ONU vuelve a la lista de espera.


## AP. Correcciones y mejoras del catálogo (C620 y C600; sin ejecutar nada en las OLT)

Copia previa en `staging/backup_pre_refine_c620|c600/`. Ningún `id` existente cambió (verificado: 1772 → 1788 OID, 0 quitados).

**Correcciones:** tensión óptica 0.01→0.001 V (5 OID); `pon_rx_power_detect_period` sin escala (900 s); 32 OID con unidad «0.001 dBm/mA/…» pasan a tener `scale` y `unit` separados (antes `scale` nulo); firmware de OID/entidades/alarmas/relaciones = 1.2.2 (igual que los comandos); 43 hojas sin nombre MIB pasan a `name = attribute`; `onu_id_append=false` en 17 escalares/IF-MIB; rx/tx de ONU con unidad dBm y centinela 65535; manifest sin rutas de ficheros y con el veredicto de bitcalc «accepted».
**Mejoras:** 16 OID IF-MIB en `uplink_port` (3 + 4 contadores de error verified_walk; HC e `if_high_speed` `inferred` porque el walk no trae ifX de xgei); 75 atributos de entidad; entidades `tcont_profile`, `traffic_profile`, `onu_traffic_profile` (los 9 comandos de perfiles las usan en `entity_ref`; sus ids no cambian); relaciones onu→pon_port(0)→tcont_profile(1)→gem_port(2)→service_port(3) y service_port→traffic_profile, `verified`; 4 alarmas de ONU por causa de baja (LOS, LOSi, DyingGasp, DeactiveSucc); comandos: parámetros extraídos de la sintaxis (58→19 sin), `related_commands` (76→31 sin), prerrequisitos por contexto.
**Inventario de lo no catalogado:** `docs/validation/observed_uncataloged_c620.json` (731 subárboles, 643 052 filas); no lo carga el loader.
**Pendiente (no hecho):** catalogar esos subárboles con definición; probar `show alarm` y `show pon onu offline information`; rollback de los demás `modify` (solo `no splitter` está verificado).


## AQ. Walks residuales de la C600

- `scripts/c600_residual_walks.sh` (solo lectura, GETNEXT con `-Cc`): preflight OK (V1.2.2_RZ).
- Columnas 26, 27, 28 y 29 de `1082.500.20.2.1`: GETNEXT devuelve `…2.1.30.1.1.285278465.1` → no existen; el hueco declarado queda cerrado (columna 25 ya capturada aparte).
- Inspector `3.6000.51.2.3.7`: 4 columnas × 750 filas, termina en la última fila de la última columna → completo. Perfiles `1082.70.67.2.3.1`: 1330 filas hasta la columna 50 → completo.
- Se anexaron 2546 filas nuevas a `docs/walks/ZTE_C600.txt` (copia previa en `staging/ZTE_C600.txt.pre_residual`); el encabezado del walk sigue diciendo INCOMPLETE porque el colector no se volvió a ejecutar. Catálogo C600 regenerado: mismos OID (no añadió ninguno nuevo; son subárboles sin definición MIB) y inventario `docs/validation/observed_uncataloged_c600.json` (709 subárboles, 855 105 filas).
- La C620 tiene los mismos dos huecos `nonincreasing` (inspector y perfiles) sin cerrar.


## AR. Análisis del documento de hallazgos del importador (2026-10-09)

**Coincide con el TKC:** sintaxis C6 vs clásicas, `show software 1`, `show pon onu uncfg`, plantilla de alta con perfiles en el service-port, `traffic-limit` con perfiles SMARTOLT → 223981, cambio de tipo → 222366 tras `[yes/no]`, `reboot` con confirmación, `write` → `......[OK].`, `Name/Description` enmascarados, `wifi-info` con guion inválido (la sintaxis es `wifi info`, ya catalogada y verificada también en C600).
**Nuevo, incorporado:** `show logfile brief` (bitácora de comandos, bloques Time/User/CMDLine, ~14 h) y `show logging alarm` (alarmas/notificaciones: `An alarm n-(m) ID i level l occurred|cleared at …` + `%GPON% … olt losi(lobi)|dgi (rack/shelf/slot/port/onu)`), ambos ejecutados hoy en la C620 (solo lectura) → `verified` en C620; C600 sin probar. `real-speed gpon` → 230240 se anotó en el documento de comportamiento (no reproducido).
**Discrepancia:** el documento da `ssid info` como sintaxis válida en C600; la verificación del TKC (2026-10-01/02) la rechazó en C600 y solo existe en C620. Pendiente de que el importador lo reconfirme con su script.
**Desactualizado:** «capturar `1082.70` completa» — el TKC ya la tiene (C600: hueco cerrado con el walk residual, fila 36; C620 en curso, fila 38).
**Seguridad:** la community de lectura expone `3902.3.6000.51.2.1` (usuarios `smartoltusr`/`zte` con contraseña codificada reversible). Esa columna está en los walks locales `docs/walks/ZTE_C620.txt`/`ZTE_C600.txt` (ignorados por git, no están en catálogo ni fixtures: verificado). Se activó `walk_collector.redaction` en `config/pipeline.yaml` para el prefijo `.1.3.6.1.4.1.3902.3.6000.51.2.1.1.1.2` en walks futuros. Recomendado: rotar esas contraseñas y restringir la vista SNMP RO (excluir `3902.3.6000`); cerrar el HTTP de la C600 expuesto a internet.


## AS. Walks residuales de la C620 y comandos nuevos

- Mismos dos huecos `nonincreasing` que la C600, cerrados con `snmpwalk -Cc` desde `.env` (solo lectura). Inspector `3.6000.51.2.3.7`: 3016 filas, 754 por columna; perfiles `1082.70.67.2.3.1`: 1330 filas, 190 por columna. Copia previa del walk en `staging/ZTE_C620.txt.pre_residual`.
- Incidencias del propio script: (1) `source .env` falló por la contraseña de la base sin comillas y la imprimió en el log local `staging/c620_residual.log` — se borró esa línea y el script ahora lee solo la variable pedida; (2) se editó el script mientras corría y el paso del inspector se truncó — se repitió aparte. Recomendación: poner comillas a los valores del `.env`, y rotar la contraseña de la base (ya estaba pendiente).
- Catálogos C620 (78 comandos: 76 verified + 2 documented) y C600 (74) regenerados.


## AT. Enlace OID ↔ comandos

- Fuente única: `OUTMAP` en `scripts/build_c620_command_catalog.py` (campo de salida → id de OID); `refinements.py` rellena `command_ref` en los OID a partir de esos `oid_ref`.
- Mapeados: estado/fase (`onu_status`), serie, tipo, distancia, última autenticación/baja/causa, potencia rx/tx de la ONU (`pon_power`), CIR/CBS/PIR/PBS del perfil de bajada, VLAN de usuario y C-VLAN del service-port y nombres de perfil ingress/egress. Sin equivalente SNMP (quedan `not_mapped`): uncfg, tabla MAC, `admin_state`/`omcc_state`, `attenuation_db`, `olt_rx_dbm` (no confirmado), bitácoras.
- Se añadieron campos de salida a `show gpon onu baseinfo` y `show service-port interface`. Ids de comandos y OID sin cambios.


## AU. OID `documented`: por qué no se confirman

- Ninguno de los 625 tiene instancias en el walk (C620 y C600 idénticos), así que ninguno puede pasar a `verified` por lectura: no es un hueco del walk sino de lo que el equipo expone.
- `structure_node` 311 (tabla/entrada), `table_empty` 287 (columnas read-write/read-create de tablas sin filas: configuración no usada), `notification` 10 (objetos de trap), `absent_in_populated_table` 17 (la tabla tiene filas y la columna no aparece): `vlan.if_acceptable_frame_types`, `pon_port.pon_rx_power_restore_default`, `service_port.srv_port_queue_id`, `olt.ether_if_holdoff_time`, `card.cpu_load_threshold`, `card.mem_usage_threshold`, `onu.pon_rogue_onu_*` (4), `power_supply.env_*` (6), `shelf.logic_shelf_no`.
- Cada uno lleva `pending_validation = {category, reason, walk_instances: 0}` (lo carga el loader en `tkc_oids.pending_validation`). El estado y el id no cambian. Esas 17 columnas son candidatas a retirar o marcar como no soportadas si una lectura directa (GET) devuelve noSuchObject.


## AV. Columnas no expuestas (C620)

- `scripts/check_absent_columns.py c620` hace un `snmpgetnext` por columna: en las 17 el siguiente OID devuelto no cuelga de la columna → el equipo no la expone. Resultado guardado en `docs/validation/absent_columns_c620.json` y leído por `refinements.py` (`pending_validation.category = not_exposed`).
- Los OID siguen en el catálogo como `documented` (no se retiraron, para no cambiar ids). C600: falta ejecutar `python scripts/check_absent_columns.py c600` con su community.


## AW. Comprobaciones opcionales previas a la carga (C600)

- `scripts/c600_optional_checks.py` (solo lectura, credenciales por prompt oculto): GETNEXT de las 17 columnas → todas `NO EXPUESTA` (`docs/validation/absent_columns_c600.json`).
- Ayuda de `show gpon remote-onu ?` en la C600: 50 subcomandos, incluye `wifi` pero no `ssid` → `ssid info` es solo C620 (el documento del importador lo daba por válido en C600: discrepancia resuelta a favor del catálogo). Hay muchos subcomandos sin catalogar (`ip-host`, `wan`, `voip`, `igmp`, `mac-filter`, `firewall`, `lct`, `performance`…).
- `show logfile brief` (357 líneas) y `show logging alarm` (326 líneas) aceptados en la C600 → `verified` en ambas familias. Catálogo: C620 78 comandos, C600 76.
- El resumen está en `docs/validation/c600_optional_checks.json`; la salida cruda (con el usuario de sesión) en `docs/walks/diagnostics/` (ignorada por git).


## AX. ONU sin autorizar por SNMP (C620)

- Corrección: el catálogo y el informe decían «por SNMP no existe tabla uncfg: solo CLI». Era falso: la tabla estaba en el walk de la C620 en `1082.500.2.2.11` (la rama de las clásicas `500.10.2.2.5` está vacía en C6). Se encontró al buscar los seriales de las ONU sin autorizar (bytes ASCII en Hex-STRING) en el walk.
- Columnas confirmadas contra la CLI en vivo (2026-10-09): 2 serial, 3 PW, 8 modelo, 10 firmware, 12 primer hallazgo (`FirstFind 00:00:54`), 13 último hallazgo. Sin confirmar: columnas 4, 5, 6, 7, 9, 11, 14, 15, 16 (la razón de fallo de autenticación «Others» es una de 14-16).
- Doc: `docs/validation/community/snmp-olt-zte_c6xx_uncfg_onu.txt` (solo C620). C600: la tabla no se ha visto (0 ONU sin autorizar) → pendiente de comprobar con una ONU en espera. Fixture: `docs/fixtures/zte-real/c620-20261002/snmp/uncfg_autofind.txt` (seriales y MAC ficticios).
- Se probó un alias `onu_type` sobre el OID de `onu_type_name` y se descartó: la ingesta fusiona por OID y habría renombrado el id existente.


## AY. Versión 1.2.0 y puerta de contrato

- Los cambios de datos hechos el 2026-10-09 sobre la 1.1.0 eran incompatibles (firmware, escala, unidad, ids nuevos): se publican como 1.2.0. La 1.1.0 anterior sigue en la base (si se cargó) y sirve de vuelta atrás; su contenido previo a los refinamientos queda en `staging/backup_pre_refine_c62*/catalog-1.1.0`.
- `scripts/catalog_diff.py` compara dos catálogos campo a campo y marca los cambios posibles de incompatibilidad. Su primer uso encontró un fallo real: las 4 alarmas de ONU que decía añadir `refinements.py` no se escribían en disco (el archivo se releía antes de guardarlo). Corregido; ahora `alarms/onu.json` tiene 5.
- `scripts/catalog_contract_check.py` (también test `tests/test_catalog_contract.py` y puerta en `python -m src.loader load`): integridad (ids únicos, sin huérfanos, firmware uniforme, sin UNRESOLVED ni multiplicador en la unidad) y 16 atributos de consumo (C620) / 6 (C600) contra las fixtures reales: serial, estado contra la verdad de terreno de la CLI, potencias en dBm, distancia, perfiles, `oper_status`, `uncfg_*`. Encontró un defecto real en la C600 (`onu_rx_power` sin unidad), ya corregido.
- Suite de pruebas: 119 correctas.


## AZ. Cargas fallidas a la base y mejoras de la puerta

- Error 1205 (Lock wait timeout): otro `src.loader` seguía abierto en otro terminal (C600).
- Error 1644 (escritura no autorizada): los triggers exigen una sesión efímera viva (TTL 5 min) y la carga de la 1.2.0 la superaba. `Loader._insert` renueva la sesión cada 200 inserciones (`UPDATE active_sessions`).
- Error 1265 (Data truncated, `alarm_type`): las 4 alarmas de ONU añadidas el 2026-10-09 usaban `type: equipment` y `severity: info`, que no existen en los ENUM de `tkc_alarms`. Ahora LOS/LOSi = optical/major, DyingGasp = power/warning, DeactiveSucc = protocol/warning. Cada intento fallido hizo rollback.
- La puerta de contrato (`scripts/catalog_contract_check.py`) valida ahora cada fila que construiría el loader contra los ENUM y los VARCHAR de `database/ispm_tkc.sql` (18 624 comprobaciones, 0 fallos); este tipo de fallo ya no llega a la base.
- Catálogo: `onu_status` de la C600 incluye `2: LOS` (no observado en C600, verificado en C620); `onu_name` y `onu_description` llevan `sensitivity: pii`.


## BA. Carga 1.2.0 completada

- C620 1.2.0 → `catalog_version_id` 13; C600 1.2.0 → 14. Las cifras cargadas coinciden con las del catálogo local.
- Pendiente: `python -m src.loader status` (SIN CAMBIOS y vigente), aviso al importador y rotación de credenciales.


## BB. Análisis frente al diagnóstico del consumidor

- Informe completo: `reports/analisis_catalogos_vs_diagnostico_2026-10-09.md`.
- Lectura CLI de solo lectura en la C620 (`show pon power attenuation` en 4 ONU) para confirmar la hipótesis D-02; sin escrituras.
- Errores míos reconocidos: receta con CBS=PBS=128 KB (el dato real es CIR/80), alarmas `offline_cause_*` sin marca de histórica, 16 atributos de `uplink_port` con nombres repetidos, y errores 223981/230240 que solo vivían en `cli_behavior.json` (que no se carga).
- Sin cambios en catálogos en esta sección; el plan queda en el punto 3 del informe.


## BC. Versión 1.3.0 (C620 y C600)

- Implementa el punto 1 del plan de `reports/analisis_catalogos_vs_diagnostico_2026-10-09.md`: D-02, D-03, D-05, D-06, D-08, D-09 (receta), D-12, D-13, D-15 y P-4.
- La 1.2.0 anterior queda copiada en `staging/release_1.2.0/{c620,c600}` y, si se cargó (ids 13 y 14), sigue en `ispm_tkc` como vuelta atrás.
- Cambio incompatible a comunicar: los 16 atributos de `uplink_port` cambian de nombre (`uplink_*`); el resto son adiciones.
- Hallazgo durante la regeneración: el grupo `uplink_port.json` no lo crea la semilla; solo existía por haber reutilizado un directorio. `refinements.py` ahora lo crea (si no, una regeneración limpia habría perdido los 16 OID).
- Sin tocar: C300/C320 (punto 2 del plan, sin ejecutar), 230240 sin comando (sintaxis no verificada), D-07/D-11/D-14.
- Pendiente: cargar 1.3.0 (C620 y luego C600) con el loader.


## BD. Reanálisis final antes de subir la 1.3.0

- **Hallazgo crítico (corregido):** los 9 000+ hallazgos `ascii_index` de `results.json` incluían el índice decodificado de `snmpCommunityTable` (`3902.3.6000.101.2.3`: 4 nombres por OLT, entre ellos la comunidad de escritura que se pegó en el chat), de la tabla de usuarios y del registro de peticiones web (`3902.3.6000.51.2`, `3902.3.101.7.5`). Se cargan en `tkc_results.payload`: **las versiones 1.1.0 y 1.2.0 ya cargadas los contienen**. En C300/C320 no ocurre (sus walks no traen la rama 3.*).
- **Corrección:** `refinements.py` elimina esos hallazgos y deja uno `sensitive_branch_redacted`; la puerta falla si reaparecen (2 fallos antes de regenerar, 0 después). Búsqueda de los 4 valores en catálogo, fixtures, docs e informes: sin coincidencias (solo `staging/`, ignorado por git).
- **Limpieza de la base:** `scripts/purge_sensitive_results.py --user <superadmin>` cuenta y, con `--apply`, borra en transacción con sesión autorizada (los triggers de `tkc_results` la exigen). Debe ejecutarlo el usuario.
- **Ensayo de carga:** `scripts/loader_dry_run.py` ejecuta el `Loader` real contra un cursor falso y valida cada INSERT (NOT NULL, ENUM, VARCHAR, DECIMAL, JSON, PK repetida) contra `database/ispm_tkc.sql`: C620 11 895 filas / 16 tablas, C600 13 649 / 16, sin problemas. Habría detectado los tres fallos de carga de la 1.2.0.
- **Riesgo bajo, sin tratar:** `empirical.sample_value` conserva números de serie de tarjetas, shelf y módulos ópticos (inventario del propio operador) y ejemplos de alarmas con posiciones de ONU.
- El hash de contenido de la 1.3.0 no cambia al redactar `results.json` (el hash no cubre ese archivo).


## BE. Carga 1.3.0 y purga

- `loader status`: C620 1.3.0 y C600 1.3.0 en T4, SIN CAMBIOS y vigentes. IDs de versión: C620 1.3.0 = 15, C600 1.3.0 = 16 (1.2.0 = 13 y 14, vuelta atrás disponible).
- Consulta de solo lectura sobre `tkc_results` por versión (ids 4, 5, 7, 8, 9, 10, 13, 14, 15, 16) buscando los tres prefijos sensibles en `payload`: 0 en todas. Tras la purga la 1.3.0 tiene 1 hallazgo menos que el local (7700 y 9489): se borró también el marcador `sensitive_branch_redacted`, porque su `payload` nombra los prefijos. Es inocuo.
- Fallo propio corregido: `purge_sensitive_results.py` no cargaba `.env` (acceso denegado de `tkc_loader`, sin contraseña); ahora lo hace igual que el loader.
- Pendiente (del usuario): rotar comunidades SNMP (lectura y escritura), credenciales Telnet y de la base; restringir la vista SNMP de lectura (excluir `3902.3.6000`); cerrar el HTTP de la C600.

## BF. Catálogo 1.2.0 de las clásicas (C320 y C300) y hallazgo de seguridad

- **Qué se hizo (sin tocar ninguna OLT ni la base):** `refine_catalog` ahora admite C300/C320 (subconjunto de los refinamientos de C6: sin alarmas, relaciones ni entidades de perfiles, que salen de la CLI de C6). `scripts/build_classic_catalog.py` genera en `staging/` y promueve a `catalog/zte/zxa10-c320|c300/catalog-1.2.0`; `_target_dir` respeta `release_versions` también para la familia semilla.
- **Diff frente a 1.1.0-validated / 1.1.0:** mismos 1003 / 952 OID, 0 añadidos, 0 quitados. Cambios: 10 `verified_community` → `documented` (0 filas en el walk de la familia), potencia con signo (C320 4 ONU, C300 7) y `suspect_values` raw 0, 16 unidades con multiplicador, 26 `UNRESOLVED`, `pii`, `serial_format`, 770/826 `pending_validation`, 18 comandos `verified` sin ejecución → `documented`, 2 `observed` y `show version` nuevo.
- **Puerta de contrato** ampliada a c320/c300 (`consumer_contract.json`, fixtures anonimizadas `docs/fixtures/zte-real/c320-20261001|c300-20261001` generadas con `scripts/build_classic_fixtures.py`): 28 947 comprobaciones, 0 fallos (antes 18 843 + las nuevas). Ensayo de carga: C320 5784 filas y C300 5089, todas caben en el esquema. 149 tests pasan.
- **Hallazgo de seguridad:** `1082.20.5.2.1.2.1.{2|50}` tiene 4 filas en C320 y 2 en C300 cuyo índice son cadenas de 12 caracteres con valor 1/2: probables comunidades SNMP (no coinciden con las del `.env`; sin MIB para confirmarlo). Estaban en `observed_firmware_strings`, `tkc_results` (cargado) y en los walks. Las del C300 están además en el historial de git del repositorio público (walk del primer commit y `context.md`).
  Hecho: prefijo añadido a `sensitive_prefixes`; walks, diagnósticos y `results.json` redactados; `context.md` limpiado; la puerta y la purga leen la lista de `config/vendors.yaml`. El hash de las versiones antiguas no cambia (no incluye `results.json`).
- Pendiente (del usuario): ejecutar `purge_sensitive_results.py` (con `--apply`) para limpiar `tkc_results`; rotar las comunidades de C320 y C300; decidir si se reescribe el historial de git; cargar `zxa10-c320` y `zxa10-c300` 1.2.0.

## BG. Carga de la 1.2.0 de las clásicas y purga

- `loader status`: C320 1.2.0 y C300 1.2.0 en T4, `SIN CAMBIOS`, vigentes; `1.1.0-validated` (C320, id 9) y `1.1.0` (C300) pasan a no vigentes y quedan como vuelta atrás. IDs: C320 1.2.0 = 17 (1003 OID, 19 comandos), C300 1.2.0 = 18 (952 OID, 19 comandos).
- Consulta de solo lectura en `tkc_results` con todos los prefijos sensibles (ahora cuatro, incluido `1082.20.5.2.1`): solo 2 filas, los marcadores `sensitive_branch_redacted` de las versiones 17 y 18 (llevan el prefijo y el número de filas omitidas, no las cadenas). Las versiones antiguas de C300/C320 no tienen ninguna: la purga funcionó.
- Pendiente (del usuario): rotar las comunidades de C300 y C320 (las del C300 están en el historial público de git), decidir si se reescribe el historial y avisar al importador de leer la 1.2.0.

## BH. Contexto de la conversación y pendiente de la C320 (2026-10-14 a 2026-10-24)

### Lo que se preguntó y lo que se respondió
1. **«Qué falta por aprovisionar en la C600 y la C620 y compara la actualidad de ambas»** (2026-10-14):
   - **C620:** las escrituras de trabajo están ejecutadas y verificadas con rollback (alta/baja, aprovisionamiento completo, `pon-onu-mng`, perfiles, tipos, `reboot` en línea, `write`). Sin resolver: ninguna ONU de prueba llegó a `working` tras el alta (oscilaba entre `syncMib`, `LOS` y `Logging`; causa sin determinar); `traffic-limit` con perfiles `SMARTOLT-*` da 223981 y `real-speed gpon` da 230240; el tipo de una ONU registrada no se puede cambiar (222366); `gemport … portid`/`tcont … allocid` manuales solo valen con `resource mode2` e ids ≥ 1024.
   - **C600:** 76 comandos; 30 lecturas verificadas y casi todas las escrituras solo con ayuda `?` o vistas en la configuración (1 verificada, 12 observadas, 23 con `?`). Falta alta/baja de ONU (0 ONU en espera), crear y borrar `traffic-profile`/`profile tcont`, `write`, `reboot`, `splitter`, y la sintaxis propia de la C600 (`mgc-service`, `voip-ip`, `tr069-mgmt`, subcomandos de `remote-onu`). La plataforma responde 501 en escritura (`cliWrite:'none'`).
   - **Comparación:** ambas con catálogo 1.3.0 (C620 78 comandos, 17 atributos; C600 76, 14), walks completos, firmware V1.2.2 / V1.2.2_RZ, sintaxis idéntica en el 90 % de los comandos; solo C620: `ssid`, `wifi`, `mgmt-ip`, `wan`, `dhcp-client`; solo C600: `mgc-service`, `voip-ip`, `tr069-mgmt`. La brecha es de evidencia de escritura, no de catálogo.
   - Propuesta no ejecutada: script de solo lectura/escritura con rollback para la C600 sin ONU (perfiles, `write`, `splitter` en puerto vacío).
2. **«Qué nos falta para el funcionamiento total y perfecto en prod de la C320»** (2026-10-23): la lectura SNMP estaba sólida, pero el catálogo C300/C320 no había recibido los refinamientos de C6 (10 OID `verified_community` sin filas, potencia con signo, 26 `UNRESOLVED`, 16 unidades con multiplicador, `pii`, 18 comandos del manual marcados `verified` sin ejecutarse) y la escritura por CLI nunca se probó en clásicas. Se hizo la **1.2.0 de C320 y C300** (sección BF).
3. **Hallazgo de seguridad al hacerla:** la tabla `1082.20.5.2.1` (4 filas en C320, 2 en C300; cadenas de 12 caracteres con acceso 1/2) parecen comunidades SNMP. Estaban en walks, `tkc_results` y, las del C300, en el historial del repositorio **público** (walk del primer commit y `context.md`). Se redactaron los archivos locales, se añadió el prefijo a `sensitive_prefixes` y se purgó la base (sección BG).
4. **«No es mejor modificar el catálogo y resubirlo?»:** para la 1.2.0 (sin cargar) se modificó directamente; para versiones ya cargadas se mantuvo la purga: el hash de contenido no incluye `results.json`, así que el loader respondería «SIN CAMBIOS» y no recargaría; forzarlo exigiría un `--force` y borrar/insertar toda la versión, y rompe la regla de no tocar versiones publicadas.
5. **«Listo, ya lo actualicé»:** el usuario ejecutó la purga y la carga; verificado en solo lectura (BG).

### Pendiente de la C320 (plan en 3 pasos; decisión del usuario: cuál C320 usar)
1. **Lecturas CLI sin riesgo** — `scripts/c320_readonly_probe.py` (por escribir): solo `show` y `?` de lista cerrada, rechaza todo lo demás; host, usuario y contraseña por prompt oculto (el `.env` solo tiene la C620). Objetivo: marcar `verified` los comandos que respondan (`show version`, `show card`, `show gpon onu state gpon-olt_P`, `detail-info`, `show pon power attenuation`, VLAN, perfiles), fixtures CLI anonimizadas y `ground_truth` de potencia para confirmar el signo de 16 bits en clásicas. Resultado esperado: **1.3.0 de C320 y C300** con comandos reales.
2. **Escritura con rollback** — requiere una ONU en espera o un puerto vacío en una C320 poco crítica: alta, aprovisionamiento, baja, reinicio y el **`write` automático tras cada SET** (agendado por el importador, nunca probado en hardware clásico). También la sintaxis para apagar una ONU en clásicas (Padilla). Sin ONU en espera no se hace.
3. **Huecos del walk** — rama `3.*` (alarmas y bitácora de comandos) y tarjetas (`1082.10.1.2.4`) de C300/C320, por SNMP de solo lectura con el colector de la C6.

### Otros pendientes abiertos (resumen)
- **Del usuario:** rotar las comunidades SNMP de C300 y C320 (las del C300 están en el historial público), y las ya listadas en BE (RO/RW de C620 y C600, Telnet, base de datos, cuentas `smartoltusr`/`zte`); restringir la vista SNMP de lectura (excluir `3902.3.6000`) y cerrar el HTTP de la C600; decidir si se reescribe el historial de git; avisar al importador de leer la 1.3.0 (C6) y la 1.2.0 (clásicas) y de que usen el OID `verified*` de cada atributo (`superseded_by`); revisar el archivo sin rastrear `38.199.30.51` de la raíz del repositorio antes de cualquier commit.
- **Del catálogo (necesita visto bueno):** D-07 catálogo de eventos de log, D-11 `exposed` por entidad, D-14 línea de versión única por familia (la C320 aún tiene 5 etiquetas, 3 sin subir), tarjetas de la C600 desde `show card`, catálogo de contadores por ONU (~400 000 filas sin catalogar), rollback de los `modify` restantes, `show alarm` y `show pon onu offline information` solo documentados, seriales de hardware de bajo riesgo en `empirical.sample_value`.
- **Con hardware:** ONU en espera en la C600 (tabla `uncfg` y escrituras), OLT no productiva, CPE/ONU estable para cerrar el alta de la C620 hasta `working`.

## BI. Sonda de solo lectura para la C320 (paso 1 del plan de BH; preparada, pendiente de ejecución por el usuario)

- `scripts/c320_readonly_probe.py` (también sirve para C300 con `--model c300`): host, puerto, usuario y contraseña por prompt (la contraseña, oculta; no se leen del `.env` ni se guardan). Solo envía `terminal length 0` y `show …`, más la ayuda `show … ?` (sin Enter, borrada con Ctrl-U); rechaza antes de enviar cualquier otra cosa (probado sin red: `conf t`, `write`, `no onu`, `reboot`, `;`, `|`, saltos de línea).
- Mide: sesión y descubrimiento (`show version` frente a `show software 1`, tarjetas, `uncfg`, estado de ONU, tipos, VLAN, perfiles, bitácora, alarmas); un puerto PON y dos ONU (una `working` y otra que no lo esté) con la sintaxis de clásicas (`gpon-onu_1/1/1:1`) y la de C6 (`gpon_onu-1/1/1:1`) para ver cuál acepta el equipo; potencia por CLI de las ONU cuyo SNMP crudo era ≥ 32768 (`--signed-fixture`, solo válido si la fixture es de ESTA misma OLT: C320 → 1/1/4:12, 1/1/5:6, 1/1/16:25, 1/2/13:46; C300 → 7 ONU); y la ayuda de `show gpon onu`, `show pon`, `show pon power`, `show gpon remote-onu`, `show alarm`, `show gpon profile`, `show qos`.
- Salida completa (seriales, MAC, nombres): `docs/walks/diagnostics/ZTE_<MODELO>_cli_reads_<fecha>.txt` (ignorada por git). Resumen solo con veredictos y los índices sustituidos por `<idx>`: `docs/validation/<modelo>_readonly_probe.json`.
- Siguiente (al recibir el resultado): pasar a `verified` los comandos que respondan, comparar CLI contra SNMP en las ONU con potencia con signo, fixtures CLI anonimizadas y catálogo 1.3.0 de C320/C300.
