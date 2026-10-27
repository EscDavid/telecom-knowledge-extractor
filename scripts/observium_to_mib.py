#!/usr/bin/env python3
"""Genera un .mib SINTÉTICO a partir de un render JSON de Observium (nivel B de
evidencia, ver docs/adaptacion_multivendor.md §2/§5) para que el MibExtractor
existente (src/extractor/mib_extractor.py) lo consuma sin cambios.

Por qué funciona sin resolver una cadena de OBJECT IDENTIFIER: el JSON de
Observium ya trae el OID numérico ABSOLUTO de cada objeto (`"oid": "1.3.6....")`,
así que cada OBJECT-TYPE se emite como una definición AUTOCONTENIDA con
`::= { <tokens numéricos> }` — MibExtractor._resolve() solo necesita que cada
token del lado derecho sea un entero, no requiere la jerarquía real del módulo.
Por eso no se emiten nodos/tablas/filas (kind in node/table/row): no aportan
ningún Oid (MibExtractor los ignora si no tienen MAX-ACCESS) y no hacen falta
para resolver el OID de ningún scalar/column, que ya vienen resueltos.

Regla de acceso (backlog #2/#3 del plan): Observium SOLO distingue
"read-write" de "no lo sé" (nunca expone read-only/read-create/not-accessible
reales) — así que un `access` ausente en el JSON se emite como
`MAX-ACCESS unknown`, un valor NO estándar pero que el extractor captura igual
(regex genérica) y que `enricher._KEEP_IF_UNCONFIRMED` protege de poda por
Fase 2: un OID sin evidencia de acceso real NUNCA se asume read-only.

Uso:
    python3 scripts/observium_to_mib.py <entrada.json> <salida.mib>
    python3 scripts/observium_to_mib.py --all   # genera los de Huawei MA5608T
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# tipos que MibExtractor._norm_syntax ya reconoce tal cual (no hace falta mapear)
_PASSTHROUGH_SYNTAX = {"Counter64", "Counter32", "Gauge32", "OCTET STRING", "INTEGER"}

# Ramas que NUNCA se catalogan, sea cual sea el .mib de origen: gestión de cuentas/sesiones
# del propio equipo, irrelevante para un extractor de conocimiento GPON y con PII real en
# el walk (hallado 2026-10-27: hwCliUserMgmt/hwCliUserParaTable trae hwCliUserName +
# hwCliUserPassword; el walk muestra usuarios reales como índice ASCII, ver
# config/vendors.yaml → Huawei.sensitive_prefixes). Evita exponer sample_oid/sample_value
# de estas columnas en el catálogo aunque Fase 2 las confirme contra el walk real.
EXCLUDE_OID_PREFIXES = (
    "1.3.6.1.4.1.2011.6.3.10",           # hwCliUserMgmt (HUAWEI-DEVICE-MIB): nombre+password de cuentas
    "1.3.6.1.4.1.2011.6.3.2.1.6",        # hwNmsGetCommunity
    "1.3.6.1.4.1.2011.6.3.2.1.7",        # hwNmsSetCommunity
    "1.3.6.1.4.1.2011.6.3.3.2.1.26",     # hwSlotExtendedBiosPassword
    "1.3.6.1.4.1.2011.6.3.34.1.6",       # hwOntRemoteHttpChnlPassword
    "1.3.6.1.4.1.2011.2.6.7.1.1.4.1.4",  # hwXPONBoardPassWord (HWMUSA-DEV-MIB): password por tarjeta
    # Ninguna de estas tenía valor real confirmado en el walk (status=documented,
    # empirical=None: SNMP nunca devolvió nada ahí) — se excluyen de todos modos por
    # precaución, para que un walk futuro nunca exponga sample_value aquí sin querer.
)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', "'")


def _emit_object(o: dict) -> str:
    name = o["name"]
    oid_tokens = " ".join(o["oid"].strip(".").split("."))
    syntax = (o.get("syntax") or "INTEGER").strip()
    access = "read-write" if o.get("access") == "read-write" else "unknown"
    desc = o.get("description") or (
        f"[sintético, sin descripción en el render de Observium] {name}")
    return (
        f"{name} OBJECT-TYPE\n"
        f"    SYNTAX      {syntax}\n"
        f"    MAX-ACCESS  {access}\n"
        f"    STATUS      current\n"
        f"    DESCRIPTION\n"
        f'        "{_escape(desc)}"\n'
        f"    ::= {{ {oid_tokens} }}\n\n"
    )


def generate(src_json: Path, dst_mib: Path) -> dict:
    data = json.loads(src_json.read_text(encoding="utf-8"))
    objs = [o for o in data["objects"] if o.get("kind") in ("scalar", "column")
            and not o["oid"].startswith(EXCLUDE_OID_PREFIXES)]
    excluded = sum(1 for o in data["objects"] if o.get("kind") in ("scalar", "column")
                  and o["oid"].startswith(EXCLUDE_OID_PREFIXES))
    counts = {"scalar": 0, "column": 0, "unknown_access": 0, "read_write": 0, "excluded": excluded}
    body_parts = []
    for o in objs:
        counts[o["kind"]] += 1
        if o.get("access") == "read-write":
            counts["read_write"] += 1
        else:
            counts["unknown_access"] += 1
        body_parts.append(_emit_object(o))

    header = (
        f"-- {data['module']} -- SINTETICO, generado por scripts/observium_to_mib.py\n"
        f"-- Fuente: {data['source']} ({data.get('source_kind', 'third_party_rendering')}), "
        f"fetched {data.get('fetched', '?')}\n"
        f"-- Generado: {dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"-- Huawei Technologies -- MA5608T -- Huawei MA56xT\n"
        f"-- Nivel de evidencia B (docs/adaptacion_multivendor.md §2): NO es el MIB\n"
        f"-- oficial del fabricante. Cada OBJECT-TYPE es AUTOCONTENIDO (OID numérico\n"
        f"-- absoluto ya resuelto por Observium); no hay jerarquía real del módulo ni\n"
        f"-- nodos/tablas/filas (no aportan Oids, ver docstring de este script).\n"
        f"-- MAX-ACCESS 'unknown' (no estándar) = Observium no distingue ese acceso de\n"
        f"-- read-only real; el pipeline lo protege de poda por Fase 2 (nunca se asume\n"
        f"-- read-only sin evidencia). root_oid={data['root_oid']}\n"
        f"-- {len(objs)} objetos (scalar+column) de {len(data['objects'])} totales en el render.\n\n"
    )
    dst_mib.parent.mkdir(parents=True, exist_ok=True)
    dst_mib.write_text(header + "".join(body_parts), encoding="utf-8")
    return counts


SOURCES = {
    "docs/huawei/ma5608t/observium/HUAWEI-GPON-MIB.json":
        "docs/huawei/ma5608t/synthetic/HUAWEI-GPON-MIB.synthetic.mib",
    "docs/huawei/ma5608t/observium/HUAWEI-XPON-MIB.json":
        "docs/huawei/ma5608t/synthetic/HUAWEI-XPON-MIB.synthetic.mib",
    # 2026-10-27: las 30 tablas "observed_only" (datos reales en el walk, sin catalogar)
    # vivían aquí — frame/slot/board/CPU/temperatura, nunca cubierto por GPON/XPON-MIB.
    "docs/huawei/ma5608t/observium/HUAWEI-DEVICE-MIB.json":
        "docs/huawei/ma5608t/synthetic/HUAWEI-DEVICE-MIB.synthetic.mib",
    "docs/huawei/ma5608t/observium/HUAWEI-ENTITY-EXTENT-MIB.json":
        "docs/huawei/ma5608t/synthetic/HUAWEI-ENTITY-EXTENT-MIB.synthetic.mib",
    "docs/huawei/ma5608t/observium/HWMUSA-DEV-MIB.json":
        "docs/huawei/ma5608t/synthetic/HWMUSA-DEV-MIB.synthetic.mib",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", help="JSON de Observium de entrada")
    ap.add_argument("dst", nargs="?", help="ruta del .mib sintético de salida")
    ap.add_argument("--all", action="store_true",
                    help="genera todos los pares conocidos (SOURCES)")
    args = ap.parse_args()

    pairs = (list(SOURCES.items()) if args.all else
             [(args.src, args.dst)] if args.src and args.dst else None)
    if not pairs:
        ap.error("falta <entrada.json> <salida.mib>, o usa --all")

    for src, dst in pairs:
        src_p, dst_p = Path(src), Path(dst)
        counts = generate(src_p, dst_p)
        excl = f", {counts['excluded']} excluidos (EXCLUDE_OID_PREFIXES)" if counts["excluded"] else ""
        print(f"{src_p.name} -> {dst_p}: {counts['scalar']} scalar + {counts['column']} "
              f"column ({counts['read_write']} read-write, {counts['unknown_access']} "
              f"unknown{excl})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
