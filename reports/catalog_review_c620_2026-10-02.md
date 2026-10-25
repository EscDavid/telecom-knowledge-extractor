# Revisión del catálogo C620 (catalog-1.1.0, generado 2026-10-02 22:12)

Alcance: `catalog/zte/zxa10-c620/catalog-1.1.0/` (1772 OID, 13 entidades, 76 comandos, 117 alarmas) contra el walk `docs/walks/ZTE_C620.txt` y el informe CLI. Solo lectura; no se modificó nada.

## Errores (afectan a quien consuma el catálogo)
| # | Hallazgo | Evidencia | Arreglo propuesto |
|---|---|---|---|
| E1 | `scale` de tensión del módulo óptico = 0.01 pero la unidad dice «0.001 Volts» y el valor es 3317 → daría 33,17 V; real 3,317 V | `optical_supply_voltage` y `optical_{c1_d,h1_d,c_min,h_min}_supply_voltage`: `scale 0.01`, `scale_confirmed 0.01` (heurística), muestra 3317 | forzar `scale 0.001`, unidad `V` |
| E2 | `pon_rx_power_detect_period`: `scale 0.01` en un campo en segundos (muestra 900) → 9 s | catálogo | quitar scale (falso positivo de la detección) |
| E3 | Firmware de OID, entidades y alarmas = `["2.0","2.1"]`; los 76 comandos = `["1.2.2"]` (firmware real C620 V1.2.2) | `firmware` en oids/*, entities/*, alarms/* | unificar a `1.2.2` (o declarar el rango real) |
| E4 | Las 43 hojas de la comunidad (`verified_walk`) tienen `name = "UNRESOLVED"` (onu_rx_power, onu_status, distancia, serie, service_port_ingress/egress_profile, IF-MIB…) | oids/onu.json, pon_port.json, olt.json | `name = attribute` cuando no hay nombre MIB |
| E5 | Hojas escalares/IF-MIB con índice de ONU: `sys_descr/sys_name/sys_uptime` (índice «scalar») y `hc_in_octets…`, `in_errors…` (ifIndex) llevan `onu_id_append: true` y están con id `oid.zte.gpon.onu.*` (algunas en el archivo olt.json o pon_port.json y con `entity_ref` olt/pon_port) | oids/olt.json, oids/pon_port.json | `onu_id_append=false`, id y archivo coherentes con `entity_ref` |
| E6 | `onu_rx_power`/`onu_tx_power`: la fórmula `raw*0.002-30` solo está en `scale_formula` (texto); `scale`/`unit` = null; falta marcar `65535 = sin señal` | oids/onu.json | campos estructurados: `unit dBm`, `formula`, `sentinel 65535` |
| E7 | `onu_status`: el mapa de enum mezcla la clave `default` con códigos numéricos y no incluye 1/3/6 (no vistos) | oids/onu.json | separar `default` y marcar los valores como «observados» |
| E8 | `manifest.json` → `observed_firmware_strings` contiene nombres de ficheros (`powerperf/*.csv`), no versiones | manifest | filtrar por patrón de versión |
| E9 | Manifest conserva `verdict: mismatch` en `bitcalc_validation` aunque la resolución es `accept` y el mapa corregido (slot 10-8, port 4-0) sí está aplicado en `card.entry` | manifest | etiquetar «accepted» |

## Huecos (mejoras)
| # | Hueco | Detalle |
|---|---|---|
| M1 | **Cobertura del walk:** 293 subárboles de 6 niveles con datos reales no tienen ninguna entrada en el catálogo (≈680 000 filas de 1,2 M). Los más grandes: `1082.500.10.2.3.2.*` (≈378 000 filas, sobre todo Counter64 por ONU), `500.10.2.2.2.*` (47 000), `500.20.2.9.2.*` (35 000), `500.20.2.3.2.*`, `50.7.2.4.1`, `500.20.2.4.25/15/63`, `500.20.2.1.30/2`, `60.1.2.50.2`, `70.10.2.3.4` | No están en los MIB de referencia; hay que catalogarlos como `observed` (OID, tipo, ejemplos, instancias) y, donde se pueda, contrastar con CLI (contadores por ONU) |
| M2 | `uplink_port` tiene 0 OID, aunque hay 8 uplinks xgei (ifType 6) con IF-MIB y HC counters | asignar ifOperStatus/ifAdminStatus/HC counters a uplink_port |
| M3 | `attributes` vacío en las 13 entidades: nada enlaza entidad ↔ OID/atributo | poblar con los atributos operativos (estado, rx/tx power, distancia, serie, VLAN, perfiles) |
| M4 | Alarmas de ONU: solo `notificationTrap`; no están LOS, DyingGasp, LOSi, etc. aunque `onu_last_offline_cause` ya trae el enum | derivar alarmas de ONU de los eventos de la comunidad |
| M5 | Comandos: 58 de 76 sin `parameters`, 69 sin `output_fields`, 76 sin `related_commands`, 73 sin `prerequisites` (las recetas sí los tienen) | rellenar desde la sintaxis y las recetas; enlazar create↔delete↔show |
| M6 | Sin entidad para perfiles (tcont, tráfico, onu profile traffic): 16 comandos con `entity_ref = null` | añadir entidades `tcont_profile`, `traffic_profile`, `onu_traffic_profile` |
| M7 | Reversibilidad: 17 comandos de tipo modify/enable sin `rollback` (veip, wan-ip, dhcp-ip, splitter, name, vport-mode, traffic-limit, wifi…) | la mayoría se revierten con `no <cmd>`; documentarlo |
| M8 | Relaciones (5 archivos) todas `inferred` con confianza 0,26 y `creation_order` solo en la primera; no reflejan el orden verificado (onu → tcont → gemport → vport/service-port → pon-onu-mng service) | sustituir por relaciones verificadas con orden |
| M9 | `card.entry` etiqueta `shelf bits 31-28` y `slot 10-8` como bits, pero son sub-identificadores del índice de la tabla de tarjetas (rack.shelf.slot): la semántica de «bits» no aplica | revisar contra el walk de la tabla de tarjetas |
| M10 | VLAN por ONU ya está cubierta: `zxAnSrvPortUserVid` (.8) y `zxAnSrvPortCVid` (.18) están `verified`; falta anotar que coinciden 26/26 con CLI y que Q-BRIDGE no sirve | anotar en las hojas |
| M11 | Documentados sin probar: `show alarm`, `show pon onu offline information` | probarlos o dejarlos como `documented` con nota |
| M12 | `onu_distance` sin escala ni centinela documentados; `onu_last_offline_cause` solo 5 valores | ampliar con más observaciones/CLI |

Prioridad sugerida: E1–E6 (corregibles ahora, con evidencia en el walk), luego M1–M3, M5–M6, M8.

## Estado tras las correcciones
Aplicadas E1–E6, E8, E9 y M2, M3, M4, M5 (parcial), M6, M7 (solo splitter), M8, M10 en `src/walk_validator/refinements.py` y `scripts/build_c620_command_catalog.py`; M1 queda como inventario (`docs/validation/observed_uncataloged_c620.json`). E7, M9, M11, M12 sin cambios. Ver sección AP del informe CLI.
