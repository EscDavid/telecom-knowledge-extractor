#!/usr/bin/env bash
# ==============================================================================
# WALK DIRIGIDO — ZTE ZXA10 C600 (primer walk real; NUNCA se ha capturado)
# ==============================================================================
# CONTEXTO CRÍTICO (ver context.md:30-31 y memoria single-shelf-devices):
#  - El walk previo etiquetado "C600" en este proyecto era en realidad un C320
#    mal identificado (mismo arbol MIB 3902.1082, mismo encoding de indice,
#    misma convencion ifType). NO hay ningun OID confirmado como "fallido"
#    contra un C600 real en este repo — es evidencia cero, no evidencia negativa.
#  - Arbol MIB de partida: mismo que C320/C300 (enterprise 3902.1082), porque
#    ZTE reutiliza el mismo espacio de OIDs GPON en toda la familia ZXA10.
#  - Chasis C600 (fuente: datasheets publicos ZTE, no walk propio):
#    11U, 19"/21", hasta 21-23 slots totales / 15-17 slots de servicio,
#    tarjetas GPON/XGS-PON/Combo de 16 puertos. Mucho mas grande que C300/C320
#    (single-shelf pero con MAS slots) — la correccion de bits shelf=1,
#    slot=bits[12:8], port=bits[4:0] hallada empiricamente en C300 NO debe
#    asumirse valida aqui: 5 bits de slot cubren hasta 32 valores, alcanza para
#    21-23 slots, pero DEBE re-derivarse contra ifName real, no copiarse.
#  - El usuario reporta que este C600 tiene pocas ONUs conectadas: un walk
#    corto de la tabla ONU (.1012.3.50.11.2.1) con pocas filas es ESPERADO,
#    no es señal de walk fallido.
# ==============================================================================
set -euo pipefail

COMMUNITY="${SNMP_COMMUNITY:?set SNMP_COMMUNITY}"
IP_C600="${IP_C600:?set IP_C600}"

# ------------------------------------------------------------------------------
# (1) ifXTable (ifName) + ifTable (ifOperStatus/ifAdminStatus) — IMPRESCINDIBLE
#     para re-derivar el bit_calculation del indice compuesto contra el C600
#     real. NO reutilizar docs/walks/resolutions.json de C300/C320 para esta
#     familia; el bitcalc_validation debe correr desde cero.
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C600" \
  1.3.6.1.2.1.31.1.1.1.1 >> docs/walks/ZTE_C600_ifnames.txt   # ifName

snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C600" \
  1.3.6.1.2.1.2.2 >> docs/walks/ZTE_C600_ifnames.txt          # ifTable completo (incluye ifOperStatus)

# ------------------------------------------------------------------------------
# (2) entPhysicalTable — entidades fisicas (shelf/card/power/fan). Con hasta
#     21-23 slots posibles, esta tabla es la unica forma de confirmar cuantas
#     tarjetas hay REALMENTE instaladas (no asumir capacidad maxima del chasis).
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr5 -t 60 -r 5 "$IP_C600" \
  1.3.6.1.2.1.47.1.1.1.1 >> docs/walks/ZTE_C600_entities.txt

# ------------------------------------------------------------------------------
# (3) Rama enterprise ZTE GPON completa — igual arbol que C320/C300, base para
#     confirmar/podar el catalogo teorico igual que se hizo con C300.
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C600" \
  1.3.6.1.4.1.3902.1082 >> docs/walks/ZTE_C600.txt

# ------------------------------------------------------------------------------
# (4) Tabla ONU operativa — MISMA rama que en C300/C320 (.1012, NO .1082, ver
#     context.md:283-284). Pocas filas esperadas en este equipo, no es error.
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C600" \
  1.3.6.1.4.1.3902.1012.3.50.11.2.1 >> docs/walks/ZTE_C600.txt

# ------------------------------------------------------------------------------
# (5) OIDs documentados como EXCLUSIVOS de C600 en el MIB (no existen/no
#     responden en C300/C320) — confirmar que SI responden aqui:
#       zxAnPonPortRogueOnuConfTable  1.3.6.1.4.1.3902.1082.500.1.2.4.1.4
#         ("This table only is used for C600 serial" — catalog/zte/.../onu.json)
#       zxAnOutOfBandIfConf{Negotiation,Duplex,Speed} (puerto out-of-band mgmt,
#         "This object is defined for C600 series NE")
#         1.3.6.1.4.1.3902.1082.30.20.2.2.5.1.21
#         1.3.6.1.4.1.3902.1082.30.20.2.2.5.1.22
#         1.3.6.1.4.1.3902.1082.30.20.2.2.5.1.23
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C600" \
  1.3.6.1.4.1.3902.1082.500.1.2.4.1.4 >> docs/walks/ZTE_C600_exclusive.txt

snmpwalk -v2c -c "$COMMUNITY" -On "$IP_C600" \
  1.3.6.1.4.1.3902.1082.30.20.2.2.5.1.21 >> docs/walks/ZTE_C600_exclusive.txt
snmpwalk -v2c -c "$COMMUNITY" -On "$IP_C600" \
  1.3.6.1.4.1.3902.1082.30.20.2.2.5.1.22 >> docs/walks/ZTE_C600_exclusive.txt
snmpwalk -v2c -c "$COMMUNITY" -On "$IP_C600" \
  1.3.6.1.4.1.3902.1082.30.20.2.2.5.1.23 >> docs/walks/ZTE_C600_exclusive.txt

# ------------------------------------------------------------------------------
# (6) OIDs documentados como NO SOPORTADOS en C600 — walkear SOLO para
#     confirmar la ausencia (esperado: noSuchObject/vacio, NO es un fallo del
#     walk sino el comportamiento documentado):
#       zxAnRogueOnuLocatingEnable   1.3.6.1.4.1.3902.1082.500.1.2.4.1.2.1.3
#       zxAnRogueOnuAutoCloseEnable  1.3.6.1.4.1.3902.1082.500.1.2.4.1.2.1.4
#       (reemplazados en C600 por la tabla del punto 5)
# ------------------------------------------------------------------------------
snmpget -v2c -c "$COMMUNITY" -On "$IP_C600" \
  1.3.6.1.4.1.3902.1082.500.1.2.4.1.2.1.3.0 >> docs/walks/ZTE_C600_not_supported_confirm.txt 2>&1 || true
snmpget -v2c -c "$COMMUNITY" -On "$IP_C600" \
  1.3.6.1.4.1.3902.1082.500.1.2.4.1.2.1.4.0 >> docs/walks/ZTE_C600_not_supported_confirm.txt 2>&1 || true

echo "Walk C600 completado. Con esta evidencia: correr bitcalc_validation desde"
echo "cero (NO reusar resolutions.json de C300/C320) y crear FAMILY_MAP[\"C600\"]"
echo "en src/walk_validator/walk_validator.py antes de generar el catalogo derivado."
