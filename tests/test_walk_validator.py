"""Tests de la Fase 2 — WalkValidator (parser, triggers y enricher).

Usan un walk sintético en memoria; no dependen del archivo real de ~663k líneas.
"""
import json
from pathlib import Path

import pytest

from src.walk_validator import (detect_vendor_family, detect_walk_type,
                                model_key)
from src.walk_validator import std_tables as ST
from src.walk_validator.enricher import Enricher
from src.walk_validator.std_tables import decode_composite
from src.walk_validator.triggers import (Findings, decode_ascii_index,
                                         is_ascii_index)
from src.walk_validator.walk_validator import WalkHalt, WalkValidator

CONFIG = {
    "paths": {"catalog": "catalog/"},
    "pipeline": {"catalog_version": "1.0.0"},
    "walk_validator": {"seed_from_family": "ZXA10 C320", "prune_unconfirmed_readonly": True},
}


def test_detect_vendor_family():
    assert detect_vendor_family(Path("ZTE_C300.txt")) == ("ZTE", "ZXA10 C300")
    assert detect_vendor_family(Path("ZTE_C320.txt")) == ("ZTE", "ZXA10 C320")
    # los sufijos de tipo no rompen la detección de vendor/modelo
    assert detect_vendor_family(Path("ZTE_C320_entities.txt")) == ("ZTE", "ZXA10 C320")
    assert detect_vendor_family(Path("ZTE_C300_ifnames.txt")) == ("ZTE", "ZXA10 C300")


def test_detect_walk_type_and_grouping():
    assert detect_walk_type(Path("ZTE_C320.txt")) == "enterprise"
    assert detect_walk_type(Path("ZTE_C320_entities.txt")) == "entity_table"
    assert detect_walk_type(Path("ZTE_C320_ifnames.txt")) == "if_table"
    # los tres del mismo modelo comparten clave de agrupación
    keys = {model_key(Path(f)) for f in
            ("ZTE_C320.txt", "ZTE_C320_entities.txt", "ZTE_C320_ifnames.txt")}
    assert keys == {"ZTE_C320"}


def test_enrich_hardware_entities_from_entphysical():
    P = ST.ENT_PHYSICAL
    walk = {  # una tarjeta (class 9) y una fuente (class 6)
        P + ".5.1": {"type": "INTEGER", "value": "9", "line": 1},
        P + ".13.1": {"type": "STRING", "value": "GTGO", "line": 2},
        P + ".5.2": {"type": "INTEGER", "value": "6", "line": 3},
        P + ".13.2": {"type": "STRING", "value": "PRWG", "line": 4},
    }
    entities = {"card": {"id": "entity.zte.gpon.hardware.card", "status": "inferred",
                         "confidence": {"overall": 0.4}},
                "power_supply": {"id": "entity.zte.gpon.hardware.power_supply",
                                 "status": "inferred", "confidence": {"overall": 0.4}}}
    n = ST.enrich_hardware_entities(entities, walk, "ZTE_C320_entities.txt", Findings())
    assert n == 2
    assert entities["card"]["status"] == "verified"
    assert entities["card"]["empirical"]["instances"] == 1
    assert "GTGO" in entities["card"]["empirical"]["samples"]


def test_enrich_ports_and_bitcalc_validation():
    # ifIndex compuesto: shelf(31-28) slot(27-24) port(23-20) = 1/1/1 y 1/2/1
    pon_idx = (1 << 28) | (1 << 24) | (1 << 20)     # 286261248
    upl_idx = (1 << 28) | (2 << 24) | (1 << 20)     # 303038464
    walk = {ST.IF_NAME + f".{pon_idx}": {"type": "STRING", "value": "gpon-onu_1/1/1", "line": 1},
            ST.IF_NAME + f".{upl_idx}": {"type": "STRING", "value": "gei_1/2/1", "line": 2}}
    entities = {"pon_port": {"id": "entity.zte.gpon.port.pon_port", "status": "inferred",
                             "confidence": {"overall": 0.4}},
                "uplink_port": {"id": "entity.zte.gpon.port.uplink_port", "status": "inferred",
                                "confidence": {"overall": 0.4}}}
    # un OID con bit_calculation aporta el mapa de bits para decodificar el ifIndex
    oid_groups = [{"oids": [{"oid": "1.1", "index": {
        "bit_calculation": True,
        "components": [{"name": "shelf", "bits": "31-28"},
                       {"name": "slot", "bits": "27-24"},
                       {"name": "port", "bits": "23-20"}]}}]}]
    findings = Findings()
    ST.enrich_port_entities(entities, oid_groups, walk, "ZTE_C320_ifnames.txt", findings)
    assert entities["pon_port"]["status"] == "verified"
    assert entities["uplink_port"]["status"] == "verified"
    # ifName y encoding alineados (rack/slot/port) → el decode COINCIDE
    val = findings.by_trigger("bitcalc_validation")[0]
    assert val["verdict"] == "match"
    assert val["agree"] == 2 and val["disagree"] == 0


def test_derive_bit_layout_from_ifindex():
    # encoding real: rack/type constante en bits altos, slot@8, port@0
    pairs = []
    for slot in (2, 20):
        for port in (1, 5, 16):
            iv = (1 << 28) | (1 << 24) | (1 << 16) | (slot << 8) | port
            pairs.append((iv, 1, slot, port))
    layout = ST.derive_bit_layout(pairs)
    assert layout["shelf"]["status"] == "constant"          # rack=1 no varía
    assert layout["slot"]["bits"].endswith("-8")
    assert layout["port"]["bits"].endswith("-0")
    # el layout derivado reproduce TODOS los valores reales
    comps = [{"name": "slot", "bits": layout["slot"]["bits"]},
             {"name": "port", "bits": layout["port"]["bits"]}]
    for iv, rack, slot, port in pairs:
        assert decode_composite(iv, comps) == {"slot": slot, "port": port}


def test_apply_bitcalc_fix_per_component():
    groups = [{"oids": [{"oid": "1.1", "index": {"bit_calculation": True, "components": [
        {"name": "slot", "bits": "27-24"}, {"name": "port", "bits": "23-20"},
        {"name": "shelf", "bits": "31-28"}, {"name": "zxanvid", "bits": ""}]}}]}]
    n = ST.apply_bitcalc_fix(groups, {"slot": "12-8", "port": "4-0"},
                             {"shelf": {"status": "constant", "observed_value": 1}})
    assert n == 1
    idx = groups[0]["oids"][0]["index"]
    c = {x["name"]: x for x in idx["components"]}
    # slot/port: corregidos y validados con fuente
    assert c["slot"]["bits"] == "12-8" and c["slot"]["validated"] is True
    assert c["slot"]["source"] == "ifXTable" and c["port"]["validated"] is True
    # shelf: aceptado para single-shelf con nota de revalidación multi-shelf
    assert c["shelf"]["validated"] is True and c["shelf"]["source"] == "single_shelf"
    assert "multi-shelf" in c["shelf"]["note"] and c["shelf"]["value"] == 1
    assert idx["validation_scope"] == "single_shelf"
    # zxanvid: sin evidencia, con fuente sugerida (VLAN)
    assert c["zxanvid"]["validated"] is False and "VLAN" in c["zxanvid"]["reason"]
    # el flag engañoso a nivel de OID desaparece; fully_validated refleja la realidad
    assert "bitcalc_validated" not in idx and idx["fully_validated"] is False


def test_community_parse_and_apply():
    from src.walk_validator import community as CM
    src = CM.parse_community(
        Path(__file__).resolve().parents[1]
        / "docs/validation/community/snmp-olt-zte_reference_extract.txt")
    assert src["meta"]["families"] == ["ZXA10 C300", "ZXA10 C320"]
    assert len(src["oids"]) == 12
    assert "ONU-ID" in src["index_spaces"] and "TYPE" in src["index_spaces"]
    assert src["enums"]["status_enum"]["4"] == "Online"

    groups = [{"entity_ref": "entity.zte.gpon.device.onu", "vendor": "ZTE",
               "family": "ZXA10 C300", "firmware": [], "oids": []}]
    findings = Findings()
    res = CM.apply_community(groups, src, "ZXA10 C300", findings, walk_confirmed=True)
    assert res["stats"]["added"] == 12
    by_attr = {o["attribute"]: o for o in groups[0]["oids"]}
    # el índice usa la fórmula community como decoder (reemplaza el bit-map)
    rx = by_attr["onu_rx_power"]
    assert rx["index"]["decoder"] == "community_formula"
    assert rx["index"]["status"] == "verified_walk"          # walk confirma la fórmula
    assert rx["scale_formula"] == "raw*0.002 - 30" and rx["conflicts"]
    assert rx["status"] == "verified_community"
    # enum resuelto
    assert by_attr["onu_status"]["enumeration"]["4"] == "Online"
    # OID numérico como clave estable, mib_name UNRESOLVED para correlación posterior
    assert by_attr["onu_serial_number"]["mib_name"] == "UNRESOLVED"


def test_validate_ascii_indices():
    # una tabla de software indexada por string ASCII: base + longitud(8) + "gtghg.fw"
    base = "1.3.6.1.4.1.3902.1082.20.30.2.2.4"
    codes = ".".join(str(ord(ch)) for ch in "gtghg.fw")
    walk_oids = [f"{base}.1.8.{codes}", f"{base}.1.7." + ".".join(str(ord(c)) for c in "default")]
    groups = [{"oids": [{"oid": base, "index": {"bit_calculation": True, "components": [
        {"name": "zxanswimagefilename", "bits": ""},
        {"name": "zxancardhisminintervalno", "bits": ""}]}}]}]
    findings = Findings()
    n = ST.validate_ascii_indices(groups, sorted(walk_oids), findings)
    assert n == 1
    c = {x["name"]: x for x in groups[0]["oids"][0]["index"]["components"]}
    # el componente string se confirma con muestras reales
    assert c["zxanswimagefilename"]["validated"] is True
    assert c["zxanswimagefilename"]["source"] == "enterprise_ascii"
    assert "gtghg.fw" in c["zxanswimagefilename"]["samples"]
    # el contador de historial NO se toca (no es string index)
    assert "validated" not in c["zxancardhisminintervalno"]
    assert findings.by_trigger("ascii_index_validation")


def test_ascii_branch_absent_marks_pending():
    # el equipo NO expone la rama del catálogo, pero SÍ la rama alternativa (1015)
    codes = ".".join(str(ord(ch)) for ch in "gtghg.fw")
    walk = sorted([f"{ST.SOFTWARE_ALT_BRANCH}.1.2.1.1.8.{codes}"])
    groups = [{"oids": [{"oid": "1.3.6.1.4.1.3902.1082.20.30.2.2.4.1",
                         "index": {"bit_calculation": True, "components": [
                             {"name": "zxanswimagefilename", "bits": ""}]}}]}]
    findings = Findings()
    n = ST.validate_ascii_indices(groups, walk, findings)
    assert n == 0                                    # no hay evidencia en la rama del catálogo
    c = groups[0]["oids"][0]["index"]["components"][0]
    assert c["validated"] is False if "validated" in c else True   # aún no validado
    # queda trackeado como pendiente con la rama candidata y su evidencia
    pv = c["pending_validation"]
    assert pv["candidate_source"] == ST.SOFTWARE_ALT_BRANCH
    assert "gtghg.fw" in pv["evidence_samples"]
    fnd = findings.by_trigger("ascii_branch_absent")[0]
    assert fnd["pending"] is True


def _wv(tmp_path, resolutions=None):
    (tmp_path / "walks").mkdir(exist_ok=True)
    if resolutions is not None:
        (tmp_path / "walks" / "resolutions.json").write_text(json.dumps(resolutions))
    config = {"paths": {"catalog": str(tmp_path / "catalog"),
                        "walks": str(tmp_path / "walks"),
                        "reports": str(tmp_path / "reports")},
              "pipeline": {"catalog_version": "1.0.0"},
              "walk_validator": {"seed_from_family": "ZXA10 C320", "halt_on_blocking": True}}
    return WalkValidator(config)


def _blocking_findings():
    f = Findings()
    f.add({"trigger": "bitcalc_validation", "blocking": True, "verdict": "mismatch",
           "proposed_fix": {"slot": "12-8", "port": "4-0"},
           "derived_layout": {"shelf": {"status": "constant", "observed_value": 1}}})
    return f


def _composite_groups():
    return [{"oids": [{"oid": "1.1", "index": {"bit_calculation": True, "components": [
        {"name": "slot", "bits": "27-24"}, {"name": "port", "bits": "23-20"},
        {"name": "shelf", "bits": "31-28"}]}}]}]


def test_halt_on_unresolved_blocking(tmp_path):
    wv = _wv(tmp_path)                       # sin resoluciones → pendiente
    groups = _composite_groups()
    with pytest.raises(WalkHalt):
        wv._resolve_blocking("ZXA10 C300", groups, _blocking_findings(), {})
    assert (tmp_path / "reports" / "walk_review" / "zxa10-c300_pending.json").exists()
    # el fix NO se aplicó (el procesado se detuvo)
    assert groups[0]["oids"][0]["index"]["components"][0]["bits"] == "27-24"


def test_accept_applies_fix_no_halt(tmp_path):
    wv = _wv(tmp_path, {"ZXA10 C300": {"bitcalc_validation": "accept"}})
    groups = _composite_groups()
    wv._resolve_blocking("ZXA10 C300", groups, _blocking_findings(), {})   # no levanta
    idx = groups[0]["oids"][0]["index"]
    c = {x["name"]: x for x in idx["components"]}
    assert c["slot"]["bits"] == "12-8" and c["slot"]["validated"] is True
    assert c["port"]["validated"] is True
    # shelf aceptado por single-shelf → el índice queda totalmente validado (con alcance)
    assert c["shelf"]["source"] == "single_shelf"
    assert idx["fully_validated"] is True and idx["validation_scope"] == "single_shelf"


def test_reject_marks_unvalidated_no_halt(tmp_path):
    wv = _wv(tmp_path, {"ZXA10 C300": {"bitcalc_validation": "reject"}})
    groups = _composite_groups()
    wv._resolve_blocking("ZXA10 C300", groups, _blocking_findings(), {})
    idx = groups[0]["oids"][0]["index"]
    assert idx["fully_validated"] is False
    assert all(c["validated"] is False for c in idx["components"])
    assert idx["components"][0]["bits"] == "27-24"           # se mantiene, no se corrige


def test_bitcalc_mismatch_detected():
    # ifName dice slot=2 pero el encoding pone slot=1 en el nibble → mismatch
    walk = {ST.IF_NAME + f".{(1 << 28) | (1 << 24)}": {  # decode slot=1
        "type": "STRING", "value": "gpon_1/2/1", "line": 1}}   # ifName slot=2
    entities = {}
    oid_groups = [{"oids": [{"oid": "1.1", "index": {
        "bit_calculation": True,
        "components": [{"name": "shelf", "bits": "31-28"},
                       {"name": "slot", "bits": "27-24"}]}}]}]
    findings = Findings()
    ST.enrich_port_entities(entities, oid_groups, walk, "w.txt", findings)
    val = findings.by_trigger("bitcalc_validation")[0]
    assert val["verdict"] == "mismatch"
    assert val["disagree"] == 1 and val["severity"] == "high"


def test_ascii_index_helpers():
    # cola imprimible larga = string de firmware embebido en el índice
    # 115,99,120,109,105,98,49,48,48,49 → 's','c','x','m','i','b','1','0','0','1'
    oid = "1.3.6.1.4.1.3902.1015.2.1.2.115.99.120.109.105.98.49.48.48.49"
    assert is_ascii_index(oid)
    assert decode_ascii_index(oid) == "scxmib1001"


def test_parse_walk_detects_not_increasing(tmp_path):
    walk = tmp_path / "ZTE_C300.txt"
    walk.write_text(
        ".1.3.6.1.4.1.3902.1082.1.1 = INTEGER: 1\n"
        ".1.3.6.1.4.1.3902.1082.1.3 = INTEGER: 2\n"
        ".1.3.6.1.4.1.3902.1082.1.2 = INTEGER: 3\n",   # fuera de orden
        encoding="utf-8")
    findings = Findings()
    parsed = WalkValidator(CONFIG).parse_walk(walk, findings)
    assert len(parsed) == 3
    assert findings.by_trigger("oid_not_increasing")


def _enricher(walk_oids):
    sorted_walk = sorted(walk_oids)
    return Enricher(walk_oids, sorted_walk, Findings(), "ZTE_C300.txt")


def test_enrich_confirmed_oid_becomes_verified_with_scale():
    base = "1.3.6.1.4.1.3902.1082.500.10.3"
    walk = {base + ".100": {"type": "INTEGER", "value": "-2300", "line": 1}}
    oid = {"id": "oid.zte.gpon.onu.rx_power", "oid": base,
           "name": "zxAnGponOntOpticalRxPower", "access": "read-only",
           "confidence": {"overall": 0.85}}
    out = _enricher(walk).enrich_oid(dict(oid))
    assert out["status"] == "verified"
    assert out["confidence"]["overall"] == 1.0          # 0.85 + 0.15
    assert out["empirical"]["scale_confirmed"] == 0.01  # -2300 → -23.00 dBm
    assert out["scale"] == 0.01
    assert out["empirical"]["instances_sampled"] == 1


def test_prune_unconfirmed_readonly_but_keep_writable():
    walk = {"1.3.6.1.4.1.3902.1082.1.1.0": {"type": "INTEGER", "value": "1", "line": 1}}
    enr = _enricher(walk)
    ro = {"id": "x", "oid": "1.3.6.1.4.1.3902.9999.1", "access": "read-only",
          "confidence": {"overall": 0.85}}
    rw = {"id": "y", "oid": "1.3.6.1.4.1.3902.8888.1", "access": "read-write",
          "confidence": {"overall": 0.85}}
    assert enr.enrich_oid(dict(ro)) is None            # podado
    kept = enr.enrich_oid(dict(rw))
    assert kept is not None and kept["status"] == "documented"


def test_prefix_match_does_not_false_positive_on_sibling():
    # base ...1.7 no debe confirmarse por ...1.70 (mismo prefijo textual, no subárbol)
    walk = {"1.3.6.1.4.1.3902.1082.1.70": {"type": "INTEGER", "value": "1", "line": 1}}
    enr = _enricher(walk)
    oid = {"id": "z", "oid": "1.3.6.1.4.1.3902.1082.1.7", "access": "read-write",
           "confidence": {"overall": 0.85}}
    out = enr.enrich_oid(dict(oid))
    assert out["status"] == "documented"               # no confirmado
