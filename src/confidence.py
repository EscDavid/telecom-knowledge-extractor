"""Motor de confianza — implementa schemas/confidence_model.json.

Las tres dimensiones:
    extraction  = max(format_authority * extraction_quality) sobre las fuentes
                  + corroboration_bonus * (nº doc_types distintos - 1)
    correlation = consistencia entre documentos (la calcula el Correlator)
    overall     = min(1.0, extraction + correlation * 0.4)

`extraction` es la base: la procedencia (autoridad del formato × calidad) ya basta
para confiar. La correlación SUMA cuando hay corroboración cruzada, pero no es un
requisito que hunda a una fuente única autoritativa (ej. un MIB ASN.1 determinista).

Después el Validator aplica penalizaciones y deriva el `status` por umbrales.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import Source


class ConfidenceModel:
    def __init__(self, spec: dict[str, Any]):
        self.doc_weights: dict[str, float] = {
            k: v for k, v in spec["doc_type_weights"].items()
            if isinstance(v, (int, float)) and k != "sum"
        }
        # Autoridad del formato (procedencia). Si el spec no la trae, cae a doc_weights.
        self.authority: dict[str, float] = spec.get("format_authority", {})
        self.authority = {k: v for k, v in self.authority.items()
                          if isinstance(v, (int, float))}
        self.authoritative_threshold: float = spec.get("authoritative_threshold", 0.80)
        self.corroboration_bonus: float = spec.get("corroboration_bonus_per_extra_source", 0.10)
        self.quality: dict[str, float] = spec["extraction_quality_factors"]
        self.extraction_weight: float = spec["three_dimensions"]["extraction"]["weight_in_overall"]
        self.correlation_weight: float = spec["three_dimensions"]["correlation"]["weight_in_overall"]
        self.penalties: dict[str, float] = {
            "unresolved_conflict": -0.20,
            "ambiguous_alias": -0.10,
            "single_source": -0.15,
            "inference_only": -0.25,
            "firmware_unconfirmed": -0.05,
        }
        # status_thresholds del spec, ordenados de mayor a menor
        self.thresholds = [
            ("verified", 0.90),
            ("documented", 0.70),
            ("observed", 0.50),
            ("inferred", 0.30),
        ]

    @classmethod
    def load(cls, schemas_dir: Path) -> "ConfidenceModel":
        with open(Path(schemas_dir) / "confidence_model.json", encoding="utf-8") as f:
            return cls(json.load(f))

    # --- extraction ----------------------------------------------------------
    def authority_of(self, doc_type: str) -> float:
        """Autoridad del formato; si no está en format_authority, cae a doc_weights."""
        if doc_type in self.authority:
            return self.authority[doc_type]
        return self.doc_weights.get(doc_type, 0.0)

    def extraction(self, sources: Iterable[Source]) -> float:
        """max(format_authority * quality) + bonus por cada doc_type extra que corrobora.

        La mejor fuente fija la base (su procedencia ya es suficiente para confiar);
        cada documento independiente adicional suma un pequeño bonus de corroboración.
        Antes era una suma de pesos que diluía a una fuente única autoritativa.
        """
        best = 0.0
        corroborating: set[str] = set()
        for s in sources:
            a = self.authority_of(s.doc_type)
            q = self.quality.get(s.quality, 0.0)
            score = a * q
            if score > best:
                best = score
            if a > 0.0 and q > 0.0:
                corroborating.add(s.doc_type)
        bonus = max(0, len(corroborating) - 1) * self.corroboration_bonus
        return min(1.0, round(best + bonus, 3))

    def is_authoritative(self, sources: Iterable[Source]) -> bool:
        """True si alguna fuente tiene un formato autoritativo (procedencia determinista)."""
        return any(self.authority_of(s.doc_type) >= self.authoritative_threshold
                   for s in sources)

    def overall(self, extraction: float, correlation: float) -> float:
        """extraction es la base; la correlación SUMA como bonus de corroboración cruzada."""
        val = extraction + correlation * self.correlation_weight
        return round(min(1.0, val), 3)

    # --- penalties + status (usados por el Validator) ------------------------
    def apply_penalties(self, overall: float, *, has_unresolved_conflict: bool = False,
                        ambiguous_alias: bool = False, single_source: bool = False,
                        inference_only: bool = False, firmware_unconfirmed: bool = False) -> float:
        if has_unresolved_conflict:
            overall += self.penalties["unresolved_conflict"]
        if ambiguous_alias:
            overall += self.penalties["ambiguous_alias"]
        if single_source:
            overall += self.penalties["single_source"]
        if inference_only:
            overall += self.penalties["inference_only"]
        if firmware_unconfirmed:
            overall += self.penalties["firmware_unconfirmed"]
        return round(max(0.0, min(1.0, overall)), 3)

    def determine_status(self, overall: float, has_active_conflict: bool = False) -> str:
        if has_active_conflict:
            return "conflicted"
        for name, threshold in self.thresholds:
            if overall >= threshold:
                return name
        return "inferred"  # < 0.30 → marca de revisión manual
