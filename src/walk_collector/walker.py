"""Recorrido (GETBULK) de UNA tarea = un subárbol, con reintentos, backoff y
protección contra bucles.

Garantías:
* una sola petición en vuelo; ``inter_request_delay_ms`` entre PDUs;
* NUNCA hay bucle infinito: sin progreso -> ``stall`` -> salto (``skip_level``) con
  un límite de saltos por tarea (``partial``);
* el fragmento recibe SOLO líneas del subárbol de la tarea;
* los cruces con el resto del sistema (caída general, latencia degradada) se
  señalan con excepciones para que el Collector decida y reanude la tarea.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import CollectorConfig
from .formatter import format_line
from .fragments import FragmentWriter
from .oid import fmt_oid, in_subtree, parse_oid, skip_level
from .pacing import AdaptiveRepetitions, Backoff, Clock, LatencyMonitor
from .state import TaskState, utc_now_iso
from .transport import (EXCEPTION_KINDS, SnmpTransport, TransportAgentError,
                        TransportTimeout, TransportTooBig)

MAX_ERRORS_KEPT = 20


class OutageDetected(Exception):
    """Los reintentos se agotaron y el GET de cordura tampoco responde: caída general."""


class SafetyTrip(Exception):
    """El monitor de latencia declaró al equipo degradado (kill-switch)."""


class _Exhausted(Exception):
    """Reintentos del request agotados (interno)."""


class _TooBigSingle(Exception):
    """tooBig con el mínimo de repeticiones (interno)."""


@dataclass
class TaskOutcome:
    status: str                      # done|empty|partial|deferred|pending
    rows_added: int = 0
    gaps: list[dict] = field(default_factory=list)
    nonincreasing: int = 0


def _inc(stats: dict | None, key: str, n: float = 1) -> None:
    if stats is not None:
        stats[key] = stats.get(key, 0) + n


def sanity_check(transport: SnmpTransport, cfg: CollectorConfig) -> bool:
    """GET de cordura (sysDescr): ¿el equipo sigue respondiendo? Auth/Fatal se propagan."""
    try:
        vbs = transport.get([cfg.outage.sanity_oid])
    except (TransportTimeout, TransportAgentError):
        return False
    return bool(vbs) and all(v.kind not in EXCEPTION_KINDS for v in vbs)


def walk_task(task: TaskState, transport: SnmpTransport, fragment: FragmentWriter,
              reps: AdaptiveRepetitions, monitor: LatencyMonitor, backoff: Backoff,
              clock: Clock, cfg: CollectorConfig,
              checkpoint: Callable[[bool], None],
              should_stop: Callable[[], bool],
              stats: dict | None = None,
              scrub: Callable[[str], str] = lambda s: s) -> TaskOutcome:
    root = parse_oid(task.root)
    out = TaskOutcome("done")
    pace = cfg.pacing.inter_request_delay_ms / 1000.0
    retry = cfg.retry

    def note_error(kind: str, msg: str) -> None:
        task.errors.append({"ts": utc_now_iso(), "kind": kind, "msg": scrub(msg)[:300]})
        del task.errors[:-MAX_ERRORS_KEPT]

    def add_gap(frm, to, reason: str) -> None:
        gap = {"from": fmt_oid(frm), "to": fmt_oid(to), "reason": reason}
        task.gaps.append(gap)
        out.gaps.append(gap)

    def retrying(fn, is_bulk: bool):
        """Ejecuta ``fn`` con reintentos/backoff. Lanza _Exhausted o _TooBigSingle."""
        attempt = 0
        consecutive = 0
        while True:
            attempt += 1
            task.requests += 1
            _inc(stats, "requests")
            try:
                res = fn()
            except TransportTooBig as exc:
                task.too_big += 1
                _inc(stats, "too_big")
                note_error("too_big", str(exc))
                attempt -= 1                      # tooBig no consume intentos
                if is_bulk and reps.current > reps.floor:
                    reps.on_too_big()             # mitad inmediata, sin backoff
                    continue
                raise _TooBigSingle() from None
            except (TransportTimeout, TransportAgentError) as exc:
                is_timeout = isinstance(exc, TransportTimeout)
                if is_timeout:
                    task.timeouts += 1
                    _inc(stats, "timeouts")
                else:
                    _inc(stats, "agent_errors")
                note_error(exc.kind, str(exc))
                monitor.record(cfg.snmp.timeout_s * 1000.0, timed_out=True)
                consecutive += 1
                if attempt >= retry.max_attempts_per_request:
                    raise _Exhausted() from None
                delay = backoff.delay(attempt)
                clock.sleep(delay)
                _inc(stats, "backoff_s", delay)
                task.retries += 1
                if is_bulk:
                    reps.on_timeout(consecutive)
                continue
            monitor.record(transport.last_latency_ms)
            if is_bulk:
                reps.on_success()
            return res

    def exhausted() -> TaskOutcome:
        """Reintentos agotados: cordura OK -> deferred; si no -> caída general."""
        if sanity_check(transport, cfg):
            out.status = "deferred"
            return out
        raise OutageDetected()

    def sync_reps() -> None:
        task.max_rep_current = reps.current
        task.max_rep_min_used = reps.min_used

    # --- GET inicial de una raíz que es instancia -------------------------------
    cursor = parse_oid(task.last_oid) if task.last_oid else root
    if task.root_is_instance and task.last_oid is None:
        try:
            vbs = retrying(lambda: transport.get([root]), False)
        except _Exhausted:
            return exhausted()
        except _TooBigSingle:
            add_gap(root, root, "too_big_single")
            vbs = []
        vb = vbs[0] if vbs else None
        if vb is not None and vb.kind not in EXCEPTION_KINDS:
            fragment.append([format_line(vb)])
            task.rows += 1
            out.rows_added += 1
        elif vb is not None and not task.gaps:
            # noSuchObject/noSuchInstance en una raíz-instancia: la rama no existe
            out.status = "empty"
            task.last_oid = fmt_oid(root)
            checkpoint(True)
            return out
        task.last_oid = fmt_oid(root)
        cursor = root

    stall = 0
    bumps = 0
    k = 0
    while True:
        if should_stop():
            out.status = "pending"
            checkpoint(True)
            return out
        try:
            vbs = retrying(lambda: transport.get_bulk(cursor, reps.current), True)
        except _Exhausted:
            sync_reps()
            checkpoint(True)
            return exhausted()
        except _TooBigSingle:
            # una fila que no cabe ni sola: gap registrado y se salta
            if bumps >= retry.max_bumps_per_task:
                add_gap(cursor, cursor, "max_bumps")
                out.status = "partial"
                break
            bumps += 1
            target = skip_level(cursor, k)
            k += 1
            add_gap(cursor, target, "too_big_single")
            cursor = target
            task.last_oid = fmt_oid(cursor)
            sync_reps()
            checkpoint(False)
            if not in_subtree(cursor, root):
                break
            continue

        sync_reps()
        lines: list[str] = []
        high = cursor
        end = False
        for vb in vbs:
            if vb.kind == "END_OF_MIB":
                end = True
                break
            if vb.kind in EXCEPTION_KINDS:
                continue
            if not in_subtree(vb.oid, root):
                end = True
                break
            lines.append(format_line(vb))
            if vb.oid > high:
                high = vb.oid
            else:
                # OID no creciente: se conserva la fila (el ensamblado deduplica)
                task.nonincreasing += 1
                out.nonincreasing += 1
        if lines:
            fragment.append(lines)
            task.rows += len(lines)
            out.rows_added += len(lines)
        progress = high > cursor
        if progress:
            cursor = high
            task.last_oid = fmt_oid(cursor)
            stall = 0
            k = 0
        elif not end:
            stall += 1
            if stall >= retry.max_stall_pdus:
                if bumps >= retry.max_bumps_per_task:
                    add_gap(cursor, cursor, "max_bumps")
                    out.status = "partial"
                    checkpoint(True)
                    break
                bumps += 1
                target = skip_level(cursor, k)
                k += 1
                add_gap(cursor, target, "nonincreasing")
                stall = 0
                cursor = target
                task.last_oid = fmt_oid(cursor)
                if not in_subtree(cursor, root):
                    end = True
        checkpoint(False)
        if end:
            break
        if monitor.verdict() == "degraded":
            checkpoint(True)
            raise SafetyTrip()
        if pace > 0:
            clock.sleep(pace)

    if out.status != "partial":
        if task.gaps:
            out.status = "partial"
        elif task.rows == 0:
            out.status = "empty"
        else:
            out.status = "done"
    sync_reps()
    checkpoint(True)
    return out
