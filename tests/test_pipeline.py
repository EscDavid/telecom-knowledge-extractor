"""Test de integración end-to-end del pipeline Fase 1 sobre fixtures de texto."""
import json
from pathlib import Path

import pytest

from src.classifier import Classifier
from src.correlator import Correlator
from src.extractor import Extractor
from src.normalizer import Normalizer
from src.validator import Validator
from src.writer import CatalogWriter

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DOCS = Path(__file__).resolve().parent / "fixtures/docs"


@pytest.fixture
def config(tmp_path):
    return {
        "paths": {
            "docs": str(FIXTURE_DOCS),
            "schemas": str(ROOT / "schemas"),
            "catalog": str(tmp_path / "catalog"),
            "logs": str(tmp_path / "logs"),
            "reports": str(tmp_path / "reports"),
        },
        "pipeline": {
            "vendor": "ZTE", "family": "ZXA10 C320", "technology": "gpon",
            "firmware": ["2.0", "2.1"], "current_firmware": "2.1",
            "catalog_version": "1.0.0",
        },
        "classifier": {"min_confidence": 0.5,
                       "known_vendors": ["ZTE", "Huawei", "VSOL"],
                       "header_pages": 3},
    }


def run_pipeline(config):
    classified = Classifier(config).run(Path(config["paths"]["docs"]))
    extracted = Extractor(config).run(classified)
    normalized = Normalizer(config).run(extracted)
    correlated = Correlator(config).run(normalized)
    validated = Validator(config).run(correlated)
    base = CatalogWriter(config).write("ZTE", "ZXA10 C320", "1.0.0", validated)
    return classified, validated, base


def test_classifier_detects_zte(config):
    classified, _, _ = run_pipeline(config)
    vendors = {d.vendor for d in classified}
    assert vendors == {"ZTE"}
    assert all(d.status in ("classified", "partial") for d in classified)
    mib = next(d for d in classified if d.path.suffix == ".my")
    assert mib.doc_type == "mib_file"


def test_pipeline_produces_oids_and_entities(config):
    _, validated, _ = run_pipeline(config)
    assert validated.manifest["counts"]["oids"] >= 3
    assert validated.manifest["counts"]["entities"] >= 1
    # la entidad ONU debe existir (sintetizada o extraída)
    ids = {e.id for e in validated.entities}
    assert "entity.zte.gpon.device.onu" in ids


def test_catalog_files_written(config):
    _, validated, base = run_pipeline(config)
    assert (base / "manifest.json").exists()
    assert (base / "entities").is_dir()
    onu_oids = base / "oids" / "onu.json"
    assert onu_oids.exists()
    data = json.loads(onu_oids.read_text())
    assert data["entity_ref"] == "entity.zte.gpon.device.onu"
    assert any(o["oid"].startswith("1.3.6.1.4.1.3902") for o in data["oids"])


def test_manifest_schema(config):
    _, validated, base = run_pipeline(config)
    manifest = json.loads((base / "manifest.json").read_text())
    for key in ("vendor", "family", "catalog_version", "counts",
                "status_distribution", "confidence"):
        assert key in manifest
    assert manifest["vendor"] == "ZTE"
    assert 0.0 <= manifest["confidence"]["avg_overall"] <= 1.0


def test_alarms_extracted(config):
    _, validated, base = run_pipeline(config)
    assert validated.manifest["counts"]["alarms"] >= 1
    alarm_file = base / "alarms" / "onu.json"
    if alarm_file.exists():
        data = json.loads(alarm_file.read_text())
        codes = {a["code"] for a in data["alarms"]}
        assert "33001" in codes
