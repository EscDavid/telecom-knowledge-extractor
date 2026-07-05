#!/usr/bin/env python3
"""Genera un reporte de riesgo de OIDs a partir del catálogo TKC.

Clasifica cada OID en:
  - risk_level        : CRITICAL / HIGH / MEDIUM / SAFE / INFO
  - recommended_role  : el rol mínimo de usuario que debería poder tocarlo
                        (monitor < operator < engineer < superuser)
  - danger_signals    : verbos/patrones que motivaron la clasificación
  - description        : descripción breve (último atributo) del objeto

Las NO riesgosas (solo lectura, índices, traps) también se clasifican y se
asignan al rol que corresponde, para poder construir vistas SNMP por permiso.

Uso:
    python scripts/risk_report.py [catalog_dir] [out_dir]
Por defecto lee el catálogo ZTE C320 y escribe en reports/security/.
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# --- modelo de permisos (RBAC) -------------------------------------------------
# Cada rol HEREDA lo del anterior. El reporte asigna a cada OID el rol MÍNIMO
# que debería tener permiso para operarlo.
PERMISSION_MODEL = {
    "monitor":  "Solo lectura (GET). Monitoreo y contadores. Sin escritura.",
    "operator": "Operación de bajo impacto: cambios de estado reversibles "
                "(habilitar/deshabilitar, limpiar estadísticas, umbrales).",
    "engineer": "Aprovisionamiento de servicio: crear/modificar VLAN, "
                "service-ports, perfiles ONU (read-create no destructivo).",
    "superuser": "Acciones destructivas o de plataforma: borrar filas "
                 "(RowStatus destroy), reset/reboot de tarjeta, firmware/upgrade.",
}

WRITABLE = {"read-write", "read-create", "write-only"}

# verbos destructivos / de plataforma (se buscan en el NOMBRE, más fiable)
DESTRUCTIVE = re.compile(
    r"reboot|restart|reload|reset|delete|destroy|erase|format|wipe|factory|"
    r"rollback|poweroff|halt", re.I)
PLATFORM = re.compile(
    r"upgrade|update|swap|switchover|activate|active|image|patch|firmware|boot",
    re.I)
SERVICE_AFFECT = re.compile(r"adminstatus|shutdown|disable|enable|admindown", re.I)
ROWSTATUS = re.compile(r"rowstatus$", re.I)


def classify(o: dict) -> dict:
    name = o.get("name", "") or ""
    access = o.get("access") or "read-only"
    desc = (o.get("description") or "").strip()
    low = name.lower()
    signals: list[str] = []

    # --- NO escribibles: clasificación informativa --------------------------
    if access not in WRITABLE:
        if access == "not-accessible":
            return _row(o, "INFO", "monitor", ["index/structural"],
                        _brief(desc, name, "Índice/columna estructural de tabla "
                               "(no consultable directamente)."))
        if access == "accessible-for-notify":
            return _row(o, "INFO", "monitor", ["trap-payload"],
                        _brief(desc, name, "Objeto transportado en notificaciones "
                               "(trap), no operable."))
        return _row(o, "SAFE", "monitor", ["read-only"],
                    _brief(desc, name, "Objeto de solo lectura para monitoreo "
                           "de " + _ent(o) + "."))

    # --- escribibles: por gravedad ------------------------------------------
    if ROWSTATUS.search(low):
        signals.append("RowStatus(destroy)")
        return _row(o, "CRITICAL", "superuser", signals,
                    _brief(desc, name, "Columna RowStatus: un SET=destroy(6) "
                           "ELIMINA la fila de " + _ent(o) + "."))
    if DESTRUCTIVE.search(low):
        signals.append("destructive:" + ",".join(sorted(set(DESTRUCTIVE.findall(low)))))
        return _row(o, "CRITICAL", "superuser", signals,
                    _brief(desc, name, "Acción destructiva/irreversible sobre "
                           + _ent(o) + " (reset/borrado)."))
    if PLATFORM.search(low) and re.search(r"sw|soft|image|patch|firmware|update|upgrade|boot", low):
        signals.append("platform:firmware/activation")
        return _row(o, "CRITICAL", "superuser", signals,
                    _brief(desc, name, "Activación/actualización de software o "
                           "firmware de la plataforma."))
    if SERVICE_AFFECT.search(low):
        signals.append("service-affecting:" + ",".join(sorted(set(SERVICE_AFFECT.findall(low)))))
        return _row(o, "HIGH", "operator", signals,
                    _brief(desc, name, "Estado administrativo escribible: "
                           "habilita/deshabilita " + _ent(o) + " (afecta servicio)."))
    if access == "read-create":
        signals.append("provisioning(read-create)")
        return _row(o, "HIGH", "engineer", signals,
                    _brief(desc, name, "Parámetro de aprovisionamiento "
                           "(crea/define configuración de " + _ent(o) + ")."))
    # read-write genérico
    signals.append("config(read-write)")
    return _row(o, "MEDIUM", "operator", signals,
                _brief(desc, name, "Parámetro de configuración escribible de "
                       + _ent(o) + "."))


def _ent(o: dict) -> str:
    return o.get("_entity", "?").split(".")[-1].replace("_", " ")


def _brief(desc: str, name: str, fallback: str) -> str:
    """Descripción breve: 1ª oración del MIB (recortada) o síntesis."""
    if desc:
        first = re.split(r"(?<=[.])\s", desc.replace("\n", " "))[0]
        first = " ".join(first.split())
        return (first[:160] + "…") if len(first) > 160 else first
    return fallback


def _row(o, risk, role, signals, description) -> dict:
    return {
        "oid": o.get("oid", ""),
        "name": o.get("name", ""),
        "entity": o.get("_entity", "?"),
        "access": o.get("access", ""),
        "risk_level": risk,
        "recommended_role": role,
        "danger_signals": signals,
        "description": description,   # último atributo, breve
    }


def main() -> None:
    catalog = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "catalog/zte/zxa10-c320/catalog-1.0.0")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/security")
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for f in sorted(glob.glob(str(catalog / "oids" / "*.json"))):
        g = json.load(open(f, encoding="utf-8"))
        for o in g.get("oids", []):
            o["_entity"] = g.get("entity_ref", "?")
            rows.append(classify(o))

    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "SAFE": 3, "INFO": 4}
    rows.sort(key=lambda r: (order[r["risk_level"]], r["entity"], r["name"]))

    summary = {
        "total": len(rows),
        "by_risk": dict(Counter(r["risk_level"] for r in rows)),
        "by_role": dict(Counter(r["recommended_role"] for r in rows)),
        "writable": sum(r["access"] in WRITABLE for r in rows),
        "critical_writable": sum(r["risk_level"] == "CRITICAL" for r in rows),
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalog": str(catalog),
        "permission_model": PERMISSION_MODEL,
        "summary": summary,
        "oids": rows,
    }

    (out_dir / "oid_risk_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(out_dir / "oid_risk_report.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["oid", "name", "entity", "access", "risk_level",
                    "recommended_role", "danger_signals", "description"])
        for r in rows:
            w.writerow([r["oid"], r["name"], r["entity"], r["access"],
                        r["risk_level"], r["recommended_role"],
                        "|".join(r["danger_signals"]), r["description"]])

    print("Reporte escrito en", out_dir)
    print("Resumen:", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
