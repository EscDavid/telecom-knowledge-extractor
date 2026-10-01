"""Manejo de secretos: la community SNMP jamás debe llegar a logs, estado,
reportes ni mensajes de error. ``Secret`` la envuelve y ``Scrubber`` es la red de
seguridad (filtro de logging + ``scrub()`` para textos de excepciones)."""
from __future__ import annotations

import logging
from typing import Iterable

MASK = "***"


class Secret:
    """Contenedor opaco. El único acceso al valor es ``reveal()``."""
    __slots__ = ("_v",)

    def __init__(self, value: str):
        self._v = value

    def reveal(self) -> str:
        return self._v

    def __bool__(self) -> bool:
        return bool(self._v)

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:  # pragma: no cover - trivial
        return isinstance(other, Secret) and other._v == self._v

    def __hash__(self) -> int:  # pragma: no cover - trivial
        return hash(("Secret", self._v))

    def __reduce__(self):  # evita que pickle/copy filtren el valor por accidente
        raise TypeError("Secret no es serializable")


class Scrubber(logging.Filter):
    """Reemplaza cualquier ocurrencia de los secretos por ``***``."""

    def __init__(self, secrets: Iterable[Secret | str] = ()):
        super().__init__()
        self._values: list[str] = []
        for s in secrets:
            self.add(s)

    def add(self, secret: Secret | str) -> None:
        v = secret.reveal() if isinstance(secret, Secret) else secret
        if v and v not in self._values:
            self._values.append(v)
            # los más largos primero: evita dejar restos si uno contiene a otro
            self._values.sort(key=len, reverse=True)

    def scrub(self, text: str) -> str:
        for v in self._values:
            if v in text:
                text = text.replace(v, MASK)
        return text

    def _scrub_obj(self, obj):
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, (Secret,)):
            return MASK
        if isinstance(obj, (bytes, bytearray)):
            try:
                return self.scrub(bytes(obj).decode("utf-8", "replace"))
            except Exception:  # pragma: no cover
                return MASK
        if isinstance(obj, BaseException):
            return self.scrub(str(obj))
        return obj

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = self.scrub(record.getMessage())
            record.args = None
        except Exception:
            record.msg = self._scrub_obj(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(self._scrub_obj(a) for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: self._scrub_obj(a) for k, a in record.args.items()}
        if record.exc_info and not record.exc_text:
            # materializa el traceback ya limpio; así ningún handler lo re-formatea con el valor
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.scrub(record.exc_text)
        if record.stack_info:
            record.stack_info = self.scrub(record.stack_info)
        return True


def install_scrubber(scrubber: Scrubber) -> None:
    """Añade el filtro a TODOS los handlers del root logger (y al root mismo)."""
    root = logging.getLogger()
    if scrubber not in root.filters:
        root.addFilter(scrubber)
    for h in root.handlers:
        if scrubber not in h.filters:
            h.addFilter(scrubber)
