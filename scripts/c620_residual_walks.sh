#!/usr/bin/env bash
# Walks residuales de la C620 (SOLO LECTURA, una petición a la vez, GETNEXT sencillo).
#  1) (omitido: columnas 26-29 ya se sabe que no existen en C6x0)
#  2) tablas con agente "no creciente": 3.6000.51.2.3.7 (inspector) y 1082.70.67.2.3.1 (perfiles DEFAULT-ONU-PROFILE)
# Uso:  bash scripts/c620_residual_walks.sh      (lee host, puerto y community de .env; no se imprimen)
set -uo pipefail
cd "$(dirname "$0")/.."
envval() { grep -m1 "^$1=" .env | cut -d= -f2- | tr -d '\r"'"'"; }   # lee solo la variable pedida (no ejecuta .env)
HOST="$(envval TKC_SNMP_HOST)"; PORT="$(envval TKC_SNMP_PORT)"; PORT="${PORT:-161}"; COMM="$(envval TKC_SNMP_COMMUNITY)"
OUT=staging/walk_extra; mkdir -p "$OUT"
SN=(snmpwalk -v2c -On -c "$COMM" -t 10 -r 2)
echo "== preflight"; snmpget -v2c -On -c "$COMM" -t 5 -r 2 "$HOST:$PORT" 1.3.6.1.2.1.1.1.0 | cut -c1-120 || exit 1
echo "== 1) inspector (3.6000.51.2.3.7)"
timeout 600 "${SN[@]}" -Cc "$HOST:$PORT" 1.3.6.1.4.1.3902.3.6000.51.2.3.7 > "$OUT/ZTE_C620_3.6000.51.2.3.7.txt"; wc -l < "$OUT/ZTE_C620_3.6000.51.2.3.7.txt"
echo "== 2) perfiles por defecto (1082.70.67.2.3.1)"
timeout 900 "${SN[@]}" -Cc "$HOST:$PORT" 1.3.6.1.4.1.3902.1082.70.67.2.3.1 > "$OUT/ZTE_C620_1082.70.67.2.3.1.txt"; wc -l < "$OUT/ZTE_C620_1082.70.67.2.3.1.txt"
echo "listo: pega la salida"
