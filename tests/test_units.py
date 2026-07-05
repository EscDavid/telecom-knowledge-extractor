"""Tests unitarios de helpers y extractores aislados."""
from pathlib import Path

from src.confidence import ConfidenceModel
from src.extractor.mib_extractor import MibExtractor
from src.ids import (build_command_id, build_entity_id, build_oid_id,
                     entity_short_name, snake)
from src.models import Source

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
MIB = (Path(__file__).resolve().parent
       / "fixtures/docs/zte/zxa10-c320/mib.my").read_text()


def test_snake():
    assert snake("GEM Port") == "gem_port"
    assert snake("ZXA10 C320") == "zxa10_c320"
    assert snake("Rx-Power/dBm") == "rx_power_dbm"


def test_id_builders():
    assert build_entity_id("ZTE", "gpon", "device", "ONU") == "entity.zte.gpon.device.onu"
    assert build_command_id("ZTE", "gpon", "onu", "show") == "command.zte.gpon.onu.show"
    assert build_oid_id("ZTE", "gpon", "onu", "Rx Power") == "oid.zte.gpon.onu.rx_power"
    assert entity_short_name("entity.zte.gpon.device.onu") == "onu"


def test_confidence_model():
    model = ConfidenceModel.load(SCHEMAS)
    # command_reference (autoridad 0.95) con calidad direct_with_page (1.0) → 0.95
    ext = model.extraction([Source("command_reference", quality="direct_with_page")])
    assert abs(ext - 0.95) < 1e-6
    # una segunda fuente independiente añade bonus de corroboración
    ext2 = model.extraction([Source("command_reference", quality="direct_with_page"),
                             Source("mib_file", quality="direct_without_page")])
    assert ext2 > ext
    # un MIB determinista, fuente única, NO se hunde: base alta y status documentado
    mib_ext = model.extraction([Source("mib_file", quality="direct_without_page")])
    assert abs(mib_ext - 0.85) < 1e-6
    assert model.is_authoritative([Source("mib_file", quality="direct_without_page")])
    assert model.determine_status(model.overall(mib_ext, 0.0)) == "documented"
    assert model.determine_status(0.95) == "verified"
    assert model.determine_status(0.6) == "observed"
    assert model.determine_status(0.95, has_active_conflict=True) == "conflicted"
    # penalización de fuente única
    assert model.apply_penalties(0.5, single_source=True) == 0.35


def test_mib_extractor_resolves_oids_and_bitcalc():
    oids = MibExtractor("ZTE", "ZXA10 C320", "gpon", ["2.0", "2.1"]).extract(MIB)
    by_name = {o.name: o for o in oids}
    assert "zxAnGponOntOpticalRxPower" in by_name
    rx = by_name["zxAnGponOntOpticalRxPower"]
    # enterprises(3902) 1082 500 10 3
    assert rx.oid == "1.3.6.1.4.1.3902.1082.500.10.3"
    assert rx.unit == "0.001 dBm"
    assert rx.index.bit_calculation is True
    assert rx.index.type == "composite"
    # enumeración detectada
    status = by_name["zxAnGponOntStatus"]
    assert status.enumeration == {"1": "online", "2": "offline", "3": "los"}
