"""Módulo 1 — Classifier.

Identifica vendor / family / firmware / doc_type de cada documento en docs/.
Lógica 100% dirigida por schemas/classifier_spec.json: tres capas votan en
paralelo (filename, header_text, content_fingerprint), nunca se detiene en la
primera, y el resultado por campo es el de mayor confianza agregada.

Equivalente en BD: un registro en tkc_documents con classifier_output JSON.
En la fase actual no se escribe en BD — devuelve objetos ClassifiedDoc.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..models import ClassifiedDoc
from ..util import read_text, sha256_file

log = logging.getLogger("tkc.classifier")


class Classifier:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        schemas_dir = Path(config["paths"]["schemas"])
        with open(schemas_dir / "classifier_spec.json", encoding="utf-8") as f:
            self.spec = json.load(f)
        cfg = config.get("classifier", {})
        self.min_confidence: float = cfg.get("min_confidence", 0.5)
        self.known_vendors = {v.lower() for v in cfg.get("known_vendors",
                                                         ["ZTE", "Huawei", "VSOL"])}
        self.header_pages: int = cfg.get("header_pages", 3)
        self._layers = {l["name"]: l for l in self.spec["detection_layers"]["layers"]}
        # Los walks (docs/walks/) y las fuentes de validación (docs/validation/) son
        # insumos de la Fase 2, NO documentos fuente: se excluyen del escaneo de Fase 1.
        paths = config.get("paths", {})
        self._exclude_dirs = [Path(paths[k]).resolve() for k in ("walks", "validation")
                              if paths.get(k)]

    # --- API -----------------------------------------------------------------
    def run(self, docs_path: Path) -> list[ClassifiedDoc]:
        docs_path = Path(docs_path)
        if not docs_path.exists():
            log.warning("Ruta de documentos inexistente: %s", docs_path)
            return []
        files = [p for p in sorted(docs_path.rglob("*"))
                 if p.is_file() and not self._is_excluded(p)]
        log.info("Classifier: %d archivo(s) encontrado(s) en %s", len(files), docs_path)
        results: list[ClassifiedDoc] = []
        for path in files:
            doc = self._classify(path)
            results.append(doc)
            log.info("  %s → vendor=%s family=%s doc_type=%s conf=%.2f status=%s",
                     path.name, doc.vendor, doc.family, doc.doc_type,
                     doc.confidence, doc.status)
        return results

    def _is_excluded(self, path: Path) -> bool:
        parents = path.resolve().parents
        return any(d in parents for d in self._exclude_dirs)

    # --- clasificación de un archivo -----------------------------------------
    def _classify(self, path: Path) -> ClassifiedDoc:
        text = read_text(path)                       # contenido completo, cacheado
        header = self._header(path, text)

        # cada campo acumula candidatos {valor: confianza_sumada}
        votes: dict[str, dict[str, float]] = {"vendor": {}, "family": {},
                                              "firmware": {}, "doc_type": {}}
        layers_report: dict[str, dict[str, Any]] = {}

        self._vote_filename(path, votes, layers_report)
        self._vote_header(header, votes, layers_report)
        self._vote_fingerprint(text, votes, layers_report)

        vendor, vendor_conf = self._winner(votes["vendor"])
        family, _ = self._winner(votes["family"])
        firmware, _ = self._winner(votes["firmware"])
        doc_type, _ = self._winner(votes["doc_type"])

        # confianza agregada: vendor + doc_type son los campos que mandan
        confidence = round(min(1.0, vendor_conf + self._winner(votes["doc_type"])[1]), 3)

        status, message = self._decide_status(vendor, doc_type, confidence)
        output = {
            "confidence": confidence,
            "method": [name for name, rep in layers_report.items() if rep.get("matched")],
            "layers": layers_report,
            "message": message,
        }
        return ClassifiedDoc(
            path=path, doc_type=doc_type, vendor=vendor, family=family,
            firmware=firmware, hash=sha256_file(path), confidence=confidence,
            status=status, classifier_output=output, text=text,
        )

    # --- capa 1: filename -----------------------------------------------------
    def _vote_filename(self, path: Path, votes, report) -> None:
        layer = self._layers["filename"]
        base = layer["base_confidence"]
        # Se evalúa la ruta completa: los docs se organizan en docs/{vendor}/{family}/,
        # así que el directorio aporta vendor/family aunque el nombre del archivo no.
        name = path.as_posix()
        matched = False
        for field, patterns in layer["patterns"].items():
            for p in patterns:
                m = re.search(p["regex"], name, re.IGNORECASE)
                if not m:
                    continue
                value = m.group(1) if p["result"] == "capture_group_1" else p["result"]
                if value:
                    votes[field][value] = votes[field].get(value, 0.0) + base
                    matched = True
        report["filename"] = {"matched": matched,
                              "confidence": base if matched else None,
                              "reason": None}

    # --- capa 2: header_text --------------------------------------------------
    def _vote_header(self, header: str, votes, report) -> None:
        layer = self._layers["header_text"]
        matched = False
        best = 0.0
        for p in layer["patterns"]:
            if p["text"].lower() in header.lower():
                votes[p["field"]][p["value"]] = votes[p["field"]].get(p["value"], 0.0) + p["weight"]
                matched = True
                best = max(best, p["weight"])
        report["header_text"] = {"matched": matched,
                                 "confidence": best if matched else None,
                                 "reason": None}

    # --- capa 3: content_fingerprint -----------------------------------------
    def _vote_fingerprint(self, text: str, votes, report) -> None:
        layer = self._layers["content_fingerprint"]
        matched = False
        best = 0.0
        for p in layer["patterns"]:
            if re.search(p["pattern"], text):
                votes[p["field"]][p["value"]] = votes[p["field"]].get(p["value"], 0.0) + p["weight"]
                matched = True
                best = max(best, p["weight"])
        # el spec reporta esta capa como "oid_prefix"
        report["oid_prefix"] = {"matched": matched,
                                "confidence": best if matched else None,
                                "reason": None}

    # --- helpers --------------------------------------------------------------
    def _header(self, path: Path, full_text: str) -> str:
        """Primeras `header_pages` páginas para PDFs; para texto, las primeras líneas."""
        if path.suffix.lower() == ".pdf":
            return read_text(path, max_pages=self.header_pages)
        return "\n".join(full_text.splitlines()[:120])

    @staticmethod
    def _winner(candidates: dict[str, float]) -> tuple[str | None, float]:
        if not candidates:
            return None, 0.0
        value, conf = max(candidates.items(), key=lambda kv: kv[1])
        return value, round(min(1.0, conf), 3)

    def _decide_status(self, vendor, doc_type, confidence) -> tuple[str, str | None]:
        if vendor and vendor.lower() not in self.known_vendors:
            return ("unclassified",
                    f"Vendor {vendor} no registrado en tkc_vendors. "
                    f"Registre el vendor antes de procesar este documento.")
        if confidence < self.min_confidence:
            return ("unclassified",
                    f"Confianza {confidence:.2f} < {self.min_confidence}. "
                    f"Requiere revisión manual, pipeline no continúa con este documento.")
        if vendor and not doc_type:
            return ("partial",
                    "Vendor detectado pero doc_type no. Continúa con extractores genéricos.")
        return ("classified", None)
