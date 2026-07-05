"""Módulo 4 — Correlator.

Cruza información entre fuentes, calcula confidence (extraction + correlation +
overall, según confidence_model.json) y deriva relaciones entre entidades.

Cruces implementados:
  - output_field de comando ↔ OID de MIB (similitud de nombre) → oid_ref / command_ref
  - prerequisites de comandos → relaciones depends_on
  - threshold_metric de alarma ↔ OID → alarm.oid_refs
  - relaciones estructurales GPON entre entidades presentes

Propagación: relation.overall <= min(endpoints); alarm.overall <= min(entity, oids).
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from ..confidence import ConfidenceModel
from ..ids import build_relation_id, entity_short_name, snake
from ..models import (Confidence, CorrelatedData, Relation, Source)

log = logging.getLogger("tkc.correlator")

# Plantillas de relaciones estructurales GPON (source_short, type, target_short,
# cardinality, required, prerequisite). Solo se emiten si ambas entidades existen.
RELATION_TEMPLATES = [
    ("onu", "belongs_to", "pon_port", "many_to_one", True, True),
    ("onu", "uses", "gem_port", "one_to_many", True, False),
    ("onu", "has", "service_port", "one_to_many", False, False),
    ("onu", "uses", "line_profile", "many_to_one", False, True),
    ("service_port", "belongs_to", "onu", "many_to_one", True, True),
    ("gem_port", "belongs_to", "onu", "many_to_one", True, True),
    ("pon_port", "belongs_to", "card", "many_to_one", True, False),
    ("card", "belongs_to", "shelf", "many_to_one", False, False),
]
_NAME_SIM_THRESHOLD = 0.62


class Correlator:
    def __init__(self, config: dict[str, Any]):
        p = config["pipeline"]
        self.vendor = p["vendor"]
        self.family = p["family"]
        self.technology = p.get("technology", "gpon")
        self.firmware = list(p.get("firmware", []))
        self.model = ConfidenceModel.load(Path(config["paths"]["schemas"]))

    def run(self, normalized) -> CorrelatedData:
        data = CorrelatedData(
            entities=normalized.entities, commands=normalized.commands,
            oids=normalized.oids, alarms=normalized.alarms,
            aliases_index=normalized.aliases_index, ambiguous=normalized.ambiguous,
        )
        # 1. extraction confidence para cada artefacto
        for art in [*data.entities, *data.commands, *data.oids, *data.alarms]:
            art.confidence.extraction = self.model.extraction(art.sources)
            for s in art.sources:
                s.confidence = self.model.doc_weights.get(s.doc_type, 0.0)

        # 2. cruces
        self._map_output_fields_to_oids(data.commands, data.oids)
        self._map_alarms_to_oids(data.alarms, data.oids)
        data.relations = self._derive_relations(data)

        # 3. correlation + overall para entidades/comandos/oids
        for art in [*data.entities, *data.commands, *data.oids]:
            art.confidence.correlation = self._correlation(art)
            art.confidence.overall = self.model.overall(
                art.confidence.extraction, art.confidence.correlation)

        # 4. propagación a relaciones y alarmas
        overall_by_id = {e.id: e.confidence.overall for e in data.entities}
        overall_by_id.update({o.id: o.confidence.overall for o in data.oids})
        self._finalize_relations(data.relations, overall_by_id)
        self._finalize_alarms(data.alarms, overall_by_id)

        log.info("Correlator: %d relaciones derivadas", len(data.relations))
        return data

    # --- cruces ---------------------------------------------------------------
    def _map_output_fields_to_oids(self, commands, oids) -> None:
        for cmd in commands:
            for field in cmd.output_fields:
                best, score = self._best_oid(field.name, oids)
                if best and score >= _NAME_SIM_THRESHOLD:
                    field.oid_ref = best.id
                    field.oid_status = "mapped"
                    if not best.command_ref:
                        best.command_ref = cmd.id

    def _map_alarms_to_oids(self, alarms, oids) -> None:
        for alarm in alarms:
            metric = (alarm.threshold or {}).get("metric") if alarm.threshold else None
            if not metric:
                continue
            best, score = self._best_oid(metric, oids)
            if best and score >= _NAME_SIM_THRESHOLD and best.id not in alarm.oid_refs:
                alarm.oid_refs.append(best.id)

    @staticmethod
    def _best_oid(name: str, oids) -> tuple[Optional[Any], float]:
        target = snake(re.sub(r"(?<!^)(?=[A-Z])", "_", name))
        best, best_score = None, 0.0
        for o in oids:
            cand = snake(re.sub(r"(?<!^)(?=[A-Z])", "_", o.name))
            score = SequenceMatcher(None, target, cand).ratio()
            score = max(score, SequenceMatcher(None, target, o.metric or "").ratio())
            if score > best_score:
                best, best_score = o, score
        return best, best_score

    # --- relaciones -----------------------------------------------------------
    def _derive_relations(self, data) -> list[Relation]:
        short_to_id = {e.short_name: e.id for e in data.entities}
        relations: list[Relation] = []
        seen: set[str] = set()

        # estructurales
        order = 0
        for src, rtype, tgt, card, required, prereq in RELATION_TEMPLATES:
            if src in short_to_id and tgt in short_to_id:
                rel = self._make_relation(
                    short_to_id[src], rtype, short_to_id[tgt], card, required, prereq,
                    creation_order=order if prereq else None,
                    doc_type="initial_configuration",
                    quality="inferred_by_context")
                if rel.id not in seen:
                    relations.append(rel)
                    seen.add(rel.id)
                    if prereq:
                        order += 1

        # desde prerequisites de comandos
        for cmd in data.commands:
            if not cmd.entity_ref:
                continue
            for i, prereq in enumerate(cmd.prerequisites):
                target_id = self._resolve_prereq(prereq, short_to_id, data.aliases_index)
                if not target_id or target_id == cmd.entity_ref:
                    continue
                rel = self._make_relation(
                    cmd.entity_ref, "depends_on", target_id, "many_to_one",
                    required=True, prereq=True, creation_order=i,
                    doc_type="command_reference", quality="direct_with_page")
                if rel.id not in seen:
                    relations.append(rel)
                    seen.add(rel.id)
        return relations

    def _make_relation(self, source_id, rtype, target_id, card, required, prereq,
                       creation_order, doc_type, quality) -> Relation:
        return Relation(
            id=build_relation_id(self.vendor, self.technology, source_id, rtype, target_id),
            type=rtype, source_entity=source_id, target=target_id,
            vendor=self.vendor, family=self.family, firmware=list(self.firmware),
            cardinality=card, required=required, prerequisite=prereq,
            creation_order=creation_order,
            sources=[Source(doc_type=doc_type, pages=None,
                            confidence=self.model.doc_weights.get(doc_type, 0.0),
                            quality=quality)],
        )

    @staticmethod
    def _resolve_prereq(prereq: str, short_to_id, alias_index) -> Optional[str]:
        if prereq.startswith("entity."):
            return prereq
        key = snake(prereq)
        if key in short_to_id:
            return short_to_id[key]
        return alias_index.get(key)

    # --- confidence -----------------------------------------------------------
    def _correlation(self, artifact) -> float:
        # La correlación es un BONUS de corroboración cruzada (se SUMA en overall).
        # Una fuente única no tiene con qué corroborarse → 0.0 (antes 0.40, un piso
        # heredado del modelo viejo donde correlation era un eje obligatorio del 40%).
        # Así un OID de MIB determinista queda en "documented", y "verified" se
        # reserva para la confirmación empírica del walk (Fase 2).
        doctypes = {s.doc_type for s in artifact.sources}
        n = len(doctypes)
        if n <= 1:
            base = 0.0
        else:
            base = min(1.0, 0.55 + 0.20 * (n - 1))
        # bono por cruce confirmado (output_field mapeado / command_ref)
        if getattr(artifact, "command_ref", None):
            base = min(1.0, base + 0.20)
        if getattr(artifact, "output_fields", None):
            if any(f.oid_status == "mapped" for f in artifact.output_fields):
                base = min(1.0, base + 0.15)
        return round(base, 3)

    def _finalize_relations(self, relations, overall_by_id) -> None:
        for rel in relations:
            rel.confidence.extraction = self.model.extraction(rel.sources)
            rel.confidence.correlation = self._correlation(rel)
            raw = self.model.overall(rel.confidence.extraction, rel.confidence.correlation)
            cap = min(overall_by_id.get(rel.source_entity, 1.0),
                      overall_by_id.get(rel.target, 1.0))
            rel.confidence.overall = round(min(raw, cap), 3)

    def _finalize_alarms(self, alarms, overall_by_id) -> None:
        for alarm in alarms:
            alarm.confidence.correlation = self._correlation(alarm)
            raw = self.model.overall(alarm.confidence.extraction, alarm.confidence.correlation)
            caps = [overall_by_id.get(alarm.entity_ref, 1.0)]
            caps += [overall_by_id.get(o, 1.0) for o in alarm.oid_refs]
            alarm.confidence.overall = round(min([raw, *caps]), 3)
