"""Formateo de varbinds al estilo ``snmpbulkwalk -On`` (sin MIBs).

Una línea por OID SIEMPRE, compatible con ``WalkValidator.parse_walk`` (que parte por
``" = "`` y luego por ``": "``). Desviación documentada respecto a net-snmp: los
Hex-STRING salen en UNA sola línea (net-snmp parte cada 16 bytes).
"""
from __future__ import annotations

from .oid import fmt_oid
from .transport import EXCEPTION_KINDS, Varbind

_WS_TO_SPACE = {0x09, 0x0D, 0x0A}


def _is_printable(data: bytes) -> bool:
    return all(0x20 <= b <= 0x7E or b in _WS_TO_SPACE for b in data)


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _string_value(data: bytes) -> str:
    if not data:
        return '""'
    if _is_printable(data):
        text = "".join(" " if b in _WS_TO_SPACE else chr(b) for b in data)
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'STRING: "{text}"'
    return f"Hex-STRING: {_hex(data)}"


def format_timeticks(ticks: int) -> str:
    """3179 → ``(3179) 0:00:31.79``; con días ``(8640000) 1 day, 0:00:00.00``."""
    cs = ticks % 100
    total_s = ticks // 100
    secs = total_s % 60
    mins = (total_s // 60) % 60
    hours = (total_s // 3600) % 24
    days = total_s // 86400
    clock = f"{hours}:{mins:02d}:{secs:02d}.{cs:02d}"
    if days:
        unit = "day" if days == 1 else "days"
        clock = f"{days} {unit}, {clock}"
    return f"({ticks}) {clock}"


def format_value(vb: Varbind) -> str | None:
    kind, val = vb.kind, vb.value
    if kind in EXCEPTION_KINDS:
        return None
    if kind == "INTEGER":
        return f"INTEGER: {int(val)}"
    if kind == "OCTETS":
        return _string_value(bytes(val))
    if kind == "OID":
        return f"OID: {fmt_oid(tuple(val))}"
    if kind == "IPADDR":
        return f"IpAddress: {val}"
    if kind == "COUNTER32":
        return f"Counter32: {int(val)}"
    if kind == "GAUGE32":
        return f"Gauge32: {int(val)}"
    if kind == "COUNTER64":
        return f"Counter64: {int(val)}"
    if kind == "TIMETICKS":
        return f"Timeticks: {format_timeticks(int(val))}"
    if kind == "OPAQUE":
        return f"Opaque: {_hex(bytes(val))}"
    if kind == "BITS":
        return f"BITS: {_hex(bytes(val))}"
    if kind == "NULL":
        return "NULL"
    raise ValueError(f"tipo de varbind desconocido: {kind!r}")


def format_line(vb: Varbind) -> str | None:
    """Línea de walk para el varbind; ``None`` para endOfMibView / noSuch*.

    Nunca contiene saltos de línea.
    """
    value = format_value(vb)
    if value is None:
        return None
    line = f"{fmt_oid(vb.oid)} = {value}"
    assert "\n" not in line and "\r" not in line
    return line
