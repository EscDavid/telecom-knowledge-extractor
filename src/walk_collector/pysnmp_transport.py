"""Transporte real sobre pysnmp (lextudio 7.1.x) — SNMPv2c, SOLO LECTURA.

pysnmp se importa de forma perezosa: el resto del módulo (y los tests) funcionan
sin él. Se usa la API ``v1arch.asyncio`` con un event loop propio y síncrono hacia
afuera: exactamente una petición en vuelo, sin threads. ``retries=0`` en el
transporte (los reintentos los controla el recolector). El logging/debug de pysnmp
se mantiene apagado: el modo debug puede volcar la community.
"""
from __future__ import annotations

import asyncio
import logging
import time

from .oid import Oid, fmt_oid
from .secrets import Scrubber, Secret
from .transport import (SnmpTransport, TransportAgentError, TransportAuthError,
                        TransportFatal, TransportTimeout, TransportTooBig, Varbind)


class PysnmpTransport(SnmpTransport):
    def __init__(self, host: str, port: int, community: Secret, timeout_s: float,
                 scrubber: Scrubber):
        try:
            from pysnmp.hlapi.v1arch.asyncio import (CommunityData, ObjectIdentity,
                                                     ObjectType, SnmpDispatcher,
                                                     UdpTransportTarget, bulk_cmd,
                                                     get_cmd, next_cmd)
        except ImportError as exc:
            raise TransportFatal("pysnmp no está instalado (pip install -r requirements.txt)",
                                 scrubber) from exc
        self._api = dict(ObjectIdentity=ObjectIdentity, ObjectType=ObjectType,
                         bulk_cmd=bulk_cmd, get_cmd=get_cmd, next_cmd=next_cmd)
        self._UdpTransportTarget = UdpTransportTarget
        self._host, self._port = host, port
        self._timeout = timeout_s
        self._scrubber = scrubber
        self._auth = CommunityData(community.reveal(), mpModel=1)   # mpModel=1 → v2c
        self._loop = asyncio.new_event_loop()
        self._dispatcher = None
        self._SnmpDispatcher = SnmpDispatcher
        self._target = None
        self._busy = False
        self.last_latency_ms = 0.0
        # Apaga el log/debug de pysnmp (el debug puede volcar la community).
        for name in ("pysnmp", "pyasn1", "pysmi"):
            logging.getLogger(name).setLevel(logging.WARNING)

    # --- infraestructura ---------------------------------------------------
    def _run(self, coro_factory):
        if self._busy:
            raise TransportFatal("petición SNMP reentrante: una sola petición en vuelo",
                                 self._scrubber)
        self._busy = True
        t0 = time.monotonic()
        try:
            return self._loop.run_until_complete(coro_factory())
        except (TransportTimeout, TransportTooBig, TransportAgentError,
                TransportAuthError, TransportFatal):
            raise
        except OSError as exc:
            raise TransportFatal(f"error de socket: {exc}", self._scrubber) from None
        finally:
            self.last_latency_ms = (time.monotonic() - t0) * 1000.0
            self._busy = False

    async def _ctx(self):
        if self._dispatcher is None:
            self._dispatcher = self._SnmpDispatcher()
        if self._target is None:
            self._target = await self._UdpTransportTarget.create(
                (self._host, self._port), timeout=self._timeout, retries=0)
        return self._dispatcher, self._target

    def _ot(self, oid: Oid):
        return self._api["ObjectType"](self._api["ObjectIdentity"](fmt_oid(oid).lstrip(".")))

    def _check(self, err_ind, err_status, err_index):
        if err_ind:
            text = str(err_ind)
            low = text.lower()
            if "timeout" in low or "no snmp response" in low:
                raise TransportTimeout(text, self._scrubber)
            if "authentication" in low:
                raise TransportAuthError(text, self._scrubber)
            raise TransportFatal(text, self._scrubber)
        if err_status:
            status = (err_status.prettyPrint() if hasattr(err_status, "prettyPrint")
                      else str(err_status))
            if status == "tooBig":
                raise TransportTooBig(status, self._scrubber)
            if status in ("authorizationError", "noAccess"):
                raise TransportAuthError(status, self._scrubber)
            raise TransportAgentError(status, status, self._scrubber)

    # --- API pública (solo lectura) ------------------------------------------
    def get(self, oids: list[Oid]) -> list[Varbind]:
        async def go():
            disp, tgt = await self._ctx()
            res = await self._api["get_cmd"](disp, self._auth, tgt,
                                             *[self._ot(o) for o in oids])
            self._check(*res[:3])
            return [convert(vb) for vb in res[3]]
        return self._run(go)

    def get_next(self, oid: Oid) -> Varbind:
        async def go():
            disp, tgt = await self._ctx()
            res = await self._api["next_cmd"](disp, self._auth, tgt, self._ot(oid))
            self._check(*res[:3])
            vbs = [convert(vb) for vb in res[3]]
            if not vbs:
                raise TransportAgentError("respuesta vacía", "genErr", self._scrubber)
            return vbs[0]
        return self._run(go)

    def get_bulk(self, start: Oid, max_repetitions: int) -> list[Varbind]:
        async def go():
            disp, tgt = await self._ctx()
            res = await self._api["bulk_cmd"](disp, self._auth, tgt, 0,
                                              max_repetitions, self._ot(start))
            self._check(*res[:3])
            return [convert(vb) for vb in res[3]]
        return self._run(go)

    def close(self) -> None:
        try:
            if self._dispatcher is not None:
                self._dispatcher.transport_dispatcher.close_dispatcher()
        except Exception:
            pass
        try:
            # cancela tareas residuales de pysnmp (handle_timeout) antes de cerrar el loop
            pend = asyncio.all_tasks(self._loop)
            for t in pend:
                t.cancel()
            if pend:
                self._loop.run_until_complete(asyncio.gather(*pend, return_exceptions=True))
            self._loop.close()
        except Exception:
            pass


def convert(vb) -> Varbind:
    """ObjectType de pysnmp → ``Varbind`` normalizado."""
    from pyasn1.type import univ
    from pysnmp.proto import rfc1902, rfc1905
    name =tuple(int(a) for a in vb[0])
    val = vb[1]
    if isinstance(val, rfc1905.EndOfMibView):
        return Varbind(name, "END_OF_MIB")
    if isinstance(val, rfc1905.NoSuchObject):
        return Varbind(name, "NO_SUCH_OBJECT")
    if isinstance(val, rfc1905.NoSuchInstance):
        return Varbind(name, "NO_SUCH_INSTANCE")
    # el orden importa: Counter32/Gauge32/TimeTicks heredan de Unsigned32/Integer32
    if isinstance(val, rfc1902.Counter64):
        return Varbind(name, "COUNTER64", int(val))
    if isinstance(val, rfc1902.Counter32):
        return Varbind(name, "COUNTER32", int(val))
    if isinstance(val, rfc1902.TimeTicks):
        return Varbind(name, "TIMETICKS", int(val))
    if isinstance(val, (rfc1902.Gauge32, rfc1902.Unsigned32)):
        return Varbind(name, "GAUGE32", int(val))
    if isinstance(val, rfc1902.Integer32):
        return Varbind(name, "INTEGER", int(val))
    if isinstance(val, rfc1902.IpAddress):
        return Varbind(name, "IPADDR", val.prettyPrint())
    if isinstance(val, rfc1902.Opaque):
        return Varbind(name, "OPAQUE", bytes(val))
    if isinstance(val, rfc1902.Bits):
        return Varbind(name, "BITS", bytes(val))
    if isinstance(val, rfc1902.OctetString):
        return Varbind(name, "OCTETS", bytes(val))
    if isinstance(val, (rfc1902.ObjectIdentifier, univ.ObjectIdentifier)):
        return Varbind(name, "OID", tuple(int(a) for a in val))
    # v1arch puede devolver tipos base de pyasn1 sin envolver
    if isinstance(val, univ.Integer):
        return Varbind(name, "INTEGER", int(val))
    return Varbind(name, "NULL")
