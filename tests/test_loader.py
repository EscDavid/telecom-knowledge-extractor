"""Tests del Loader — Fase 1 (hashing y readiness). No requieren MySQL."""
import json
from pathlib import Path

from src.loader.hashing import catalog_root_hash
from src.loader.readiness import readiness


def _mk_catalog(tmp: Path, *, oid_status="documented", ent_status="documented",
                overall=0.85, generated_at="2026-01-01", empirical=None) -> Path:
    d = tmp / "cat"
    for sub in ("entities", "oids", "commands/show", "alarms"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    oid = {"id": "oid.onu.rx", "oid": "1.3.6.1", "status": oid_status,
           "confidence": {"overall": overall}, "generated_at": generated_at}
    if empirical:
        oid["empirical"] = empirical
    (d / "entities" / "onu.json").write_text(json.dumps(
        {"id": "entity.zte.gpon.device.onu", "status": ent_status,
         "confidence": {"overall": overall}}))
    (d / "oids" / "onu.json").write_text(json.dumps(
        {"entity_ref": "entity.zte.gpon.device.onu", "oids": [oid]}))
    (d / "commands" / "show" / "show.json").write_text(json.dumps(
        {"id": "command.show.onu", "status": "verified", "confidence": {"overall": 0.95}}))
    (d / "alarms" / "onu.json").write_text(json.dumps(
        {"entity_ref": "entity.zte.gpon.device.onu",
         "alarms": [{"id": "alarm.los", "status": "documented", "confidence": {"overall": overall}}]}))
    return d


# --- hashing -----------------------------------------------------------------
def test_hash_deterministico(tmp_path):
    h1 = catalog_root_hash(_mk_catalog(tmp_path / "a"))
    h2 = catalog_root_hash(_mk_catalog(tmp_path / "b"))
    assert h1 == h2 and len(h1) == 64


def test_hash_ignora_campos_volatiles(tmp_path):
    h1 = catalog_root_hash(_mk_catalog(tmp_path / "a", generated_at="2026-01-01"))
    h2 = catalog_root_hash(_mk_catalog(tmp_path / "b", generated_at="2099-12-31"))
    assert h1 == h2                       # generated_at no afecta el hash


def test_hash_detecta_cambio_de_status(tmp_path):
    h_doc = catalog_root_hash(_mk_catalog(tmp_path / "a", oid_status="documented"))
    h_walk = catalog_root_hash(_mk_catalog(tmp_path / "b", oid_status="verified_walk"))
    assert h_doc != h_walk                # status SI entra en el hash


# --- readiness ---------------------------------------------------------------
def test_readiness_tier3_sano(tmp_path):
    tier, _, m = readiness(_mk_catalog(tmp_path, overall=0.85))
    assert tier == 3 and m["layers_ok"] and m["entities_inferred"] == 0


def test_readiness_tier2_con_inferred(tmp_path):
    tier, _, _ = readiness(_mk_catalog(tmp_path, ent_status="inferred", overall=0.85))
    assert tier == 2


def test_readiness_tier4_con_walk(tmp_path):
    tier, _, m = readiness(_mk_catalog(
        tmp_path, oid_status="verified_walk", overall=0.95,
        empirical={"source": "walk"}))
    assert tier == 4 and m["has_walk"]


def test_readiness_tier1_incompleto(tmp_path):
    d = _mk_catalog(tmp_path)
    for f in (d / "commands").rglob("*.json"):   # quitar una capa
        f.unlink()
    tier, _, m = readiness(d)
    assert tier == 1 and not m["layers_ok"]
