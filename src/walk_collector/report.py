"""Reporte final de la corrida (``report.json`` + ``report.md``).

Nunca incluye la community ni el host en claro (el estado ya no los contiene).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .assembler import AssemblyResult
from .state import (COMPLETE_OK, FAILED, PARTIAL, PH_ABORTED, PH_STOPPED, SKIPPED, EMPTY, DONE,
                    RunState, atomic_write_json, utc_now_iso)


def compute_result(state: RunState) -> str:
    if state.phase == PH_ABORTED:
        return "ABORTED"
    if state.phase == PH_STOPPED:
        return "STOPPED"
    active = [t for t in state.tasks if t.status != SKIPPED]
    if active and all(t.status in COMPLETE_OK for t in active):
        return "COMPLETE"
    return "INCOMPLETE"


def build_report(state: RunState, assemblies: Iterable[AssemblyResult],
                 finished_at: str | None = None) -> dict:
    asm = {a.output: a for a in assemblies}
    outputs: dict[str, dict] = {}
    for name in dict.fromkeys(t.output for t in state.tasks):
        a = asm.get(name)
        if a is None:
            outputs[name] = {"status": "not_assembled", "rows": 0, "file": None,
                             "published": False, "sha256": None, "dup_dropped": 0,
                             "dup_conflicts": 0}
        else:
            outputs[name] = {"status": "complete" if a.complete else "incomplete",
                             "rows": a.rows, "file": a.location or None,
                             "published": a.published, "sha256": a.sha256,
                             "dup_dropped": a.dup_dropped, "dup_conflicts": a.dup_conflicts}
    tasks = state.tasks
    last_err = lambda t: (t.errors[-1]["msg"] if t.errors else None)   # noqa: E731
    coverage = {
        "complete": [t.root for t in tasks if t.status == DONE],
        "partial": [{"root": t.root, "gaps": t.gaps} for t in tasks if t.status == PARTIAL],
        "empty": [t.root for t in tasks if t.status == EMPTY],
        "failed": [{"root": t.root, "last_error": last_err(t)} for t in tasks if t.status == FAILED],
        "skipped": [t.root for t in tasks if t.status == SKIPPED],
    }
    s = state.stats
    totals = {
        "requests": s.get("requests", 0),
        "rows": sum(t.rows for t in tasks),
        "retries": sum(t.retries for t in tasks),
        "timeouts": s.get("timeouts", 0), "too_big": s.get("too_big", 0),
        "agent_errors": s.get("agent_errors", 0),
        "backoff_s": round(s.get("backoff_s", 0.0), 2),
        "safety_pauses": s.get("safety_pauses", 0), "outages": s.get("outages", 0),
        "latency_ms": s.get("latency_ms", {}),
    }
    return {
        "run_id": state.run_id, "model_key": state.model_key,
        "result": compute_result(state), "phase": state.phase, "stop_reason": state.stop_reason,
        "sys_descr": state.target.get("sys_descr"),
        "sys_object_id": state.target.get("sys_object_id"),
        "started_at": s.get("started_at"), "finished_at": finished_at or utc_now_iso(),
        "duration_s": round(s.get("elapsed_s", 0.0), 1),
        "outputs": outputs, "coverage": coverage, "totals": totals,
        "tasks": [{"id": t.id, "output": t.output, "root": t.root, "status": t.status,
                   "rows": t.rows, "requests": t.requests, "retries": t.retries,
                   "timeouts": t.timeouts, "too_big": t.too_big, "nonincreasing": t.nonincreasing,
                   "max_rep_min_used": t.max_rep_min_used, "gaps": len(t.gaps),
                   "duration_s": round(t.duration_s, 1)} for t in tasks],
    }


def render_markdown(rep: dict) -> str:
    L = [f"# Reporte del recolector — {rep['model_key']}", "",
         f"- Resultado: **{rep['result']}** (fase `{rep['phase']}`"
         + (f", motivo: {rep['stop_reason']}" if rep.get("stop_reason") else "") + ")",
         f"- Corrida: `{rep['run_id']}` — duración {rep['duration_s']} s",
         f"- Equipo: {rep.get('sys_descr') or '(sin preflight)'}",
         f"- sysObjectID: `{rep.get('sys_object_id') or '-'}`", "", "## Outputs", "",
         "| output | estado | filas | publicado | duplicados (conflictos) |", "|---|---|---|---|---|"]
    for name, o in rep["outputs"].items():
        L.append(f"| {name} | {o['status']} | {o['rows']} | {'sí' if o['published'] else 'no'} "
                 f"| {o['dup_dropped']} ({o['dup_conflicts']}) |")
    t = rep["totals"]
    L += ["", "## Totales", "",
          f"- Peticiones: {t['requests']} — filas: {t['rows']} — reintentos: {t['retries']}",
          f"- Timeouts: {t['timeouts']} — tooBig: {t['too_big']} — errores del agente: {t['agent_errors']}",
          f"- Backoff acumulado: {t['backoff_s']} s — pausas de seguridad: {t['safety_pauses']} "
          f"— caídas: {t['outages']}",
          f"- Latencia (ms): {t['latency_ms']}", "", "## Cobertura", "",
          f"- Completas: {len(rep['coverage']['complete'])} — vacías: {len(rep['coverage']['empty'])} "
          f"— parciales: {len(rep['coverage']['partial'])} — fallidas: {len(rep['coverage']['failed'])} "
          f"— omitidas: {len(rep['coverage']['skipped'])}"]
    for p in rep["coverage"]["partial"]:
        L.append(f"  - parcial `{p['root']}`: {len(p['gaps'])} hueco(s)")
    for f in rep["coverage"]["failed"]:
        L.append(f"  - fallida `{f['root']}`: {f['last_error']}")
    L += ["", "## Comandos para continuar", "", "```",
          "py -m src.walk_collector --resume                  # retoma lo pendiente",
          "py -m src.walk_collector --resume --retry-failed   # reintenta también las fallidas",
          "py -m src.walk_collector --assemble-only           # re-ensambla desde los fragmentos (sin red)",
          "```", ""]
    return "\n".join(L)


def write_reports(report: dict, state_dir: Path) -> tuple[Path, Path]:
    state_dir = Path(state_dir)
    js = state_dir / "report.json"
    md = state_dir / "report.md"
    atomic_write_json(js, report)
    tmp = md.with_name(md.name + ".tmp")
    tmp.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    import os
    os.replace(tmp, md)
    return js, md
