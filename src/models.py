"""Modelos de datos del pipeline TKC.

Cada artefacto (Entity, Command, Oid, Relation, Alarm) tiene un `to_dict()` que
produce exactamente la forma definida en el schema JSON correspondiente
(schemas/schema_*.json), porque ese dict es lo que el Writer serializa a disco.

Las clases *Group agrupan artefactos por entidad para los archivos de salida
oids/{entity}.json, relations/{entity}.json y alarms/{entity}.json.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .ids import snake

# --- Calidad de extracción (factores de confidence_model.json) ---------------
QUALITY_DIRECT_PAGE = "direct_with_page"
QUALITY_DIRECT_NO_PAGE = "direct_without_page"
QUALITY_INFERRED_CONTEXT = "inferred_by_context"
QUALITY_INFERRED_CORRELATION = "inferred_by_correlation"
QUALITY_DEDUCED = "deduced_without_evidence"


@dataclass
class Source:
    """Trazabilidad de un documento que respalda un artefacto."""
    doc_type: str
    pages: Optional[list[int]] = None
    confidence: float = 0.0
    quality: str = QUALITY_DIRECT_NO_PAGE  # no se serializa, alimenta el cálculo

    def to_dict(self) -> dict[str, Any]:
        return {"doc_type": self.doc_type, "pages": self.pages,
                "confidence": round(self.confidence, 3)}


@dataclass
class Confidence:
    extraction: float = 0.0
    correlation: float = 0.0
    overall: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"extraction": round(self.extraction, 3),
                "correlation": round(self.correlation, 3),
                "overall": round(self.overall, 3)}


@dataclass
class Alias:
    name: str
    source: str               # doc_type
    firmware_scope: str = "all"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source,
                "firmware_scope": self.firmware_scope}


@dataclass
class Attribute:
    name: str
    type: str
    range: Optional[str] = None
    required: bool = False
    source: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "range": self.range,
                "required": self.required, "source": self.source}


@dataclass
class Conflict:
    field: str
    source_a: dict[str, Any]
    source_b: dict[str, Any]
    resolution: str = "unresolved"   # unresolved|source_a_wins|source_b_wins|manual
    severity: str = "high"           # se usa para tkc_results, no en el schema de entidad

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "source_a": self.source_a,
                "source_b": self.source_b, "resolution": self.resolution}


@dataclass
class Lifecycle:
    introduced_in: Optional[str] = None
    deprecated_in: Optional[str] = None
    removed_in: Optional[str] = None
    status: str = "introduced"   # introduced|stable|modified|deprecated|removed
    replacement: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"introduced_in": self.introduced_in,
                "deprecated_in": self.deprecated_in,
                "removed_in": self.removed_in, "status": self.status,
                "replacement": self.replacement}


@dataclass
class RelationRef:
    """Referencia rápida embebida en la entidad. La verdad vive en relations.json."""
    type: str
    target: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "target": self.target}


@dataclass
class Entity:
    canonical_name: str
    vendor: str
    family: str
    technology: str
    type: str                                   # device|port|logical|hardware|profile|protocol
    id: str = ""
    firmware: list[str] = field(default_factory=list)
    description: Optional[str] = None
    is_critical: bool = False
    aliases: list[Alias] = field(default_factory=list)
    attributes: list[Attribute] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = field(default_factory=Confidence)
    status: str = "observed"
    lifecycle: Lifecycle = field(default_factory=Lifecycle)
    relations: list[RelationRef] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def canonical_name_snake(self) -> str:
        return snake(self.canonical_name)

    @property
    def short_name(self) -> str:
        return self.id.split(".")[-1] if self.id else self.canonical_name_snake

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "vendor": self.vendor,
            "family": self.family,
            "firmware": self.firmware,
            "technology": self.technology,
            "type": self.type,
            "description": self.description,
            "is_critical": self.is_critical,
            "aliases": [a.to_dict() for a in self.aliases],
            "attributes": [a.to_dict() for a in self.attributes],
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence.to_dict(),
            "status": self.status,
            "lifecycle": self.lifecycle.to_dict(),
            "relations": [r.to_dict() for r in self.relations],
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


@dataclass
class Param:
    name: str
    type: str
    pattern: Optional[str] = None
    range: Optional[str] = None
    required: bool = False
    description: Optional[str] = None
    example: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "pattern": self.pattern,
                "range": self.range, "required": self.required,
                "description": self.description, "example": self.example}


@dataclass
class OutputField:
    name: str
    type: str
    unit: Optional[str] = None
    oid_ref: Optional[str] = None
    oid_status: str = "not_mapped"   # mapped|not_mapped|inferred

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "unit": self.unit,
                "oid_ref": self.oid_ref, "oid_status": self.oid_status}


@dataclass
class Command:
    canonical_name: str
    vendor: str
    family: str
    technology: str
    category: str                               # show|create|delete|modify|enable|disable|reset|diagnose
    cli_mode: str
    syntax: str
    id: str = ""
    firmware: list[str] = field(default_factory=list)
    entity_ref: Optional[str] = None
    description: Optional[str] = None
    parameters: list[Param] = field(default_factory=list)
    output_fields: list[OutputField] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    related_commands: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = field(default_factory=Confidence)
    status: str = "documented"
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def canonical_name_snake(self) -> str:
        return snake(self.canonical_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "vendor": self.vendor,
            "family": self.family,
            "firmware": self.firmware,
            "technology": self.technology,
            "category": self.category,
            "cli_mode": self.cli_mode,
            "entity_ref": self.entity_ref,
            "description": self.description,
            "syntax": self.syntax,
            "parameters": [p.to_dict() for p in self.parameters],
            "output_fields": [o.to_dict() for o in self.output_fields],
            "prerequisites": self.prerequisites,
            "related_commands": self.related_commands,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence.to_dict(),
            "status": self.status,
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


@dataclass
class OidIndex:
    type: str = "simple"             # simple|composite
    bit_calculation: bool = False
    components: Optional[list[dict[str, str]]] = None

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "bit_calculation": self.bit_calculation,
                "components": self.components}


@dataclass
class Oid:
    oid: str
    name: str
    entity_ref: str
    vendor: str
    family: str
    technology: str
    syntax: str
    id: str = ""
    mib_table: Optional[str] = None
    firmware: list[str] = field(default_factory=list)
    index: OidIndex = field(default_factory=OidIndex)
    unit: Optional[str] = None
    scale: Optional[float] = None
    access: str = "read-only"
    enumeration: Optional[dict[str, str]] = None
    description: Optional[str] = None
    command_ref: Optional[str] = None
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = field(default_factory=Confidence)
    status: str = "observed"
    conflicts: list[Conflict] = field(default_factory=list)
    metric: str = ""                 # nombre corto de la métrica (rx_power, status...)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "oid": self.oid,
            "name": self.name,
            "mib_table": self.mib_table,
            "index": self.index.to_dict(),
            "syntax": self.syntax,
            "unit": self.unit,
            "scale": self.scale,
            "access": self.access,
            "enumeration": self.enumeration,
            "description": self.description,
            "command_ref": self.command_ref,
            "status": self.status,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence.to_dict(),
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


@dataclass
class Relation:
    id: str
    type: str                        # belongs_to|uses|has|depends_on|maps_to|triggers
    source_entity: str
    target: str
    vendor: str
    family: str
    cardinality: str = "many_to_one"
    required: bool = False
    description: Optional[str] = None
    prerequisite: bool = False
    creation_order: Optional[int] = None
    firmware: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = field(default_factory=Confidence)
    status: str = "documented"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "target": self.target,
            "cardinality": self.cardinality,
            "required": self.required,
            "description": self.description,
            "prerequisite": self.prerequisite,
            "creation_order": self.creation_order,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence.to_dict(),
            "status": self.status,
        }


@dataclass
class Alarm:
    code: str
    name: str
    canonical_name: str
    entity_ref: str
    vendor: str
    family: str
    severity: str
    type: str
    id: str = ""
    firmware: list[str] = field(default_factory=list)
    description: Optional[str] = None
    probable_causes: list[str] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)
    oid_trap: Optional[str] = None
    oid_refs: list[str] = field(default_factory=list)
    auto_clear: bool = False
    clear_condition: Optional[str] = None
    threshold: Optional[dict[str, Any]] = None
    escalation: dict[str, Any] = field(default_factory=lambda: {
        "warning_after_minutes": None, "major_after_minutes": None,
        "critical_after_minutes": None})
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = field(default_factory=Confidence)
    status: str = "documented"
    conflicts: list[Conflict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "canonical_name": self.canonical_name,
            "entity_ref": self.entity_ref,
            "severity": self.severity,
            "type": self.type,
            "description": self.description,
            "probable_causes": self.probable_causes,
            "remediation": self.remediation,
            "oid_trap": self.oid_trap,
            "oid_refs": self.oid_refs,
            "auto_clear": self.auto_clear,
            "clear_condition": self.clear_condition,
            "threshold": self.threshold,
            "escalation": self.escalation,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence.to_dict(),
            "status": self.status,
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


# --- Agrupadores de salida (un archivo por entidad) --------------------------

@dataclass
class _Group:
    entity_ref: str
    entity_name: str
    vendor: str
    family: str
    firmware: list[str]


@dataclass
class OidGroup(_Group):
    oids: list[Oid] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"entity_ref": self.entity_ref, "vendor": self.vendor,
                "family": self.family, "firmware": self.firmware,
                "oids": [o.to_dict() for o in self.oids]}


@dataclass
class RelationGroup(_Group):
    relations: list[Relation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"entity_ref": self.entity_ref, "vendor": self.vendor,
                "family": self.family, "firmware": self.firmware,
                "relations": [r.to_dict() for r in self.relations]}


@dataclass
class AlarmGroup(_Group):
    alarms: list[Alarm] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"entity_ref": self.entity_ref, "vendor": self.vendor,
                "family": self.family, "firmware": self.firmware,
                "alarms": [a.to_dict() for a in self.alarms]}


# --- Contenedores entre fases ------------------------------------------------

@dataclass
class ClassifiedDoc:
    path: Path
    doc_type: Optional[str]
    vendor: Optional[str]
    family: Optional[str]
    firmware: Optional[str]
    hash: str
    confidence: float
    status: str                      # classified|partial|unclassified
    classifier_output: dict[str, Any]
    text: str = ""                   # contenido cacheado (PDF extraído o texto MIB)


@dataclass
class ExtractedData:
    entities: list[Entity] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    oids: list[Oid] = field(default_factory=list)
    alarms: list[Alarm] = field(default_factory=list)


@dataclass
class NormalizedData(ExtractedData):
    aliases_index: dict[str, str] = field(default_factory=dict)   # alias -> entity_id
    ambiguous: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CorrelatedData(NormalizedData):
    relations: list[Relation] = field(default_factory=list)


@dataclass
class ValidatedData:
    entities: list[Entity] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    oids: list[OidGroup] = field(default_factory=list)
    relations: list[RelationGroup] = field(default_factory=list)
    alarms: list[AlarmGroup] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
