"""Agente SNMPv2c mínimo sobre UDP en 127.0.0.1 — SOLO para tests.

Sustituye a snmpsim (no instalable en Windows sin rutas largas habilitadas). Sirve
GET / GETNEXT / GETBULK desde un dict {oid_tuple: valor pysnmp} y descarta en
silencio las peticiones con otra community (igual que un agente v2c real).
"""
from __future__ import annotations

import socket
import threading

from pyasn1.codec.ber import decoder, encoder
from pysnmp.proto import rfc1902, rfc1905
from pysnmp.proto.api import v2c


class UdpAgent:
    def __init__(self, tree: dict, community: str = "public"):
        self.keys = sorted(tree)
        self.tree = tree
        self.community = community
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=2)
        self.sock.close()

    def _next(self, oid):
        for k in self.keys:
            if k > oid:
                return k
        return None

    def _run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                msg, _ = decoder.decode(data, asn1Spec=v2c.Message())
                if str(v2c.apiMessage.get_community(msg)) != self.community:
                    continue
                req = v2c.apiMessage.get_pdu(msg)
                rsp_msg = v2c.apiMessage.get_response(msg)
                rsp = v2c.apiMessage.get_pdu(rsp_msg)
                v2c.apiPDU.set_request_id(rsp, v2c.apiPDU.get_request_id(req))
                oids = [tuple(int(a) for a in vb[0]) for vb in v2c.apiPDU.get_varbinds(req)]
                out = []
                if req.isSameTypeWith(rfc1905.GetRequestPDU()):
                    for o in oids:
                        out.append((o, self.tree.get(o, rfc1905.NoSuchInstance(""))))
                elif req.isSameTypeWith(rfc1905.GetNextRequestPDU()):
                    for o in oids:
                        n = self._next(o)
                        out.append((n, self.tree[n]) if n else (o, rfc1905.EndOfMibView("")))
                else:  # GETBULK (non-repeaters=0 en el recolector)
                    reps = int(req[2])
                    cur = oids[0]
                    for _ in range(reps):
                        n = self._next(cur)
                        if n is None:
                            out.append((cur, rfc1905.EndOfMibView("")))
                            break
                        out.append((n, self.tree[n]))
                        cur = n
                v2c.apiPDU.set_varbinds(rsp, out)
                self.sock.sendto(encoder.encode(rsp_msg), addr)
            except Exception:  # agente de prueba: ante basura, no responde
                continue


def sample_tree(n_ifnames: int = 40) -> dict:
    """Árbol chico con los tipos principales (sysDescr, sysUpTime, ifName, Counter64…)."""
    t = {
        (1, 3, 6, 1, 2, 1, 1, 1, 0): rfc1902.OctetString(b"ZXA10 C620 test"),
        (1, 3, 6, 1, 2, 1, 1, 2, 0): rfc1902.ObjectIdentifier((1, 3, 6, 1, 4, 1, 3902, 1082)),
        (1, 3, 6, 1, 2, 1, 1, 3, 0): rfc1902.TimeTicks(3179),
    }
    for i in range(1, n_ifnames + 1):
        t[(1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 1, i)] = rfc1902.OctetString(f"gpon_olt-1/1/{i}".encode())
        t[(1, 3, 6, 1, 2, 1, 2, 2, 1, 1, i)] = rfc1902.Integer32(i)
        t[(1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 6, i)] = rfc1902.Counter64(2 ** 40 + i)
        t[(1, 3, 6, 1, 2, 1, 2, 2, 1, 5, i)] = rfc1902.Gauge32(1000000000)
        t[(1, 3, 6, 1, 2, 1, 4, 20, 1, 1, i)] = rfc1902.IpAddress(f"10.0.0.{i}")
    return t
