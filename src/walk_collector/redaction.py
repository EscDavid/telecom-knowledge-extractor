"""Redacción opcional de PII al ensamblar (los fragmentos crudos NO se tocan).

Con ``mode=prefixes`` los valores STRING / Hex-STRING bajo los prefijos indicados
(nombres, descripciones y seriales de ONU) se reemplazan por ``REDACTED-<hmac8>``:
estable con la misma sal (permite cruzar sin exponer el dato), irreversible sin ella.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Iterable

from .oid import Oid, in_subtree, line_key

_STRING = 'STRING: "'
_HEX = "Hex-STRING: "


class Redactor:
    def __init__(self, mode: str = "none", prefixes: Iterable[Oid] = (), salt: bytes = b""):
        if mode not in ("none", "prefixes"):
            raise ValueError("redaction.mode debe ser 'none' o 'prefixes'")
        self.mode = mode
        self.prefixes = tuple(prefixes)
        self.salt = salt
        self.redacted = 0

    @property
    def active(self) -> bool:
        return self.mode == "prefixes" and bool(self.prefixes)

    def _tag(self, value: str) -> str:
        return hmac.new(self.salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]

    def apply(self, line: str) -> str:
        if not self.active:
            return line
        head, sep, value = line.partition(" = ")
        if not sep or not (value.startswith(_STRING) or value.startswith(_HEX)):
            return line
        try:
            key = line_key(line)
        except ValueError:
            return line
        if not any(in_subtree(key, p) for p in self.prefixes):
            return line
        self.redacted += 1
        return f'{head} = STRING: "REDACTED-{self._tag(value)}"'


def load_or_create_salt(path: Path) -> bytes:
    """Sal persistente en el directorio de estado (``redaction.salt``)."""
    path = Path(path)
    if path.exists():
        return bytes.fromhex(path.read_text(encoding="utf-8").strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    path.write_text(salt.hex(), encoding="utf-8")
    return salt
