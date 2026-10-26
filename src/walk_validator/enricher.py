"""Fase 2 — enricher: cruza el walk contra el catálogo teórico y lo especializa.

Trabaja a nivel de dicts JSON (los mismos que escribe el CatalogWriter), no sobre
los modelos, para mantener la fase desacoplada de la Fase 1.

Reglas clave:
  - Matching por PREFIJO con bisect: las líneas del walk son instancias
    (`base_oid + índice`); un OID base se confirma si el walk contiene `base` o
    algo que empiece por `base + "."`.
  - STATUS_MATRIX (en_mib, en_walk, conflicto) → status.
  - Confirmado → verified (+0.15 de confianza, bloque `empirical`).
  - No confirmado read-only → PODADO del catálogo (registro en findings).
    writable/read-create/not-accessible/notify → se conservan (un GET-walk no los
    lista aunque existan).
  - Con `prune_mode: covered_branch` (perfil del vendor) solo se poda dentro de las
    ramas que el walk efectivamente recorrió: un walk parcial por subárbol no debe
    borrar lo que simplemente no se caminó.
"""
from __future__ import annotations

from bisect import bisect_left
from typing import Any, Optional

from ..ids import build_oid_id, snake
from ..profiles import VendorProfile, branch_root
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

# accesos que NO se podan aunque no respondan (config/acción/estructura/notify).
# "unknown" = fuente de nivel B sin MAX-ACCESS real (ej. render de Observium, que
# solo distingue "read-write" de "no lo sé"): un acceso desconocido NUNCA se asume
# read-only, así que tampoco se poda por falta de respuesta (backlog #3 de
# docs/adaptacion_multivendor.md).
_KEEP_IF_UNCONFIRMED = {"read-write", "read-create", "write-only",
                        "not-accessible", "accessible-for-notify", "unknown"}

_CONFIRM_BUMP = 0.15


class Enricher:
    def __init__(self, walk_oids: dict[str, dict], sorted_walk: list[str],
                 findings: Findings, source_name: str, *,
                 prune_unconfirmed_readonly: bool = True,
                 profile: Optional[VendorProfile] = None):
        self.walk = walk_oids
        self.sorted_walk = sorted_walk
        self.findings = findings
        self.source_name = source_name
        self.prune_ro = prune_unconfirmed_readonly
        # ramas recorridas por el walk (None = modo "all": se poda en todo el catálogo)
        self._depth = profile.prune_branch_depth if profile else 2
        self._covered: Optional[set[str]] = None
        if profile and profile.prune_mode == "covered_branch":
            self._covered = {branch_root(w, self._depth) for w in sorted_walk}
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
        """Devuelve el OID enriquecido, o None si debe podarse del catálogo."""
        base = oid.get("oid") or ""
        access = oid.get("access") or "read-only"
        confirmed, sample, count = self._confirm(base)
        conflicted = confirmed and self._is_conflicted(base)
        status = STATUS_MATRIX.get((True, confirmed, conflicted), "documented")

        if not confirmed:
            prune = self.prune_ro and access not in _KEEP_IF_UNCONFIRMED
            not_walked = (prune and self._covered is not None
                          and branch_root(base, self._depth) not in self._covered)
            if not_walked:
                prune = False            # la rama no se caminó: ausencia ≠ no soportado
            T.trigger_documented_only(self.findings, oid.get("id", ""), base, access, prune)
            if not_walked:
                self.findings.items[-1]["branch_not_walked"] = True
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

    def materialize_observed_groups(self, vendor: str, family: str,
                                    technology: str = "gpon") -> list[dict]:
        """Backlog #1 de docs/adaptacion_multivendor.md — modo walk-first: SIN semilla
        (ni MIB oficial ni Observium), construye el catálogo entero a partir del walk.

        Sin MIB no sabemos dónde termina cada OID base y empieza su índice de
        instancia, así que se usa la misma aproximación de `triggers.extract_table_prefix`
        que ya usa `detect_observed_only` para findings (recorta el último componente).
        Cada base distinta se vuelve UN Oid con nombre UNRESOLVED, acceso "unknown"
        (ver _KEEP_IF_UNCONFIRMED) y status="observed" — el nivel de confianza más bajo
        del catálogo: confirma que el OID existe, no qué significa."""
        bases: dict[str, dict] = {}
        for w in self.sorted_walk:
            base = T.extract_table_prefix(w)
            entry = bases.setdefault(base, {"count": 0, "sample_oid": w})
            entry["count"] += 1
        entity_ref = f"entity.{vendor.lower()}.{technology.lower()}.unresolved.walk_observed"
        oids = []
        for base, info in sorted(bases.items(), key=lambda kv: tuple(
                int(p) for p in kv[0].split(".") if p.isdigit())):
            sample = info["sample_oid"]
            snmp_type = self.walk.get(sample, {}).get("type", "UNKNOWN")
            oids.append({
                "id": build_oid_id(vendor, technology, "unresolved", base.replace(".", "_")),
                "oid": base, "name": "UNRESOLVED", "entity_ref": entity_ref,
                "vendor": vendor, "family": family, "technology": technology,
                "firmware": [], "syntax": snmp_type, "access": "unknown",
                "status": "observed",
                "description": ("Walk-first: sin MIB/semilla para este vendor. Base inferida "
                                "recortando el último componente del OID como índice de "
                                "instancia (aproximación — puede ser incorrecta si el índice "
                                "real es compuesto)."),
                "empirical": {"source": self.source_name, "instances": info["count"],
                             "sample_oid": sample,
                             "sample_value": self.walk.get(sample, {}).get("value")},
                "sources": [{"doc_type": "walk", "pages": None, "confidence": 0.0}],
                "confidence": {"overall": 0.0},
            })
        return [{"entity_ref": entity_ref, "vendor": vendor, "family": family,
                 "firmware": [], "oids": oids}] if oids else []

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
