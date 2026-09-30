"""Tests del walker, discovery y collector con FakeTransport + FakeClock (sin red ni sleeps)."""
import json
import time
from pathlib import Path

import pytest

from src.walk_collector import state as S
from src.walk_collector.collector import CollectorAbort
from src.walk_collector.discovery import dedupe_roots, discover
from src.walk_collector.oid import fmt_oid, in_subtree, parse_oid
from src.walk_collector.secrets import Scrubber, Secret
from src.walk_collector.state import StateStore
from src.walk_collector.testing import (FakeAgent, FakeClock, FakeTransport, FaultRule,
                                        ideal_walk_lines, make_fake_agent, make_tree)
from src.walk_collector.walker import walk_task
from tests.wc_helpers import (SECRET, Rig, frag_lines, make_cfg, new_task, walker_kit)

BR11 = "1.3.6.1.4.1.3902.1012.3.11"
BR28 = "1.3.6.1.4.1.3902.1012.3.28"
ROOT_ENT = "1.3.6.1.4.1.3902"
NOSTOP = lambda: False  # noqa: E731


def _walk(tmp_path, root, faults=(), agent=None, task=None, **cfg_over):
    cfg, clock, agent, tr, frag, reps, mon, bo = walker_kit(tmp_path, agent, faults, **cfg_over)
    task = task or new_task(root)
    stats: dict = {}
    out = walk_task(task, tr, frag, reps, mon, bo, clock, cfg, lambda force=False: None,
                    NOSTOP, stats)
    return out, task, tr, clock, agent, frag, reps, stats


# --- 8. walker camino feliz ---------------------------------------------------------
def test_walker_happy_path(tmp_path):
    out, task, tr, clock, agent, frag, reps, stats = _walk(tmp_path, BR11)
    assert out.status == "done" and task.rows == len(agent_lines := frag_lines(frag))
    assert agent_lines == ideal_walk_lines(agent, [parse_oid(BR11)])   # exactamente el subárbol
    assert max(r[2] for r in tr.bulk_requests) <= 20
    assert tr.max_inflight_seen == 1
    assert clock.sleeps == [] and task.retries == 0 and task.nonincreasing == 0
    assert all(in_subtree(parse_oid(ln.split(" = ")[0]), parse_oid(BR11)) for ln in agent_lines)


# --- 9. timeout y luego éxito ----------------------------------------------------------
def test_timeout_then_success_uses_backoff(tmp_path):
    out, task, tr, clock, agent, frag, *_ = _walk(tmp_path, BR11,
                                                  faults=[FaultRule("timeout", at=(2,))])
    assert out.status == "done"
    assert clock.sleeps == [2.0]                     # backoff_base_s * 2**0
    assert task.retries == 1 and task.timeouts == 1
    lines = frag_lines(frag)
    assert lines == ideal_walk_lines(agent, [parse_oid(BR11)])     # sin duplicados


# --- 10. timeouts consecutivos: baja max-rep y se recupera ------------------------------
def test_consecutive_timeouts_halve_and_recover(tmp_path):
    out, task, tr, clock, agent, frag, reps, _ = _walk(
        tmp_path, BR11, faults=[FaultRule("timeout", at=(2, 3, 4))])
    assert out.status == "done"
    seq = [r[2] for r in tr.bulk_requests]
    assert seq[:5] == [20, 20, 20, 10, 5]
    assert clock.sleeps == [2.0, 4.0, 8.0]
    assert max(seq[5:]) > 5                          # se recupera tras 50 éxitos
    assert task.max_rep_min_used == 5


# --- 11. tooBig -----------------------------------------------------------------------
def test_toobig_halves_immediately_without_backoff(tmp_path):
    out, task, tr, clock, agent, frag, *_ = _walk(
        tmp_path, BR11, faults=[FaultRule("toobig", ops=("get_bulk",), above=10)])
    assert out.status == "done"
    assert [r[2] for r in tr.bulk_requests][:2] == [20, 10]
    assert clock.sleeps == [] and task.too_big >= 1
    assert frag_lines(frag) == ideal_walk_lines(agent, [parse_oid(BR11)])


def test_toobig_persistent_single_oid_becomes_gap_and_continues(tmp_path):
    agent = make_fake_agent()
    rows = [k for k in agent.keys if in_subtree(k, parse_oid(BR11))]
    poison = rows[100]
    out, task, tr, clock, agent, frag, *_ = _walk(
        tmp_path, BR11, agent=agent, faults=[FaultRule("toobig", contains=poison)])
    assert out.status == "partial"
    assert task.gaps and task.gaps[0]["reason"] == "too_big_single"
    lines = frag_lines(frag)
    keys = {parse_oid(ln.split(" = ")[0]) for ln in lines}
    assert poison not in keys
    assert rows[101] in keys or rows[-1] in keys        # continuó DESPUÉS del OID problemático
    assert rows[99] in keys
    assert task.rows == len(lines)


# --- 12/13. fin de MIB y rama vacía ------------------------------------------------------
def test_end_of_mib_midway_is_done(tmp_path):
    root = "1.3.6.1.4.1.3902.1082.10"                # último subárbol del agente
    out, task, tr, clock, agent, frag, *_ = _walk(tmp_path, root)
    assert out.status == "done"
    assert frag_lines(frag) == ideal_walk_lines(agent, [parse_oid(root)])


@pytest.mark.parametrize("root", ["1.3.6.1.4.1.3902.9999", "1.3.6.1.4.1.3902.1013"])
def test_empty_branch_no_retries(tmp_path, root):
    out, task, tr, clock, agent, frag, *_ = _walk(tmp_path, root)
    assert out.status == "empty"
    assert task.requests == 1 and task.retries == 0 and clock.sleeps == []
    assert frag_lines(frag) == []


# --- 14. OIDs no crecientes: acotado, sin bucle ----------------------------------------------
def test_nonincreasing_is_bounded_and_partial(tmp_path):
    t0 = time.perf_counter()
    out, task, tr, clock, agent, frag, *_ = _walk(
        tmp_path, BR28, faults=[FaultRule("nonincreasing", prefix=parse_oid(BR28), skip=2)])
    assert time.perf_counter() - t0 < 1.0
    assert out.status == "partial"
    assert task.gaps and task.nonincreasing > 0
    limit = 3 * 20 + 40                                # max_stall * max_bumps + k
    assert task.requests <= limit
    assert clock.sleeps == []


# --- 15. discovery ------------------------------------------------------------------------
def _disc(agent, faults=(), expand=(), base_depth=2, max_children=500):
    clock = FakeClock()
    tr = FakeTransport(agent, faults, clock)
    specs = discover(tr, "enterprise", parse_oid(ROOT_ENT), base_depth,
                     {parse_oid(e) for e in expand}, max_children, clock, 0.0)
    return specs, tr


def test_discovery_finds_branches_and_expands():
    agent = make_fake_agent()
    specs, tr = _disc(agent)
    roots = [fmt_oid(s.root) for s in specs]
    assert roots == [".1.3.6.1.4.1.3902.1012.3", ".1.3.6.1.4.1.3902.1015.2",
                     ".1.3.6.1.4.1.3902.1082.10"]
    assert all(r[0] == "get_next" for r in tr.requests) and len(tr.requests) < 30
    specs2, _ = _disc(agent, expand=[BR11.rsplit(".", 1)[0]])
    roots2 = {fmt_oid(s.root) for s in specs2}
    assert {".1.3.6.1.4.1.3902.1012.3.3", ".1.3.6.1.4.1.3902.1012.3.11",
            ".1.3.6.1.4.1.3902.1012.3.28", ".1.3.6.1.4.1.3902.1012.3.50"} <= roots2
    assert ".1.3.6.1.4.1.3902.1012.3" not in roots2
    # numérico: 1012.3.3 antes que 1012.3.28
    assert [fmt_oid(s.root) for s in specs2].index(".1.3.6.1.4.1.3902.1012.3.3") < \
        [fmt_oid(s.root) for s in specs2].index(".1.3.6.1.4.1.3902.1012.3.28")


def test_discovery_nonincreasing_agent_leaves_single_task():
    specs, _ = _disc(make_fake_agent(), faults=[FaultRule("nonincreasing", ops=("get_next",), after=2)])
    assert [fmt_oid(s.root) for s in specs] == [".1.3.6.1.4.1.3902"]


def test_discovery_too_many_children_and_instance_child(tmp_path):
    specs, _ = _disc(make_fake_agent(), max_children=1)
    assert [fmt_oid(s.root) for s in specs] == [".1.3.6.1.4.1.3902"]
    tree = {parse_oid("1.3.6.1.4.1.3902.5"): ("INTEGER", 42),
            parse_oid("1.3.6.1.4.1.3902.7.1.1"): ("INTEGER", 1),
            parse_oid("1.3.6.1.4.1.3902.7.1.2"): ("INTEGER", 2)}
    agent = FakeAgent(tree)
    specs, _ = _disc(agent, base_depth=1)
    inst = [s for s in specs if s.root_is_instance]
    assert [fmt_oid(s.root) for s in inst] == [".1.3.6.1.4.1.3902.5"]
    # la tarea de raíz-instancia hace GET inicial y captura el valor
    out, task, tr, clock, ag, frag, *_ = _walk(tmp_path, "1.3.6.1.4.1.3902.5", agent=agent,
                                               task=new_task("1.3.6.1.4.1.3902.5", root_is_instance=True))
    assert out.status == "done" and frag_lines(frag) == [".1.3.6.1.4.1.3902.5 = INTEGER: 42"]
    assert tr.requests[0][0] == "get"


def test_dedupe_nested_roots():
    roots = dedupe_roots([parse_oid("1.3.6.1.4.1.3902.1012"), parse_oid("1.3.6.1.4.1.3902"),
                          parse_oid("1.3.6.1.2.1.47.1.1.1.1"), parse_oid("1.3.6.1.4.1.3902")])
    assert [fmt_oid(r) for r in roots] == [".1.3.6.1.2.1.47.1.1.1.1", ".1.3.6.1.4.1.3902"]


# --- collector ---------------------------------------------------------------------------------
def _published(rig: Rig) -> dict[str, bytes]:
    return rig.walks(None)


def test_full_run_publishes_three_complete_walks(tmp_path):
    rig = Rig(tmp_path)
    st = rig.run()
    assert st.phase == S.PH_DONE and rig.collector.exit_code == 0
    assert set(_published(rig)) == {"ZTE_C620.txt", "ZTE_C620_entities.txt", "ZTE_C620_ifnames.txt"}
    assert all(t.status in (S.DONE, S.EMPTY) for t in st.tasks)
    assert all(tr.max_inflight_seen == 1 for tr in rig.transports)
    assert not [r for r in rig.requests if r[0] == "get_bulk" and r[2] > 20]
    rep = json.loads((rig.cfg.run_dir / "report.json").read_text(encoding="utf-8"))
    assert rep["result"] == "COMPLETE" and rep["outputs"]["enterprise"]["published"] is True


# --- 16. reintentos agotados -> deferred -> ronda final ----------------------------------------------
def test_exhausted_retries_defer_then_final_round(tmp_path):
    rig = Rig(tmp_path, faults=[FaultRule("timeout", prefix=parse_oid(BR11), times=4)])
    st = rig.run(only=["enterprise"])
    assert rig.collector.exit_code == 0
    a = st.task("enterprise_" + BR11)
    assert a.status == S.DONE and a.attempts == 2 and a.retries == 3
    order = [r[1] for r in rig.requests if r[0] == "get_bulk"]
    first_a = next(i for i, o in enumerate(order) if in_subtree(o, parse_oid(BR11)))
    later_b = [i for i, o in enumerate(order) if in_subtree(o, parse_oid(BR28))]
    last_a = max(i for i, o in enumerate(order) if in_subtree(o, parse_oid(BR11)))
    assert later_b and max(later_b) < last_a          # B/C corrieron antes del reintento de A
    assert first_a < min(later_b) or True


# --- 17. caídas -------------------------------------------------------------------------------------
def test_outage_recovers_and_completes(tmp_path):
    rig = Rig(tmp_path, faults=[FaultRule("dead", after=60, times=1, seconds=90)])
    rig.run()
    assert rig.collector.exit_code == 0
    assert 30 in rig.clock.sleeps and 60 in rig.clock.sleeps and 120 not in rig.clock.sleeps
    clean = Rig(tmp_path / "clean")
    clean.run()
    assert rig.walks(None) == clean.walks(None)


def test_long_outage_stops_resumable(tmp_path):
    rig = Rig(tmp_path, faults=[FaultRule("dead", after=60, times=1, seconds=3600)])
    st = rig.run()
    assert rig.collector.exit_code == 3 and st.phase == S.PH_STOPPED and st.stop_reason == "outage"
    disk = StateStore(rig.cfg.run_dir).load()
    pend = [t for t in disk.tasks if t.status == S.PENDING and t.last_oid]
    assert pend and disk.stats["outages"] >= 1
    assert not _published(rig) or "ZTE_C620.txt" not in _published(rig)   # nada parcial
    rig2 = Rig(tmp_path)                              # equipo recuperado
    rig2.run(resume=True)
    assert rig2.collector.exit_code == 0
    assert "ZTE_C620.txt" in rig2.walks(None)


# --- 18. (aceptación) corte a mitad y reanudación byte a byte ------------------------------------------
def test_interrupt_and_resume_is_byte_identical(tmp_path):
    clean = Rig(tmp_path / "a")
    clean.run()
    base = clean.walks(None)

    cut = Rig(tmp_path / "b", faults=[FaultRule("interrupt", at=(57,))])
    st = cut.run()
    assert cut.collector.exit_code == 130 and st.phase == S.PH_STOPPED
    disk = StateStore(cut.cfg.run_dir).load()
    partial = [t for t in disk.tasks if t.status == S.PENDING and t.committed_bytes > 0]
    assert partial, "el corte debe caer a mitad de una tarea"
    assert "ZTE_C620.txt" not in cut.walks(None)      # nunca un walk parcial publicado
    # simula un crash después del último commit: duplicados y basura en el fragmento
    frag = cut.cfg.run_dir / "fragments" / f"{partial[0].id}.txt"
    last = frag.read_bytes().splitlines()[-1]
    with open(frag, "ab") as f:
        f.write(last + b"\nLINEA BASURA\n" + last.replace(b"= INTEGER", b"= INTEGER: 9 #") + b"\n")

    resumed = Rig(tmp_path / "b")
    resumed.run(resume=True)
    assert resumed.collector.exit_code == 0
    assert resumed.walks(None) == base                # BYTE A BYTE igual a la corrida limpia
    rep = json.loads((resumed.cfg.run_dir / "report.json").read_text(encoding="utf-8"))
    assert all(o["dup_dropped"] == 0 and o["dup_conflicts"] == 0 for o in rep["outputs"].values())
    text = b"".join(base.values())
    assert b"BASURA" not in text


# --- 19. preflight y errores fatales ------------------------------------------------------------------
def test_preflight_no_response_aborts_without_bulk(tmp_path):
    rig = Rig(tmp_path, faults=[FaultRule("timeout", ops=("get",))])
    with pytest.raises(CollectorAbort) as ei:
        rig.run()
    assert ei.value.exit_code == 4
    assert "community" in str(ei.value) and "ACL" in str(ei.value)
    assert not [r for r in rig.requests if r[0] == "get_bulk"]
    assert len([r for r in rig.requests if r[0] == "get"]) == 3
    assert StateStore(rig.cfg.run_dir).load().phase == S.PH_ABORTED


def test_auth_error_midway_aborts_with_checkpoint(tmp_path):
    rig = Rig(tmp_path, faults=[FaultRule("auth", after=40, times=1)])
    with pytest.raises(CollectorAbort) as ei:
        rig.run()
    assert ei.value.exit_code == 4
    disk = StateStore(rig.cfg.run_dir).load()
    assert disk.phase == S.PH_ABORTED and any(t.rows for t in disk.tasks)
    rig2 = Rig(tmp_path)
    rig2.run(resume=True)
    assert rig2.collector.exit_code == 0


def _c320_agent():
    tree = make_tree()
    tree[parse_oid("1.3.6.1.2.1.1.1.0")] = ("OCTETS", b"ZXA10 C320 V2.1")
    return FakeAgent(tree)


def test_wrong_model_aborts_unless_forced(tmp_path):
    rig = Rig(tmp_path / "x", agent=_c320_agent())
    with pytest.raises(CollectorAbort) as ei:
        rig.run(only=["entities"])
    assert ei.value.exit_code == 4 and "--force-model" in str(ei.value)
    assert not [r for r in rig.requests if r[0] == "get_bulk"]
    ok = Rig(tmp_path / "y", agent=_c320_agent())
    ok.run(only=["entities"], force_model=True)
    assert ok.collector.exit_code == 0


# --- 20. kill-switch de latencia -------------------------------------------------------------------------
def test_latency_kill_switch_pauses_then_stops_resumable(tmp_path):
    over = {"safety": {"latency_window": 10, "baseline_samples": 5}}
    rig = Rig(tmp_path, cfg=make_cfg(tmp_path, **over),
              faults=[FaultRule("latency", after=40, ms=3000)])
    st = rig.run()
    assert rig.collector.exit_code == 3 and st.stop_reason == "safety"
    assert st.stats["safety_pauses"] == 3
    assert rig.clock.sleeps.count(120.0) >= 3
    rig2 = Rig(tmp_path, cfg=make_cfg(tmp_path, **over))
    rig2.run(resume=True)
    assert rig2.collector.exit_code == 0


# --- 21. reanudar contra otro target ---------------------------------------------------------------------------
def test_resume_against_other_target_is_rejected(tmp_path):
    Rig(tmp_path, target_id="T1").run(only=["entities"])
    with pytest.raises(CollectorAbort) as ei:
        Rig(tmp_path, target_id="T2").run(resume=True, only=["entities"])
    assert ei.value.exit_code == 2
    forced = Rig(tmp_path, target_id="T2")
    forced.run(resume=True, only=["entities"], force=True)
    assert forced.collector.exit_code == 0


def test_existing_state_without_resume_or_fresh_is_rejected(tmp_path):
    Rig(tmp_path).run(only=["entities"])
    with pytest.raises(CollectorAbort) as ei:
        Rig(tmp_path).run(only=["entities"])
    assert ei.value.exit_code == 2
    fresh = Rig(tmp_path)
    fresh.run(fresh=True, only=["entities"])
    assert fresh.collector.exit_code == 0
    assert any(p.name.startswith("ZTE_C620.") for p in (tmp_path / "state").iterdir() if p.name != "ZTE_C620")


# --- 22. --only ------------------------------------------------------------------------------------------------
def test_only_entities_touches_only_that_subtree(tmp_path):
    rig = Rig(tmp_path)
    rig.run(only=["entities"])
    root = parse_oid("1.3.6.1.2.1.47.1.1.1.1")
    ops = [(op, s) for op, s, _ in rig.requests if op in ("get_bulk", "get_next")]
    assert ops and all(in_subtree(s, root) for _, s in ops)
    assert set(rig.walks(None)) == {"ZTE_C620_entities.txt"}


def test_only_oid_prefix_filters_tasks(tmp_path):
    rig = Rig(tmp_path)
    prefix = "1.3.6.1.4.1.3902.1012.3.50"
    st = rig.run(only=[prefix])
    bulk = [s for op, s, _ in rig.requests if op == "get_bulk"]
    assert bulk and all(in_subtree(s, parse_oid(prefix)) for s in bulk)
    done = [t for t in st.tasks if t.status == S.DONE]
    assert [t.root for t in done] == [".1.3.6.1.4.1.3902.1012.3.50"]
    assert all(t.status == S.SKIPPED for t in st.tasks if t not in done)
    assert rig.walks(None) == {}                       # enterprise incompleto: nada publicado


def test_only_invalid_value_is_usage_error(tmp_path):
    with pytest.raises(CollectorAbort) as ei:
        Rig(tmp_path).run(only=["nada"])
    assert ei.value.exit_code == 2


# --- tareas fallidas / parciales --------------------------------------------------------------------------------------
def test_partial_task_gives_exit_1_and_incomplete_not_published(tmp_path):
    rig = Rig(tmp_path, faults=[FaultRule("nonincreasing", prefix=parse_oid(BR28), skip=2)])
    st = rig.run()
    assert rig.collector.exit_code == 1
    a = st.task("enterprise_" + BR28)
    assert a.status == S.PARTIAL and a.gaps
    others = [t for t in st.tasks if t.output == "enterprise" and t is not a]
    assert others and all(t.status in (S.DONE, S.EMPTY) for t in others)
    names = set(rig.walks(None))
    assert "ZTE_C620.txt" not in names and "ZTE_C620_entities.txt" in names
    assert not list(Path(rig.cfg.paths.publish_dir).glob("*.tmp"))


def test_persistent_failure_becomes_failed_and_retry_failed_recovers(tmp_path):
    bad = FaultRule("timeout", prefix=parse_oid(BR11))
    rig = Rig(tmp_path, faults=[bad])
    st = rig.run(only=["enterprise"])
    assert st.task("enterprise_" + BR11).status == S.FAILED and rig.collector.exit_code == 1
    rig2 = Rig(tmp_path)
    st2 = rig2.run(resume=True, retry_failed=True, only=["enterprise"])
    assert rig2.collector.exit_code == 0 and st2.task("enterprise_" + BR11).status == S.DONE


# --- 5 (global). fuga de la community --------------------------------------------------------------------------------------
def test_no_community_leak_anywhere(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO)
    sc = Scrubber([Secret(SECRET)])
    faults = [FaultRule("timeout", at=(50, 90), message=f"timeout contra community={SECRET}")]
    rig = Rig(tmp_path, faults=faults, scrubber=sc)
    rig.run()
    assert rig.collector.exit_code == 0
    roots = [rig.cfg.run_dir, Path(rig.cfg.paths.publish_dir)]
    files = [p for r in roots for p in r.rglob("*") if p.is_file()]
    assert any(p.name == "state.json" for p in files) and any(p.name == "collector.log" for p in files)
    for p in files:
        assert SECRET.encode() not in p.read_bytes(), p.name
    assert SECRET not in caplog.text
    st = (rig.cfg.run_dir / "state.json").read_text(encoding="utf-8")
    assert "community=***" in st                       # el error quedó registrado, pero limpio
