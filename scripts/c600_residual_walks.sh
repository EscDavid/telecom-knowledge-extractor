#!/usr/bin/env bash
# Walks residuales de la C600 (SOLO LECTURA, una petición a la vez, GETNEXT sencillo).
#  1) confirma que las columnas 26-29 de 1082.500.20.2.1 no existen (el hueco declarado iba de .25 a .30)
#  2) tablas con agente "no creciente": 3.6000.51.2.3.7 (inspector) y 1082.70.67.2.3.1 (perfiles DEFAULT-ONU-PROFILE)
# Uso:  bash scripts/c600_residual_walks.sh      (pide la community por prompt oculto; no se guarda)
set -uo pipefail
cd "$(dirname "$0")/.."
HOST="${C600_HOST:-190.14.224.10}"; PORT="${C600_SNMP_PORT:-2161}"
read -rsp "Community SNMP de solo lectura de la C600: " COMM; echo
OUT=staging/walk_extra; mkdir -p "$OUT"
SN=(snmpwalk -v2c -On -c "$COMM" -t 10 -r 2)
echo "== preflight"; snmpget -v2c -On -c "$COMM" -t 5 -r 2 "$HOST:$PORT" 1.3.6.1.2.1.1.1.0 | cut -c1-120 || exit 1
echo "== 1) siguiente OID tras las columnas 26..29"
for c in 26 27 28 29; do snmpgetnext -v2c -On -c "$COMM" -t 10 -r 2 "$HOST:$PORT" 1.3.6.1.4.1.3902.1082.500.20.2.1.$c | cut -c1-110; done | tee "$OUT/ZTE_C600_cols26_29_getnext.txt"
echo "== 2) inspector (3.6000.51.2.3.7)"
timeout 600 "${SN[@]}" -Cc "$HOST:$PORT" 1.3.6.1.4.1.3902.3.6000.51.2.3.7 > "$OUT/ZTE_C600_3.6000.51.2.3.7.txt"; wc -l < "$OUT/ZTE_C600_3.6000.51.2.3.7.txt"
echo "== 3) perfiles por defecto (1082.70.67.2.3.1)"
timeout 900 "${SN[@]}" -Cc "$HOST:$PORT" 1.3.6.1.4.1.3902.1082.70.67.2.3.1 > "$OUT/ZTE_C600_1082.70.67.2.3.1.txt"; wc -l < "$OUT/ZTE_C600_1082.70.67.2.3.1.txt"
echo "listo: pega la salida"
