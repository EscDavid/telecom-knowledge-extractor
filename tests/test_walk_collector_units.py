"""Tests unitarios del walk collector: oid, formatter, config, credenciales, secretos,
ritmo, escritura atómica y fragmentos. Sin red y sin dormir de verdad."""
import logging
import random
from pathlib import Path

import pytest

from src.walk_collector.config import (ConfigError, load_collector_config, load_credentials,
                                       lower_max_repetitions, mask_host)
from src.walk_collector.formatter import format_line, format_timeticks
from src.walk_collector.fragments import FragmentCorrupt, FragmentWriter, read_fragment_lines
from src.walk_collector.oid import (fmt_oid, in_subtree, line_key, next_sibling, parse_oid,
                                    skip_level)
from src.walk_collector.pacing import AdaptiveRepetitions, Backoff, LatencyMonitor
from src.walk_collector.secrets import Scrubber, Secret, install_scrubber
from src.walk_collector.state import (RunState, StateStore, TaskState, atomic_write_json)
from src.walk_collector.transport import TransportTimeout, Varbind
from src.walk_validator import WalkValidator
from src.walk_validator.triggers import Findings

REPO = Path(__file__).resolve().parents[1]
PIPELINE = REPO / "config" / "pipeline.yaml"


# --- 1. oid ------------------------------------------------------------------
def test_parse_and_fmt_oid():
    assert parse_oid(".1.3.6") == (1, 3, 6)
    assert parse_oid("1.3.6") == (1, 3, 6)
    assert fmt_oid((1, 3, 6)) == ".1.3.6"
    for bad in ("", "1.a.3", "1..3", "-1.2"):
        with pytest.raises(ValueError):
            parse_oid(bad)


def test_in_subtree_is_by_arcs_not_text():
    assert in_subtree(parse_oid("1.7.1"), parse_oid("1.7"))
    assert in_subtree(parse_oid("1.7"), parse_oid("1.7"))
    assert not in_subtree(parse_oid("1.70"), parse_oid("1.7"))      # 1.7 NO está en 1.70
    assert not in_subtree(parse_oid("1.7"), parse_oid("1.7.1"))


def test_numeric_order_and_sibling_and_skip():
    a = parse_oid("1.3.6.1.4.1.3902.1012.3.3.1")
    b = parse_oid("1.3.6.1.4.1.3902.1012.3.28.1")
    assert a < b                                                     # numérico
    assert fmt_oid(a) > fmt_oid(b)                                   # el texto se equivoca
    assert next_sibling((1, 3, 6)) == (1, 3, 7)
    o = (1, 3, 6, 1, 4)
    assert skip_level(o, 0) == (1, 3, 6, 1, 5)
    assert skip_level(o, 1) == (1, 3, 6, 2)
    assert skip_level(o, 2) == (1, 3, 7)
    assert skip_level((5,), 3) == (6,)                               # no se sale de la raíz
    assert line_key(".1.3.6.10 = INTEGER: 1") == (1, 3, 6, 10)


# --- 2. formatter -----------------------------------------------------------
def _vb(kind, value=None, oid=(1, 3, 6, 1)):
    return Varbind(oid, kind, value)


def test_format_each_kind():
    assert format_line(_vb("INTEGER", -2300)) == ".1.3.6.1 = INTEGER: -2300"
    assert format_line(_vb("OCTETS", b"")) == '.1.3.6.1 = ""'
    assert format_line(_vb("OCTETS", b"hola")) == '.1.3.6.1 = STRING: "hola"'
    assert format_line(_vb("OCTETS", b'a"b\\c')) == '.1.3.6.1 = STRING: "a\\"b\\\\c"'
    assert format_line(_vb("OCTETS", b"CDTC\x1d\xdb\x9e\xb4")) == \
        ".1.3.6.1 = Hex-STRING: 43 44 54 43 1D DB 9E B4"
    assert format_line(_vb("OID", (1, 3, 6, 1, 4))) == ".1.3.6.1 = OID: .1.3.6.1.4"
    assert format_line(_vb("IPADDR", "10.0.0.1")) == ".1.3.6.1 = IpAddress: 10.0.0.1"
    assert format_line(_vb("COUNTER32", 5)) == ".1.3.6.1 = Counter32: 5"
    assert format_line(_vb("GAUGE32", 6)) == ".1.3.6.1 = Gauge32: 6"
    assert format_line(_vb("COUNTER64", 2 ** 40)) == f".1.3.6.1 = Counter64: {2 ** 40}"
    assert format_line(_vb("OPAQUE", b"\x9f\x78")) == ".1.3.6.1 = Opaque: 9F 78"
    assert format_line(_vb("BITS", b"\xa0")) == ".1.3.6.1 = BITS: A0"
    assert format_line(_vb("NULL")) == ".1.3.6.1 = NULL"
    for k in ("END_OF_MIB", "NO_SUCH_OBJECT", "NO_SUCH_INSTANCE"):
        assert format_line(_vb(k)) is None


def test_format_multiline_string_stays_one_line():
    line = format_line(_vb("OCTETS", b"linea1\r\nlinea2\tfin"))
    assert "\n" not in line and "\r" not in line
    assert line == '.1.3.6.1 = STRING: "linea1  linea2 fin"'


def test_format_timeticks():
    assert format_timeticks(3179) == "(3179) 0:00:31.79"
    assert format_timeticks(8640000) == "(8640000) 1 day, 0:00:00.00"
    assert format_timeticks(123456789) == "(123456789) 14 days, 6:56:07.89"


def test_format_roundtrip_with_parse_walk(tmp_path):
    vbs = [_vb("INTEGER", -5, (1, 3, 6, 1, 1)), _vb("OCTETS", b"", (1, 3, 6, 1, 2)),
           _vb("OCTETS", b"txt", (1, 3, 6, 1, 3)), _vb("OCTETS", b"\x00\x01", (1, 3, 6, 1, 4)),
           _vb("TIMETICKS", 3179, (1, 3, 6, 1, 5)), _vb("NULL", None, (1, 3, 6, 1, 6))]
    f = tmp_path / "w.txt"
    f.write_text("\n".join(format_line(v) for v in vbs) + "\n", encoding="utf-8")
    wv = WalkValidator({"paths": {"catalog": str(tmp_path)}, "pipeline": {}})
    walk = wv.parse_walk(f, Findings())
    assert len(walk) == 6
    assert walk["1.3.6.1.1"] == {"type": "INTEGER", "value": "-5", "line": 1}
    assert walk["1.3.6.1.3"]["type"] == "STRING" and walk["1.3.6.1.3"]["value"] == '"txt"'
    assert walk["1.3.6.1.4"]["type"] == "Hex-STRING"
    assert walk["1.3.6.1.5"]["type"] == "Timeticks"
    assert not Findings().by_trigger("oid_not_increasing")


# --- 3. config -----------------------------------------------------------------
def test_real_pipeline_yaml_loads():
    cfg = load_collector_config(PIPELINE)
    assert cfg.model_key == "ZTE_C620"
    assert set(cfg.outputs) == {"enterprise", "entities", "ifnames"}
    assert cfg.snmp.max_repetitions == 20
    assert cfg.output_filename("ifnames") == "ZTE_C620_ifnames.txt"
    assert cfg.outputs["ifnames"].roots == (parse_oid("1.3.6.1.2.1.2.2.1"),
                                            parse_oid("1.3.6.1.2.1.31.1.1.1.1"))
    assert cfg.run_dir.name == "ZTE_C620"


def test_max_repetitions_above_20_is_clamped_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="tkc.walk_collector.config"):
        cfg = load_collector_config(PIPELINE, overrides={"snmp": {"max_repetitions": 50}})
    assert cfg.snmp.max_repetitions == 20
    assert "tope duro" in caplog.text


def test_snmp_version_3_is_error():
    with pytest.raises(ConfigError, match="2c"):
        load_collector_config(PIPELINE, overrides={"snmp": {"version": 3}})


def test_missing_section_is_clear_error(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("paths: {}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="walk_collector"):
        load_collector_config(p)
    p.write_text("walk_collector:\n  vendor: ZTE\n  model: C620\n  expect_sysdescr_regex: x\n",
                 encoding="utf-8")
    with pytest.raises(ConfigError, match="snmp"):
        load_collector_config(p)


def test_cli_max_repetitions_can_only_lower(caplog):
    cfg = load_collector_config(PIPELINE)
    assert lower_max_repetitions(cfg, 10).snmp.max_repetitions == 10
    with caplog.at_level(logging.WARNING, logger="tkc.walk_collector.config"):
        assert lower_max_repetitions(cfg, 30).snmp.max_repetitions == 20
    assert "solo puede bajar" in caplog.text


def test_state_dir_expands_env_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("TKC_TEST_BASE", str(tmp_path))
    cfg = load_collector_config(PIPELINE, overrides={"paths": {"state_dir": "$TKC_TEST_BASE/st"}})
    assert cfg.paths.state_dir == tmp_path / "st"


# --- 4. credenciales -----------------------------------------------------------
ENV = {"TKC_SNMP_HOST": "10.20.30.239", "TKC_SNMP_PORT": "161", "TKC_SNMP_COMMUNITY": "S3cr3t-Comm"}


def _boom(_prompt):
    raise AssertionError("getpass no debía invocarse")


def test_credentials_full_env_never_prompts():
    cred = load_credentials(load_collector_config(PIPELINE), environ=ENV, getpass=_boom)
    assert cred.host == "10.20.30.239" and cred.port == 161
    assert cred.community.reveal() == "S3cr3t-Comm"
    assert cred.masked_host() == "x.x.x.239" and mask_host("olt.example.net") == "***.net"
    assert len(cred.target_id) == 16


def test_empty_community_prompts_hidden():
    env = dict(ENV, TKC_SNMP_COMMUNITY="")
    cred = load_credentials(load_collector_config(PIPELINE), environ=env,
                            getpass=lambda p: "desde-prompt", isatty=lambda: True)
    assert cred.community.reveal() == "desde-prompt"


def test_empty_community_no_prompt_or_no_tty_fails():
    cfg = load_collector_config(PIPELINE)
    env = dict(ENV, TKC_SNMP_COMMUNITY="")
    with pytest.raises(ConfigError, match="TKC_SNMP_COMMUNITY"):
        load_credentials(cfg, environ=env, no_prompt=True, getpass=_boom, isatty=lambda: True)
    with pytest.raises(ConfigError, match="TKC_SNMP_COMMUNITY"):
        load_credentials(cfg, environ=env, getpass=_boom, isatty=lambda: False)


def test_missing_host_names_variable_not_value():
    with pytest.raises(ConfigError) as ei:
        load_credentials(load_collector_config(PIPELINE),
                         environ={"TKC_SNMP_COMMUNITY": "S3cr3t-Comm"}, getpass=_boom)
    assert "TKC_SNMP_HOST" in str(ei.value) and "S3cr3t-Comm" not in str(ei.value)


def test_secret_repr_hides_value():
    s = Secret("x-super-secreto")
    assert "x-super-secreto" not in repr(s) and "x-super-secreto" not in str(s)
    assert repr(Secret("x")) == "Secret('***')"
    assert s.reveal() == "x-super-secreto"


# --- 5. scrubber -----------------------------------------------------------------
def test_scrubber_cleans_msg_args_and_exceptions():
    sc = Scrubber([Secret("S3cr3t-Comm")])
    assert sc.scrub("community=S3cr3t-Comm ok") == "community=*** ok"
    rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "usando %s y %s",
                            ("S3cr3t-Comm", 5), None)
    try:
        raise RuntimeError("falló con S3cr3t-Comm")
    except RuntimeError:
        import sys
        rec.exc_info = sys.exc_info()
    assert sc.filter(rec)
    assert "S3cr3t-Comm" not in rec.getMessage()
    assert "S3cr3t-Comm" not in (rec.exc_text or "")
    assert rec.getMessage() == "usando *** y 5"
    err = TransportTimeout("timeout con S3cr3t-Comm", sc)
    assert "S3cr3t-Comm" not in str(err)


def test_install_scrubber_covers_root_handlers(tmp_path):
    root = logging.getLogger()
    h = logging.FileHandler(tmp_path / "x.log", encoding="utf-8")
    root.addHandler(h)
    try:
        install_scrubber(Scrubber([Secret("S3cr3t-Comm")]))
        logging.getLogger("tkc.otro").warning("clave S3cr3t-Comm")
        h.flush()
    finally:
        root.removeHandler(h)
        h.close()
        for flt in list(root.filters):
            root.removeFilter(flt)
    assert "S3cr3t-Comm" not in (tmp_path / "x.log").read_text(encoding="utf-8")


# --- 6. pacing ---------------------------------------------------------------------
def test_backoff_grows_and_caps_with_jitter():
    b = Backoff(2, 60, 0.0)
    assert [b.delay(n) for n in range(1, 8)] == [2, 4, 8, 16, 32, 60, 60]
    bj = Backoff(2, 60, 0.2, random.Random(1))
    for n in range(1, 8):
        base = min(60, 2 * 2 ** (n - 1))
        d = bj.delay(n)
        assert base * 0.8 <= d <= base * 1.2


def test_adaptive_repetitions_halves_floors_and_recovers():
    r = AdaptiveRepetitions(20, floor=1, recover_after=50)
    r.on_timeout(1)
    assert r.current == 20                       # el primer timeout no baja
    seq = []
    for _ in range(5):
        r.on_timeout(2)
        seq.append(r.current)
    assert seq == [10, 5, 2, 1, 1]               # 20→10→5→2→1 y no baja de 1
    for _ in range(49):
        r.on_success()
    assert r.current == 1
    r.on_success()
    assert r.current == 2                        # tras 50 éxitos seguidos
    for _ in range(50 * 10):
        r.on_success()
    assert r.current == 20                       # nunca supera el techo
    r.on_too_big()
    assert r.current == 10 and r.min_used == 1


def test_latency_monitor_degrades_only_when_sustained():
    m = LatencyMonitor(window=10, baseline_samples=5, factor=4.0, min_ms=800, sustain=3)
    for _ in range(5):
        m.record(30)
    assert m.baseline_ms == 30 and m.verdict() == "ok"
    m.record(5000)                               # un pico aislado no basta
    assert m.verdict() == "ok"
    for _ in range(20):
        m.record(30)
    assert m.verdict() == "ok"
    for _ in range(25):
        m.record(3000)
    assert m.verdict() == "degraded"
    m.reset_window()
    assert m.verdict() == "ok" and m.baseline_ms == 30


def test_latency_monitor_timeouts_degrade():
    m = LatencyMonitor(window=10, baseline_samples=3, factor=4.0, min_ms=800, sustain=2)
    for _ in range(3):
        m.record(20)
    for _ in range(6):
        m.record(3000, timed_out=True)
    assert m.verdict() == "degraded"


# --- 7. atomic_write_json / estado -----------------------------------------------
def test_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    import os
    real = os.replace
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("bloqueado")
        return real(a, b)
    monkeypatch.setattr(os, "replace", flaky)
    sleeps = []
    p = tmp_path / "s.json"
    atomic_write_json(p, {"a": 1}, sleep=sleeps.append)
    assert p.read_text(encoding="utf-8").count('"a"') == 1
    assert sleeps == [0.2, 0.4] and not (tmp_path / "s.json.tmp").exists()


def test_atomic_write_failure_keeps_original(tmp_path):
    p = tmp_path / "s.json"
    atomic_write_json(p, {"ok": True})
    with pytest.raises(TypeError):
        atomic_write_json(p, {"bad": object()})
    assert '"ok": true' in p.read_text(encoding="utf-8")
    assert not (tmp_path / "s.json.tmp").exists()


def test_state_store_roundtrip_and_archive(tmp_path):
    store = StateStore(tmp_path / "run")
    st = RunState(run_id="20260930T101500Z", model_key="ZTE_C620",
                  tasks=[TaskState(id="t1", output="enterprise", root=".1.3.6")])
    store.save(st)
    back = store.load()
    assert back.tasks[0].id == "t1" and back.model_key == "ZTE_C620"
    arch = store.archive()
    assert arch.exists() and not store.exists()


# --- fragmentos -------------------------------------------------------------------
def test_fragment_truncates_garbage_after_last_commit(tmp_path):
    p = tmp_path / "frag" / "t.txt"
    w = FragmentWriter(p)
    w.append([".1.3.6.1 = INTEGER: 1", ".1.3.6.2 = INTEGER: 2"])
    off = w.commit()
    w.append([".1.3.6.3 = INTEGER: 3"])          # sin commit: debe descartarse al reanudar
    w.close()
    with open(p, "ab") as f:
        f.write(b"basura sin salto")
    w2 = FragmentWriter(p, committed_bytes=off)
    w2.append([".1.3.6.3 = INTEGER: 3"])
    w2.commit()
    w2.close()
    assert read_fragment_lines(p) == [".1.3.6.1 = INTEGER: 1", ".1.3.6.2 = INTEGER: 2",
                                      ".1.3.6.3 = INTEGER: 3"]
    with pytest.raises(FragmentCorrupt):
        FragmentWriter(p, committed_bytes=10_000)
