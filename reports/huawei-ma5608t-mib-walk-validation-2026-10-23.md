# Validación Fase 2 — catálogo MIB Huawei vs walk real (MA5608T, 2026-10-23)

Fuentes: `docs/huawei/ma5608t/observium/HUAWEI-GPON-MIB.json` y `HUAWEI-XPON-MIB.json`
(1022 y 1549 objetos respectivamente, extraídos de la representación de Observium —
no hay `.mib` oficial de Huawei en el proyecto) contra `docs/walks/Huawei_MA5608T.txt`
(walk completo, 608 239 filas, `tkc-walk-collector` sobre R015, `status:COMPLETE`).

Metodología: para cada objeto `scalar`/`column` definido en los dos MIB, se comprobó si
existe **al menos una instancia real** en el walk (prefijo exacto de OID, comparación de
tuplas vía `bisect`, script en el scratchpad de la sesión). `node`, `table` y `row` son
entradas estructurales y no se evalúan directamente. Resultado completo por OID en
`docs/validation/huawei_ma5608t_mib_walk_validation.json`.

## Hallazgo 1 — HUAWEI-GPON-MIB (`.1.3.6.1.4.1.2011.5.100`) no está implementado en este firmware

**0 de 881 objetos scalar/column tienen una sola instancia en el walk.** El walk sí
incluyó `2011.5.100` como raíz a recorrer (aparece en el header `roots:` del archivo) y
el recolector marcó la tarea `COMPLETE` — no es un walk incompleto ni un árbol que
«se nos olvidó» recorrer: el agente SNMP de la MA5608T (R015) simplemente no devuelve
nada bajo ese subárbol. Conclusión: **todo `HUAWEI-GPON-MIB` queda `absent_in_walk`** y
no debe usarse como fuente para el catálogo de esta familia/firmware — es un módulo
legado o de otra línea de producto, reemplazado por `HUAWEI-XPON-MIB` en este equipo.

## Hallazgo 2 — HUAWEI-XPON-MIB (`.1.3.6.1.4.1.2011.6.128`): patrón GPON/EPON muy limpio

El root tiene 606 547 instancias reales en el walk. Desglose por prefijo de nombre de
tabla (columnas, no escalares — los escalares son 21/23 presentes, 91 %):

| Grupo | Columnas presentes | Columnas totales | Cobertura | Tablas | Tablas en 0% |
|---|---:|---:|---:|---:|---:|
| `hwGpon*` | 451 | 576 | **78.3 %** | 46 | 10 |
| `hwEpon*` | 16 | 586 | **2.7 %** | 38 | 36 |
| `hwXpon*` (genérico/compartido GPON+EPON) | 46 | 156 | 29.5 % | 15 | 10 |

**Lectura:** este MA5608T es un chasis **GPON puro**. Las 38 tablas `hwEpon*` están
casi íntegramente en 0 % (36 de 38 completamente vacías, las 2 restantes con cobertura
mínima) — consistente con que el módulo `HUAWEI-XPON-MIB` cubre ambas tecnologías
(GPON y EPON comparten el mismo MIB "xPON") pero el hardware/software instalado solo
tiene tarjetas y licencias GPON activas. Esto **no es una ONU nueva ni un fallo de
walk**: es la firma esperada de un equipo sin EPON. Regla a aplicar en el catálogo:
podar/marcar como `not_applicable_hardware` las tablas `hwEpon*` para esta familia,
en vez de `absent_in_walk` genérico (la distinción importa: `absent_in_walk` sugiere
"podría aparecer con otra configuración", `not_applicable_hardware` dice "esta OLT no
tiene EPON, punto").

Las tablas `hwGpon*` en 0 % (10 de 46) y las `hwXpon*` genéricas parciales son casos
normales de *features opcionales no configuradas* (SLA profiles, perfiles SNMP de ONT,
pruebas de loopback NNI/UNI, rutas estáticas, dual-parent, port-class) — no indican
problema, solo que no se usan en este equipo. Detalle completo por tabla en el JSON de
validación (`by_table` puede regenerarse con el mismo script).

## Tablas 100 % confirmadas (uso real, candidatas sólidas para el catálogo)

`hwGponOntTrafficFlowStatisticTable`, `hwGponDeviceOntCfgCapabilityTable`,
`hwGponOltGemStatisticTable`, `hwGponOntGemIndexStatisticTable`,
`hwGponDeviceOntOpticalDdmInfoTable`, `hwGponOntStatisticTable`,
`hwGponOltOpticsDdmInfoTable`, `hwGponDeviceOntAlarmStateInfoTable`,
`hwGponDeviceOntExtendConfigTable`, `hwGponDeviceLineProfMulticastGemCfgTable`,
`hwXponDeviceOntExtLoopbackTable`, `hwGponDeviceGemLoopbackTable`,
`hwXponDeviceRogueOntTable`, `hwGponOntEthernetStatisticTable` (96.6 %).

## Relevancia para el bloqueo RW ya conocido

`hwGponDeviceSrvProfileInfoTable` (`.1.3.6.1.4.1.2011.6.128.1.1.3.65`, la tabla que
rechazó el `SET` de creación por SNMP con `errorStatus` 6553514/6553511) está en
**75 % de cobertura (3/4 columnas)** — confirma que la tabla sí se lee perfectamente
por SNMP (coherente con lo ya sabido); la columna faltante y el resto de la evidencia
no cambian la conclusión ya cerrada: la creación es solo por CLI (`ont-srvprofile`
+ `commit`), ver `docs/validation/commands/huawei_ma56xt_provisioning_recipes.json`.

## Siguiente paso sugerido (no ejecutado)

Si se decide construir un catálogo real para Huawei (writer/catalog_writer), esta
validación ya da la poda de primer nivel: descartar `HUAWEI-GPON-MIB` completo,
descartar `hwEpon*` de `HUAWEI-XPON-MIB` como `not_applicable_hardware`, y usar el
resto como semilla con status `verified_walk`/`absent_in_walk` por columna según el
JSON. Pero integrar Huawei al pipeline `src/` (classifier→extractor→...→writer) es
una tarea de ingeniería aparte, no fue lo que se pidió en esta sesión.
