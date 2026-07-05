"""Fase 2 — enricher: cruza el walk contra el catálogo teórico y lo especializa.

Trabaja a nivel de dicts JSON (los mismos que escribe el CatalogWriter), no sobre
los modelos, para mantener la fase desacoplada de la Fase 1.

Reglas clave:
  - Matching por PREFIJO con bisect: las líneas del walk son instancias
    (`base_oid + índice`); un OID base se confirma si el walk contiene `base` o
    algo que empiece por `base + "."`.
  - STATUS_MATRIX (en_mib, en_walk, conflicto) → status.
  - Confirmado → verified (+0.15 de confianza, bloque `empirical`).
  - No confirmado read-only → PODADO del catálogo C300 (registro en findings).
    writable/read-create/not-accessible/notify → se conservan (un GET-walk no los
    lista aunque existan).
"""
from __future__ import annotations

from bisect import bisect_left
from typing import Any, Optional

from ..ids import snake
from . import triggers as T
from .triggers import Findings

# (en_mib, en_walk, conflicto) → status
STATUS_MATRIX = {
    (True, True, False): "verified",
    (True, False, False): "documented",
    (False, True, False): "observed",
    (True, True, True): "conflicted",
    (True, False, True): "documented",
    (False, False, False): "inferred",
}

# accesos que NO se podan aunque no respondan (config/acción/estructura/notify)
_KEEP_IF_UNCONFIRMED = {"read-write", "read-create", "write-only",
                        "not-accessible", "accessible-for-notify"}

_CONFIRM_BUMP = 0.15


class Enricher:
    def __init__(self, walk_oids: dict[str, dict], sorted_walk: list[str],
                 findings: Findings, source_name: str, *,
                 prune_unconfirmed_readonly: bool = True):
        self.walk = walk_oids
        self.sorted_walk = sorted_walk
        self.findings = findings
        self.source_name = source_name
        self.prune_ro = prune_unconfirmed_readonly
        # instancias fuera de orden → sus bases quedan conflicted
        self.conflicted_instances = set()
        for f in findings.by_trigger("oid_not_increasing"):
            for k in ("oid_actual", "oid_anterior"):
                if f.get(k):
                    self.conflicted_instances.add(f[k].lstrip("."))

    # --- matching por prefijo -------------------------------------------------
    def _confirm(self, base: str) -> tuple[bool, Optional[str], int]:
        """(confirmado, oid_instancia_muestra, nº_instancias) para un OID base."""
        b = base.lstrip(".")
        i = bisect_left(self.sorted_walk, b)
        sample = None
        if i < len(self.sorted_walk):
            cand = self.sorted_walk[i]
            if cand == b or cand.startswith(b + "."):
                sample = cand
        if sample is None:
            # buscar la primera instancia bajo b + "."
            j = bisect_left(self.sorted_walk, b + ".")
            if j < len(self.sorted_walk) and self.sorted_walk[j].startswith(b + "."):
                sample = self.sorted_walk[j]
        if sample is None:
            return False, None, 0
        lo = bisect_left(self.sorted_walk, b + ".")
        hi = bisect_left(self.sorted_walk, b + "/")   # "/" (0x2F) va justo tras "." (0x2E)
        count = max(hi - lo, 1)
        return True, sample, count

    def _is_conflicted(self, base: str) -> bool:
        b = base.lstrip(".")
        return any(ci.startswith(b + ".") or ci == b for ci in self.conflicted_instances)

    # --- enriquecimiento de un OID -------------------------------------------
    def enrich_oid(self, oid: dict) -> Optional[dict]:
        """Devuelve el OID enriquecido, o None si debe podarse del catálogo C300."""
        base = oid.get("oid") or ""
        access = oid.get("access") or "read-only"
        confirmed, sample, count = self._confirm(base)
        conflicted = confirmed and self._is_conflicted(base)
        status = STATUS_MATRIX.get((True, confirmed, conflicted), "documented")

        if not confirmed:
            prune = self.prune_ro and access not in _KEEP_IF_UNCONFIRMED
            T.trigger_documented_only(self.findings, oid.get("id", ""), base, access, prune)
            if prune:
                return None
            oid["status"] = "documented"
            return oid

        # confirmado empíricamente
        sample_value = self.walk.get(sample, {}).get("value")
        oid["status"] = status
        conf = oid.setdefault("confidence", {})
        if status == "verified":
            conf["overall"] = round(min(1.0, (conf.get("overall") or 0.0) + _CONFIRM_BUMP), 3)
        # detección de escala sobre el valor real
        scale = self._maybe_scale(oid, base, sample_value)
        oid["empirical"] = {
            "source": self.source_name,
            "sample_oid": sample,
            "sample_value": sample_value,
            "instances_sampled": count,
            "scale_confirmed": scale,
        }
        return oid

    def _maybe_scale(self, oid: dict, base: str, sample_value) -> Optional[float]:
        try:
            v = int(str(sample_value).strip())
        except (TypeError, ValueError):
            return None
        # normaliza el nombre MIB (zxAnGponOntOpticalRxPower → ..._rx_power) para
        # que las SCALE_HINTS (rx_power, tx_power, ...) lo reconozcan.
        metric_name = snake(oid.get("name", "")) + " " + (oid.get("id", "") or "")
        scale = T.trigger_scale_detection(self.findings, base, metric_name, v)
        if scale is not None:
            oid["scale"] = scale
        return scale

    # --- grupos + observed-only ----------------------------------------------
    def enrich_groups(self, groups: list[dict], family: str) -> list[dict]:
        out = []
        for g in groups:
            g = dict(g)
            g["family"] = family
            kept = [self.enrich_oid(dict(o)) for o in g.get("oids", [])]
            g["oids"] = [o for o in kept if o is not None]
            if g["oids"]:
                out.append(g)
        return out

    def detect_observed_only(self, base_oids: list[str], top: int = 30) -> None:
        """Ramas presentes en el walk sin cobertura en el catálogo → findings por tabla."""
        bases = sorted(o.lstrip(".") for o in base_oids)
        by_table: dict[str, list[str]] = {}
        for w in self.sorted_walk:
            j = bisect_left(bases, w)
            covered = False
            for cand in (bases[j - 1] if j > 0 else None, bases[j] if j < len(bases) else None):
                if cand and (w == cand or w.startswith(cand + ".")):
                    covered = True
                    break
            if not covered:
                by_table.setdefault(T.extract_table_prefix(w), []).append(w)
        for tabla, oids in sorted(by_table.items(), key=lambda kv: -len(kv[1]))[:top]:
            s = oids[0]
            T.trigger_observed_only(self.findings, tabla, len(oids), s,
                                    self.walk.get(s, {}).get("value", ""))
