"""Credenciales por marca/modelo (src/creds.py) y su uso en el colector."""
from __future__ import annotations

from src import creds
from src.walk_collector.config import env_presence, load_collector_config, load_credentials

LEGACY = {"TKC_SNMP_HOST": "10.0.0.9", "TKC_SNMP_PORT": "161", "TKC_SNMP_COMMUNITY": "legacy-c",
          "TKC_TELNET_PORT": "23", "TKC_TELNET_USER": "u", "TKC_TELNET_PASSWORD": "p"}


def test_vendor_variable_wins_over_legacy_for_zte():
    env = dict(LEGACY, TKC_ZTE_RO_COMMUNITY="zte-new")
    assert creds.get("ZTE", "RO_COMMUNITY", environ=env) == "zte-new"
    assert creds.get("ZTE", "HOST", environ=env) == "10.0.0.9"          # legacy como respaldo


def test_model_override_beats_vendor():
    env = {"TKC_ZTE_RO_COMMUNITY": "brand", "TKC_ZTE_C600_RO_COMMUNITY": "model"}
    assert creds.get("ZTE", "RO_COMMUNITY", "C600", env) == "model"
    assert creds.get("ZTE", "RO_COMMUNITY", "C620", env) == "brand"


def test_legacy_zte_credentials_never_leak_to_other_vendors():
    for vendor in ("VSOL", "Huawei"):
        assert creds.get(vendor, "RO_COMMUNITY", environ=LEGACY) is None
        assert creds.get(vendor, "HOST", environ=LEGACY) is None


def test_empty_values_are_ignored_and_cli_host_defaults_to_host():
    env = {"TKC_VSOL_HOST": "1.2.3.4", "TKC_VSOL_RO_COMMUNITY": "   ", "TKC_VSOL_CLI_HOST": ""}
    assert creds.get("VSOL", "RO_COMMUNITY", environ=env) is None
    assert creds.get("VSOL", "CLI_HOST", environ=env) == "1.2.3.4"


def test_describe_never_returns_values():
    rows = creds.describe("ZTE", environ=dict(LEGACY, TKC_ZTE_RO_COMMUNITY="zte-new"))
    assert all(set(r) == {"key", "present", "var", "secret", "expected"} for r in rows)
    assert "zte-new" not in str(rows) and "legacy-c" not in str(rows)


def test_collector_uses_vendor_variables():
    cfg = load_collector_config("config/pipeline.yaml")
    env = dict(LEGACY, TKC_ZTE_HOST="10.9.9.9", TKC_ZTE_SNMP_PORT="2161", TKC_ZTE_RO_COMMUNITY="c600-comm")
    assert all(env_presence(cfg, env).values())
    c = load_credentials(cfg, no_prompt=True, environ=env)
    assert (c.host, c.port) == ("10.9.9.9", 2161) and c.community.reveal() == "c600-comm"
    # sin variables por marca: se mantiene el comportamiento histórico
    c0 = load_credentials(cfg, no_prompt=True, environ=LEGACY)
    assert (c0.host, c0.port) == ("10.0.0.9", 161) and c0.community.reveal() == "legacy-c"


def test_rw_community_is_never_used_for_queries():
    """La community de escritura solo se almacena: ningún módulo/script la lee para consultar."""
    from pathlib import Path
    allowed = {"src/creds.py", "scripts/vsol_web_probe.py", "tests/test_creds.py"}
    offenders = []
    for base in ("src", "scripts", "tests"):
        for f in Path(base).rglob("*"):
            if f.suffix in (".py", ".sh", ".yaml") and f.as_posix() not in allowed:
                if "RW_COMMUNITY" in f.read_text(encoding="utf-8", errors="ignore"):
                    offenders.append(f.as_posix())
    assert not offenders, offenders
    # y el colector no la expone: solo existe la clave RO en su mapa de variables
    from src.walk_collector import config as c
    assert "RW_COMMUNITY" not in open(c.__file__, encoding="utf-8").read()
