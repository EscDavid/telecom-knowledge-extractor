"""Ensamblado de los fragmentos de un output en un walk único, ordenado y sin duplicados.

* orden NUMÉRICO por arcos (1012.3.3 < 1012.3.28), no lexicográfico;
* deduplicación por OID (si un mismo OID reaparece con otro valor: ``dup_conflicts`` y
  queda el último);
* encabezado ``# tkc-walk-collector v1 ...`` (sin `` = ``: ``parse_walk`` lo ignora);
* se escribe primero a un archivo de trabajo y se verifica estrictamente creciente antes
  de publicar.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .fragments import read_fragment_lines
from .oid import Oid, fmt_oid, line_key
from .redaction import Redactor
from .state import COMPLETE_OK, TaskState

HEADER_PREFIX = "# tkc-walk-collector v1"


@dataclass
class AssemblyResult:
    output: str
    path: Path | None
    rows: int
    dup_dropped: int
    dup_conflicts: int
    complete: bool
    published: bool = False
    sha256: str = ""
    location: str = ""


def format_header(h: dict) -> str:
    parts = [HEADER_PREFIX, f"model:{h['model']}", f"output:{h['output']}",
             f"status:{h['status']}"]
    if h.get("status") == "INCOMPLETE" and "missing" in h:
        parts[-1] = f"status:INCOMPLETE missing:{h['missing']}"
    parts += [f"rows:{h['rows']}", f"run:{h['run']}", f"roots:{','.join(h['roots'])}"]
    line = " ".join(parts)
    assert " = " not in line
    return line


def output_is_complete(tasks: Iterable[TaskState]) -> bool:
    ts = list(tasks)
    return bool(ts) and all(t.status in COMPLETE_OK for t in ts)


def assemble_output(output: str, tasks: list[TaskState], fragments_dir: Path, dest: Path,
                    header: dict, redactor: Redactor | None = None) -> AssemblyResult:
    """Lee los fragmentos de ``tasks``, deduplica, ordena y escribe ``dest`` (archivo de
    trabajo). ``header`` lleva model/output/run/roots (status y rows los completa aquí)."""
    redactor = redactor or Redactor()
    rows: dict[Oid, str] = {}
    dup_dropped = dup_conflicts = 0
    for t in tasks:
        for ln in read_fragment_lines(Path(fragments_dir) / f"{t.id}.txt", t.committed_bytes):
            if " = " not in ln:
                continue
            try:
                key = line_key(ln)
            except ValueError:
                continue
            prev = rows.get(key)
            if prev is not None:
                dup_dropped += 1
                if prev != ln:
                    dup_conflicts += 1
            rows[key] = ln
    complete = output_is_complete(tasks)
    missing = sum(1 for t in tasks if t.status not in COMPLETE_OK)
    h = dict(header, rows=len(rows), status="COMPLETE" if complete else "INCOMPLETE")
    if not complete:
        h["missing"] = missing
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    with open(dest, "wb") as f:
        def emit(text: str) -> None:
            b = text.encode("utf-8") + b"\n"
            sha.update(b)
            f.write(b)
        emit(format_header(h))
        for key in sorted(rows):
            emit(redactor.apply(rows[key]))
        f.flush()
        os.fsync(f.fileno())
    return AssemblyResult(output=output, path=dest, rows=len(rows), dup_dropped=dup_dropped,
                          dup_conflicts=dup_conflicts, complete=complete, sha256=sha.hexdigest())


def verify_strictly_increasing(path: Path) -> tuple[bool, int]:
    """(ok, n_filas): OIDs estrictamente crecientes; ignora líneas sin `` = ``."""
    prev: Oid | None = None
    n = 0
    with open(path, "r", encoding="utf-8", newline="") as f:
        for ln in f:
            ln = ln.rstrip("\r\n")
            if " = " not in ln:
                continue
            key = line_key(ln)
            if prev is not None and key <= prev:
                return False, n
            prev = key
            n += 1
    return True, n


def iter_walk_lines(path: Path) -> Iterator[str]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        for ln in f:
            yield ln.rstrip("\r\n")


def roots_of(roots: Iterable[Oid]) -> list[str]:
    return [fmt_oid(r) for r in roots]
