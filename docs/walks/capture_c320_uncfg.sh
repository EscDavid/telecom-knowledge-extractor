#!/usr/bin/env bash
# ==============================================================================
# DISPARAR APENAS HAYA CONFIRMACION DE UNA ONU SIN AUTORIZAR/AUTOFIND EN LA C320
# ("Net max prueba", 190.14.224.10). Ver memoria uncfg-onu-fabricated-oid.
#
# Uso:
#   SNMP_COMMUNITY_C320='la-community-real' ./docs/walks/capture_c320_uncfg.sh
#
# Que hace:
#   1) Camina la tabla uncfg real (.1082.500.10.2.2.5) contra la C320.
#   2) Si encuentra filas reales (no "No Such Object" / vacio), guarda el walk
#      crudo en docs/walks/ZTE_C320_uncfg.txt (misma convencion que C300).
#   3) Agrega "ZXA10 C320" a `families:` en el doc de validacion community ya
#      escrito (snmp-olt-zte_uncfg_onu.txt), que hoy solo tiene C300.
#   4) Corre main.py para que Fase 2 lo ingiera y quede en el catalogo C320
#      versionado por content_hash (nunca por INSERT manual en la BD).
#
# Si la tabla sigue vacia (tabla real, transitoria por naturaleza -- confirmado
# que el TIPO de objeto existe en ambos modelos, solo el contenido va y viene),
# el script no toca nada y avisa para reintentar mas tarde.
# ==============================================================================
set -euo pipefail

COMMUNITY="${SNMP_COMMUNITY_C320:?set SNMP_COMMUNITY_C320}"
IP_C320="190.14.224.10"
OID="1.3.6.1.4.1.3902.1082.500.10.2.2.5"
OUT="docs/walks/ZTE_C320_uncfg.txt"
COMMUNITY_DOC="docs/validation/community/snmp-olt-zte_uncfg_onu.txt"

echo "Caminando $OID contra $IP_C320 ..."
snmpwalk -v2c -c "$COMMUNITY" "$IP_C320" "$OID" > "$OUT.tmp" 2>&1 || true

if ! grep -q "No Such Object\|No Such Instance" "$OUT.tmp" && [ -s "$OUT.tmp" ]; then
    mv "$OUT.tmp" "$OUT"
    echo "OK -- $(wc -l < "$OUT") lineas reales capturadas en $OUT"

    if grep -q "^families: ZXA10 C300$" "$COMMUNITY_DOC"; then
        sed -i 's/^families: ZXA10 C300$/families: ZXA10 C300, ZXA10 C320/' "$COMMUNITY_DOC"
        echo "OK -- families actualizado a 'ZXA10 C300, ZXA10 C320' en $COMMUNITY_DOC"
    else
        echo "AVISO -- families ya no tenia el valor esperado; revisar manualmente:"
        grep "^families:" "$COMMUNITY_DOC"
    fi

    echo "Corriendo main.py para que Fase 2 lo ingiera..."
    .venv/bin/python main.py

    echo
    echo "LISTO. Verificar:"
    echo "  python3 -c \"import json; d=json.load(open('catalog/zte/zxa10-c320/catalog-1.0.0-validated/oids/onu.json')); [print(o['attribute'],o['status']) for o in d['oids'] if (o.get('attribute') or '').startswith('uncfg')]\""
    echo "Despues, para subir a la DB real:"
    echo "  python -m src.loader load zxa10-c320 --version 1.0.0-validated --user <superadmin> --authorize"
else
    rm -f "$OUT.tmp"
    echo "Tabla vacia o ausente en este momento (No Such Object / No Such Instance / walk vacio)."
    echo "Es transitorio (confirmado: el objeto SI existe en el firmware C320, ver memoria"
    echo "uncfg-onu-fabricated-oid) -- no hay ninguna ONU en autofind AHORA. Reintentar cuando"
    echo "haya confirmacion de una."
fi
