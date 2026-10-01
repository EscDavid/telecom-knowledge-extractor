"""Utilidades de OIDs numéricos — el orden y la pertenencia se calculan por ARCOS,
nunca por texto (``1.7`` no está en ``1.70`` y ``1012.3.3`` precede a ``1012.3.28``)."""
from __future__ import annotations

Oid = tuple[int, ...]


def parse_oid(s: str) -> Oid:
    """``".1.3.6"`` / ``"1.3.6"`` → ``(1, 3, 6)``. ValueError si no es numérico."""
    txt = s.strip().lstrip(".")
    if not txt:
        raise ValueError("OID vacío")
    try:
        arcs = tuple(int(p) for p in txt.split("."))
    except ValueError:
        raise ValueError(f"OID no numérico: {s!r}") from None
    if any(a < 0 for a in arcs):
        raise ValueError(f"OID con arcos negativos: {s!r}")
    return arcs


def fmt_oid(o: Oid) -> str:
    """``(1, 3, 6)`` → ``".1.3.6"`` (con punto inicial, como ``snmpwalk -On``)."""
    return "." + ".".join(str(a) for a in o)


def in_subtree(o: Oid, root: Oid) -> bool:
    """¿``o`` es ``root`` o cuelga de él? Comparación por arcos."""
    return len(o) >= len(root) and o[: len(root)] == root


def next_sibling(o: Oid) -> Oid:
    """``(..., n)`` → ``(..., n+1)``: primer OID posterior a todo el subárbol de ``o``."""
    if not o:
        raise ValueError("OID vacío")
    return o[:-1] + (o[-1] + 1,)


def skip_level(o: Oid, level: int) -> Oid:
    """Salto hacia adelante: ``level=0`` → hermano de ``o``; ``1`` → hermano del padre…

    Se usa para escapar de un OID que no avanza (gap registrado por el walker).
    """
    if level < 0:
        raise ValueError("level debe ser >= 0")
    cut = len(o) - level
    if cut < 1:
        cut = 1
    return next_sibling(o[:cut])


def line_key(line: str) -> Oid:
    """Clave numérica de una línea de fragmento (``".1.3.6 = INTEGER: 1"``)."""
    head = line.split(" = ", 1)[0]
    return parse_oid(head)
