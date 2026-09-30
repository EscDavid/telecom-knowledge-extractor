"""Fragmentos append-only por tarea (``fragments/<task_id>.txt``).

Contrato de consistencia (exactly-once): las líneas se agregan al fragmento; en cada
checkpoint se hace ``commit()`` (flush + fsync) y SOLO después se persiste el estado
con el offset devuelto. Al reanudar, el fragmento se TRUNCA a ``committed_bytes`` y se
descarta cualquier línea posterior al último commit.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


class FragmentCorrupt(Exception):
    """El fragmento es más corto que el offset comprometido (no debería ocurrir)."""


class FragmentWriter:
    def __init__(self, path: Path, committed_bytes: int = 0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            if committed_bytes:
                raise FragmentCorrupt(f"falta el fragmento {self.path.name} "
                                      f"(se esperaban {committed_bytes} bytes)")
            self.path.touch()
        size = self.path.stat().st_size
        if size < committed_bytes:
            raise FragmentCorrupt(f"fragmento {self.path.name} truncado: {size} < {committed_bytes}")
        self._f = open(self.path, "r+b")
        self._f.truncate(committed_bytes)      # descarta basura posterior al último commit
        self._f.seek(committed_bytes)
        self._committed = committed_bytes

    def append(self, lines: Iterable[str]) -> None:
        for ln in lines:
            self._f.write(ln.encode("utf-8") + b"\n")

    def commit(self) -> int:
        """flush + fsync; devuelve el offset comprometido."""
        self._f.flush()
        os.fsync(self._f.fileno())
        self._committed = self._f.tell()
        return self._committed

    @property
    def committed(self) -> int:
        return self._committed

    def close(self) -> None:
        if not self._f.closed:
            try:
                self._f.flush()
            finally:
                self._f.close()


def read_fragment_lines(path: Path, limit: int | None = None) -> list[str]:
    """Líneas de un fragmento (sin salto), leyendo a lo sumo ``limit`` bytes (el offset
    comprometido: lo posterior es basura de un corte). Inexistente -> lista vacía."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "rb") as f:
        data = f.read() if limit is None else f.read(limit)
    return [ln for ln in data.decode("utf-8", errors="replace").split("\n") if ln]
