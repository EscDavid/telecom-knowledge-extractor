"""Utilidades compartidas por los tests del walk collector (no es un archivo de tests)."""
from __future__ import annotations

from pathlib import Path

from src.walk_collector.collector import Collector
from src.walk_collector.config import CollectorConfig, load_collector_config
from src.walk_collector.pacing import AdaptiveRepetitions, Backoff, LatencyMonitor
from src.walk_collector.state import TaskState
from src.walk_collector.testing import FakeAgent, FakeClock, FakeTransport, make_fake_agent
from src.walk_collector.oid import fmt_oid, parse_oid

REPO = Path(__file__).resolve().parents[1]
PIPELINE = REPO / "config" / "pipeline.yaml"

SECRET = "S3cr3t-Comm"


def make_cfg(tmp_path: Path, **overrides) -> CollectorConfig:
    """Config real de pipeline.yaml con ritmo cero y rutas en tmp_path."""
    ov = {
        "pacing": {"inter_request_delay_ms": 0, "inter_task_delay_s": 0,
                   "checkpoint_every_requests": 5, "checkpoint_every_s": 1e9},
        "retry": {"jitter": 0.0},
        "paths": {"state_dir": str(tmp_path / "state"), "publish_dir": str(tmp_path / "walks")},
    }
    for k, v in overrides.items():
        ov.setdefault(k, {})
        if isinstance(v, dict):
            ov[k].update(v)
        else:
            ov[k] = v
    return load_collector_config(PIPELINE, overrides=ov)


class Rig:
    """Collector + transportes falsos que comparten agente y reloj."""

    def __init__(self, tmp_path: Path, agent: FakeAgent | None = None, faults=(),
                 cfg: CollectorConfig | None = None, clock: FakeClock | None = None,
                 run_id: str = "20260930T101500Z", target_id: str = "T1", **collector_kw):
        self.cfg = cfg or make_cfg(tmp_path)
        self.agent = agent or make_fake_agent()
        self.clock = clock or FakeClock()
        self.faults = list(faults)
        self.transports: list[FakeTransport] = []
        self.collector = Collector(self.cfg, self._factory, self.clock, run_id=run_id,
                                   target_id=target_id, **collector_kw)

    def _factory(self) -> FakeTransport:
        tr = FakeTransport(self.agent, self.faults, self.clock)
        self.transports.append(tr)
        return tr

    @property
    def requests(self):
        return [r for tr in self.transports for r in tr.requests]

    def run(self, **kw):
        return self.collector.run(**kw)

    def walks(self, tmp_path: Path) -> dict[str, bytes]:
        d = self.cfg.paths.publish_dir
        return {p.name: p.read_bytes() for p in sorted(Path(d).glob("*"))} if Path(d).exists() else {}


def walker_kit(tmp_path: Path, agent: FakeAgent | None = None, faults=(), **cfg_over):
    """Piezas sueltas para llamar a walk_task directamente."""
    from src.walk_collector.fragments import FragmentWriter
    cfg = make_cfg(tmp_path, **cfg_over)
    clock = FakeClock()
    agent = agent or make_fake_agent()
    tr = FakeTransport(agent, faults, clock)
    frag = FragmentWriter(tmp_path / "frag" / "t.txt")
    reps = AdaptiveRepetitions(cfg.snmp.max_repetitions, floor=cfg.snmp.min_repetitions)
    sf = cfg.safety
    mon = LatencyMonitor(sf.latency_window, sf.baseline_samples, sf.degrade_factor,
                         sf.degrade_min_ms, sf.sustain_checks)
    bo = Backoff(cfg.retry.backoff_base_s, cfg.retry.backoff_max_s, 0.0)
    return cfg, clock, agent, tr, frag, reps, mon, bo


def new_task(root: str, **kw) -> TaskState:
    return TaskState(id="t1", output="enterprise", root=fmt_oid(parse_oid(root)), **kw)


def frag_lines(frag) -> list[str]:
    from src.walk_collector.fragments import read_fragment_lines
    frag.commit()
    return read_fragment_lines(frag.path)
