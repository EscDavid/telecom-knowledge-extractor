"""Contrato de transporte SNMP del recolector — SOLO LECTURA.

La interfaz expone únicamente ``get``, ``get_next`` y ``get_bulk``; no existe
ningún método de escritura a propósito. Las excepciones llevan mensajes ya
pasados por el ``Scrubber`` para que la community nunca aparezca en ellos.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .oid import Oid
from .secrets import Scrubber

# Tipos de valor normalizados (independientes de la librería concreta).
KINDS = ("INTEGER", "OCTETS", "OID", "IPADDR", "COUNTER32", "GAUGE32", "COUNTER64",
         "TIMETICKS", "OPAQUE", "BITS", "NULL",
         "END_OF_MIB", "NO_SUCH_OBJECT", "NO_SUCH_INSTANCE")
EXCEPTION_KINDS = ("END_OF_MIB", "NO_SUCH_OBJECT", "NO_SUCH_INSTANCE")


@dataclass(frozen=True)
class Varbind:
    oid: Oid
    kind: str
    value: Any = None   # int | bytes | Oid | str (IPADDR) según ``kind``


class TransportError(Exception):
    """Base de errores de transporte. El mensaje SIEMPRE pasa por ``scrub()``."""
    kind = "error"

    def __init__(self, message: str = "", scrubber: Scrubber | None = None):
        if scrubber is not None:
            message = scrubber.scrub(message)
        super().__init__(message)


class TransportTimeout(TransportError):
    kind = "timeout"


class TransportTooBig(TransportError):
    kind = "too_big"


class TransportAgentError(TransportError):
    """El agente respondió con error-status distinto de tooBig (genErr, etc.)."""
    kind = "agent_error"

    def __init__(self, message: str = "", status: str = "genErr",
                 scrubber: Scrubber | None = None):
        super().__init__(message, scrubber)
        self.status = status


class TransportAuthError(TransportError):
    kind = "auth"


class TransportFatal(TransportError):
    """Error irrecuperable de socket/DNS/librería."""
    kind = "fatal"


class SnmpTransport(ABC):
    """Una sola petición en vuelo. Sin escritura: la recolección es de solo lectura."""

    last_latency_ms: float = 0.0

    @abstractmethod
    def get(self, oids: list[Oid]) -> list[Varbind]: ...

    @abstractmethod
    def get_next(self, oid: Oid) -> Varbind: ...

    @abstractmethod
    def get_bulk(self, start: Oid, max_repetitions: int) -> list[Varbind]: ...

    def close(self) -> None:
        return None
