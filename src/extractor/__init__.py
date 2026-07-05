"""Módulo 2 — Extractor.

Orquesta un extractor por doc_type (según classifier_spec.json → doc_types):
    mib_file              → MibExtractor
    command_reference     → CommandExtractor
    initial_configuration → EntityExtractor (+ dependencias en CommandExtractor)
    product_catalog       → EntityExtractor + AlarmExtractor
    alarm_reference       → AlarmExtractor
    mib_specification     → EntityExtractor + MibExtractor
    hardware_description  → EntityExtractor

No interpreta ni relaciona — solo transforma texto en estructuras crudas.
"""
from __future__ import annotations

import logging
from typing import Any

from ..models import ClassifiedDoc, ExtractedData
from .alarm_extractor import AlarmExtractor
from .cmd_extractor import CommandExtractor
from .entity_extractor import EntityExtractor
from .mib_extractor import MibExtractor

log = logging.getLogger("tkc.extractor")


class Extractor:
    def __init__(self, config: dict[str, Any]):
        p = config["pipeline"]
        self.vendor = p["vendor"]
        self.family = p["family"]
        self.technology = p.get("technology", "gpon")
        self.firmware = list(p.get("firmware", []))
        kw = dict(vendor=self.vendor, family=self.family,
                  technology=self.technology, firmware=self.firmware)
        self.mib = MibExtractor(**kw)
        self.cmd = CommandExtractor(**kw)
        self.entity = EntityExtractor(**kw)
        self.alarm = AlarmExtractor(**kw)

    def run(self, classified_docs: list[ClassifiedDoc]) -> ExtractedData:
        data = ExtractedData()
        # Pre-pass: tabla global de asignaciones OID de TODOS los MIB, para que las
        # referencias importadas (ej. zxAnSystem desde ZTE-AN-SMI) resuelvan a OIDs
        # absolutos aunque vivan en otro archivo.
        self._mib_assignments = self._global_mib_assignments(classified_docs)
        if self._mib_assignments:
            log.info("Extractor: %d símbolos OID en la tabla global (resolución cruzada)",
                     len(self._mib_assignments))
        for doc in classified_docs:
            if doc.status == "unclassified":
                log.warning("Saltando documento unclassified: %s", doc.path.name)
                continue
            self._dispatch(doc, data)
        log.info("Extractor: %d entidades, %d comandos, %d OIDs, %d alarmas (brutos)",
                 len(data.entities), len(data.commands), len(data.oids), len(data.alarms))
        return data

    def _global_mib_assignments(self, classified_docs: list[ClassifiedDoc]) -> dict:
        assignments: dict = {}
        for doc in classified_docs:
            if doc.status == "unclassified":
                continue
            if doc.doc_type in ("mib_file", "mib_specification"):
                assignments.update(self.mib.collect_assignments(doc.text))
        return assignments

    def _dispatch(self, doc: ClassifiedDoc, data: ExtractedData) -> None:
        dt = doc.doc_type
        text = doc.text
        ga = self._mib_assignments
        if dt == "mib_file":
            data.oids += self.mib.extract(text, dt, extra_assignments=ga)
            data.alarms += self.mib.extract_notifications(text, dt, extra_assignments=ga)
        elif dt == "command_reference":
            data.commands += self.cmd.extract(text, dt)
        elif dt == "initial_configuration":
            data.entities += self.entity.extract(text, dt)
            data.commands += self.cmd.extract(text, dt)
        elif dt == "product_catalog":
            data.entities += self.entity.extract(text, dt)
            data.alarms += self.alarm.extract(text, dt)
        elif dt == "alarm_reference":
            data.alarms += self.alarm.extract(text, dt)
        elif dt == "mib_specification":
            data.entities += self.entity.extract(text, dt)
            data.oids += self.mib.extract(text, dt, extra_assignments=self._mib_assignments)
        elif dt == "hardware_description":
            data.entities += self.entity.extract(text, dt)
        else:
            # partial / sin doc_type → extractores genéricos de entidad
            log.info("Documento %s sin doc_type claro: extracción genérica de entidades",
                     doc.path.name)
            data.entities += self.entity.extract(text, dt or "product_catalog")


__all__ = ["Extractor", "MibExtractor", "CommandExtractor",
           "EntityExtractor", "AlarmExtractor"]
