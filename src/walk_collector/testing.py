"""Dobles de prueba: agente SNMP simulado, transporte falso y reloj virtual.

Permiten probar TODO el recolector sin red y sin dormir de verdad. También los usa
``--simulate`` (nunca toca la red). Ningún doble implementa escritura SNMP.
"""
from __future__ import annotations

import bisect
import random
from dataclasses import dataclass
from typing import Iterable

from .oid import Oid, in_subtree
from .transport import (SnmpTransport, TransportAgentError, TransportAuthError,
                        TransportFatal, TransportTimeout, TransportTooBig,
                        Varbind)


class FakeClock:
    """Reloj virtual: ``sleep`` avanza el tiempo sin esperar y deja registro."""

    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        if s > 0:
            self.sleeps.append(s)
            self.now += s

    def advance(self, s: float) -> None:
        """Avanza el tiempo sin registrarlo como sleep (tiempo consumido por el equipo/red)."""
        self.now += s


class FakeAgent:
    """Árbol MIB ordenado con semántica correcta de GET / GETNEXT / GETBULK."""

    def __init__(self, tree: dict[Oid, tuple[str, object]]):
        self.tree = dict(tree)
        self.keys = sorted(self.tree)

    def _vb(self, oid: Oid) -> Varbind:
        kind, value = self.tree[oid]
        return Varbind(oid, kind, value)

    def get(self, oids: Iterable[Oid]) -> list[Varbind]:
        return [self._vb(o) if o in self.tree else Varbind(o, "NO_SUCH_INSTANCE") for o in oids]

    def next_key(self, oid: Oid) -> Oid | None:
        i = bisect.bisect_right(self.keys, oid)
        return self.keys[i] if i < len(self.keys) else None

    def get_next(self, oid: Oid) -> Varbind:
        k = self.next_key(oid)
        return self._vb(k) if k is not None else Varbind(oid, "END_OF_MIB")

    def get_bulk(self, start: Oid, max_repetitions: int) -> list[Varbind]:
        out: list[Varbind] = []
        cur = start
        for _ in range(max_repetitions):
            k = self.next_key(cur)
            if k is None:
                out.append(Varbind(cur, "END_OF_MIB"))
                break
            out.append(self._vb(k))
            cur = k
        return out

    def floor_key(self, oid: Oid) -> Oid | None:
        """Mayor OID existente <= ``oid`` (para simular agentes defectuosos)."""
        i = bisect.bisect_right(self.keys, oid)
        return self.keys[i - 1] if i else None


@dataclass
class FaultRule:
    """Falla inyectada. Se activa cuando coinciden TODOS los filtros dados.

    kind: timeout | toobig | generr | auth | fatal | nonincreasing | dead | latency | interrupt
    Filtros: ``at`` (índices 1-based de petición), ``after`` (desde el índice, incl.),
    ``until`` (hasta el índice, incl.), ``prefix`` (el OID de partida cuelga de él),
    ``contains`` (la respuesta contendría exactamente ese OID), ``ops``, ``above``
    (solo si max_repetitions > above), ``times`` (máximo de disparos).
    """
    kind: str
    at: tuple[int, ...] | None = None
    after: int | None = None
    until: int | None = None
    prefix: Oid | None = None
    contains: Oid | None = None
    ops: tuple[str, ...] = ("get", "get_next", "get_bulk")
    above: int = 0
    times: int | None = None
    seconds: float = 0.0     # dead: duración según el reloj
    ms: float = 0.0          # latency
    message: str = ""        # timeout: texto del error (para probar el scrubbing)
    skip: int = 0            # ignora las primeras N peticiones que cumplen los filtros
    matched: int = 0
    fired: int = 0


class FakeTransport(SnmpTransport):
    def __init__(self, agent: FakeAgent, faults: Iterable[FaultRule] = (),
                 clock: FakeClock | None = None, timeout_s: float = 3.0,
                 base_latency_ms: float = 30.0):
        self.agent = agent
        self.faults = list(faults)
        self.clock = clock
        self.timeout_s = timeout_s
        self.base_latency_ms = base_latency_ms
        self.requests: list[tuple[str, object, int]] = []   # (op, start|oids, max_rep)
        self.max_inflight_seen = 0
        self._inflight = 0
        self._dead_until = 0.0
        self.last_latency_ms = 0.0
        self.closed = False

    # --- utilidades de test --------------------------------------------------
    @property
    def bulk_requests(self) -> list[tuple[str, object, int]]:
        return [r for r in self.requests if r[0] == "get_bulk"]

    def _now(self) -> float:
        return self.clock.monotonic() if self.clock else 0.0

    def _advance(self, seconds: float) -> None:
        if self.clock:
            self.clock.advance(seconds)

    # --- motor de fallas -----------------------------------------------------
    def _matches(self, r: FaultRule, idx: int, op: str, start: Oid | None, max_rep: int,
                 resp: list[Varbind] | None) -> bool:
        if op not in r.ops:
            return False
        if r.times is not None and r.fired >= r.times:
            return False
        if r.at is not None and idx not in r.at:
            return False
        if r.after is not None and idx < r.after:
            return False
        if r.until is not None and idx > r.until:
            return False
        if r.prefix is not None and (start is None or not in_subtree(start, r.prefix)):
            return False
        if r.contains is not None:
            lst = resp if isinstance(resp, list) else ([resp] if resp is not None else [])
            if all(v.oid != r.contains for v in lst):
                return False
        if op == "get_bulk" and r.above and max_rep <= r.above:
            return False
        r.matched += 1
        return r.matched > r.skip

    def _dispatch(self, op: str, start: Oid | None, max_rep: int, compute) -> object:
        self.requests.append((op, start, max_rep))
        idx = len(self.requests)
        self._inflight += 1
        self.max_inflight_seen = max(self.max_inflight_seen, self._inflight)
        try:
            # ¿el equipo está "caído"?
            if self._dead_until and self._now() < self._dead_until:
                self._advance(self.timeout_s)
                raise TransportTimeout("sin respuesta (equipo caído)")
            resp = compute()
            latency = self.base_latency_ms
            for r in self.faults:
                if not self._matches(r, idx, op, start, max_rep, resp):
                    continue
                r.fired += 1
                if r.kind == "interrupt":
                    raise KeyboardInterrupt()
                if r.kind == "timeout":
                    self._advance(self.timeout_s)
                    raise TransportTimeout(r.message or "sin respuesta")
                if r.kind == "toobig":
                    raise TransportTooBig("tooBig")
                if r.kind == "generr":
                    raise TransportAgentError("genErr", "genErr")
                if r.kind == "auth":
                    raise TransportAuthError("autenticación")
                if r.kind == "fatal":
                    raise TransportFatal("socket cerrado")
                if r.kind == "dead":
                    self._dead_until = self._now() + r.seconds
                    self._advance(self.timeout_s)
                    raise TransportTimeout("sin respuesta (equipo caído)")
                if r.kind == "latency":
                    latency = r.ms
                elif r.kind == "nonincreasing":
                    resp = self._nonincreasing(op, start)
            self.last_latency_ms = latency
            self._advance(latency / 1000.0)
            return resp
        finally:
            self._inflight -= 1

    def _nonincreasing(self, op: str, start: Oid | None):
        """Agente defectuoso: responde un OID <= al pedido (nunca avanza)."""
        k = self.agent.floor_key(start) if start else None
        if k is None:
            k = self.agent.keys[0]
        vb = self.agent._vb(k)
        return vb if op == "get_next" else [vb]

    # --- API SnmpTransport -----------------------------------------------------
    def get(self, oids: list[Oid]) -> list[Varbind]:
        return self._dispatch("get", oids[0] if oids else None, 0,
                              lambda: self.agent.get(oids))

    def get_next(self, oid: Oid) -> Varbind:
        return self._dispatch("get_next", oid, 0, lambda: self.agent.get_next(oid))

    def get_bulk(self, start: Oid, max_repetitions: int) -> list[Varbind]:
        return self._dispatch("get_bulk", start, max_repetitions,
                              lambda: self.agent.get_bulk(start, max_repetitions))

    def close(self) -> None:
        self.closed = True


# --- árbol de prueba -----------------------------------------------------------
def _o(s: str) -> Oid:
    return tuple(int(x) for x in s.strip(".").split("."))


def make_tree(seed: int = 7, scale: float = 1.0) -> dict[Oid, tuple[str, object]]:
    """~2000 filas con la forma de una OLT: ramas enterprise 3902.*, entPhysicalTable,
    ifTable e ifName con índices compuestos grandes (tipo 268501248)."""
    rng = random.Random(seed)
    t: dict[Oid, tuple[str, object]] = {}

    def put(oid: str, kind: str, value: object) -> None:
        t[_o(oid)] = (kind, value)

    def rand_text(n: int) -> bytes:
        return bytes(rng.choice(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/.") for _ in range(n))

    # system
    put("1.3.6.1.2.1.1.1.0", "OCTETS", b"ZXA10 C620 V2.0.1 Software, test agent")
    put("1.3.6.1.2.1.1.2.0", "OID", _o("1.3.6.1.4.1.3902.1082.1001.620"))
    put("1.3.6.1.2.1.1.3.0", "TIMETICKS", 3179)
    put("1.3.6.1.2.1.1.5.0", "OCTETS", b"OLT-TEST")

    # entPhysicalTable (47.1.1.1.1.<col>.<idx>)
    n_ent = int(40 * scale)
    for i in range(1, n_ent + 1):
        cls = 3 if i == 1 else (6 if i % 11 == 0 else (7 if i % 7 == 0 else 9))
        base = "1.3.6.1.2.1.47.1.1.1.1"
        put(f"{base}.2.{i}", "OCTETS", f"ZXA10 C620 component {i}".encode())
        put(f"{base}.5.{i}", "INTEGER", cls)
        put(f"{base}.7.{i}", "OCTETS", f"comp-{i}".encode())
        put(f"{base}.11.{i}", "OCTETS", b"" if i % 5 == 0 else rand_text(12))
        put(f"{base}.13.{i}", "OCTETS", rand_text(6))

    # ifTable / ifName con índices compuestos grandes
    ports = [0x10010000 + (slot << 8) + port for slot in range(1, 5) for port in range(1, int(16 * scale) + 1)]
    for idx in ports:
        slot, port = (idx >> 8) & 0xFF, idx & 0xFF
        put(f"1.3.6.1.2.1.2.2.1.1.{idx}", "INTEGER", idx)
        put(f"1.3.6.1.2.1.2.2.1.2.{idx}", "OCTETS", f"gpon_olt-1/{slot}/{port}".encode())
        put(f"1.3.6.1.2.1.2.2.1.5.{idx}", "GAUGE32", 2488000000)
        put(f"1.3.6.1.2.1.31.1.1.1.1.{idx}", "OCTETS", f"gpon_olt-1/{slot}/{port}".encode())

    # enterprise 3902.1012.3.{3,11,28,50}.*
    def table(prefix: str, cols: int, rows: int, kinds: list[str]) -> None:
        for c in range(1, cols + 1):
            for r in range(1, rows + 1):
                idx = ports[r - 1] if r <= len(ports) else 500000000 + r
                kind = kinds[(c - 1) % len(kinds)]
                oid = f"{prefix}.{c}.{idx}"
                if kind == "INTEGER":
                    put(oid, kind, rng.randint(-3000, 3000))
                elif kind == "OCTETS":
                    put(oid, kind, rand_text(rng.randint(3, 16)))
                elif kind == "BIN":
                    put(oid, "OCTETS", bytes([0x43, 0x44, 0x54, 0x43, 0x1D, 0xDB, 0x9E, rng.randint(0, 255)]))
                elif kind == "TIMETICKS":
                    put(oid, kind, rng.randint(0, 200000000))
                elif kind == "COUNTER64":
                    put(oid, kind, rng.randint(0, 2 ** 40))
                elif kind == "GAUGE32":
                    put(oid, kind, rng.randint(0, 100000))
                elif kind == "IPADDR":
                    put(oid, kind, f"10.0.{rng.randint(0, 255)}.{rng.randint(1, 254)}")
                elif kind == "OID":
                    put(oid, kind, _o("1.3.6.1.4.1.3902.1082.10.1"))

    table("1.3.6.1.4.1.3902.1012.3.3.1", 2, int(10 * scale), ["INTEGER", "OCTETS"])
    table("1.3.6.1.4.1.3902.1012.3.11.1", 4, int(150 * scale), ["INTEGER", "OCTETS", "BIN", "TIMETICKS"])
    table("1.3.6.1.4.1.3902.1012.3.28.1", 3, int(150 * scale), ["COUNTER64", "GAUGE32", "OCTETS"])
    table("1.3.6.1.4.1.3902.1012.3.50.1", 2, int(150 * scale), ["INTEGER", "IPADDR"])
    table("1.3.6.1.4.1.3902.1015.2.1.1", 3, int(100 * scale), ["OCTETS", "INTEGER", "OID"])
    # 3902.1082.10.*: escalares y una tabla con índice pequeño
    for i in range(1, int(40 * scale) + 1):
        put(f"1.3.6.1.4.1.3902.1082.10.1.1.{i}.0", "INTEGER", i - 20)
    table("1.3.6.1.4.1.3902.1082.10.2.1", 2, int(60 * scale), ["OCTETS", "INTEGER"])
    return t


def make_fake_agent(seed: int = 7, scale: float = 1.0) -> FakeAgent:
    return FakeAgent(make_tree(seed, scale))


def ideal_walk_lines(agent: FakeAgent, roots: Iterable[Oid]) -> list[str]:
    """Walk 'ideal' (GETNEXT exhaustivo) de las raíces, en orden numérico: referencia de tests."""
    from .formatter import format_line
    out: list[str] = []
    for root in sorted(roots):
        cur = root
        first = True
        while True:
            if first and root in agent.tree:
                vb = agent._vb(root)
                first = False
                out.append(format_line(vb))
                continue
            first = False
            vb = agent.get_next(cur)
            if vb.kind == "END_OF_MIB" or not in_subtree(vb.oid, root):
                break
            out.append(format_line(vb))
            cur = vb.oid
    return out
