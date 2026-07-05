"""Fase 2 — triggers automáticos del WalkValidator.

Cada trigger inspecciona el walk o el cruce walk↔catálogo y registra un
`finding` (dict) en un objeto `Findings`. Los findings se vuelcan a
`results.json` del catálogo enriquecido y guían las acciones sobre el catálogo
(status=conflicted, index_type=ascii, poda, etc.).

No muta el catálogo directamente: solo detecta y describe. El enricher lee estos
findings para decidir acciones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Findings:
    """Colector de hallazgos de la validación empírica."""
    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, finding: dict[str, Any]) -> None:
        self.items.append(finding)

    def by_trigger(self, name: str) -> list[dict[str, Any]]:
        return [f for f in self.items if f.get("trigger") == name]

    def blocking(self) -> list[dict[str, Any]]:
        """Hallazgos que exigen confirmación/rechazo antes de escribir el catálogo."""
        return [f for f in self.items if f.get("blocking")]

    def conflicted_tables(self) -> set[str]:
        return {f["tabla"] for f in self.by_trigger("oid_not_increasing") if f.get("tabla")}

    def ascii_tables(self) -> set[str]:
        return {f["tabla"] for f in self.by_trigger("ascii_index") if f.get("tabla")}


# --- utilidades de OID --------------------------------------------------------
def extract_table_prefix(oid: str) -> str:
    """Prefijo de tabla: recorta el índice de instancia final.

    Heurística: una tabla SNMP tiene la forma ...tabla.entry.columna.INDICE.
    Sin el MIB no conocemos el largo del índice, así que usamos el OID sin su
    último componente como aproximación estable para agrupar hallazgos.
    """
    parts = oid.lstrip(".").split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else oid.lstrip(".")


def is_ascii_index(oid: str) -> bool:
    """True si los componentes finales del OID forman texto ASCII imprimible.

    Caso real: 3902.1015.2.1.2... con índices 115,99,120,... = 's','c','x',...
    """
    parts = oid.lstrip(".").split(".")
    tail = parts[-10:]
    chars = [int(p) for p in tail if p.isdigit()]
    if not chars:
        return False
    printable = sum(1 for c in chars if 32 <= c <= 126)
    return printable / len(chars) > 0.7


def decode_ascii_index(oid: str) -> str:
    """Decodifica los componentes imprimibles finales del OID a texto."""
    parts = oid.lstrip(".").split(".")
    out = []
    for p in reversed(parts):
        if p.isdigit() and 32 <= int(p) <= 126:
            out.append(chr(int(p)))
        else:
            break
    return "".join(reversed(out))


# --- triggers durante el parse ------------------------------------------------
def trigger_oid_not_increasing(findings: Findings, current_oid: str,
                               previous_oid: str, line_num: int) -> None:
    """La OLT devolvió OIDs fuera de orden (tabla inestable / lexicográfico roto)."""
    tabla = extract_table_prefix(current_oid)
    findings.add({
        "trigger": "oid_not_increasing",
        "tabla": tabla,
        "oid_actual": current_oid,
        "oid_anterior": previous_oid,
        "linea": line_num,
        "catalog_action": f"status=conflicted en OIDs de tabla {tabla}",
        "severity": "high",
    })


def trigger_ascii_index(findings: Findings, oid: str) -> None:
    """Índice de tabla codificado como caracteres ASCII (ej. versiones de firmware)."""
    tabla = extract_table_prefix(oid)
    findings.add({
        "trigger": "ascii_index",
        "tabla": tabla,
        "oid": oid,
        "decoded_value": decode_ascii_index(oid),
        "catalog_action": f"index_type=ascii en tabla {tabla}",
        "severity": "low",
    })


# --- triggers durante el cruce ------------------------------------------------
def trigger_partial_response(findings: Findings, tabla_prefix: str,
                             capturados: int, esperados: int) -> None:
    """Rama con menos OIDs de los esperados (timeout / respuesta parcial)."""
    findings.add({
        "trigger": "partial_response",
        "tabla": tabla_prefix,
        "capturados": capturados,
        "esperados": esperados,
        "catalog_action": f"status=observed en OIDs de rama {tabla_prefix}",
        "severity": "medium",
    })


def trigger_observed_only(findings: Findings, tabla: str, instancias: int,
                          sample_oid: str, sample_value: str) -> None:
    """Rama que responde en producción pero no está en el catálogo teórico.

    Agregado por tabla (no por instancia) para no generar miles de entradas.
    """
    findings.add({
        "trigger": "observed_only",
        "tabla": tabla,
        "instancias": instancias,
        "sample_oid": sample_oid,
        "sample_value": sample_value,
        "catalog_action": "status=observed, agregar a investigación",
        "severity": "low",
    })


def trigger_documented_only(findings: Findings, oid_id: str, oid_string: str,
                            access: str, pruned: bool) -> None:
    """OID teórico del MIB que no respondió en el walk.

    Si se poda (read-only sin respaldo) → sale del catálogo C300. Si se conserva
    (writable/action) → queda como documented no confirmado.
    """
    findings.add({
        "trigger": "documented_only",
        "oid_id": oid_id,
        "oid": oid_string,
        "access": access,
        "pruned": pruned,
        "catalog_action": ("podado del catálogo C300 (sin respuesta en walk)"
                           if pruned else "status=documented (no confirmado en producción)"),
        "severity": "low",
    })


def trigger_out_of_range(findings: Findings, oid: str, value: int,
                         expected_min: int, expected_max: int) -> None:
    """Valor SNMP fuera del rango esperado según el MIB."""
    findings.add({
        "trigger": "out_of_range",
        "oid": oid,
        "value_real": value,
        "range_expected": f"{expected_min} a {expected_max}",
        "catalog_action": "revisar scale o unidad del OID",
        "severity": "medium",
    })


# --- detección de escala ------------------------------------------------------
SCALE_HINTS = {
    "rx_power": {"range": (-50, 10), "unit": "dBm"},
    "tx_power": {"range": (-10, 10), "unit": "dBm"},
    "temperature": {"range": (0, 100), "unit": "celsius"},
    "voltage": {"range": (0, 60), "unit": "volts"},
}


def trigger_scale_detection(findings: Findings, oid: str, oid_name: str,
                            value: int) -> Optional[float]:
    """Detecta empíricamente la escala de una métrica óptica/ambiental.

    Caso real: rx_power llega como -2300 → -23.00 dBm (scale=0.01). Devuelve la
    escala detectada o None.
    """
    name = (oid_name or "").lower()
    for metric, hint in SCALE_HINTS.items():
        if metric in name:
            lo, hi = hint["range"]
            if lo <= value <= hi:
                return None  # ya está en rango, sin escala
            for scale in (0.1, 0.01, 0.001):
                scaled = value * scale
                if lo <= scaled <= hi:
                    findings.add({
                        "trigger": "scale_detected",
                        "oid": oid,
                        "raw_value": value,
                        "scale": scale,
                        "scaled_value": round(scaled, 3),
                        "unit": hint["unit"],
                        "catalog_action": f"scale={scale} confirmado empíricamente",
                        "severity": "low",
                    })
                    return scale
    return None
