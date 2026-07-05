"""Fase 2 — WalkValidator: valida el catálogo teórico contra snmpwalks reales.

Detecta vendor/modelo por el nombre del archivo, parsea los walks, siembra un
catálogo nuevo desde el backbone teórico (C320) y lo especializa con la evidencia
empírica, produciendo un catálogo separado (ej. C300) sin tocar la Fase 1.

Un mismo modelo puede aportar VARIOS walks complementarios (todos convergen en un
único catálogo):

    ZTE_C320.txt          → enterprise   (rama 3902.*) → enriquece OIDs
    ZTE_C320_entities.txt → entity_table (entPhysicalTable) → entidades hardware
    ZTE_C320_ifnames.txt  → if_table     (ifXTable) → entidades port + bit_calculation

    docs/walks/ZTE_C300*.txt  +  catalog/zte/zxa10-c320/...  (semilla)
      → catalog/zte/zxa10-c300/catalog-1.0.0/  (enriquecido + podado)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Union

from ..ids import entity_short_name
from . import community
from . import std_tables as ST
from . import triggers as T
from .enricher import Enricher
from .triggers import Findings

log = logging.getLogger("tkc.walk_validator")

VENDOR_MAP = {"ZTE": "ZTE", "Huawei": "Huawei", "VSOL": "VSOL"}
FAMILY_MAP = {
    "C300": "ZXA10 C300", "C320": "ZXA10 C320",
    "MA5608T": "MA5608T", "V1600G": "V1600G", "V1600GS": "V1600GS",
}

# Sufijo del nombre → tipo de walk. 'enterprise' es el default (sin sufijo).
WALK_TYPE_MAP = {
    "_entities": "entity_table",   # entPhysicalTable (1.3.6.1.2.1.47.1.1.1.1)
    "_ifnames": "if_table",        # ifXTable ifName   (1.3.6.1.2.1.31.1.1.1.1)
}


class WalkHalt(Exception):
    """El procesado se detuvo por hallazgos bloqueantes sin resolver.

    El pipeline no escribe el catálogo enriquecido hasta que el operador confirme
    (accept) o rechace (reject) cada hallazgo en el archivo de resoluciones.
    """
    def __init__(self, family: str, findings: list, review_path: Path):
        self.family = family
        self.findings = findings
        self.review_path = review_path
        super().__init__(f"{len(findings)} hallazgo(s) bloqueante(s) en {family}; "
                         f"revisar {review_path}")


def detect_walk_type(filepath: Path) -> str:
    """`ZTE_C320_entities.txt` → 'entity_table'; sin sufijo → 'enterprise'."""
    stem = filepath.stem
    for suffix, walk_type in WALK_TYPE_MAP.items():
        if stem.endswith(suffix):
            return walk_type
    return "enterprise"


def _base_stem(filepath: Path) -> str:
    """Nombre sin el sufijo de tipo: `ZTE_C320_ifnames` → `ZTE_C320`."""
    stem = filepath.stem
    for suffix in WALK_TYPE_MAP:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def detect_vendor_family(filepath: Path) -> tuple[str, str]:
    """`ZTE_C300.txt` / `ZTE_C300_entities.txt` → `('ZTE', 'ZXA10 C300')`."""
    parts = _base_stem(filepath).split("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Nombre inválido: {filepath.name}. Esperado VENDOR_MODELO[_tipo].txt")
    vendor_raw, model_raw = parts
    vendor = VENDOR_MAP.get(vendor_raw)
    family = FAMILY_MAP.get(model_raw)
    if not vendor:
        raise ValueError(f"Vendor '{vendor_raw}' no registrado en tkc_vendors")
    if not family:
        raise ValueError(f"Modelo '{model_raw}' no registrado en tkc_families")
    return vendor, family


def model_key(filepath: Path) -> str:
    """Clave de agrupación: varios walks del mismo modelo → un catálogo."""
    return _base_stem(filepath)


def _oid_key(oid: str):
    try:
        return tuple(int(x) for x in oid.split("."))
    except ValueError:
        return None


class WalkValidator:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.catalog_base = Path(config["paths"]["catalog"])
        wv = config.get("walk_validator", {})
        self.seed_family = wv.get("seed_from_family", "ZXA10 C320")
        self.prune_ro = wv.get("prune_unconfirmed_readonly", True)
        self.halt_on_blocking = wv.get("halt_on_blocking", True)
        # Todos los equipos ZTE C3xx del proyecto son single-shelf (rack=1 siempre).
        self.single_shelf = wv.get("single_shelf", True)
        self.version = config["pipeline"].get("catalog_version", "1.0.0")
        self.walks_dir = Path(config["paths"].get("walks", "docs/walks/"))
        self.validation_dir = Path(config["paths"].get("validation", "docs/validation/"))
        self.reports_dir = Path(config["paths"].get("reports", "reports/"))
        self.mirror_families = wv.get("mirror_walk_to_families", [])
        self.resolutions = self._load_resolutions()
        self.community_sources = self._load_community()
        self._community_summary: list[dict] = []

    def _load_community(self) -> list[dict]:
        """Parsea las fuentes de validación community (docs/validation/**/*.txt)."""
        out: list[dict] = []
        if not self.validation_dir.exists():
            return out
        for f in sorted(self.validation_dir.rglob("*.txt")):
            try:
                src = community.parse_community(f)
            except OSError as exc:
                log.error("no se pudo leer fuente community %s: %s", f.name, exc)
                continue
            if src["meta"].get("doc_type") == "community":
                src["_path"] = str(f)
                out.append(src)
        return out

    def _load_resolutions(self) -> dict:
        """Decisiones del operador: {family: {trigger: 'accept'|'reject'}}.

        Se leen de docs/walks/resolutions.json (editable sin tocar el código).
        """
        f = self.walks_dir / "resolutions.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                log.error("resolutions.json inválido: %s", exc)
        return {}

    # --- parse ---------------------------------------------------------------
    def parse_walk(self, filepath: Path, findings: Findings) -> dict[str, dict]:
        """Parsea un walk línea a línea. Dispara triggers not-increasing y ascii."""
        walk: dict[str, dict] = {}
        prev_oid = None
        prev_key = None
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or " = " not in line:
                    continue
                oid_part, value_part = line.split(" = ", 1)
                oid = oid_part.strip().lstrip(".")
                if ": " in value_part:
                    snmp_type, value = value_part.split(": ", 1)
                else:
                    snmp_type, value = "UNKNOWN", value_part

                key = _oid_key(oid)
                if prev_key and key and key <= prev_key:
                    T.trigger_oid_not_increasing(findings, oid, prev_oid, line_num)
                if T.is_ascii_index(oid):
                    T.trigger_ascii_index(findings, oid)

                walk[oid] = {"type": snmp_type.strip(), "value": value.strip(), "line": line_num}
                prev_oid, prev_key = oid, key or prev_key
        log.info("WalkValidator: %d OIDs parseados de %s", len(walk), filepath.name)
        return walk

    # --- orquestación --------------------------------------------------------
    def run(self, walk_files: Union[Path, list[Path]]) -> Path:
        """Procesa todos los walks de un mismo modelo hacia un único catálogo."""
        if isinstance(walk_files, (str, Path)):
            walk_files = [Path(walk_files)]
        walk_files = list(walk_files)
        vendor, family = detect_vendor_family(walk_files[0])

        seed = self._seed_dir(vendor)
        if not seed.exists():
            raise FileNotFoundError(
                f"Catálogo semilla no encontrado: {seed}. Genera antes la Fase 1 "
                f"con family='{self.seed_family}'.")

        findings = Findings()
        oid_groups = self._load_dir(seed / "oids")
        entities = self._load_dir(seed / "entities")
        for coll in (oid_groups, entities):
            for d in coll:
                _relabel_family(d, family)
        entities_by_short = {entity_short_name(e.get("id", "")): e for e in entities}

        enriched_oids = oid_groups
        enterprise_sorted: list[str] = []
        processed: dict[str, str] = {}
        # enterprise primero: enriquece OIDs antes de que if_table lea el bit_calculation
        for wf in sorted(walk_files, key=lambda p: detect_walk_type(p) != "enterprise"):
            wtype = detect_walk_type(wf)
            processed[wf.name] = wtype
            walk = self.parse_walk(wf, findings)
            if wtype == "enterprise":
                sorted_walk = sorted(walk)
                enterprise_sorted = sorted_walk
                enricher = Enricher(walk, sorted_walk, findings, wf.name,
                                    prune_unconfirmed_readonly=self.prune_ro)
                base_oids = [o["oid"] for g in oid_groups for o in g.get("oids", [])]
                enriched_oids = enricher.enrich_groups(oid_groups, family)
                enricher.detect_observed_only(base_oids)
            elif wtype == "entity_table":
                n = ST.enrich_hardware_entities(entities_by_short, walk, wf.name, findings)
                log.info("WalkValidator: %d entidades hardware confirmadas (entPhysicalTable)", n)
            elif wtype == "if_table":
                ST.enrich_port_entities(entities_by_short, oid_groups, walk, wf.name, findings)
                # ifTable (ifOperStatus/ifType) → operación de PON ports
                ST.enrich_pon_operational(entities_by_short, enriched_oids, walk, wf.name,
                                          findings, vendor=vendor, family=family)

        # índices ASCII de software/parche: se validan con las instancias del walk enterprise
        if enterprise_sorted:
            n = ST.validate_ascii_indices(enriched_oids, enterprise_sorted, findings)
            log.info("WalkValidator: %d índice(s) ASCII confirmados con el walk enterprise", n)
            # onu_count por PON port: derivado de la tabla ONU del walk enterprise
            ST.derive_pon_onu_count(entities_by_short, enterprise_sorted, findings)

        # --- gate de bloqueo: hallazgos críticos requieren confirmación/rechazo ---
        self._resolve_blocking(family, enriched_oids, findings, processed)

        # --- fuente(s) community: leaves de ONU + fórmula de índice + enums --------
        # Las fórmulas de índice pueden estar en una fuente y usarse en otra
        # (reconciliación) → se comparten todas las index_spaces.
        merged_spaces: dict = {}
        for src in self.community_sources:
            merged_spaces.update(src.get("index_spaces", {}))
        self._community_summary = []
        for src in sorted(self.community_sources, key=lambda s: s["_path"]):
            if family not in src["meta"].get("families", []):
                continue
            res = community.apply_community(enriched_oids, src, family, findings,
                                            walk_confirmed=True, vendor=vendor,
                                            index_spaces=merged_spaces)
            res["source"] = Path(src["_path"]).name
            self._community_summary.append(res)
            log.info("WalkValidator: community %s → +%d OIDs / %d degradados en %s",
                     res["source"], res["stats"]["added"], res["stats"]["downgraded"], family)

        target = self._target_dir(vendor, family)
        self._write_catalog(seed, target, vendor, family, enriched_oids,
                            list(entities_by_short.values()), findings, processed)
        log.info("WalkValidator: catálogo %s enriquecido en %s", family, target)
        return target

    def _resolve_blocking(self, family: str, enriched_oids: list[dict],
                          findings: Findings, processed: dict[str, str]) -> None:
        """Aplica accept/reject a cada hallazgo bloqueante; si queda alguno sin
        resolver y halt_on_blocking está activo, detiene el procesado (WalkHalt)."""
        blocking = findings.blocking()
        if not blocking:
            return
        decisions = self.resolutions.get(family, {})
        unresolved = []
        for bf in blocking:
            decision = decisions.get(bf["trigger"])
            bf["resolution"] = decision or "pending"
            if decision == "accept":
                fix = bf.get("proposed_fix") or {}
                n = ST.apply_bitcalc_fix(enriched_oids, fix, bf.get("derived_layout"),
                                         single_shelf=self.single_shelf)
                log.info("WalkValidator: [accept] %s → fix aplicado a %d OIDs (%s)",
                         bf["trigger"], n, fix)
            elif decision == "reject":
                n = ST.mark_bitcalc_unvalidated(enriched_oids)
                log.info("WalkValidator: [reject] %s → %d índices marcados no validados",
                         bf["trigger"], n)
            else:
                unresolved.append(bf)
        if unresolved and self.halt_on_blocking:
            review = self._write_pending(family, unresolved, findings, processed)
            raise WalkHalt(family, unresolved, review)

    def _write_pending(self, family: str, unresolved: list[dict],
                       findings: Findings, processed: dict[str, str]) -> Path:
        slug = family.lower().replace(" ", "-")
        path = self.reports_dir / "walk_review" / f"{slug}_pending.json"
        self._write_json(path, {
            "status": "PENDING_REVIEW",
            "family": family,
            "walks": processed,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "blocking_findings": unresolved,
            "how_to_resolve": (
                "El catálogo NO se escribió. Revisa cada hallazgo y edita "
                "docs/walks/resolutions.json con "
                f'{{"{family}": {{"<trigger>": "accept"|"reject"}}}} '
                "y vuelve a ejecutar `python main.py`. "
                "accept = aplicar proposed_fix; reject = mantener y marcar no validado."),
        })
        return path

    def _seed_dir(self, vendor: str) -> Path:
        return (self.catalog_base / vendor.lower()
                / self.seed_family.lower().replace(" ", "-") / f"catalog-{self.version}")

    def _target_dir(self, vendor: str, family: str) -> Path:
        # Si el modelo del walk es el mismo que la semilla teórica, el catálogo
        # validado va a un directorio aparte para NO pisar la base de Fase 1.
        version = f"{self.version}-validated" if family == self.seed_family else self.version
        return (self.catalog_base / vendor.lower()
                / family.lower().replace(" ", "-") / f"catalog-{version}")

    # --- IO ------------------------------------------------------------------
    @staticmethod
    def _load_dir(path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(path.glob("*.json"))]

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_catalog(self, seed: Path, target: Path, vendor: str, family: str,
                       enriched_oids: list[dict], enriched_entities: list[dict],
                       findings: Findings, processed: dict[str, str]) -> None:
        # OIDs enriquecidos (con poda)
        for g in enriched_oids:
            self._write_json(target / "oids" / f"{_group_name(g)}.json", g)

        # entidades enriquecidas (hardware/port confirmados por las tablas estándar)
        for e in enriched_entities:
            self._write_json(target / "entities" / f"{entity_short_name(e.get('id', ''))}.json", e)

        # commands/relations/alarms se copian re-etiquetando la familia
        for sub in ("commands", "relations", "alarms"):
            src = seed / sub
            if not src.exists():
                continue
            for f in src.rglob("*.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                _relabel_family(data, family)
                self._write_json(target / f.relative_to(seed), data)

        self._write_json(target / "results.json", {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "walks": processed,
            "findings": findings.items,
        })
        self._write_json(target / "manifest.json",
                         self._manifest(vendor, family, enriched_oids, enriched_entities,
                                        findings, processed))

    def _manifest(self, vendor: str, family: str, enriched_oids: list[dict],
                  enriched_entities: list[dict], findings: Findings,
                  processed: dict[str, str]) -> dict:
        oid_status = Counter(o["status"] for g in enriched_oids for o in g["oids"])
        ent_status = Counter(e.get("status", "?") for e in enriched_entities)
        trig = Counter(f["trigger"] for f in findings.items)
        fw_strings = sorted({f["decoded_value"] for f in findings.by_trigger("ascii_index")
                             if f.get("decoded_value")})
        bitcalc = findings.by_trigger("bitcalc_validation")
        # validaciones que quedan PENDIENTES (evidencia existe en otra rama del walk)
        pending = [{"trigger": f["trigger"], "oids": f.get("oids", []),
                    "pending_validation": f.get("pending_validation")}
                   for f in findings.items if f.get("pending")]
        return {
            "project": "Telecom Knowledge Compiler (TKC) — Fase 2",
            "vendor": vendor,
            "family": family,
            "phase": "walk_validation",
            "seed_family": self.seed_family,
            "walks": processed,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "counts": {
                "oids_kept": sum(len(g["oids"]) for g in enriched_oids),
                "oids_pruned": sum(1 for f in findings.by_trigger("documented_only") if f["pruned"]),
                "entities_confirmed": sum(1 for e in enriched_entities
                                          if e.get("status") == "verified"),
            },
            "status_distribution": {"oids": dict(oid_status), "entities": dict(ent_status)},
            "triggers": dict(trig),
            "bitcalc_validation": bitcalc[0] if bitcalc else None,
            "pending_validations": pending,
            "community": ({"sources": [c["source"] for c in self._community_summary],
                           "onu_leaves_added": sum(c["stats"]["added"] for c in self._community_summary),
                           "index_decoder": self._community_summary[0]["index_spaces"] and
                           {s: self._community_summary[0]["index_spaces"][s].get("formula")
                            for s in self._community_summary[0]["index_spaces"]},
                           "snmp_params": self._community_summary[0].get("snmp"),
                           "optical": self._community_summary[0].get("optical")}
                          if self._community_summary else None),
            "observed_firmware_strings": fw_strings[:20],
        }


def _group_name(group: dict) -> str:
    ref = group.get("entity_ref") or "unknown"
    return ref.split(".")[-1]


def _relabel_family(data: Any, family: str) -> None:
    if isinstance(data, dict):
        if "family" in data:
            data["family"] = family
        for v in data.values():
            _relabel_family(v, family)
    elif isinstance(data, list):
        for v in data:
            _relabel_family(v, family)
