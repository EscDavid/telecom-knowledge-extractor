"""Fase 2 — WalkValidator: valida el catálogo teórico contra snmpwalks reales.

Detecta vendor/modelo por el nombre del archivo, parsea los walks, siembra un
catálogo nuevo desde el backbone teórico y lo especializa con la evidencia empírica,
produciendo un catálogo separado sin tocar la Fase 1.

Todo lo específico del vendor (enterprise, ramas, nombres de interfaz, familias,
semilla) viene de su perfil en config/vendors.yaml (src/profiles.py). Un modelo
puede aportar VARIOS walks complementarios (todos convergen en un único catálogo):

    <VENDOR>_<MODELO>.txt          → enterprise   → enriquece OIDs
    <VENDOR>_<MODELO>_entities.txt → entity_table (entPhysicalTable) → entidades hardware
    <VENDOR>_<MODELO>_ifnames.txt  → if_table     (ifXTable) → entidades port + bit_calculation

    docs/walks/ZTE_C300*.txt  +  catalog/zte/zxa10-c320/...  (semilla)
      → catalog/zte/zxa10-c300/catalog-1.0.0/  (enriquecido + podado)

Semilla: `walk_validator.seed_from_family` (solo para el vendor del pipeline) >
`seed_family` del perfil > la propia familia del walk (Fase 1 de ese modelo).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Optional, Union

from ..ids import entity_short_name
from ..profiles import ProfileRegistry, VendorProfile, default_registry, registry_from_config
from . import community
from . import std_tables as ST
from . import triggers as T
from .enricher import Enricher
from .triggers import Findings

log = logging.getLogger("tkc.walk_validator")

# Vistas de compatibilidad derivadas de config/vendors.yaml (fuente de verdad).
VENDOR_MAP = {v: v for v in default_registry().vendors()}
FAMILY_MAP = {tok: fam for tok, (_v, fam) in default_registry().families().items()}

# Sufijo del nombre → tipo de walk. 'enterprise' es el default (sin sufijo).
WALK_TYPE_MAP = {
    "_entities": "entity_table",   # entPhysicalTable (1.3.6.1.2.1.47.1.1.1.1)
    "_ifnames": "if_table",        # ifXTable ifName   (1.3.6.1.2.1.31.1.1.1.1)
    "_ifxfull": "if_table",        # ifXTable completa (con contadores 64-bit); mismo tipo
    "_system": "enterprise",       # escalares MIB-II (sysDescr/sysObjectID...); se tratan
                                   # como evidencia "enterprise" más, no como tabla aparte
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


def detect_vendor_family(filepath: Path,
                         registry: ProfileRegistry | None = None) -> tuple[str, str]:
    """`ZTE_C300.txt` / `ZTE_C300_entities.txt` → `('ZTE', 'ZXA10 C300')`.

    El modelo se busca en las `families` del PERFIL del vendor del nombre (dos
    vendors pueden compartir un token de modelo sin colisionar).
    """
    reg = registry or default_registry()
    parts = _base_stem(filepath).split("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Nombre inválido: {filepath.name}. Esperado VENDOR_MODELO[_tipo].txt")
    vendor_raw, model_raw = parts
    if vendor_raw not in reg.vendors():
        raise ValueError(f"Vendor '{vendor_raw}' no registrado en config/vendors.yaml")
    family = reg.get(vendor_raw).families.get(model_raw)
    if not family:
        raise ValueError(f"Modelo '{model_raw}' no registrado para el vendor {vendor_raw} "
                         f"(families en config/vendors.yaml)")
    return vendor_raw, family


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
        self.registry = registry_from_config(config)
        self._pipeline_vendor = (config.get("pipeline") or {}).get("vendor")
        self._cfg_seed = wv.get("seed_from_family")
        self._cfg_single_shelf = wv.get("single_shelf")
        self.prune_ro = wv.get("prune_unconfirmed_readonly", True)
        self.halt_on_blocking = wv.get("halt_on_blocking", True)
        self.release_versions = wv.get("release_versions", {}) or {}
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
        vendor, family = detect_vendor_family(walk_files[0], self.registry)
        profile = self.registry.get(vendor)
        seed_family = self._seed_family(profile, family)
        single_shelf = self._single_shelf(profile)

        seed = self._seed_dir(vendor, seed_family)
        findings = Findings()
        oid_groups = self._load_dir(seed / "oids")
        entities = self._load_dir(seed / "entities")
        # modo walk-first (backlog #1 de docs/adaptacion_multivendor.md): sin semilla
        # (ni MIB oficial ni .mib sintético), el catálogo se construye ENTERO desde el
        # walk — nombres UNRESOLVED, status=observed. Nunca se activa para un vendor que
        # sí tiene semilla (oid_groups/entities no vacíos), así que no cambia nada de lo
        # que ya funciona para ZTE/Huawei.
        walk_first = not oid_groups and not entities
        if walk_first:
            log.warning("WalkValidator: sin catálogo semilla en %s — modo walk-first "
                        "(todo status=observed, nombres UNRESOLVED)", seed)
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
                                    prune_unconfirmed_readonly=self.prune_ro, profile=profile,
                                    family=family)
                if walk_first:
                    enriched_oids = enricher.materialize_observed_groups(
                        vendor, family, profile.technology)
                    log.info("WalkValidator: walk-first → %d OID(s) UNRESOLVED materializados "
                             "de %s", sum(len(g["oids"]) for g in enriched_oids), wf.name)
                else:
                    base_oids = [o["oid"] for g in oid_groups for o in g.get("oids", [])]
                    enriched_oids = enricher.enrich_groups(oid_groups, family)
                    enricher.detect_observed_only(base_oids)
            elif wtype == "entity_table":
                n = ST.enrich_hardware_entities(entities_by_short, walk, wf.name, findings,
                                            profile=profile, walk_first=walk_first, family=family)
                log.info("WalkValidator: %d entidades hardware confirmadas (entPhysicalTable)", n)
            elif wtype == "if_table":
                ST.enrich_port_entities(entities_by_short, oid_groups, walk, wf.name, findings,
                                        profile=profile, walk_first=walk_first, family=family)
                # ifTable (ifOperStatus/ifType) → operación de PON ports
                ST.enrich_pon_operational(entities_by_short, enriched_oids, walk, wf.name,
                                          findings, vendor=vendor, technology=profile.technology,
                                          family=family, profile=profile, walk_first=walk_first)

        # índices ASCII de software/parche: se validan con las instancias del walk enterprise
        if enterprise_sorted:
            n = ST.validate_ascii_indices(enriched_oids, enterprise_sorted, findings,
                                          profile=profile)
            log.info("WalkValidator: %d índice(s) ASCII confirmados con el walk enterprise", n)
            # onu_count por PON port: derivado de la tabla ONU del walk enterprise
            ST.derive_pon_onu_count(entities_by_short, enterprise_sorted, findings,
                                    profile=profile)

        # --- gate de bloqueo: hallazgos críticos requieren confirmación/rechazo ---
        self._resolve_blocking(family, enriched_oids, findings, processed, single_shelf)

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
                                            technology=profile.technology,
                                            index_spaces=merged_spaces)
            res["source"] = Path(src["_path"]).name
            self._community_summary.append(res)
            log.info("WalkValidator: community %s → +%d OIDs / %d degradados en %s",
                     res["source"], res["stats"]["added"], res["stats"]["downgraded"], family)

        target = self._target_dir(vendor, family, seed_family)
        self._write_catalog(seed, target, vendor, family, enriched_oids,
                            list(entities_by_short.values()), findings, processed,
                            profile=profile, seed_family=seed_family)
        log.info("WalkValidator: catálogo %s enriquecido en %s", family, target)
        return target

    def _resolve_blocking(self, family: str, enriched_oids: list[dict],
                          findings: Findings, processed: dict[str, str],
                          single_shelf: bool | None = None) -> None:
        """Aplica accept/reject a cada hallazgo bloqueante; si queda alguno sin
        resolver y halt_on_blocking está activo, detiene el procesado (WalkHalt)."""
        blocking = findings.blocking()
        if not blocking:
            return
        if single_shelf is None:        # llamada directa: se deduce del perfil dueño de la familia
            owner = self.registry.vendor_of_family(family)
            single_shelf = self._single_shelf(self.registry.get(owner)) if owner else False
        decisions = self.resolutions.get(family, {})
        unresolved = []
        for bf in blocking:
            decision = decisions.get(bf["trigger"])
            bf["resolution"] = decision or "pending"
            if decision == "accept":
                fix = bf.get("proposed_fix") or {}
                n = ST.apply_bitcalc_fix(enriched_oids, fix, bf.get("derived_layout"),
                                         single_shelf=single_shelf)
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

    def _seed_family(self, profile: VendorProfile, family: str) -> str:
        """Familia semilla: config (solo vendor del pipeline) > perfil > la propia familia."""
        if self._cfg_seed and profile.vendor == self._pipeline_vendor:
            return self._cfg_seed
        return profile.seed_family or family

    def _single_shelf(self, profile: VendorProfile) -> bool:
        """Single-shelf: perfil > config (solo vendor del pipeline) > False (no se asume)."""
        if profile.single_shelf is not None:
            return bool(profile.single_shelf)
        if self._cfg_single_shelf is not None and profile.vendor == self._pipeline_vendor:
            return bool(self._cfg_single_shelf)
        return False

    def _profile_source_rel(self) -> Optional[str]:
        """Ruta de config/vendors.yaml relativa al cwd (portable entre dispositivos) —
        backlog #5: la ruta absoluta de `source_path` es específica de la máquina."""
        p = self.registry.source_path
        if p is None:
            return None
        try:
            return str(Path(p).resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return str(p)

    def _seed_dir(self, vendor: str, seed_family: str) -> Path:
        return (self.catalog_base / vendor.lower()
                / seed_family.lower().replace(" ", "-") / f"catalog-{self.version}")

    def _target_dir(self, vendor: str, family: str, seed_family: str) -> Path:
        # Si el modelo del walk es el mismo que la semilla teórica, el catálogo
        # validado va a un directorio aparte para NO pisar la base de Fase 1.
        version = self.release_versions.get(family) or (f"{self.version}-validated" if family == seed_family else self.version)
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
                       findings: Findings, processed: dict[str, str],
                       profile: VendorProfile | None = None,
                       seed_family: str | None = None) -> None:
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

        self._apply_command_sources(target, family)

        self._write_json(target / "results.json", {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "walks": processed,
            "findings": findings.items,
        })
        self._write_json(target / "manifest.json",
                         self._manifest(vendor, family, enriched_oids, enriched_entities,
                                        findings, processed, seed_family))
        hook = profile.refinement_hook() if profile else None
        if hook:
            hook(target, family, self.walks_dir)

    def _apply_command_sources(self, target: Path, family: str) -> int:
        """Comandos verificados en hardware (docs/validation/commands/*.json). Si el documento declara
        meta.replace_seed, sustituyen a los comandos heredados de la semilla (sintaxis del manual C320)."""
        d = self.validation_dir / "commands"
        if not d.exists():
            return 0
        n = 0
        for f in sorted(d.glob("*.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            cmds = (doc.get("commands") or {}).get(family)
            if not cmds:
                continue
            if (doc.get("meta") or {}).get("replace_seed"):
                import shutil
                shutil.rmtree(target / "commands", ignore_errors=True)
            for c in cmds:
                self._write_json(target / "commands" / c["category"] / f"{c['id'].split('.')[-1]}.json", c)
                n += 1
            log.info("WalkValidator: comandos verificados %s → +%d en %s", f.name, n, family)
        return n

    def _manifest(self, vendor: str, family: str, enriched_oids: list[dict],
                  enriched_entities: list[dict], findings: Findings,
                  processed: dict[str, str], seed_family: str | None = None) -> dict:
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
            "seed_family": seed_family,
            "vendor_profile": {
                "vendor": vendor,
                "source": self._profile_source_rel(),
                "sha256": self.registry.source_sha256,
            },
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
