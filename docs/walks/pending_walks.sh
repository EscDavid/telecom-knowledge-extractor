#!/usr/bin/env bash
# ==============================================================================
# WALKS PENDIENTES — gaps confirmados por revisión del catálogo (2026-07-09)
# Ejecutar contra IP_C300 e IP_C320 reales. COMMUNITY a definir por el usuario.
# ==============================================================================
set -euo pipefail

COMMUNITY="${SNMP_COMMUNITY:?set SNMP_COMMUNITY}"
IP_C300="${IP_C300:?set IP_C300}"
IP_C320="${IP_C320:?set IP_C320}"

# ------------------------------------------------------------------------------
# (1) ifOperStatus — NUNCA capturado pese a existir ZTE_C300_ifnames.txt.
#     Ese archivo solo trae ifName (.1.3.6.1.2.1.31.1.1.1.1); falta la rama
#     ifTable estándar completa (.1.3.6.1.2.1.2.2), que sí incluye ifOperStatus
#     (.1.3.6.1.2.1.2.2.1.8) e ifAdminStatus (.1.3.6.1.2.1.2.2.1.7).
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C300" \
  1.3.6.1.2.1.2.2 >> docs/walks/ZTE_C300_ifTable.txt

snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C320" \
  1.3.6.1.2.1.2.2 >> docs/walks/ZTE_C320_ifTable.txt

# ------------------------------------------------------------------------------
# (2) zxAnGponOP — confirmar en walk real (hoy solo hay nota documental de
#     ausencia, no una salida de walk archivada). Debe dar 0 líneas; si diera
#     algo, invalida la premisa "no está poblada por este firmware".
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C300" \
  1.3.6.1.4.1.3902.1082.500.21.2.1 >> docs/walks/ZTE_C300_gponOP.txt

snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C320" \
  1.3.6.1.4.1.3902.1082.500.21.2.1 >> docs/walks/ZTE_C320_gponOP.txt

# ------------------------------------------------------------------------------
# (3) entPhysicalTable en C320 — el walk existente (ZTE_C320_entities.txt)
#     solo tiene 1 línea; repetir con retries más agresivos, puede ser timeout
#     parcial del walk original, no ausencia real de la tabla.
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr5 -t 60 -r 5 "$IP_C320" \
  1.3.6.1.2.1.47.1.1.1.1 >> docs/walks/ZTE_C320_entities_retry.txt

# ------------------------------------------------------------------------------
# (4) OLT_HIGH_TEMP — no hay ningún threshold poblado; capturar directamente el
#     valor vivo de temperatura (zxAnEnvTemp / OID exacto a confirmar en el MIB)
#     para al menos tener un dato oper real, ya que no existe tabla de umbrales
#     ni motor que la use todavía.
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C300" \
  1.3.6.1.4.1.3902.1082.10.10.3 >> docs/walks/ZTE_C300_env.txt

snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C320" \
  1.3.6.1.4.1.3902.1082.10.10.3 >> docs/walks/ZTE_C320_env.txt

# ------------------------------------------------------------------------------
# (5) ONU sin configurar / autofind ("show gpon onu uncfg" en la CLI, sin OID
#     asociado en ningun MIB que tengamos). NO existe ningun OID confirmado
#     para esta tabla en el catalogo -- el numero 1082.500.10.2.2.5 que se
#     propuso en un plan aparte es una EXTRAPOLACION sin fuente, no un dato
#     documentado. Antes de cargar nada al catalogo hay que descubrirlo por
#     walk real, igual que se hizo con bitcalc en C300.
#     PRECONDICION: debe haber al menos una ONU en estado autofind/no
#     provisionada en el equipo al momento de correr esto (si no, un resultado
#     vacio no prueba nada). El indice tampoco debe asumirse igual al de las
#     ONU ya provisionadas (ONU-ID slot*256+pon): "show gpon onu uncfg" no
#     toma indice como parametro en la CLI, lo que sugiere que una ONU sin
#     provisionar puede no tener onu-id asignado todavia.
#     Se camina ancho (vecindad de las tablas ONU y de la rogue table ya
#     confirmada vacia) para localizarla sin adivinar la columna exacta.
# ------------------------------------------------------------------------------
snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C300" \
  1.3.6.1.4.1.3902.1082.500.1 >> docs/walks/ZTE_C300_onu_uncfg_candidates.txt

snmpbulkwalk -v2c -c "$COMMUNITY" -On -Cr10 -t 30 -r 3 "$IP_C300" \
  1.3.6.1.4.1.3902.1082.500.10.2 >> docs/walks/ZTE_C300_onu_uncfg_candidates.txt

echo "Walks pendientes completados. Revisar líneas nuevas antes de mover a catalog/."
