#!/usr/bin/env bash
# Walk de SOLO LECTURA de la Huawei MA5608T con net-snmp (sin Python), pensado para
# correr DENTRO de la LAN de gestión (p. ej. desde el servidor que recibe los traps).
#
#   HOST=192.168.10.5 ./scripts/huawei_walk_lan.sh              # pide la community oculta
#   HOST=192.168.10.5 MAX_MIN=15 ./scripts/huawei_walk_lan.sh --dry-run
#
# Variables:  HOST (obligatoria)  PORT=161  MAX_MIN=18  OUT=./huawei_walks
#             HUAWEI_RO_COMMUNITY (opcional; si falta se pide por prompt, sin eco)
#             SKIP_PREFLIGHT=1 (no exigir sysDescr de Huawei)
#
# Seguridad: solo GET/GETBULK. La community va por un snmp.conf temporal (modo 600),
# nunca en argv. Los valores sensibles (password/LOID/checkcode/descripción de ONT)
# se enmascaran al escribir. Una sola petición en vuelo, -Cr20 y pausa entre ramas.
# Salida (formato `snmpbulkwalk -On`, listo para docs/walks/):
#   Huawei_MA5608T_entities.txt   Huawei_MA5608T_ifnames.txt   Huawei_MA5608T.txt
set -u
HOST="${HOST:?define HOST=<ip de gestión de la OLT>}"
PORT="${PORT:-161}"
MAX_MIN="${MAX_MIN:-18}"
OUT="${OUT:-./huawei_walks}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
TARGET="udp:${HOST}:${PORT}"

ENT_ROOTS=(1.3.6.1.2.1.47.1.1.1.1)
IF_ROOTS=(1.3.6.1.2.1.2.2.1 1.3.6.1.2.1.31.1.1.1.1)
OID_ROOTS=(
  1.3.6.1.2.1.1             # system
  1.3.6.1.4.1.2011.2.6.7    # HWMUSA-DEV-MIB
  1.3.6.1.4.1.2011.5.25.31  # HUAWEI-ENTITY-EXTENT-MIB
  1.3.6.1.4.1.2011.5.100    # HUAWEI-GPON-MIB (¿implementada?)
  1.3.6.1.4.1.2011.6.3      # HUAWEI-DEVICE-MIB
  1.3.6.1.4.1.2011.6.128    # HUAWEI-XPON-MIB (la más grande: al final)
)
# prefijos cuyo valor STRING se enmascara (password, LOID, checkcode, descripción de ONT)
REDACT=(
  1.3.6.1.4.1.2011.6.128.1.1.2.43.1.4  1.3.6.1.4.1.2011.6.128.1.1.2.43.1.9
  1.3.6.1.4.1.2011.6.128.1.1.2.43.1.13 1.3.6.1.4.1.2011.6.128.1.1.2.43.1.14
  1.3.6.1.4.1.2011.6.128.1.1.2.48.1.3  1.3.6.1.4.1.2011.6.128.1.1.2.48.1.9
  1.3.6.1.4.1.2011.6.128.1.1.2.48.1.10 1.3.6.1.4.1.2011.6.128.1.1.2.52.1.7
  1.3.6.1.4.1.2011.6.128.1.1.2.52.1.12 1.3.6.1.4.1.2011.6.128.1.1.2.52.1.13
  1.3.6.1.4.1.2011.5.100.1.1.1.5.1.5   1.3.6.1.4.1.2011.5.100.1.1.1.5.1.14
  1.3.6.1.4.1.2011.5.100.1.1.1.5.1.38  1.3.6.1.4.1.2011.5.100.1.1.1.5.1.39
  1.3.6.1.4.1.2011.5.100.1.1.1.9.1.3   1.3.6.1.4.1.2011.5.100.1.1.1.9.1.9
  1.3.6.1.4.1.2011.5.100.1.1.1.9.1.10  1.3.6.1.4.1.2011.5.100.1.1.2.1.1.7
  1.3.6.1.4.1.2011.5.100.1.1.2.1.1.12  1.3.6.1.4.1.2011.5.100.1.1.2.1.1.13
)

command -v snmpbulkwalk >/dev/null || { echo "falta net-snmp (snmpbulkwalk/snmpget)"; exit 2; }

echo "Objetivo: ${TARGET}  | tope total: ${MAX_MIN} min | salida: ${OUT}"
if [ "$DRY" = 1 ]; then
  echo "DRY-RUN: no se abre ninguna conexión. Orden de ramas:"
  for r in "${ENT_ROOTS[@]}" "${IF_ROOTS[@]}" "${OID_ROOTS[@]}"; do echo "  $r"; done
  exit 0
fi

mkdir -p "$OUT"
TMP="$(mktemp -d)"; chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT
COMM="${HUAWEI_RO_COMMUNITY:-}"
if [ -z "$COMM" ]; then read -rs -p "Community SNMP de SOLO LECTURA: " COMM; echo; fi
[ -n "$COMM" ] || { echo "community vacía"; exit 2; }
umask 077
printf 'defVersion 2c\ndefCommunity %s\n' "$COMM" > "$TMP/snmp.conf"
unset COMM HUAWEI_RO_COMMUNITY
export SNMPCONFPATH="$TMP"
OPTS=(-On -t 5 -r 2)

# --- preflight: una sola lectura de sysDescr ---------------------------------
DESCR="$(snmpget "${OPTS[@]}" "$TARGET" 1.3.6.1.2.1.1.1.0 2>/dev/null | grep -m1 '= STRING:')"
if [ -z "$DESCR" ]; then
  echo "ABORTADO: el equipo no respondió al preflight (host/puerto/community/ruta)."; exit 4
fi
echo "sysDescr: $(printf '%s' "$DESCR" | sed -E 's/^[^=]*= STRING: //' | head -c 100)"
if [ "${SKIP_PREFLIGHT:-0}" != 1 ] && ! printf '%s' "$DESCR" | grep -qiE 'huawei|MA56|MA58|SmartAX'; then
  echo "ABORTADO: sysDescr no parece Huawei MA56xx (usa SKIP_PREFLIGHT=1 para forzar)."; exit 4
fi

DEADLINE=$(( $(date +%s) + MAX_MIN*60 ))
mask() {   # descarta "No Such…"/"No more variables" y enmascara STRING sensibles
  awk -v list="${REDACT[*]}" 'BEGIN{n=split(list,P," ")}
    /= No Such (Object|Instance)|= No more variables|End of MIB/ { next }
    { o=$1; sub(/^\./,"",o); hit=0
      for(i=1;i<=n;i++) if (index(o, P[i] ".")==1 || o==P[i]) {hit=1;break}
      if (hit && $0 ~ /= STRING:/) { sub(/= STRING:.*/, "= STRING: \"***\"") }
      print }'
}
walk_roots() {  # $1=archivo  resto=raíces
  local file="$OUT/$1"; shift; : > "$file"
  local root left rc n
  for root in "$@"; do
    left=$(( DEADLINE - $(date +%s) ))
    if [ "$left" -le 0 ]; then echo "  [tiempo agotado] sin caminar: $root"; continue; fi
    printf '  %-28s ' "$root"
    timeout "$left" snmpbulkwalk -v2c "${OPTS[@]}" -Cr20 "$TARGET" "$root" 2>"$TMP/err" | mask > "$TMP/root.txt"
    rc=${PIPESTATUS[0]}
    n=$(wc -l < "$TMP/root.txt"); cat "$TMP/root.txt" >> "$file"
    case "$rc" in
      0)   if [ "$n" -eq 0 ]; then echo "sin instancias (rama no implementada o vacía)"; else echo "completa ($n líneas)"; fi ;;
      124) echo "CORTADA por el tope de tiempo (parcial, $n líneas)" ;;
      *)   echo "terminó con código $rc ($n líneas): $(grep -v -e '^Created' -e '^MIB search' "$TMP/err" | head -c 120)" ;;
    esac
    sleep 2
  done
  echo "  → $file  ($(wc -l < "$file") líneas)"
}

echo "== entPhysicalTable";  walk_roots "Huawei_MA5608T_entities.txt" "${ENT_ROOTS[@]}"
echo "== ifTable + ifXTable"; walk_roots "Huawei_MA5608T_ifnames.txt"  "${IF_ROOTS[@]}"
echo "== enterprise";         walk_roots "Huawei_MA5608T.txt"          "${OID_ROOTS[@]}"
echo "Listo. Copia ${OUT}/Huawei_MA5608T*.txt a docs/walks/ del proyecto."
