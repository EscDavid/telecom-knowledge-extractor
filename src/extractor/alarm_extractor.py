"""AlarmExtractor — extrae alarmas de product_catalog o alarm_reference.

Detecta filas de tabla de alarmas con formato `<code> <NAME> <severity> ...`
(códigos ZTE 330xx) y deriva tipo/severidad. Causas y remediación se leen de los
bloques de texto contiguos si existen.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import QUALITY_DIRECT_NO_PAGE, Alarm, Source

log = logging.getLogger("tkc.extractor.alarm")

_SEVERITY_MAP = {
    "critical": "critical", "crit": "critical",
    "major": "major",
    "minor": "warning", "warning": "warning", "warn": "warning",
}
_TYPE_KEYWORDS = [
    (r"\bLOS\b|optical|power|signal|dying.?gasp", "optical"),
    (r"board|card|chassis|hardware|fan", "hardware"),
    (r"voltage|supply|battery", "power"),
    (r"auth|security|unauthorized|illegal", "security"),
    (r"traffic|bandwidth|congestion|overload", "traffic"),
    (r"ploam|omci|gpon|register|protocol", "protocol"),
    (r"temperature|humidity|environ", "environmental"),
]
# fila de alarma: código numérico de 4-5 dígitos + nombre en MAYÚSCULAS/_  + severidad
_ALARM_ROW_RE = re.compile(
    r"(?P<code>\b\d{4,5}\b)\s+(?P<name>[A-Z][A-Z0-9_ ]{2,40}?)\s+"
    r"(?P<sev>critical|major|minor|warning)\b",
    re.IGNORECASE,
)


class AlarmExtractor:
    def __init__(self, vendor: str, family: str, technology: str, firmware: list[str]):
        self.vendor = vendor
        self.family = family
        self.technology = technology
        self.firmware = firmware

    def extract(self, text: str, doc_type: str = "alarm_reference") -> list[Alarm]:
        if not text:
            return []
        alarms: list[Alarm] = []
        seen: set[str] = set()
        for m in _ALARM_ROW_RE.finditer(text):
            code = m.group("code")
            if code in seen:
                continue
            seen.add(code)
            name = "_".join(m.group("name").split()).upper()
            window = text[m.start(): m.start() + 500]
            alarms.append(Alarm(
                code=code, name=name,
                canonical_name=self._canonical(name),
                entity_ref=self._guess_entity(name + " " + window),
                vendor=self.vendor, family=self.family,
                firmware=list(self.firmware),
                severity=_SEVERITY_MAP.get(m.group("sev").lower(), "warning"),
                type=self._guess_type(name + " " + window),
                description=self._description(window),
                probable_causes=self._list_after(window, r"(?:Probable\s*)?Causes?"),
                remediation=self._list_after(window, r"(?:Remediation|Action|Handling|Suggestion)s?"),
                auto_clear=bool(re.search(r"auto.?clear|self.?clear", window, re.IGNORECASE)),
                sources=[Source(doc_type=doc_type, pages=None, confidence=0.0,
                                quality=QUALITY_DIRECT_NO_PAGE)],
            ))
        log.info("AlarmExtractor(%s): %d alarma(s)", doc_type, len(alarms))
        return alarms

    # --- helpers --------------------------------------------------------------
    @staticmethod
    def _canonical(name: str) -> str:
        return name.replace("_", " ").title()

    @staticmethod
    def _guess_entity(blob: str) -> str:
        low = blob.lower()
        for kw, entity in [("onu", "onu"), ("ont", "onu"), ("pon", "pon_port"),
                           ("card", "card"), ("board", "card"), ("olt", "olt")]:
            if kw in low:
                return entity
        return "olt"

    @staticmethod
    def _guess_type(blob: str) -> str:
        for rx, t in _TYPE_KEYWORDS:
            if re.search(rx, blob, re.IGNORECASE):
                return t
        return "protocol"

    @staticmethod
    def _description(window: str) -> Optional[str]:
        m = re.search(r"(?:Description|Meaning)\s*[:：]\s*([^\n]+)", window, re.IGNORECASE)
        return m.group(1).strip()[:300] if m else None

    @staticmethod
    def _list_after(window: str, label_rx: str) -> list[str]:
        m = re.search(label_rx + r"\s*[:：]\s*(.+?)(?:\n\s*\n|$)", window,
                      re.IGNORECASE | re.DOTALL)
        if not m:
            return []
        chunk = m.group(1)
        items = re.split(r"\n\s*[-*•]\s*|\n\d+[.)]\s*|;\s*", chunk)
        return [" ".join(i.split()) for i in items if i.strip()][:6]
