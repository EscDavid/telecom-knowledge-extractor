"""Módulo 5 — Validator.

Aplica penalizaciones de confidence_model.json, deriva el `status` final por
umbrales, detecta huérfanos/conflictos (registros estilo tkc_results), agrupa
OIDs/relaciones/alarmas por entidad para la escritura y construye el manifest
del catálogo.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..confidence import ConfidenceModel
from ..ids import entity_short_name
from ..models import (AlarmGroup, OidGroup, RelationGroup, RelationRef,
                      ValidatedData)

log = logging.getLogger("tkc.validator")

_INFERRED_QUALITIES = {"inferred_by_context", "inferred_by_correlation",
                       "deduced_without_evidence"}


class Validator:
    def __init__(self, config: dict[str, Any]):
        p = config["pipeline"]
        self.vendor = p["vendor"]
        self.family = p["family"]
        self.technology = p.get("technology", "gpon")
        self.firmware = list(p.get("firmware", []))
        self.catalog_version = p.get("catalog_version", "1.0.0")
        self.model = ConfidenceModel.load(Path(config["paths"]["schemas"]))

    def run(self, correlated) -> ValidatedData:
        ambiguous_ids = {i for a in correlated.ambiguous for i in a["candidates"]}
        results: list[dict[str, Any]] = []

        # 1. penalizaciones + status final por artefacto
        for art, atype in self._all_artifacts(correlated):
            self._finalize(art, atype, ambiguous_ids, results)

        # orden determinista → salida reproducible (permite diff teoría vs. Fase 2)
        results.sort(key=lambda r: (r["result_type"], r["artifact_type"], r["artifact_id"]))

        # 2. relaciones embebidas en cada entidad (referencia rápida)
        self._attach_relation_refs(correlated.entities, correlated.relations)

        # 3. agrupación para escritura
        data = ValidatedData(
            entities=correlated.entities,
            commands=correlated.commands,
            oids=self._group_oids(correlated),
            relations=self._group_relations(correlated),
            alarms=self._group_alarms(correlated),
            conflicts=results,
        )
        data.manifest = self._build_manifest(correlated, data)
        log.info("Validator: %d conflictos/huérfanos registrados", len(results))
        return data

    # --- finalización por artefacto ------------------------------------------
    def _all_artifacts(self, correlated):
        for e in correlated.entities:
            yield e, "entity"
        for c in correlated.commands:
            yield c, "command"
        for o in correlated.oids:
            yield o, "oid"
        for r in correlated.relations:
            yield r, "relation"
        for a in correlated.alarms:
            yield a, "alarm"

    def _finalize(self, art, atype, ambiguous_ids, results) -> None:
        doctypes = {s.doc_type for s in art.sources}
        # Fuente única SOLO penaliza si NO es de formato autoritativo: un MIB ASN.1
        # determinista no necesita corroboración para que su procedencia sea fiable.
        single = len(doctypes) <= 1 and not self.model.is_authoritative(art.sources)
        inference_only = bool(art.sources) and all(
            s.quality in _INFERRED_QUALITIES for s in art.sources)
        ambiguous = getattr(art, "id", None) in ambiguous_ids
        unresolved = any(getattr(c, "resolution", "unresolved") == "unresolved"
                         for c in getattr(art, "conflicts", []))
        firmware_unconfirmed = not getattr(art, "firmware", None)

        art.confidence.overall = self.model.apply_penalties(
            art.confidence.overall,
            has_unresolved_conflict=unresolved, ambiguous_alias=ambiguous,
            single_source=single, inference_only=inference_only,
            firmware_unconfirmed=firmware_unconfirmed)
        art.status = self.model.determine_status(art.confidence.overall, unresolved)

        # huérfano: solo respaldado por inferencia/correlación, sin doc real
        if inference_only and atype in {"entity", "oid", "command", "alarm"}:
            results.append(self._orphan_result(art, atype))
        # conflictos activos → registro tkc_results
        for c in getattr(art, "conflicts", []):
            results.append(self._conflict_result(art, atype, c))

    def _orphan_result(self, art, atype) -> dict[str, Any]:
        return {
            "result_type": "orphan", "artifact_type": atype, "artifact_id": art.id,
            "vendor": self.vendor, "resolved": False,
            "payload": {"reason": "Artefacto solo respaldado por inferencia, sin documento fuente directo",
                        "since_version": self.catalog_version},
        }

    def _conflict_result(self, art, atype, c) -> dict[str, Any]:
        return {
            "result_type": "conflict", "artifact_type": atype, "artifact_id": art.id,
            "vendor": self.vendor, "resolved": c.resolution != "unresolved",
            "payload": {"field": c.field, "source_a": c.source_a, "source_b": c.source_b,
                        "resolution": c.resolution, "severity": getattr(c, "severity", "high")},
        }

    # --- relaciones embebidas -------------------------------------------------
    @staticmethod
    def _attach_relation_refs(entities, relations) -> None:
        by_source = defaultdict(list)
        for r in relations:
            by_source[r.source_entity].append(RelationRef(type=r.type, target=r.target))
        for e in entities:
            e.relations = by_source.get(e.id, [])

    # --- agrupación -----------------------------------------------------------
    def _group_oids(self, correlated) -> list[OidGroup]:
        fw_by_entity = {e.id: e.firmware for e in correlated.entities}
        groups: dict[str, OidGroup] = {}
        for o in correlated.oids:
            g = groups.get(o.entity_ref)
            if not g:
                g = OidGroup(entity_ref=o.entity_ref,
                             entity_name=entity_short_name(o.entity_ref),
                             vendor=self.vendor, family=self.family,
                             firmware=fw_by_entity.get(o.entity_ref, list(self.firmware)),
                             oids=[])
                groups[o.entity_ref] = g
            g.oids.append(o)
        return list(groups.values())

    def _group_relations(self, correlated) -> list[RelationGroup]:
        groups: dict[str, RelationGroup] = {}
        for r in correlated.relations:
            g = groups.get(r.source_entity)
            if not g:
                g = RelationGroup(entity_ref=r.source_entity,
                                  entity_name=entity_short_name(r.source_entity),
                                  vendor=self.vendor, family=self.family,
                                  firmware=list(self.firmware), relations=[])
                groups[r.source_entity] = g
            g.relations.append(r)
        return list(groups.values())

    def _group_alarms(self, correlated) -> list[AlarmGroup]:
        groups: dict[str, AlarmGroup] = {}
        for a in correlated.alarms:
            g = groups.get(a.entity_ref)
            if not g:
                g = AlarmGroup(entity_ref=a.entity_ref,
                               entity_name=entity_short_name(a.entity_ref),
                               vendor=self.vendor, family=self.family,
                               firmware=list(self.firmware), alarms=[])
                groups[a.entity_ref] = g
            g.alarms.append(a)
        return list(groups.values())

    # --- manifest -------------------------------------------------------------
    def _build_manifest(self, correlated, data) -> dict[str, Any]:
        all_arts = [*correlated.entities, *correlated.commands, *correlated.oids,
                    *correlated.relations, *correlated.alarms]
        overalls = [a.confidence.overall for a in all_arts] or [0.0]
        return {
            "project": "Telecom Knowledge Compiler (TKC)",
            "vendor": self.vendor,
            "family": self.family,
            "technology": self.technology,
            "catalog_version": self.catalog_version,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "firmware": self.firmware,
            "counts": {
                "entities": len(correlated.entities),
                "commands": len(correlated.commands),
                "oids": len(correlated.oids),
                "relations": len(correlated.relations),
                "alarms": len(correlated.alarms),
                "conflicts": len([r for r in data.conflicts if r["result_type"] == "conflict"]),
                "orphans": len([r for r in data.conflicts if r["result_type"] == "orphan"]),
            },
            "status_distribution": self._status_distribution(correlated),
            "confidence": {
                "avg_overall": round(sum(overalls) / len(overalls), 3),
                "min_overall": round(min(overalls), 3),
            },
            "ambiguous_aliases": len(correlated.ambiguous),
        }

    @staticmethod
    def _status_distribution(correlated) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        groups = {"entities": correlated.entities, "commands": correlated.commands,
                  "oids": correlated.oids, "relations": correlated.relations,
                  "alarms": correlated.alarms}
        for name, arts in groups.items():
            dist: dict[str, int] = defaultdict(int)
            for a in arts:
                dist[a.status] += 1
            out[name] = dict(dist)
        return out
