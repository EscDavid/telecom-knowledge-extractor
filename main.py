#!/usr/bin/env python3
"""Punto de entrada del pipeline TKC — Fase 1 (generación de catálogos JSON).

    docs/ → Classifier → Extractor → Normalizer → Correlator → Validator → Writer
          → catalog/{vendor}/{family}/catalog-{version}/

Uso:
    python main.py [--config config/pipeline.yaml]
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

import yaml

from src.classifier import Classifier
from src.correlator import Correlator
from src.extractor import Extractor
from src.normalizer import Normalizer
from src.validator import Validator
from src.walk_validator import WalkValidator, model_key
from src.walk_validator.walk_validator import WalkHalt
from src.writer import CatalogWriter


def timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def setup_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(logs_dir / f"run_{timestamp()}.log", encoding="utf-8"),
                logging.StreamHandler(sys.stdout)]
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="TKC pipeline — Fase 1")
    parser.add_argument("--config", default="config/pipeline.yaml")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    setup_logging(Path(config["paths"]["logs"]))
    log = logging.getLogger("tkc.main")
    log.info("=== TKC pipeline iniciado (%s %s) ===",
             config["pipeline"]["vendor"], config["pipeline"]["family"])

    docs_path = Path(config["paths"]["docs"])

    classified = Classifier(config).run(docs_path)
    extracted = Extractor(config).run(classified)
    normalized = Normalizer(config).run(extracted)
    correlated = Correlator(config).run(normalized)
    validated = Validator(config).run(correlated)

    base = CatalogWriter(config).write(
        vendor=config["pipeline"]["vendor"],
        family=config["pipeline"]["family"],
        version=config["pipeline"].get("catalog_version", "1.0.0"),
        validated_data=validated,
    )

    counts = validated.manifest["counts"]
    log.info("Catálogo generado en %s", base)
    for key in ("entities", "commands", "oids", "relations", "alarms",
                "conflicts", "orphans"):
        log.info("  %-10s: %d", key, counts[key])

    # --- Fase 2: validación empírica por snmpwalk (opcional) -----------------
    walks_dir = Path(config["paths"].get("walks", "docs/walks/"))
    walk_files = sorted(walks_dir.glob("*.txt")) if walks_dir.exists() else []
    if not walk_files:
        log.info("Sin archivos de walk en %s — omitiendo Fase 2", walks_dir)
    # Varios walks del mismo modelo (principal + _entities + _ifnames) convergen
    # en un único catálogo: se agrupan por modelo antes de procesar.
    by_model: dict[str, list[Path]] = {}
    for wf in walk_files:
        by_model.setdefault(model_key(wf), []).append(wf)
    halted = False
    for model, files in by_model.items():
        names = ", ".join(f.name for f in files)
        log.info("=== Fase 2: validando modelo %s con %s ===", model, names)
        try:
            enriched = WalkValidator(config).run(files)
            log.info("Catálogo enriquecido generado en %s", enriched)
        except WalkHalt as halt:
            halted = True
            log.error("⛔ PROCESADO DETENIDO para %s: %d hallazgo(s) bloqueante(s) "
                      "sin resolver. El catálogo NO se escribió.", halt.family, len(halt.findings))
            log.error("   Acción requerida: revisa %s", halt.review_path)
            log.error("   Luego edita docs/walks/resolutions.json (accept/reject) y re-ejecuta.")
        except (ValueError, FileNotFoundError) as exc:
            log.error("Fase 2 abortada para %s: %s", model, exc)

    if not classified:
        log.warning("No se encontraron documentos en %s — catálogo vacío. "
                    "Coloca los PDFs/MIB del fabricante en esa ruta.", docs_path)
    return 2 if halted else 0


if __name__ == "__main__":
    raise SystemExit(main())
