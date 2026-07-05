"""Módulo 6 (Fase 1) — CatalogWriter.

Reemplaza al Loader en la fase actual: toma el output del Validator y escribe los
JSON en la estructura de catalog/ (sin BD).

    catalog/{vendor}/{family}/catalog-{version}/
      ├── manifest.json
      ├── entities/{entity}.json
      ├── commands/{category}/{command}.json
      ├── oids/{entity}.json
      ├── relations/{entity}.json
      └── alarms/{entity}.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..ids import snake
from ..models import ValidatedData

log = logging.getLogger("tkc.writer")


class CatalogWriter:
    def __init__(self, config: dict[str, Any]):
        self.base_path = Path(config["paths"]["catalog"])

    def write(self, vendor: str, family: str, version: str,
              validated_data: ValidatedData) -> Path:
        base = (self.base_path / vendor.lower()
                / family.lower().replace(" ", "-") / f"catalog-{version}")
        base.mkdir(parents=True, exist_ok=True)

        self._write_json(base / "manifest.json", validated_data.manifest)

        ent_dir = base / "entities"
        for entity in validated_data.entities:
            ent_dir.mkdir(exist_ok=True)
            self._write_json(ent_dir / f"{entity.short_name}.json", entity.to_dict())

        for cmd in validated_data.commands:
            cmd_dir = base / "commands" / cmd.category
            cmd_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(cmd_dir / f"{cmd.canonical_name_snake}.json", cmd.to_dict())

        for group, sub in ((validated_data.oids, "oids"),
                           (validated_data.relations, "relations"),
                           (validated_data.alarms, "alarms")):
            for item in group:
                d = base / sub
                d.mkdir(exist_ok=True)
                self._write_json(d / f"{snake(item.entity_name)}.json", item.to_dict())

        # registro de conflictos/huérfanos (estilo tkc_results, fuera del catálogo limpio)
        if validated_data.conflicts:
            self._write_json(base / "results.json", validated_data.conflicts)

        log.info("Catálogo escrito en %s", base)
        return base

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
