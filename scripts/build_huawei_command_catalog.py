#!/usr/bin/env python3
"""Convierte docs/validation/commands/huawei_ma56xt_diagnostic_commands.json (comandos
`display` citados de un post del foro oficial Huawei) al formato que
WalkValidator._apply_command_sources espera: {"commands": {"<family>": [Command, ...]}}.

Ninguno de estos comandos se ejecutó contra hardware real (la cuenta Telnet actual no
tiene privilegio); quedan marcados status="documented", nunca "verified".

Uso: python scripts/build_huawei_command_catalog.py
Salida: docs/validation/commands/huawei_ma5608t_commands.json
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs/validation/commands/huawei_ma56xt_diagnostic_commands.json"
OUT = ROOT / "docs/validation/commands/huawei_ma5608t_commands.json"

VENDOR, FAMILY, TECH, FIRMWARE = "Huawei", "MA5608T", "gpon", ["R015"]
EVIDENCE = ("comando citado en un post del foro oficial Huawei Enterprise (forum.huawei.com, "
           "autor RicoFranco, 2019-03-01, 28419 vistas, 14 likes) — nunca ejecutado contra "
           "este equipo: la cuenta Telnet actual está en vista de usuario (Mnz.principal>), "
           "sin privilegio para entrar a modo configuración/ver salidas reales.")

# clave de la fuente -> nombre corto de entidad YA presente en el catálogo Huawei
# (ver catalog/huawei/ma5608t/catalog-1.0.0/entities/); None = no hay entidad clara,
# el comando se ancla a "global" en vez de inventar una referencia que no existe.
ENTITY_MAP = {
    "ver_ont_detallada": "onu",
    "trafico_puerta_pon": "pon_port", "config_puerta_pon": "pon_port",
    "estado_optico_puerta_pon": "pon_port", "estadisticas_puerta_pon": "pon_port",
    "trafico_puerta_eth": "uplink_port", "estadisticas_puerta_eth": "uplink_port",
    "estado_puerta_eth": "uplink_port",
    "estado_modulo_optico_eth": "optical_module",
    "interfaz_meth": "olt", "interfaz_vlanif": "vlan",
    "listar_dba_profiles": "dba", "ver_dba_profile": "dba",
}


def _mode(context: str | None) -> tuple[str, str | None]:
    if not context:
        return "privileged_exec", None
    return "interface_config", context


def convert() -> dict:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    commands = []
    for key, c in src["commands"].items():
        entity = ENTITY_MAP.get(key)
        entity_ref = f"entity.{VENDOR.lower()}.{TECH}.{_etype(entity)}.{entity}" if entity else None
        cli_mode, cli_context = _mode(c.get("context"))
        fields = c.get("fields_observed") or c.get("columns") or []
        if isinstance(fields, list) and fields and isinstance(fields[0], str):
            output_fields = [{"name": f, "type": "string", "unit": None,
                              "oid_ref": None, "oid_status": "not_mapped"} for f in fields]
        else:
            output_fields = []
        notes_parts = list(c.get("notes") or [])
        if c.get("example"):
            notes_parts.append(f"ejemplo: {c['example']}")
        commands.append({
            "id": f"command.{VENDOR.lower()}.{TECH}.{entity or 'global'}.show.{key}",
            "canonical_name": c["cmd"], "vendor": VENDOR, "family": FAMILY,
            "firmware": list(FIRMWARE), "technology": TECH, "category": "show",
            "cli_mode": cli_mode, "cli_context": cli_context, "entity_ref": entity_ref,
            "description": None, "syntax": c["cmd"],
            "parameters": [], "output_fields": output_fields,
            "prerequisites": [], "related_commands": [], "rollback": None, "errors": [],
            "notes": "; ".join(notes_parts) or None,
            "evidence": EVIDENCE,
            "sources": [{"doc_type": "community", "pages": None, "confidence": 0.3}],
            "confidence": {"extraction": 0.3, "correlation": 0.0, "overall": 0.3},
            "status": "documented", "conflicts": [],
        })
    return {
        "meta": {
            "doc_type": "commands", "vendor": VENDOR, "families": [FAMILY],
            "replace_seed": False,
            "source": str(SRC.relative_to(ROOT)),
            "generated_by": "scripts/build_huawei_command_catalog.py",
        },
        "commands": {FAMILY: commands},
    }


def _etype(short: str | None) -> str:
    from src.normalizer.normalizer import SHORT_NAME_TYPE
    return SHORT_NAME_TYPE.get(short, "logical") if short else "logical"


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT))
    doc = convert()
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(doc['commands'][FAMILY])} comandos -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
