"""Orquestador de la recolección: preflight -> discovery -> tareas -> ronda final ->
ensamblado/publicación -> reporte.

Solo lectura SNMP. Una sola petición en vuelo. Todo el avance se persiste con el orden
fragmento -> estado (exactly-once), de modo que ante cualquier corte se reanuda con
``--resume`` sin huecos ni duplicados.

Códigos de salida (``Collector.exit_code`` / ``CollectorAbort.exit_code``):
0 completo y publicado · 1 terminó con tareas failed/partial · 2 uso/config ·
3 detenido por seguridad/caída/runtime (reanudable) · 4 preflight/auth/modelo ·
5 E/S local · 130 interrumpido.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Callable, Iterable

from . import state as S
from .assembler import (AssemblyResult, assemble_output, iter_walk_lines,
                        verify_strictly_increasing)
from .config import CollectorConfig
from .discovery import TaskSpec, dedupe_roots, discover, task_id
from .fragments import FragmentCorrupt, FragmentWriter
from .oid import Oid, fmt_oid, in_subtree, parse_oid
from .pacing import AdaptiveRepetitions, Backoff, Clock, LatencyMonitor, RealClock
from .redaction import Redactor, load_or_create_salt
from .report import build_report, write_reports
from .secrets import Scrubber
from .sink import FileSink, WalkSink
from .state import RunState, StateStore, TaskState
from .transport import (EXCEPTION_KINDS, SnmpTransport, TransportAgentError, TransportAuthError,
                        TransportFatal, TransportTimeout)
from .walker import OutageDetected, SafetyTrip, sanity_check, walk_task

log = logging.getLogger("tkc.walk_collector")

SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1, 0)
SYS_OBJECT_ID = (1, 3, 6, 1, 2, 1, 1, 2, 0)
SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)

GENERIC_NO_RESPONSE = ("El equipo no respondió al preflight. Verifica host, puerto, community "
                       "y ACL de SNMP (en SNMPv2c una community incorrecta se descarta en "
                       "silencio: no se distingue de un timeout).")


class CollectorAbort(Exception):
    """Aborto de la corrida con código de salida (2 config, 4 preflight/auth/modelo, 5 E/S)."""

    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


class StopRun(Exception):
    """Detención ordenada y reanudable (seguridad, caída prolongada, runtime, Ctrl+C)."""

    def __init__(self, reason: str, exit_code: int = 3):
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code


def _text(value: object) -> str:
    return bytes(value).decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)


class Collector:
    def __init__(self, cfg: CollectorConfig, transport_factory: Callable[[], SnmpTransport],
                 clock: Clock | None = None, store: StateStore | None = None, *,
                 target_id: str = "local", scrubber: Scrubber | None = None,
                 run_id: str | None = None, rng: random.Random | None = None,
                 sink: WalkSink | None = None, publish: bool = True,
                 allow_incomplete: bool | None = None):
        self.cfg = cfg
        self.factory = transport_factory
        self.clock: Clock = clock or RealClock()
        self.store = store or StateStore(cfg.run_dir)
        self.target_id = target_id
        self.scrubber = scrubber or Scrubber()
        self._run_id = run_id
        self.sink: WalkSink = sink or FileSink(cfg.paths.publish_dir)
        self.publish = publish
        self.allow_incomplete = cfg.allow_incomplete if allow_incomplete is None else allow_incomplete
        self.backoff = Backoff(cfg.retry.backoff_base_s, cfg.retry.backoff_max_s,
                               cfg.retry.jitter, rng or random.Random())
        sf = cfg.safety
        self.monitor = LatencyMonitor(sf.latency_window, sf.baseline_samples, sf.degrade_factor,
                                      sf.degrade_min_ms, sf.sustain_checks)
        self.transport: SnmpTransport | None = None
        self.state: RunState | None = None
        self.exit_code: int | None = None
        self.assemblies: list[AssemblyResult] = []
        self._stop_flag = False
        self._stop_reason: str | None = None
        self._max_runtime_s: float | None = None
        self._t_start = 0.0
        self._elapsed0 = 0.0
        self._ckpt_reqs = 0
        self._last_ckpt = 0.0
        self._log_handler: logging.Handler | None = None
        self._scrub = self.scrubber.scrub

    # ------------------------------------------------------------------ utilidades
    def request_stop(self) -> None:
        """Ctrl+C: termina el PDU en curso, hace checkpoint y sale (exit 130)."""
        self._stop_flag = True
        self._stop_reason = "interrupted"

    def _should_stop(self) -> bool:
        if self._stop_flag:
            return True
        if self._max_runtime_s and self._elapsed() >= self._max_runtime_s:
            self._stop_reason = "max_runtime"
            return True
        return False

    def _elapsed(self) -> float:
        return self._elapsed0 + (self.clock.monotonic() - self._t_start)

    def _ensure_transport(self) -> SnmpTransport:
        if self.transport is None:
            self.transport = self.factory()
        return self.transport

    def _save(self) -> None:
        st = self.state
        st.stats["elapsed_s"] = round(self._elapsed(), 1)
        st.stats["latency_ms"] = self.monitor.summary()
        self.store.save(st)

    def _set_phase(self, phase: str) -> None:
        self.state.phase = phase
        log.info("fase: %s", phase)
        self._save()

    def _parse_only(self, only: Iterable[str]) -> tuple[set[str], list[Oid]]:
        names: set[str] = set()
        prefixes: list[Oid] = []
        for item in only:
            if item in self.cfg.outputs:
                names.add(item)
                continue
            try:
                prefixes.append(parse_oid(item))
            except ValueError:
                raise CollectorAbort(
                    f"--only '{item}' no es un output ({', '.join(self.cfg.outputs)}) ni un OID",
                    2) from None
        return names, prefixes

    @staticmethod
    def _overlaps(a: Oid, b: Oid) -> bool:
        return in_subtree(a, b) or in_subtree(b, a)

    def _output_selected(self, name: str, names: set[str], prefixes: list[Oid]) -> bool:
        if not names and not prefixes:
            return True
        if name in names:
            return True
        return any(self._overlaps(r, p) for r in self.cfg.outputs[name].roots for p in prefixes)

    def _task_selected(self, t: TaskState, names: set[str], prefixes: list[Oid]) -> bool:
        if not names and not prefixes:
            return True
        if t.output in names:
            return True
        root = parse_oid(t.root)
        return any(self._overlaps(root, p) for p in prefixes)

    # ------------------------------------------------------------------ plan
    def plan(self, only: Iterable[str] = ()) -> list[TaskSpec]:
        """Tareas previstas SIN red. Con estado previo, las del estado; si no, una por raíz
        (las ramas ``discover: true`` se expandirán con GETNEXT durante la corrida)."""
        names, prefixes = self._parse_only(only)
        if self.store.exists():
            try:
                st = self.store.load()
                return [TaskSpec(t.id, t.output, parse_oid(t.root), t.root_is_instance)
                        for t in st.tasks if self._task_selected(t, names, prefixes)]
            except (ValueError, OSError, KeyError, TypeError):
                pass
        specs = []
        for name, out in self.cfg.outputs.items():
            if not self._output_selected(name, names, prefixes):
                continue
            for root in dedupe_roots(out.roots):
                specs.append(TaskSpec(task_id(name, root), name, root))
        return specs

    # ------------------------------------------------------------------ preflight
    def preflight(self, force_model: bool = False) -> dict:
        """GET de sysDescr/sysObjectID/sysUpTime. Aborta (exit 4) si no responde o si el
        modelo no coincide. No emite ningún GETBULK."""
        tr = self._ensure_transport()
        attempts = self.cfg.snmp.preflight_attempts
        vbs = None
        for n in range(1, attempts + 1):
            try:
                vbs = tr.get([SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME])
                self.monitor.record(tr.last_latency_ms)
                break
            except (TransportTimeout, TransportAgentError):
                log.warning("preflight sin respuesta (intento %d/%d)", n, attempts)
                if n < attempts:
                    self.clock.sleep(self.backoff.delay(n))
        if vbs is None:
            raise CollectorAbort(GENERIC_NO_RESPONSE, 4)
        by_oid = {v.oid: v for v in vbs}
        d = by_oid.get(SYS_DESCR)
        if d is None or d.kind in EXCEPTION_KINDS:
            raise CollectorAbort("El equipo no expone sysDescr (noSuchObject): community sin "
                                 "acceso a la vista MIB-2 o equipo incorrecto.", 4)
        sys_descr = _text(d.value)[:200]
        oid_vb = by_oid.get(SYS_OBJECT_ID)
        sys_oid = fmt_oid(tuple(oid_vb.value)) if oid_vb is not None and oid_vb.kind == "OID" else None
        up_vb = by_oid.get(SYS_UPTIME)
        info = {"sys_descr": sys_descr, "sys_object_id": sys_oid,
                "sys_uptime": up_vb.value if up_vb is not None else None,
                "latency_ms": round(tr.last_latency_ms, 1)}
        if not re.search(self.cfg.expect_sysdescr_regex, sys_descr):
            if not force_model:
                raise CollectorAbort(
                    f"sysDescr '{sys_descr}' no coincide con el modelo esperado "
                    f"/{self.cfg.expect_sysdescr_regex}/. Usa --force-model si es correcto.", 4)
            log.warning("sysDescr no coincide con /%s/ pero se continúa por --force-model",
                        self.cfg.expect_sysdescr_regex)
        return info

    # ------------------------------------------------------------------ apertura de estado
    def _open(self, resume: bool, fresh: bool, force: bool) -> RunState:
        exists = self.store.exists()
        if exists and fresh:
            dest = self.store.archive()
            log.info("estado previo archivado en %s", dest.name)
            exists = False
        if exists and not resume:
            raise CollectorAbort(f"Ya existe estado en {self.store.dir}. Usa --resume para "
                                 "continuar o --fresh para archivarlo y empezar de cero.", 2)
        if resume and not exists:
            raise CollectorAbort("No hay estado previo para reanudar (usa la corrida sin --resume).", 2)
        if exists:
            try:
                st = self.store.load()
            except (ValueError, OSError, KeyError, TypeError) as exc:
                raise CollectorAbort(f"estado ilegible: {exc}", 2) from None
            problems = []
            if st.target.get("target_id") != self.target_id:
                problems.append("otro host/puerto (target_id distinto)")
            if st.config_hash != self.cfg.config_hash():
                problems.append("la configuración de qué recolectar cambió (config_hash)")
            if st.model_key != self.cfg.model_key:
                problems.append("otro modelo")
            if problems and not force:
                raise CollectorAbort("No se puede reanudar: " + "; ".join(problems)
                                     + ". Usa --force para ignorarlo.", 2)
            log.info("reanudando corrida %s (%d tareas)", st.run_id, len(st.tasks))
            return st
        st = RunState(run_id=self._run_id or S.new_run_id(), model_key=self.cfg.model_key,
                      target={"target_id": self.target_id}, config_hash=self.cfg.config_hash())
        st.stats["started_at"] = S.utc_now_iso()
        return st

    def _install_log(self) -> None:
        self.store.dir.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(self.store.dir / "collector.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        h.addFilter(self.scrubber)
        pkg = logging.getLogger("tkc.walk_collector")
        if pkg.level == logging.NOTSET or pkg.level > logging.INFO:
            pkg.setLevel(logging.INFO)
        pkg.addHandler(h)
        self._log_handler = h

    def _remove_log(self) -> None:
        if self._log_handler is not None:
            logging.getLogger("tkc.walk_collector").removeHandler(self._log_handler)
            self._log_handler.close()
            self._log_handler = None

    # ------------------------------------------------------------------ run
    def run(self, *, resume: bool = False, fresh: bool = False, only: Iterable[str] = (),
            retry_failed: bool = False, discover_only: bool = False, force_model: bool = False,
            force: bool = False, max_runtime_s: float | None = None) -> RunState:
        only = tuple(only)
        self._parse_only(only)                       # valida antes de tocar disco
        self.state = self._open(resume, fresh, force)
        st = self.state
        self._max_runtime_s = max_runtime_s or (self.cfg.safety.max_runtime_min * 60 or None)
        self._elapsed0 = float(st.stats.get("elapsed_s", 0.0))
        self._t_start = self.clock.monotonic()
        self._last_ckpt = self._t_start
        self._stop_flag = False
        self._install_log()
        self.assemblies = []
        abort: CollectorAbort | None = None
        try:
            try:
                self._pipeline(only, retry_failed, discover_only, force_model, force)
            except StopRun as stop:
                st.phase, st.stop_reason = S.PH_STOPPED, stop.reason
                self.exit_code = stop.exit_code
                log.warning("corrida detenida (%s); se puede reanudar con --resume", stop.reason)
            except KeyboardInterrupt:
                st.phase, st.stop_reason = S.PH_STOPPED, "interrupted"
                self.exit_code = 130
                log.warning("interrumpido por el usuario; se puede reanudar con --resume")
            except CollectorAbort as exc:
                abort = exc
            except TransportAuthError as exc:
                abort = CollectorAbort(f"el equipo rechazó la autenticación: {self._scrub(str(exc))}", 4)
            except TransportFatal as exc:
                abort = CollectorAbort(f"error irrecuperable de transporte: {self._scrub(str(exc))}", 4)
            except (OSError, FragmentCorrupt) as exc:
                abort = CollectorAbort(f"error de E/S local: {self._scrub(str(exc))}", 5)
            if abort is not None:
                st.phase, st.stop_reason = S.PH_ABORTED, self._scrub(str(abort))
                self.exit_code = abort.exit_code
                log.error("corrida abortada: %s", st.stop_reason)
        finally:
            self._finalize()
        if abort is not None:
            raise abort
        return st

    def _pipeline(self, only, retry_failed, discover_only, force_model, force) -> None:
        st = self.state
        names, prefixes = self._parse_only(only)
        self._ensure_transport()
        self._set_phase(S.PH_PREFLIGHT)
        info = self.preflight(force_model)
        prev_oid = st.target.get("sys_object_id")
        if prev_oid and info["sys_object_id"] and prev_oid != info["sys_object_id"] and not force:
            raise CollectorAbort("No se puede reanudar: sysObjectID distinto al de la corrida "
                                 "guardada (otro equipo). Usa --force para ignorarlo.", 2)
        st.target.update(sys_descr=info["sys_descr"], sys_object_id=info["sys_object_id"])
        log.info("preflight OK: %s (%d ms)", info["sys_descr"], info["latency_ms"])

        # estado de tareas para ESTA corrida
        for t in st.tasks:
            if t.status == S.SKIPPED:
                t.status = S.PENDING
            elif t.status == S.RUNNING:
                t.status = S.PENDING
            elif t.status == S.FAILED and retry_failed:
                t.status = S.PENDING
        self._set_phase(S.PH_DISCOVERY)
        self._discover(names, prefixes)
        for t in st.tasks:
            if not self._task_selected(t, names, prefixes) and t.status in (S.PENDING, S.DEFERRED):
                t.status = S.SKIPPED
        self._save()
        if discover_only:
            log.info("discover-only: %d tarea(s) planificadas", len(st.tasks))
            st.phase, st.stop_reason = S.PH_STOPPED, "discover_only"
            self.exit_code = 0
            return

        self._set_phase(S.PH_COLLECTING)
        for i, t in enumerate([t for t in st.tasks if t.status in (S.PENDING, S.RUNNING)]):
            if i:
                self.clock.sleep(self.cfg.pacing.inter_task_delay_s)
            self._run_task(t)

        self._set_phase(S.PH_FINAL_RETRY)
        for _ in range(self.cfg.retry.final_retry_rounds):
            deferred = [t for t in st.tasks if t.status == S.DEFERRED]
            if not deferred:
                break
            log.info("ronda final: %d tarea(s) diferidas", len(deferred))
            for t in deferred:
                self.clock.sleep(self.cfg.pacing.inter_task_delay_s)
                self._run_task(t)
        for t in st.tasks:
            if t.status == S.DEFERRED:
                t.status = S.FAILED
                t.finished_at = S.utc_now_iso()
        self._set_phase(S.PH_ASSEMBLING)
        self.assemblies = self._assemble_all()
        st.phase = S.PH_DONE
        active = [t for t in st.tasks if t.status != S.SKIPPED]
        bad = [t for t in active if t.status in (S.FAILED, S.PARTIAL)]
        self.exit_code = 1 if bad else 0

    # ------------------------------------------------------------------ discovery
    def _discover(self, names: set[str], prefixes: list[Oid]) -> None:
        st = self.state
        tr = self._ensure_transport()
        cfg = self.cfg
        pace = cfg.pacing.inter_request_delay_ms / 1000.0
        for name, out in cfg.outputs.items():
            if name in st.discovered_outputs or not self._output_selected(name, names, prefixes):
                continue
            specs: list[TaskSpec] = []
            for root in dedupe_roots(out.roots):
                if not out.discover:
                    specs.append(TaskSpec(task_id(name, root), name, root))
                    continue
                found = None
                for attempt in (1, 2):
                    try:
                        found = discover(tr, name, root, cfg.discovery.base_depth,
                                         set(cfg.discovery.expand), cfg.discovery.max_children,
                                         self.clock, pace, backoff=self.backoff)
                        break
                    except (TransportTimeout, TransportAgentError) as exc:
                        log.warning("discovery de %s falló (%s)", fmt_oid(root),
                                    self._scrub(str(exc)))
                        if not sanity_check(tr, cfg):
                            self._handle_outage()
                if found is None:
                    log.warning("discovery no concluyó en %s: queda como una sola tarea", fmt_oid(root))
                    found = [TaskSpec(task_id(name, root), name, root)]
                specs.extend(found)
            known = {t.id for t in st.tasks}
            for sp in specs:
                if sp.id not in known:
                    st.tasks.append(TaskState(id=sp.id, output=sp.output, root=fmt_oid(sp.root),
                                              root_is_instance=sp.root_is_instance))
            st.discovered_outputs.append(name)
            log.info("output %s: %d tarea(s)", name, len(specs))
            self._save()

    # ------------------------------------------------------------------ tareas
    def _run_task(self, task: TaskState) -> None:
        st = self.state
        cfg = self.cfg
        tr = self._ensure_transport()
        frag = FragmentWriter(self.store.fragments_dir / f"{task.id}.txt", task.committed_bytes)
        task.status = S.RUNNING
        task.attempts += 1
        task.started_at = task.started_at or S.utc_now_iso()
        reps = AdaptiveRepetitions(cfg.snmp.max_repetitions, floor=cfg.snmp.min_repetitions)
        t0 = self.clock.monotonic()
        log.info("tarea %s (%s) desde %s", task.id, task.status, task.last_oid or task.root)

        def checkpoint(force: bool = False) -> None:
            # orden fragmento -> estado: primero fsync del fragmento, luego el state.json
            self._ckpt_reqs += 1
            now = self.clock.monotonic()
            if (force or self._ckpt_reqs >= cfg.pacing.checkpoint_every_requests
                    or now - self._last_ckpt >= cfg.pacing.checkpoint_every_s):
                task.committed_bytes = frag.commit()
                self._save()
                self._ckpt_reqs = 0
                self._last_ckpt = now

        try:
            while True:
                try:
                    outcome = walk_task(task, tr, frag, reps, self.monitor, self.backoff,
                                        self.clock, cfg, checkpoint, self._should_stop,
                                        st.stats, self._scrub)
                except OutageDetected:
                    self._handle_outage()
                    continue
                except SafetyTrip:
                    self._handle_safety()
                    continue
                break
        except BaseException:
            # persiste lo comprometido para poder reanudar exactamente desde aquí
            try:
                task.committed_bytes = frag.commit()
                if task.status == S.RUNNING:
                    task.status = S.PENDING
                self._save()
            except Exception:
                pass
            raise
        finally:
            frag.close()
            task.duration_s += self.clock.monotonic() - t0
        if outcome.status == "pending":
            task.status = S.PENDING
            self._save()
            reason = self._stop_reason or "interrupted"
            raise StopRun(reason, 130 if reason == "interrupted" else 3)
        task.status = outcome.status
        if task.status != S.DEFERRED:
            task.finished_at = S.utc_now_iso()
        log.info("tarea %s -> %s (%d filas, %d peticiones)", task.id, task.status,
                 task.rows, task.requests)
        self._save()

    # ------------------------------------------------------------------ caídas / seguridad
    def _handle_outage(self) -> None:
        """Modo caída: espera creciente + GET de cordura hasta ``max_outage_min``."""
        st = self.state
        tr = self._ensure_transport()
        cfg = self.cfg.outage
        st.stats["outages"] = st.stats.get("outages", 0) + 1
        t0 = self.clock.monotonic()
        limit = cfg.max_outage_min * 60
        i = 0
        log.warning("el equipo dejó de responder: modo caída (máx. %.0f min)", cfg.max_outage_min)
        while True:
            w = cfg.wait_s[min(i, len(cfg.wait_s) - 1)]
            i += 1
            self.clock.sleep(w)
            if sanity_check(tr, self.cfg):
                log.info("el equipo volvió tras %.0f s", self.clock.monotonic() - t0)
                self.monitor.reset_window()
                return
            if self.clock.monotonic() - t0 >= limit:
                raise StopRun("outage", 3)
            if self._stop_flag:
                raise StopRun("interrupted", 130)

    def _handle_safety(self) -> None:
        st = self.state
        sf = self.cfg.safety
        if st.stats.get("safety_pauses", 0) >= sf.max_safety_pauses:
            raise StopRun("safety", 3)
        st.stats["safety_pauses"] = st.stats.get("safety_pauses", 0) + 1
        log.warning("latencia degradada: pausa de seguridad %d/%d de %.0f s",
                    st.stats["safety_pauses"], sf.max_safety_pauses, sf.pause_s)
        self._save()
        self.clock.sleep(sf.pause_s)
        if not sanity_check(self._ensure_transport(), self.cfg):
            self._handle_outage()
        self.monitor.reset_window()

    # ------------------------------------------------------------------ ensamblado
    def _assemble_all(self, allow_partial_input: bool = False) -> list[AssemblyResult]:
        st = self.state
        results: list[AssemblyResult] = []
        for name in dict.fromkeys(t.output for t in st.tasks):
            tasks = [t for t in st.tasks if t.output == name]
            if any(t.status in (S.PENDING, S.RUNNING, S.DEFERRED, S.SKIPPED) for t in tasks) \
                    and not allow_partial_input:
                continue
            results.append(self._assemble_one(name, tasks))
        return results

    def _assemble_one(self, name: str, tasks: list[TaskState]) -> AssemblyResult:
        cfg = self.cfg
        fname = cfg.output_filename(name)
        redactor = Redactor("none")
        if cfg.redaction.mode == "prefixes":
            salt = load_or_create_salt(self.store.dir / "redaction.salt")
            redactor = Redactor("prefixes", cfg.redaction.prefixes, salt)
        header = {"model": cfg.model_key, "output": name, "run": self.state.run_id,
                  "roots": [fmt_oid(r) for r in cfg.outputs[name].roots]}
        dest = self.store.assembled_dir / (fname + ".tmp")
        res = assemble_output(name, tasks, self.store.fragments_dir, dest, header, redactor)
        ok, n = verify_strictly_increasing(dest)
        if not ok or n != res.rows:
            raise CollectorAbort(f"el ensamblado de {name} no quedó estrictamente creciente", 5)
        if self.publish and (res.complete or self.allow_incomplete):
            res.location = self.sink.write_output(cfg.model_key, name, iter_walk_lines(dest),
                                                  {"filename": fname, "complete": res.complete,
                                                   "rows": res.rows, "sha256": res.sha256})
            res.published = True
            log.info("publicado %s (%d filas, %s)", fname, res.rows,
                     "COMPLETE" if res.complete else "INCOMPLETE")
        elif not res.complete:
            log.warning("%s incompleto: NO se publica (usa --allow-incomplete para forzarlo)", fname)
        return res

    def assemble_only(self) -> RunState:
        """Re-ensambla y publica desde los fragmentos, sin red."""
        if not self.store.exists():
            raise CollectorAbort("No hay estado ni fragmentos para ensamblar.", 2)
        self.state = self.store.load()
        self._t_start = self.clock.monotonic()
        self._elapsed0 = float(self.state.stats.get("elapsed_s", 0.0))
        self._install_log()
        abort = None
        try:
            try:
                self.assemblies = self._assemble_all(allow_partial_input=self.allow_incomplete)
            except CollectorAbort as exc:
                abort = exc
            except OSError as exc:
                abort = CollectorAbort(f"error de E/S local: {self._scrub(str(exc))}", 5)
            if abort is None:
                bad = [a for a in self.assemblies if not a.complete]
                self.exit_code = 1 if bad else 0
            else:
                self.exit_code = abort.exit_code
        finally:
            self._write_reports()
            self._remove_log()
        if abort is not None:
            raise abort
        return self.state

    # ------------------------------------------------------------------ cierre
    def _write_reports(self) -> None:
        try:
            write_reports(build_report(self.state, self.assemblies), self.store.dir)
        except OSError as exc:
            log.error("no se pudo escribir el reporte: %s", self._scrub(str(exc)))

    def _finalize(self) -> None:
        st = self.state
        try:
            for t in st.tasks:
                if t.status == S.RUNNING:
                    t.status = S.PENDING
            self._save()
        except OSError as exc:
            log.error("no se pudo guardar el estado final: %s", self._scrub(str(exc)))
        self._write_reports()
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
            self.transport = None
        self._remove_log()
