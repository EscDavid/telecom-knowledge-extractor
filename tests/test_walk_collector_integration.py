"""Integración del walk collector: ensamblado, pipeline Fase 2, publicación, redacción,
CLI y (opcional) el transporte pysnmp real contra un agente UDP local en 127.0.0.1."""
import json
import re
from pathlib import Path

import pytest

from src.walk_collector import state as S
from src.walk_collector.__main__ import main
from src.walk_collector.assembler import (assemble_output, format_header,
                                          verify_strictly_increasing)
from src.walk_collector.oid import parse_oid
from src.walk_collector.redaction import Redactor
from src.walk_collector.state import TaskState
from src.walk_collector.testing import FakeClock, FakeTransport, FaultRule, make_fake_agent
from src.walk_validator import detect_vendor_family, detect_walk_type, model_key
from src.walk_validator import std_tables as ST
from src.walk_validator.triggers import Findings
from src.walk_validator.walk_validator import WalkValidator
from tests.wc_helpers import REPO, SECRET, Rig, make_cfg

CONFIG = {
    "paths": {"catalog": "catalog/"},
    "pipeline": {"catalog_version": "1.0.0"},
    "walk_validator": {"seed_from_family": "ZXA10 C320", "prune_unconfirmed_readonly": True},
}
BR28 = parse_oid("1.3.6.1.4.1.3902.1012.3.28")


# --- 24. assembler --------------------------------------------------------------------
def _frag(tmp_path, name, lines):
    d = tmp_path / "frags"
    d.mkdir(exist_ok=True)
    p = d / f"{name}.txt"
    data = "".join(ln + "\n" for ln in lines).encode()
    p.write_bytes(data)
    return TaskState(id=name, output="enterprise", root=".1.3.6", status=S.DONE,
                     committed_bytes=len(data))


def test_assembler_sorts_numerically_and_dedups(tmp_path):
    a = _frag(tmp_path, "a", [".1.3.6.1.4.1.3902.1012.3.28.1 = INTEGER: 2",
                              ".1.3.6.1.4.1.3902.1012.3.3.1 = INTEGER: 1"])
    b = _frag(tmp_path, "b", [".1.3.6.1.4.1.3902.1012.3.3.1 = INTEGER: 1",       # solape idéntico
                              ".1.3.6.1.4.1.3902.1012.3.28.1 = INTEGER: 99",     # solape en conflicto
                              ".1.3.6.1.4.1.3902.1012.3.11.5 = STRING: \"x\""])
    dest = tmp_path / "out" / "w.tmp"
    header = {"model": "ZTE_C620", "output": "enterprise", "run": "R", "roots": [".1.3.6.1.4.1.3902"]}
    res = assemble_output("enterprise", [a, b], tmp_path / "frags", dest, header)
    body = [ln for ln in dest.read_text(encoding="utf-8").splitlines() if " = " in ln]
    assert [ln.split(" = ")[0] for ln in body] == [
        ".1.3.6.1.4.1.3902.1012.3.3.1", ".1.3.6.1.4.1.3902.1012.3.11.5",
        ".1.3.6.1.4.1.3902.1012.3.28.1"]                   # 3 < 11 < 28 (numérico)
    assert res.rows == 3 and res.dup_dropped == 2 and res.dup_conflicts == 1
    assert body[-1].endswith("INTEGER: 99")                # queda el último
    assert res.complete and verify_strictly_increasing(dest) == (True, 3)
    first = dest.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# tkc-walk-collector v1 ") and " = " not in first
    assert "status:COMPLETE" in first and "rows:3" in first


def test_assembler_ifnames_two_roots_ordered_numerically(tmp_path):
    a = _frag(tmp_path, "if", [".1.3.6.1.2.1.31.1.1.1.1.5 = STRING: \"gpon_olt-1/1/1\"",
                               ".1.3.6.1.2.1.2.2.1.2.5 = STRING: \"gpon_olt-1/1/1\""])
    dest = tmp_path / "o.tmp"
    assemble_output("ifnames", [a], tmp_path / "frags", dest,
                    {"model": "M", "output": "ifnames", "run": "R", "roots": []})
    keys = [ln.split(" = ")[0] for ln in dest.read_text(encoding="utf-8").splitlines() if " = " in ln]
    assert keys == [".1.3.6.1.2.1.2.2.1.2.5", ".1.3.6.1.2.1.31.1.1.1.1.5"]   # 2.2.1 antes que 31.1.1.1.1
    assert verify_strictly_increasing(dest)[0]


def test_verify_detects_non_increasing_and_ignores_headers(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("# cabecera\n.1.3.6.2 = INTEGER: 1\n.1.3.6.1 = INTEGER: 2\n", encoding="utf-8")
    assert verify_strictly_increasing(p)[0] is False
    p.write_text("# cabecera\n.1.3.6.1 = INTEGER: 1\n\n.1.3.6.2 = INTEGER: 2\n", encoding="utf-8")
    assert verify_strictly_increasing(p) == (True, 2)


def test_incomplete_header_format():
    h = format_header({"model": "M", "output": "enterprise", "run": "R", "roots": [".1.3"],
                       "rows": 7, "status": "INCOMPLETE", "missing": 2})
    assert "status:INCOMPLETE missing:2" in h and " = " not in h


# --- 25. integración con la Fase 2 ---------------------------------------------------------
def test_published_walks_feed_walk_validator(tmp_path):
    rig = Rig(tmp_path)
    rig.run()
    pub = Path(rig.cfg.paths.publish_dir)
    rep = json.loads((rig.cfg.run_dir / "report.json").read_text(encoding="utf-8"))
    wv = WalkValidator(CONFIG)
    walks = {}
    for name, out in (("ZTE_C620.txt", "enterprise"), ("ZTE_C620_entities.txt", "entities"),
                      ("ZTE_C620_ifnames.txt", "ifnames")):
        f = pub / name
        findings = Findings()
        walk = wv.parse_walk(f, findings)
        assert not findings.by_trigger("oid_not_increasing"), name
        assert len(walk) == rep["outputs"][out]["rows"]            # el encabezado se ignora
        assert detect_vendor_family(f) == ("ZTE", "ZXA10 C620")
        walks[out] = walk
    assert detect_walk_type(pub / "ZTE_C620.txt") == "enterprise"
    assert detect_walk_type(pub / "ZTE_C620_entities.txt") == "entity_table"
    assert detect_walk_type(pub / "ZTE_C620_ifnames.txt") == "if_table"
    assert {model_key(p) for p in pub.glob("*.txt")} == {"ZTE_C620"}
    ifn = ST.extract_if_names(walks["ifnames"])
    assert len(ifn) == 64 and all(v.startswith("gpon_olt-1/") for v in ifn.values())
    ent = ST.extract_ent_physical(walks["entities"])
    assert len(ent) == 40 and ent["1"]["class"] == 3 and ent["1"]["descr"].startswith("ZXA10 C620")


# --- 26. política de publicación -----------------------------------------------------------------
def _partial_rig(tmp_path, **kw):
    return Rig(tmp_path, faults=[FaultRule("nonincreasing", prefix=BR28, skip=2)], **kw)


def test_incomplete_output_is_not_published_by_default(tmp_path):
    rig = _partial_rig(tmp_path)
    rig.run()
    pub = Path(rig.cfg.paths.publish_dir)
    assert not (pub / "ZTE_C620.txt").exists() and (pub / "ZTE_C620_entities.txt").exists()
    assert not list(pub.glob("*.tmp"))
    assert (rig.cfg.run_dir / "assembled" / "ZTE_C620.txt.tmp").exists()   # solo en el estado


def test_allow_incomplete_publishes_with_incomplete_header(tmp_path):
    rig = _partial_rig(tmp_path, allow_incomplete=True)
    rig.run()
    f = Path(rig.cfg.paths.publish_dir) / "ZTE_C620.txt"
    first = f.read_text(encoding="utf-8").splitlines()[0]
    assert "status:INCOMPLETE" in first and "missing:1" in first and " = " not in first
    assert verify_strictly_increasing(f)[0]


def test_no_publish_leaves_publish_dir_empty(tmp_path):
    rig = Rig(tmp_path, publish=False)
    rig.run(only=["entities"])
    assert not Path(rig.cfg.paths.publish_dir).exists() or not list(Path(rig.cfg.paths.publish_dir).iterdir())
    assert (rig.cfg.run_dir / "assembled" / "ZTE_C620_entities.txt.tmp").exists()


def test_assemble_only_republishes_without_network(tmp_path):
    rig = Rig(tmp_path)
    rig.run()
    pub = Path(rig.cfg.paths.publish_dir)
    before = {p.name: p.read_bytes() for p in pub.glob("*.txt")}
    for p in pub.glob("*.txt"):
        p.unlink()
    rig2 = Rig(tmp_path)
    rig2.collector.assemble_only()
    assert rig2.transports == []                        # ni siquiera se abrió transporte
    assert {p.name: p.read_bytes() for p in pub.glob("*.txt")} == before


# --- 27. redacción --------------------------------------------------------------------------------
def test_redactor_prefixes_stable_and_selective():
    red = Redactor("prefixes", [parse_oid("1.3.6.1.2.1.47.1.1.1.1.11")], salt=b"sal")
    a = red.apply('.1.3.6.1.2.1.47.1.1.1.1.11.3 = STRING: "ABC123"')
    b = red.apply('.1.3.6.1.2.1.47.1.1.1.1.11.9 = STRING: "ABC123"')
    assert re.fullmatch(r'\.1\.3\.6\.1\.2\.1\.47\.1\.1\.1\.1\.11\.3 = STRING: "REDACTED-[0-9a-f]{8}"', a)
    assert a.split(": ", 1)[1] == b.split(": ", 1)[1]                  # estable con la misma sal
    other = Redactor("prefixes", [parse_oid("1.3.6.1.2.1.47.1.1.1.1.11")], salt=b"otra")
    assert other.apply('.1.3.6.1.2.1.47.1.1.1.1.11.3 = STRING: "ABC123"') != a
    for intact in ['.1.3.6.1.2.1.47.1.1.1.1.5.3 = INTEGER: 9',              # fuera del prefijo
                   '.1.3.6.1.2.1.47.1.1.1.1.7.3 = STRING: "comp-3"',        # otra columna
                   '.1.3.6.1.2.1.47.1.1.1.1.11.4 = INTEGER: 5',             # no es STRING
                   '.1.3.6.1.2.1.47.1.1.1.1.11.5 = ""']:                    # vacío
        assert red.apply(intact) == intact
    assert Redactor("none").apply('.1.3.6.1 = STRING: "x"') == '.1.3.6.1 = STRING: "x"'


def test_redaction_applies_on_assembly_not_on_fragments(tmp_path):
    cfg = make_cfg(tmp_path, redaction={"mode": "prefixes",
                                        "prefixes": ["1.3.6.1.2.1.47.1.1.1.1.11"]})
    rig = Rig(tmp_path, cfg=cfg)
    rig.run(only=["entities"])
    pub = (Path(cfg.paths.publish_dir) / "ZTE_C620_entities.txt").read_text(encoding="utf-8")
    serial_rows = [ln for ln in pub.splitlines() if ln.startswith(".1.3.6.1.2.1.47.1.1.1.1.11.")]
    assert serial_rows and all('REDACTED-' in ln or ln.endswith('= ""') for ln in serial_rows)
    assert any("REDACTED-" in ln for ln in serial_rows)
    assert ".1.3.6.1.2.1.47.1.1.1.1.7.1 = STRING" in pub and "comp-1" in pub   # lo demás intacto
    raw = "".join(p.read_text(encoding="utf-8") for p in (cfg.run_dir / "fragments").glob("entities*.txt"))
    assert "REDACTED" not in raw                                          # fragmentos crudos
    assert (cfg.run_dir / "redaction.salt").exists()


# --- 28. solo lectura (estático) ------------------------------------------------------------------------
def test_module_is_read_only_static():
    forbidden = re.compile(r"set_cmd|setCmd|SetRequest|\.set\(|def set_|snmpset", re.I)
    for f in (REPO / "src" / "walk_collector").glob("*.py"):
        hits = [ln for ln in f.read_text(encoding="utf-8").splitlines() if forbidden.search(ln)]
        assert not hits, (f.name, hits)


# --- 23 + CLI ---------------------------------------------------------------------------------------------
ENV = {"TKC_SNMP_HOST": "10.20.30.239", "TKC_SNMP_PORT": "161", "TKC_SNMP_COMMUNITY": SECRET}


def _cli(tmp_path, *extra, factory=None, clock=None):
    return main(["--state-dir", str(tmp_path / "st"), "--out-dir", str(tmp_path / "walks"),
                 "--no-prompt", *extra], transport_factory=factory, load_env=False,
                clock=clock if clock is not None else FakeClock())


def test_dry_run_never_opens_transport(tmp_path, monkeypatch, capsys):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

    def boom():
        raise AssertionError("dry-run no debe abrir transporte")
    assert _cli(tmp_path, "--dry-run", factory=boom) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "entities" in out and "presente" in out
    assert SECRET not in out and "10.20.30.239" not in out
    assert not (tmp_path / "st").exists()                 # ni siquiera crea estado


def test_dry_run_missing_host_names_variable(tmp_path, monkeypatch, capsys):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    assert _cli(tmp_path, "--dry-run") == 2
    assert "TKC_SNMP_HOST: FALTA" in capsys.readouterr().out


def test_cli_missing_credentials_is_usage_error(tmp_path, monkeypatch, capsys):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    assert _cli(tmp_path, "--only", "entities") == 2
    assert "TKC_SNMP_HOST" in capsys.readouterr().err


def test_cli_run_with_injected_transport_masks_host_and_hides_community(tmp_path, monkeypatch, capsys):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    agent = make_fake_agent()
    clock = FakeClock()
    rc = _cli(tmp_path, "--only", "entities", "--max-repetitions", "10",
              factory=lambda: FakeTransport(agent, (), clock))
    out = capsys.readouterr()
    assert rc == 0
    assert "x.x.x.239" in out.out and "10.20.30.239" not in out.out + out.err
    assert SECRET not in out.out + out.err
    assert (tmp_path / "walks" / "ZTE_C620_entities.txt").exists()


def test_cli_state_conflict_and_resume_rules(tmp_path, monkeypatch, capsys):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    agent, clock = make_fake_agent(), FakeClock()
    fac = lambda: FakeTransport(agent, (), clock)   # noqa: E731
    assert _cli(tmp_path, "--only", "entities", factory=fac) == 0
    assert _cli(tmp_path, "--only", "entities", factory=fac) == 2      # hay estado y no se pidió nada
    assert _cli(tmp_path, "--only", "entities", "--fresh", factory=fac) == 0
    assert _cli(tmp_path, "--retry-failed", factory=fac) == 2          # requiere --resume
    with pytest.raises(SystemExit) as ei:
        _cli(tmp_path, "--resume", "--fresh")
    assert ei.value.code == 2


def test_cli_simulate_never_touches_network_or_docs_walks(tmp_path, monkeypatch, capsys):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    before = sorted(p.name for p in (REPO / "docs" / "walks").iterdir())
    assert _cli(tmp_path, "--simulate", "--only", "entities") == 0
    assert (tmp_path / "walks" / "ZTE_C620_entities.txt").exists()
    assert sorted(p.name for p in (REPO / "docs" / "walks").iterdir()) == before
    assert "SIMULACION" in capsys.readouterr().out


def test_cli_discover_only_saves_plan_then_resume_collects(tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    agent, clock = make_fake_agent(), FakeClock()
    tr_holder = []

    def fac():
        tr = FakeTransport(agent, (), clock)
        tr_holder.append(tr)
        return tr
    assert _cli(tmp_path, "--discover-only", factory=fac) == 0
    assert not [r for tr in tr_holder for r in tr.requests if r[0] == "get_bulk"]
    st = json.loads((tmp_path / "st" / "ZTE_C620" / "state.json").read_text(encoding="utf-8"))
    assert len(st["tasks"]) == 9 and all(t["status"] == "pending" for t in st["tasks"])
    assert _cli(tmp_path, "--resume", factory=fac) == 0
    assert (tmp_path / "walks" / "ZTE_C620.txt").exists()


# --- 29. pysnmp real contra un agente UDP local ----------------------------------------------------------



def _to_pysnmp(tree):
    from pysnmp.proto import rfc1902
    conv = {"INTEGER": rfc1902.Integer32, "OCTETS": rfc1902.OctetString,
            "GAUGE32": rfc1902.Gauge32, "TIMETICKS": rfc1902.TimeTicks,
            "COUNTER64": rfc1902.Counter64, "IPADDR": rfc1902.IpAddress,
            "OID": lambda v: rfc1902.ObjectIdentifier(tuple(v))}
    return {oid: conv[k](v) for oid, (k, v) in tree.items()}


def test_pysnmp_transport_against_local_udp_agent():
    pytest.importorskip("pysnmp", reason="pysnmp no instalado")
    from src.walk_collector.pysnmp_transport import PysnmpTransport
    from src.walk_collector.secrets import Scrubber, Secret
    from src.walk_collector.transport import TransportTimeout, Varbind
    from tests.udp_agent import UdpAgent, sample_tree
    sc = Scrubber([Secret(SECRET)])
    with UdpAgent(sample_tree(40), community=SECRET) as ag:
        tr = PysnmpTransport("127.0.0.1", ag.port, Secret(SECRET), 1.0, sc)
        try:
            d = tr.get([parse_oid("1.3.6.1.2.1.1.1.0")])[0]
            assert d.kind == "OCTETS" and d.value == b"ZXA10 C620 test"
            assert tr.get([parse_oid("1.3.6.1.2.1.1.3.0")])[0].kind == "TIMETICKS"
            assert tr.get([parse_oid("1.3.6.1.2.1.1.2.0")])[0].kind == "OID"
            assert tr.get([parse_oid("1.3.6.1.2.1.99.1.0")])[0].kind == "NO_SUCH_INSTANCE"
            nxt = tr.get_next(parse_oid("1.3.6.1.2.1.1"))
            assert nxt.oid == parse_oid("1.3.6.1.2.1.1.1.0")
            bulk = tr.get_bulk(parse_oid("1.3.6.1.2.1.31.1.1.1.1"), 20)
            assert len(bulk) == 20 and bulk[0].kind == "OCTETS"
            kinds = {v.kind for v in tr.get_bulk(parse_oid("1.3.6.1.2.1.31.1.1.1.6"), 5)}
            assert "COUNTER64" in kinds
            assert tr.get([parse_oid("1.3.6.1.2.1.4.20.1.1.3")])[0] == \
                Varbind(parse_oid("1.3.6.1.2.1.4.20.1.1.3"), "IPADDR", "10.0.0.3")
            assert tr.get([parse_oid("1.3.6.1.2.1.2.2.1.5.1")])[0].kind == "GAUGE32"
            tail = tr.get_bulk(parse_oid("1.3.6.1.2.1.31.1.1.1.6.39"), 10)
            assert any(v.kind == "END_OF_MIB" for v in tail) or len(tail) >= 1
            assert tr.last_latency_ms > 0
        finally:
            tr.close()
        bad = PysnmpTransport("127.0.0.1", ag.port, Secret("otra-community"), 0.4,
                              Scrubber([Secret("otra-community")]))
        try:
            with pytest.raises(TransportTimeout) as ei:
                bad.get([parse_oid("1.3.6.1.2.1.1.1.0")])
            assert "otra-community" not in str(ei.value)
        finally:
            bad.close()


def test_full_collection_over_pysnmp_matches_fake_transport(tmp_path):
    pytest.importorskip("pysnmp", reason="pysnmp no instalado")
    from src.walk_collector.collector import Collector
    from src.walk_collector.pacing import RealClock
    from src.walk_collector.pysnmp_transport import PysnmpTransport
    from src.walk_collector.secrets import Scrubber, Secret
    from tests.udp_agent import UdpAgent
    agent = make_fake_agent(scale=0.3)
    fake = Rig(tmp_path / "fake", agent=agent)
    fake.run(only=["entities", "ifnames"])
    sc = Scrubber([Secret(SECRET)])
    with UdpAgent(_to_pysnmp(agent.tree), community=SECRET) as ag:
        cfg = make_cfg(tmp_path / "real", snmp={"timeout_s": 2.0})
        col = Collector(cfg, lambda: PysnmpTransport("127.0.0.1", ag.port, Secret(SECRET),
                                                     cfg.snmp.timeout_s, sc),
                        RealClock(), target_id="T1", run_id="20260930T101500Z", scrubber=sc)
        col.run(only=["entities", "ifnames"])
    assert col.exit_code == 0
    a, b = fake.walks(None), Rig(tmp_path / "real").walks(None)
    assert a and set(a) == {"ZTE_C620_entities.txt", "ZTE_C620_ifnames.txt"}
    assert a == b                                        # pysnmp y el fake producen los mismos bytes
