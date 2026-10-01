"""Estado persistente de la corrida (``state.json``) con escritura atómica.

El estado NUNCA contiene la community ni el host en claro: el objetivo se identifica
con ``target_id = sha256(host:port)[:16]``.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1

# estados de tarea
PENDING, RUNNING, DEFERRED = "pending", "running", "deferred"
DONE, EMPTY, PARTIAL, FAILED, SKIPPED = "done", "empty", "partial", "failed", "skipped"
TERMINAL = (DONE, EMPTY, PARTIAL, FAILED)
COMPLETE_OK = (DONE, EMPTY)

# fases
PH_PREFLIGHT, PH_DISCOVERY, PH_COLLECTING = "preflight", "discovery", "collecting"
PH_FINAL_RETRY, PH_ASSEMBLING, PH_DONE = "final_retry", "assembling", "done"
PH_STOPPED, PH_ABORTED = "stopped", "aborted"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def atomic_write_json(path: Path, data: Any, retries: int = 5,
                      sleep: Callable[[float], None] | None = None) -> None:
    """tmp + fsync + ``os.replace``. En Windows ``replace`` puede fallar con
    PermissionError (antivirus/OneDrive/lector): se reintenta con 0.2*2^n s."""
    sleep = sleep or time.sleep
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")   # falla ANTES de tocar disco
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        for n in range(retries + 1):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if n >= retries:
                    raise
                sleep(0.2 * (2 ** n))
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


@dataclass
class TaskState:
    id: str
    output: str
    root: str                       # OID con punto inicial
    root_is_instance: bool = False
    status: str = PENDING
    last_oid: str | None = None
    rows: int = 0
    committed_bytes: int = 0
    requests: int = 0
    attempts: int = 0
    retries: int = 0
    timeouts: int = 0
    too_big: int = 0
    max_rep_current: int = 0
    max_rep_min_used: int = 0
    nonincreasing: int = 0
    gaps: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float = 0.0


@dataclass
class RunState:
    run_id: str
    model_key: str
    target: dict = field(default_factory=dict)
    config_hash: str = ""
    phase: str = PH_PREFLIGHT
    stop_reason: str | None = None
    discovered_outputs: list[str] = field(default_factory=list)
    tasks: list[TaskState] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {
        "requests": 0, "timeouts": 0, "too_big": 0, "agent_errors": 0, "backoff_s": 0.0,
        "safety_pauses": 0, "outages": 0,
        "latency_ms": {"baseline": 0, "p50": 0, "p95": 0, "max": 0},
        "started_at": None, "elapsed_s": 0.0})
    schema_version: int = SCHEMA_VERSION

    def task(self, task_id: str) -> TaskState | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunState":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"schema_version de estado no soportado: {d.get('schema_version')}")
        tasks = [TaskState(**t) for t in d.get("tasks", [])]
        rest = {k: v for k, v in d.items() if k != "tasks"}
        return cls(tasks=tasks, **rest)


class StateStore:
    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.path = self.dir / "state.json"

    @property
    def fragments_dir(self) -> Path:
        return self.dir / "fragments"

    @property
    def assembled_dir(self) -> Path:
        return self.dir / "assembled"

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> RunState:
        with open(self.path, encoding="utf-8") as f:
            return RunState.from_dict(json.load(f))

    def save(self, state: RunState) -> None:
        atomic_write_json(self.path, state.to_dict())

    def archive(self) -> Path:
        """``--fresh``: renombra el directorio a ``<dir>.<timestamp>``."""
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.dir.with_name(f"{self.dir.name}.{stamp}")
        n = 1
        while dest.exists():
            dest = self.dir.with_name(f"{self.dir.name}.{stamp}_{n}")
            n += 1
        os.replace(self.dir, dest)
        return dest
