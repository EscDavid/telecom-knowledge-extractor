"""Perfiles de vendor — todo lo específico de un fabricante, leído de config/vendors.yaml.

El pipeline (Fase 1 y Fase 2) no debe contener OIDs, nombres de interfaz ni fórmulas
de ningún vendor: pregunta al perfil. Un valor `None` significa "desconocido" y la
validación correspondiente se OMITE (nunca se hereda un valor de otro vendor).
"""
from __future__ import annotations

import hashlib
import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

log = logging.getLogger("tkc.profiles")

DEFAULT_VENDORS_FILE = Path(__file__).resolve().parent.parent / "config" / "vendors.yaml"
ENTERPRISES = "1.3.6.1.4.1"                       # prefijo de todo OID enterprise
_ENTERPRISES_ARCS = len(ENTERPRISES.split(".")) + 1   # + el nº de enterprise = 7

# Heurísticas genéricas (no son de un vendor): se usan cuando el perfil no las define.
GENERIC_PON_KEYWORDS = ("pon",)
GENERIC_UPLINK_KEYWORDS = ("uplink", "gei", "xge", "eth", "gigabit")
GENERIC_IFTYPE_PON = 250       # IANAifType gpon(250)
GENERIC_IFTYPE_UPLINK = 6      # IANAifType ethernetCsmacd(6)

# Perfil que usan las llamadas heredadas que no pasan `profile` (compatibilidad con
# código y tests previos al multi-vendor). La orquestación SIEMPRE pasa el perfil real.
LEGACY_DEFAULT_VENDOR = "ZTE"

# nombre en vendors.yaml → "módulo:función" con firma refine(target: Path, family: str, walks_dir: Path|None)
REFINEMENT_HOOKS = {"zte_c6xx": "src.walk_validator.refinements:refine_catalog"}


@dataclass(frozen=True)
class VendorProfile:
    vendor: str
    technology: str = "gpon"
    enterprise_oid: Optional[str] = None
    seed_family: Optional[str] = None
    families: dict[str, str] = field(default_factory=dict)
    single_shelf: Optional[bool] = None
    ifname_regex: Optional[str] = None
    pon_keywords: tuple[str, ...] = GENERIC_PON_KEYWORDS
    uplink_keywords: tuple[str, ...] = GENERIC_UPLINK_KEYWORDS
    iftype_pon: int = GENERIC_IFTYPE_PON
    iftype_uplink: int = GENERIC_IFTYPE_UPLINK
    pon_port_index: Optional[dict] = None
    bit_index: Optional[dict] = None
    onu_count_source: Optional[dict] = None
    software_branches: Optional[dict] = None
    sensitive_prefixes: tuple[str, ...] = ()
    metric_prefixes: tuple[str, ...] = ()    # prefijos snake_case de nombres MIB que se recortan
    prune_mode: str = "all"                  # all | covered_branch
    prune_branch_depth: int = 2
    refinements: Optional[str] = None
    ent_module_refine: bool = False          # entPhysicalClass=module que son ventilador/fuente → fan/power_supply
    # backlog #8 de docs/adaptacion_multivendor.md: entPhysicalTable confirma hardware real
    # (entPhysicalClass es un enum estándar, no específico de vendor) pero la semilla de este
    # vendor puede no tener la entidad (ej. Huawei: XPON-MIB no cubre chassis/tarjetas, esas
    # viven en HUAWEI-DEVICE-MIB, nunca ingerido). Con esto en true, enrich_hardware_entities
    # sintetiza la entidad que falte — SOLO respaldada por una clase SNMP real confirmada, no
    # por heurística de texto. False (default) = comportamiento actual, "no está en el
    # catálogo" sigue significando "no aplica a esta familia" (ZTE sin cambios).
    ent_synthesize_from_walk: bool = False
    legacy_env: bool = False                 # acepta las variables antiguas TKC_SNMP_*/TKC_TELNET_*

    # --- ids de entidad derivados del vendor (no hardcodeados a ZTE) -----------
    @property
    def entity_prefix(self) -> str:
        return f"entity.{self.vendor.lower()}.{self.technology.lower()}"

    @property
    def pon_port_entity_ref(self) -> str:
        return f"{self.entity_prefix}.port.pon_port"

    @property
    def onu_entity_ref(self) -> str:
        return f"{self.entity_prefix}.device.onu"

    def refinement_hook(self) -> Optional[Callable]:
        if not self.refinements:
            return None
        target = REFINEMENT_HOOKS.get(self.refinements)
        if not target:
            log.warning("hook de refinamiento desconocido '%s' (vendor %s)", self.refinements, self.vendor)
            return None
        mod, _, fn = target.partition(":")
        return getattr(importlib.import_module(mod), fn)


def _tuple(v: Any, default: tuple = ()) -> tuple:
    return tuple(v) if v else default


def _from_dict(vendor: str, d: dict) -> VendorProfile:
    ifn = d.get("ifname") or {}
    ift = d.get("iftype") or {}
    return VendorProfile(
        vendor=vendor,
        technology=d.get("technology", "gpon"),
        enterprise_oid=d.get("enterprise_oid"),
        seed_family=d.get("seed_family"),
        families=dict(d.get("families") or {}),
        single_shelf=d.get("single_shelf"),
        ifname_regex=ifn.get("regex"),
        pon_keywords=_tuple(ifn.get("pon_keywords"), GENERIC_PON_KEYWORDS),
        uplink_keywords=_tuple(ifn.get("uplink_keywords"), GENERIC_UPLINK_KEYWORDS),
        iftype_pon=int(ift.get("pon", GENERIC_IFTYPE_PON)),
        iftype_uplink=int(ift.get("uplink", GENERIC_IFTYPE_UPLINK)),
        pon_port_index=d.get("pon_port_index"),
        bit_index=d.get("bit_index"),
        onu_count_source=d.get("onu_count_source"),
        software_branches=d.get("software_branches"),
        sensitive_prefixes=_tuple(d.get("sensitive_prefixes")),
        metric_prefixes=_tuple(d.get("metric_prefixes")),
        prune_mode=d.get("prune_mode", "all"),
        prune_branch_depth=int(d.get("prune_branch_depth", 2)),
        refinements=d.get("refinements"),
        legacy_env=bool(d.get("legacy_env", False)),
        ent_module_refine=bool(d.get("ent_module_refine", False)),
        ent_synthesize_from_walk=bool(d.get("ent_synthesize_from_walk", False)),
    )


class ProfileRegistry:
    def __init__(self, profiles: dict[str, VendorProfile], *,
                 source_path: Optional[Path] = None, source_sha256: Optional[str] = None):
        self.profiles = profiles
        # backlog #5 de docs/adaptacion_multivendor.md: trazabilidad de qué
        # vendors.yaml (y versión exacta de su contenido) produjo un catálogo.
        self.source_path = source_path
        self.source_sha256 = source_sha256

    def get(self, vendor: str) -> VendorProfile:
        """Perfil del vendor; si no está registrado, uno genérico SIN supuestos de vendor."""
        p = self.profiles.get(vendor)
        if p is None:                      # el .env usa MAYÚSCULAS (TKC_HUAWEI_*) y el yaml "Huawei"
            p = next((v for k, v in self.profiles.items() if k.lower() == str(vendor).lower()), None)
        if p is None:
            log.warning("vendor '%s' sin perfil en vendors.yaml: se usa perfil genérico", vendor)
            p = VendorProfile(vendor=vendor)
        return p

    def vendors(self) -> list[str]:
        return list(self.profiles)

    def vendor_of_family(self, family: str) -> Optional[str]:
        for v, p in self.profiles.items():
            if family in p.families.values():
                return v
        return None

    def families(self) -> dict[str, tuple[str, str]]:
        """token de modelo → (vendor, familia). Si un token se repite entre vendors gana el primero."""
        out: dict[str, tuple[str, str]] = {}
        for v, p in self.profiles.items():
            for token, family in p.families.items():
                out.setdefault(token, (v, family))
        return out


def load_registry(path: Optional[Path] = None) -> ProfileRegistry:
    f = Path(path) if path else DEFAULT_VENDORS_FILE
    if not f.exists():
        log.warning("no existe %s: todos los vendors usarán el perfil genérico", f)
        return ProfileRegistry({}, source_path=f)
    raw_bytes = f.read_bytes()
    raw = yaml.safe_load(raw_bytes) or {}
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return ProfileRegistry({v: _from_dict(v, d or {}) for v, d in raw.items()},
                           source_path=f, source_sha256=digest)


_default: Optional[ProfileRegistry] = None


def default_registry() -> ProfileRegistry:
    """Registro cargado una vez desde config/vendors.yaml."""
    global _default
    if _default is None:
        _default = load_registry()
    return _default


def registry_from_config(config: dict) -> ProfileRegistry:
    """Respeta `paths.vendors` del pipeline.yaml si existe; si no, el archivo por defecto."""
    p = (config.get("paths") or {}).get("vendors")
    return load_registry(Path(p)) if p else default_registry()


# --- utilidades de OID ---------------------------------------------------------
def branch_root(oid: str, depth: int) -> str:
    """Raíz de 'rama' de un OID: enterprise + `depth` arcos (p. ej. 2011.6.128).

    Para OIDs fuera de enterprises se usa el OID sin sus 2 últimos arcos.
    """
    arcs = oid.lstrip(".").split(".")
    if oid.lstrip(".").startswith(ENTERPRISES + "."):
        return ".".join(arcs[: _ENTERPRISES_ARCS + depth])
    return ".".join(arcs[: max(1, len(arcs) - 2)])
