"""Perfiles de vendor (config/vendors.yaml): la Fase 2 no debe asumir ZTE para otro vendor."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.extractor.mib_extractor import MibExtractor
from src.profiles import (ProfileRegistry, VendorProfile, branch_root, default_registry,
                          load_registry)
from src.walk_validator import detect_vendor_family
from src.walk_validator import std_tables as ST
from src.walk_validator.enricher import Enricher
from src.walk_validator.triggers import Findings
from src.walk_validator.walk_validator import WalkValidator

REG = default_registry()
ENT = "1.3.6.1.4.1.2011"


def test_registry_has_known_vendors_and_families():
    assert {"ZTE", "Huawei", "VSOL"} <= set(REG.vendors())
    assert REG.get("ZTE").families["C620"] == "ZXA10 C620"
    assert REG.get("Huawei").families["MA5608T"] == "MA5608T"
    assert REG.vendor_of_family("V1600G") == "VSOL"


def test_unknown_vendor_gets_generic_profile_without_assumptions():
    p = REG.get("Nokia")
    assert p.bit_index is None and p.pon_port_index is None and p.onu_count_source is None
    assert p.software_branches is None and p.single_shelf is None
    assert p.entity_prefix == "entity.nokia.gpon"


def test_detect_vendor_family_uses_vendor_profile():
    assert detect_vendor_family(Path("Huawei_MA5608T_ifnames.txt")) == ("Huawei", "MA5608T")
    assert detect_vendor_family(Path("VSOL_V1600G.txt")) == ("VSOL", "V1600G")
    with pytest.raises(ValueError):
        detect_vendor_family(Path("ZTE_MA5608T.txt"))        # modelo de otro vendor
    with pytest.raises(ValueError):
        detect_vendor_family(Path("Nokia_X.txt"))


def test_same_model_token_in_two_vendors_does_not_collide(tmp_path):
    f = tmp_path / "v.yaml"
    f.write_text("A:\n  families: {X1: 'A X1'}\nB:\n  families: {X1: 'B X1'}\n")
    reg = load_registry(f)
    assert detect_vendor_family(Path("A_X1.txt"), reg) == ("A", "A X1")
    assert detect_vendor_family(Path("B_X1.txt"), reg) == ("B", "B X1")


def test_branch_root():
    assert branch_root(ENT + ".6.128.1.1.2.46.1.15.4194312448.0", 2) == ENT + ".6.128"
    assert branch_root(ENT + ".5.100.1.1", 1) == ENT + ".5"
    assert branch_root("1.3.6.1.2.1.2.2.1.8.1", 2) == "1.3.6.1.2.1.2.2.1"


# --- Fase 1: índice bit-packed solo si el perfil lo declara -----------------------
def test_bit_index_only_for_vendors_that_declare_it():
    mib = """T-MIB DEFINITIONS ::= BEGIN
    tEntry OBJECT-TYPE
        SYNTAX X MAX-ACCESS not-accessible STATUS current DESCRIPTION "x"
        INDEX { shelfNo, slotNo, portNo } ::= { tTable 1 }
    tCol OBJECT-TYPE
        SYNTAX INTEGER MAX-ACCESS read-only STATUS current DESCRIPTION "x"
        ::= { tEntry 1 }
    END"""
    assert MibExtractor("ZTE", "F", "gpon", [])._looks_like_bitindex(["shelfNo", "slotNo", "portNo"])
    assert not MibExtractor("Huawei", "F", "gpon", [])._looks_like_bitindex(["shelfNo", "slotNo", "portNo"])
    assert not MibExtractor("VSOL", "F", "gpon", [])._looks_like_bitindex(["a", "b"])


# --- Fase 2: ifName / ifIndex / conteo de ONUs ------------------------------------
def test_classify_ifname_uses_profile_keywords():
    hw = REG.get("Huawei")
    assert ST.classify_ifname("GPON 0/1/0", hw) == "pon_port"
    assert ST.classify_ifname("GigabitEthernet0/0/1", hw) == "uplink_port"
    assert ST.classify_ifname("Vlanif100", hw) is None            # no se inventa una clase


def test_ifname_regex_from_profile():
    p = VendorProfile(vendor="X", ifname_regex=r"(?P<rack>\d+)-(?P<slot>\d+)-(?P<port>\d+)$")
    assert ST._ifname_indices("pon 1-2-3", p) == (1, 2, 3)
    assert ST._ifname_indices("pon 7", p) is None
    assert ST._ifname_indices("gpon_1/2/1", REG.get("ZTE")) == (1, 2, 1)


def test_pon_operational_without_index_formula_claims_no_formula():
    walk = {f"{ST.IF_TABLE}.8.5": {"value": "1"}, f"{ST.IF_TABLE}.3.5": {"value": "250"}}
    groups: list[dict] = []
    ST.enrich_pon_operational({}, groups, walk, "VSOL_V1600G2B_ifnames.txt", Findings(),
                              vendor="VSOL", family="V1600G2B", profile=REG.get("VSOL"))
    g = groups[0]
    assert g["entity_ref"] == "entity.vsol.gpon.port.pon_port"
    idx = g["oids"][0]["index"]
    assert idx["type"] == "simple" and idx["bit_calculation"] is False and "formula" not in idx
    assert not any("285278208" in str(o) for o in g["oids"])


def test_pon_operational_zte_keeps_formula():
    walk = {f"{ST.IF_TABLE}.8.5": {"value": "1"}}
    groups: list[dict] = []
    ST.enrich_pon_operational({}, groups, walk, "ZTE_C320_ifnames.txt", Findings(),
                              vendor="ZTE", profile=REG.get("ZTE"))
    assert groups[0]["entity_ref"] == "entity.zte.gpon.port.pon_port"
    assert groups[0]["oids"][0]["index"]["formula"] == "suffix = 285278208 + slot*256 + pon"


def test_onu_count_from_huawei_source_and_skipped_without_source():
    col = REG.get("Huawei").onu_count_source["oid"]
    walk = sorted([f"{col}4194312448.0", f"{col}4194312448.1", f"{col}4194312704.0"])
    ents = {"pon_port": {"status": "documented"}}
    f = Findings()
    ST.derive_pon_onu_count(ents, walk, f, REG.get("Huawei"))
    assert ents["pon_port"]["empirical"]["onu_count"]["total_onus"] == 3
    assert ents["pon_port"]["empirical"]["onu_count"]["ports_with_onus"] == 2
    f2 = Findings()
    ST.derive_pon_onu_count({"pon_port": {"status": "documented"}}, walk, f2, REG.get("VSOL"))   # sin fuente → nada
    assert not f2.items


def test_software_alt_branch_is_not_applied_to_vendor_without_it():
    alt = REG.get("ZTE").software_branches["alt_branch"]
    codes = ".".join(str(ord(c)) for c in "gtghg.fw")
    walk = sorted([f"{alt}.1.2.1.1.8.{codes}"])
    groups = [{"oids": [{"oid": REG.get("ZTE").software_branches["catalog_prefix"] + "2.2.4.1",
                         "index": {"bit_calculation": True, "components": [
                             {"name": "zxanswimagefilename", "bits": ""}]}}]}]
    f = Findings()
    n = ST.validate_ascii_indices(groups, walk, f, profile=REG.get("Huawei"))
    assert n == 0 and not f.by_trigger("ascii_index_validation")


# --- poda acotada a ramas caminadas -------------------------------------------------
def _enricher(profile, walk_oids):
    walk = {o: {"type": "INTEGER", "value": "1", "line": i} for i, o in enumerate(walk_oids)}
    return Enricher(walk, sorted(walk), Findings(), "t.txt", profile=profile)


def _ro(oid):
    return {"id": "oid.x." + oid, "oid": oid, "access": "read-only", "name": "n"}


def test_covered_branch_prunes_only_inside_walked_branches():
    walked = ENT + ".6.128.1.1.2.46.1.15.1.0"
    en = _enricher(REG.get("Huawei"), [walked])
    assert en.enrich_oid(_ro(ENT + ".6.128.1.1.2.46.1.99")) is None          # rama caminada, sin respuesta → poda
    kept = en.enrich_oid(_ro(ENT + ".5.100.1.1.1.6.1.4"))                    # rama NO caminada → se conserva
    assert kept is not None and kept["status"] == "documented"
    assert en.findings.by_trigger("documented_only")[-1]["branch_not_walked"] is True


def test_prune_mode_all_keeps_legacy_behavior():
    en = _enricher(REG.get("ZTE"), ["1.3.6.1.4.1.3902.1082.500.1.1.0"])
    assert en.enrich_oid(_ro("1.3.6.1.4.1.2011.5.100.1.1")) is None          # modo all: poda en todo el catálogo


# --- orquestación: semilla y single-shelf por vendor ---------------------------------
def _wv(**cfg):
    config = {"paths": {"catalog": "c", "walks": "w", "reports": "r"},
              "pipeline": {"vendor": "ZTE", "catalog_version": "1.0.0"},
              "walk_validator": cfg}
    return WalkValidator(config)


def test_seed_family_precedence():
    wv = _wv(seed_from_family="ZXA10 C300")
    assert wv._seed_family(REG.get("ZTE"), "ZXA10 C620") == "ZXA10 C300"      # config gana (vendor del pipeline)
    assert wv._seed_family(REG.get("Huawei"), "MA5608T") == "MA5608T"         # sin semilla ZTE: la propia familia
    assert _wv()._seed_family(REG.get("ZTE"), "ZXA10 C620") == "ZXA10 C320"   # perfil


def test_single_shelf_is_not_assumed_for_other_vendors():
    wv = _wv(single_shelf=True)
    assert wv._single_shelf(REG.get("ZTE")) is True
    assert wv._single_shelf(REG.get("VSOL")) is False                         # null en perfil y config global solo ZTE
    assert wv._single_shelf(REG.get("Huawei")) is True                        # verificado: 1 chasis en entPhysical


def test_registry_type():
    assert isinstance(REG, ProfileRegistry)


# --- Huawei MA5608T: estructura observada en el walk real (2026-10-22), sin datos del abonado ----
def _w(d):
    return {o: {"type": "x", "value": v, "line": i} for i, (o, v) in enumerate(d.items())}


def test_huawei_pon_ifindex_formula_matches_observed_ports():
    f = REG.get("Huawei").pon_port_index["formula"]
    assert "4194304000" in f and "slot*8192" in f and "port*256" in f
    ports = {"GPON 0/0/0": 4194304000, "GPON 0/0/1": 4194304256, "GPON 0/1/15": 4194316032}
    for name, ifindex in ports.items():
        _, slot, port = (int(x) for x in name.split()[-1].split("/"))
        assert 4194304000 + slot * 8192 + port * 256 == ifindex
        assert ST._ifname_indices(name, REG.get("Huawei")) == (0, slot, port)


def test_huawei_ports_and_pon_operational():
    base = "1.3.6.1.2.1."
    walk = _w({base + "31.1.1.1.1.4194304000": "GPON 0/0/0", base + "31.1.1.1.1.4194304256": "GPON 0/0/1",
               base + "31.1.1.1.1.234905600": "ethernet0/3/0", base + "31.1.1.1.1.263": "meth0",
               base + "31.1.1.1.1.264": "vlanif26",
               base + "2.2.1.3.4194304000": "250", base + "2.2.1.3.4194304256": "250",
               base + "2.2.1.3.234905600": "6", base + "2.2.1.8.4194304000": "1",
               base + "2.2.1.8.4194304256": "2", base + "2.2.1.8.234905600": "1"})
    ents = {"pon_port": {"status": "documented"}, "uplink_port": {"status": "documented"}}
    f = Findings()
    ST.enrich_port_entities(ents, [], walk, "t", f, profile=REG.get("Huawei"))
    got = {x["entity"]: x["instances"] for x in f.by_trigger("entity_confirmed")}
    assert got == {"pon_port": 2, "uplink_port": 1}                    # meth0/vlanif no se inventan como uplink
    groups: list[dict] = []
    ST.enrich_pon_operational(ents, groups, walk, "t", f, vendor="Huawei", family="MA5608T",
                              profile=REG.get("Huawei"))
    op = f.by_trigger("pon_operational")[0]
    assert (op["pon_ports"], op["oper_up"], op["oper_down"]) == (2, 1, 1)
    assert not f.by_trigger("bitcalc_validation")                      # Huawei no es bit-packed


def test_huawei_entphysical_strict_classes_and_module_refine():
    P = "1.3.6.1.2.1.47.1.1.1.1."
    rows = {  # índice: (descr, clase)
        1: ("Manufactured Board, MA5608T, H801MABR", 3), 2: ("RACK-300", 11), 3: ("RACK-300", 11),
        4: ("SLOT-300", 5), 5: ("Fan Box ,MA5608T,H831FCBB0", 9), 6: ("Finished Board,MA5608T,H801MPWD,AC Power Board", 9),
        7: ("Manufactured Board,MA5600T,H805GPFD,16 ports GPON", 9), 8: ("", 10)}
    walk = {}
    for i, (d, c) in rows.items():
        walk[P + f"2.{i}"] = d
        walk[P + f"5.{i}"] = str(c)
    ents = {k: {"status": "documented"} for k in ("shelf", "card", "fan", "power_supply")}
    f = Findings()
    ST.enrich_hardware_entities(ents, _w(walk), "t", f, profile=REG.get("Huawei"))
    got = {x["entity"]: x["instances"] for x in f.by_trigger("entity_confirmed")}
    assert got == {"shelf": 1, "fan": 1, "power_supply": 1, "card": 1}   # "RACK-300" (clase 11) NO cuenta como shelf
    # con el perfil heredado (ZTE) el comportamiento anterior no cambia
    ents2 = {k: {"status": "documented"} for k in ("shelf", "card", "fan", "power_supply")}
    f2 = Findings()
    ST.enrich_hardware_entities(ents2, _w(walk), "t", f2, profile=REG.get("ZTE"))
    assert {x["entity"]: x["instances"] for x in f2.by_trigger("entity_confirmed")}["shelf"] == 3


def test_huawei_onu_count_from_ont_runstatus():
    col = REG.get("Huawei").onu_count_source["oid"]
    walk = sorted([f"{col}4194304000.0", f"{col}4194304000.1", f"{col}4194304256.5"])
    ents = {"pon_port": {"status": "documented"}}
    ST.derive_pon_onu_count(ents, walk, Findings(), REG.get("Huawei"))
    c = ents["pon_port"]["empirical"]["onu_count"]
    assert (c["total_onus"], c["ports_with_onus"], c["max_per_port"]) == (3, 2, 2)
