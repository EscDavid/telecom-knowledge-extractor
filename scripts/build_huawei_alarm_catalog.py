#!/usr/bin/env python3
"""Construye docs/validation/alarms/huawei_ma5608t_alarm_types.json desde los ÚNICOS
objetos reales con enum de tipo-de-alarma que Observium expone para Huawei (ningún .mib
de Huawei trae NOTIFICATION-TYPE en su render — ver docs/adaptacion_multivendor.md).

No son traps tradicionales: son los valores de un campo "tipo de alarma" dentro de un
objeto de monitoreo real (confirmado por MibExtractor: ambos OID ya están en el catálogo
XPON-MIB). oid_trap siempre None — nunca hubo un OID de trap propio que fabricar;
oid_refs apunta al escalar REAL que define el enum, compartido por todos sus miembros.

Fuente: docs/huawei/ma5608t/observium/HUAWEI-XPON-TRAP-MIB.json (hwXponProfOntOpticalMoudle
AlarmType, 8 valores con enum_from_description real) + hwGponProfOntTDMPortAlarmType, cuyo
enum NO lo parseó el scraper de Observium (formato "Nombre (SIGLA)," en vez de "nombre(n) -
texto") — se transcribe a mano desde su DESCRIPTION real, citada tal cual abajo.

Uso: python scripts/build_huawei_alarm_catalog.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAP_MIB = ROOT / "docs/huawei/ma5608t/observium/HUAWEI-XPON-TRAP-MIB.json"
OUT = ROOT / "docs/validation/alarms/huawei_ma5608t_alarm_types.json"

VENDOR, FAMILY, TECH = "Huawei", "MA5608T", "gpon"
OPTICAL_OID = "1.3.6.1.4.1.2011.6.128.1.1.11.4"   # hwXponProfOntOpticalMoudleAlarmType
TDM_OID = "1.3.6.1.4.1.2011.6.128.1.1.11.1"       # hwGponProfOntTDMPortAlarmType (sic, nombre
                                                    # heredado de GPON-MIB pero vive bajo XPON)
TDM_DESCRIPTION_VERBATIM = (
    "This object indicates the alarm type.\nOptions:\n1. Transmit failure (TF),\n"
    "2. Loss of frame (LOF),\n3. Out of frame (OOF),\n4. Remote alarm indication (RAI),\n"
    "5. 2.048 Mbit/s alarm indication signal (AIS).")
TDM_TYPES = [  # transcrito a mano de TDM_DESCRIPTION_VERBATIM (el scraper no lo parseó)
    ("TF", "Transmit failure"), ("LOF", "Loss of frame"), ("OOF", "Out of frame"),
    ("RAI", "Remote alarm indication"),
    ("AIS", "2.048 Mbit/s alarm indication signal"),
]

EVIDENCE = ("tipo de alarma documentado en un objeto real de HUAWEI-XPON-MIB (render de "
           "Observium, nivel de evidencia B — ver docs/adaptacion_multivendor.md §2); no es "
           "un NOTIFICATION-TYPE/trap propio — Huawei no expone esos en ningún .mib fetched "
           "(ninguno de los 7 módulos ingeridos tiene kind=notification). oid_trap=null a "
           "propósito: no existe un OID de trap que citar, y no se fabrica uno.")


def _alarm(code_suffix: str, name: str, oid: str, atype: str, severity: str, desc: str) -> dict:
    entity_ref = f"entity.{VENDOR.lower()}.{TECH}.port.pon_port"   # ambos tipos cuelgan del ONT/PON
    return {
        "id": f"alarm.{VENDOR.lower()}.{TECH}.pon_port.{name}",
        "code": f"huawei.alarm_type.{code_suffix}", "name": name,
        "canonical_name": name.replace("_", " ").title(),
        "entity_ref": entity_ref, "vendor": VENDOR, "family": FAMILY,
        "firmware": ["R015"], "severity": severity, "type": atype,
        "description": desc,
        "probable_causes": [], "remediation": [],
        "oid_trap": None, "oid_refs": [oid],
        "auto_clear": False, "clear_condition": None, "threshold": None,
        "escalation": {"warning_after_minutes": None, "major_after_minutes": None,
                       "critical_after_minutes": None},
        "sources": [{"doc_type": "community", "pages": None, "confidence": 0.3}],
        "confidence": {"extraction": 0.3, "correlation": 0.0, "overall": 0.3},
        "status": "documented", "conflicts": [],
    }


def build() -> dict:
    trap_mib = json.loads(TRAP_MIB.read_text(encoding="utf-8"))
    optical = next(o for o in trap_mib["objects"] if o["oid"] == OPTICAL_OID)
    assert optical["enum_from_description"], "esperaba enum real en hwXponProfOntOpticalMoudleAlarmType"

    alarms = []
    for _num, label in sorted(optical["enum_from_description"].items(), key=lambda kv: int(kv[0])):
        alarms.append(_alarm(f"optical_module.{label.lower()}", f"optical_{label}",
                             OPTICAL_OID, "optical", "warning", optical["description"]))
    for acronym, label in TDM_TYPES:
        alarms.append(_alarm(f"tdm_port.{acronym.lower()}", f"tdm_{acronym.lower()}",
                             TDM_OID, "hardware", "major",
                             f"{label} ({acronym}). " + TDM_DESCRIPTION_VERBATIM))

    return {
        "meta": {
            "doc_type": "alarms", "vendor": VENDOR, "families": [FAMILY],
            "source": str(TRAP_MIB.relative_to(ROOT)),
            "generated_by": "scripts/build_huawei_alarm_catalog.py",
            "note": EVIDENCE,
        },
        "alarms": {FAMILY: alarms},
    }


def main() -> int:
    doc = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(doc['alarms'][FAMILY])} alarmas -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
