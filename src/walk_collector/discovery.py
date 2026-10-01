"""Descubrimiento de ramas por skip-scan con GETNEXT.

Para partir un árbol enorme (enterprise 3902.*) en tareas manejables sin recorrerlo:
``GETNEXT(nodo)`` devuelve el primer OID; su hijo directo ``c`` se deduce recortando
el OID al arco siguiente; luego ``GETNEXT(next_sibling(c))`` salta TODO el subárbol de
``c``. Cada hijo cuesta un solo GETNEXT.

Limitación conocida: si el hermano ``c+1`` fuera una hoja (instancia) exacta, el
``GETNEXT`` la salta; en las ramas de tablas de la OLT no ocurre (los arcos son ramas).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from .oid import Oid, fmt_oid, in_subtree, next_sibling
from .pacing import Backoff, Clock
from .transport import (EXCEPTION_KINDS, SnmpTransport, TransportAgentError, TransportTimeout)

log = logging.getLogger("tkc.walk_collector.discovery")


@dataclass
class TaskSpec:
    id: str
    output: str
    root: Oid
    root_is_instance: bool = False


def task_id(output: str, root: Oid) -> str:
    """Id determinista y válido como nombre de archivo (sin ``:``)."""
    return f"{output}_{'.'.join(str(a) for a in root)}"


def dedupe_roots(roots: Iterable[Oid]) -> list[Oid]:
    """Quita raíces anidadas (las que cuelgan de otra) y duplicados: subárboles disjuntos."""
    uniq = sorted(set(roots))
    kept: list[Oid] = []
    for r in uniq:
        if not any(in_subtree(r, k) for k in kept):
            kept.append(r)
    return kept


def _children(transport: SnmpTransport, node: Oid, max_children: int, clock: Clock,
              pace_s: float, attempts: int, backoff: Backoff | None
              ) -> list[tuple[Oid, bool]] | None:
    """Hijos directos de ``node`` como (arco_hijo, es_instancia). ``None`` si no se puede
    expandir (agente defectuoso o demasiados hijos)."""
    out: list[tuple[Oid, bool]] = []
    cur = node
    first = True
    while True:
        if not first and pace_s > 0:
            clock.sleep(pace_s)
        first = False
        vb = _get_next(transport, cur, clock, attempts, backoff)
        if vb.kind in EXCEPTION_KINDS or not in_subtree(vb.oid, node):
            return out
        if vb.oid <= cur:
            log.warning("agente no creciente en discovery (%s <= %s): %s queda como una sola tarea",
                        fmt_oid(vb.oid), fmt_oid(cur), fmt_oid(node))
            return None
        child = vb.oid[: len(node) + 1]
        out.append((child, vb.oid == child))
        if len(out) > max_children:
            log.warning("más de %d hijos bajo %s: queda como una sola tarea",
                        max_children, fmt_oid(node))
            return None
        cur = next_sibling(child)


def _get_next(transport, oid, clock, attempts, backoff):
    for n in range(1, attempts + 1):
        try:
            return transport.get_next(oid)
        except (TransportTimeout, TransportAgentError):
            if n >= attempts:
                raise
            if backoff is not None:
                clock.sleep(backoff.delay(n))


def discover(transport: SnmpTransport, output: str, root: Oid, base_depth: int,
             expand: set[Oid], max_children: int, clock: Clock, pace_s: float,
             attempts: int = 3, backoff: Backoff | None = None) -> list[TaskSpec]:
    """Tareas (subárboles disjuntos) de una raíz. Profundidad relativa a ``root``:
    los hijos con profundidad < ``base_depth`` (o listados en ``expand``) se expanden."""
    specs: list[TaskSpec] = []

    def visit(node: Oid) -> None:
        kids = _children(transport, node, max_children, clock, pace_s, attempts, backoff)
        if not kids:                       # None (no expandible) o sin hijos
            specs.append(TaskSpec(task_id(output, node), output, node))
            return
        for child, is_instance in kids:
            depth = len(child) - len(root)
            if is_instance:
                specs.append(TaskSpec(task_id(output, child), output, child, True))
            elif depth < base_depth or child in expand:
                visit(child)
            else:
                specs.append(TaskSpec(task_id(output, child), output, child))

    visit(root)
    # sin duplicados y en orden numérico
    seen: dict[Oid, TaskSpec] = {}
    for s in specs:
        seen.setdefault(s.root, s)
    return [seen[r] for r in sorted(seen)]
