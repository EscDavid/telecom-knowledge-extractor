"""Configuración del recolector: carga/validación de ``walk_collector`` en
``config/pipeline.yaml`` y resolución de credenciales desde el entorno.

Aquí NO hay secretos: el YAML solo nombra las variables de entorno. Los mensajes de
error nombran la variable faltante, jamás su valor.
"""
from __future__ import annotations

import copy
import dataclasses
import getpass as _getpass
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from .oid import Oid, fmt_oid, parse_oid
from .secrets import Secret

log = logging.getLogger("tkc.walk_collector.config")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "pipeline.yaml"

# Tope duro de repeticiones por GETBULK: con más, la respuesta supera 1472 B, se
# fragmenta IP y se pierde (medido en producción en isp-management).
MAX_REPETITIONS_HARD_CAP = 20


class ConfigError(Exception):
    """Configuración o credenciales inválidas (exit 2)."""


@dataclass
class SnmpCfg:
    version: str = "2c"
    host_env: str = "TKC_SNMP_HOST"
    port_env: str = "TKC_SNMP_PORT"
    community_env: str = "TKC_SNMP_COMMUNITY"
    default_port: int = 161
    timeout_s: float = 3.0
    max_repetitions: int = 20
    min_repetitions: int = 1
    preflight_attempts: int = 3


@dataclass
class PacingCfg:
    inter_request_delay_ms: float = 50
    inter_task_delay_s: float = 2
    checkpoint_every_requests: int = 25
    checkpoint_every_s: float = 5


@dataclass
class RetryCfg:
    max_attempts_per_request: int = 4
    backoff_base_s: float = 2
    backoff_max_s: float = 60
    jitter: float = 0.2
    final_retry_rounds: int = 1
    max_stall_pdus: int = 3
    max_bumps_per_task: int = 20


@dataclass
class OutageCfg:
    sanity_oid: Oid = (1, 3, 6, 1, 2, 1, 1, 1, 0)
    wait_s: tuple[float, ...] = (30, 60, 120, 300)
    max_outage_min: float = 30


@dataclass
class SafetyCfg:
    latency_window: int = 50
    baseline_samples: int = 20
    degrade_factor: float = 4.0
    degrade_min_ms: float = 800
    sustain_checks: int = 3
    pause_s: float = 120
    max_safety_pauses: int = 3
    max_runtime_min: float = 0


@dataclass
class OutputCfg:
    name: str
    suffix: str
    roots: tuple[Oid, ...]
    discover: bool = False


@dataclass
class DiscoveryCfg:
    base_depth: int = 2
    expand: tuple[Oid, ...] = ()
    max_children: int = 500


@dataclass
class PathsCfg:
    state_dir: Path = Path("state/walk_collector")
    publish_dir: Path = Path("docs/walks")


@dataclass
class RedactionCfg:
    mode: str = "none"
    prefixes: tuple[Oid, ...] = ()


@dataclass
class CollectorConfig:
    vendor: str
    model: str
    expect_sysdescr_regex: str
    snmp: SnmpCfg
    pacing: PacingCfg
    retry: RetryCfg
    outage: OutageCfg
    safety: SafetyCfg
    outputs: dict[str, OutputCfg]
    discovery: DiscoveryCfg
    paths: PathsCfg
    allow_incomplete: bool = False
    redaction: RedactionCfg = field(default_factory=RedactionCfg)

    @property
    def model_key(self) -> str:
        """``ZTE_C620`` — prefijo de los archivos publicados."""
        return f"{self.vendor}_{self.model}"

    @property
    def run_dir(self) -> Path:
        """Directorio de estado de ESTE modelo: ``<state_dir>/ZTE_C620/``."""
        return self.paths.state_dir / self.model_key

    def output_filename(self, output: str) -> str:
        return f"{self.model_key}{self.outputs[output].suffix}.txt"

    def config_hash(self) -> str:
        """Hash de lo que define QUÉ se recolecta (no del ritmo: ese puede cambiar al reanudar)."""
        basis = {
            "vendor": self.vendor, "model": self.model,
            "outputs": {k: [o.suffix, [fmt_oid(r) for r in o.roots], o.discover]
                        for k, o in sorted(self.outputs.items())},
            "discovery": [self.discovery.base_depth,
                          [fmt_oid(e) for e in self.discovery.expand],
                          self.discovery.max_children],
        }
        raw = json.dumps(basis, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:16]


# --- carga -----------------------------------------------------------------
def _section(d: Mapping, key: str, where: str) -> Mapping:
    if key not in d or not isinstance(d[key], Mapping):
        raise ConfigError(f"falta la sección '{where}{key}' en la configuración")
    return d[key]


def _get(d: Mapping, key: str, where: str, cast: Callable = lambda x: x, required: bool = True,
         default: Any = None):
    if key not in d:
        if required:
            raise ConfigError(f"falta la clave '{where}{key}' en la configuración")
        return default
    try:
        return cast(d[key])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"valor inválido en '{where}{key}': {exc}") from None


def _oid_list(values: Any, where: str) -> tuple[Oid, ...]:
    if not isinstance(values, (list, tuple)):
        raise ConfigError(f"'{where}' debe ser una lista de OIDs")
    try:
        return tuple(parse_oid(str(v)) for v in values)
    except ValueError as exc:
        raise ConfigError(f"'{where}': {exc}") from None


def _deep_merge(base: dict, extra: Mapping) -> dict:
    for k, v in extra.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def parse_collector_config(raw: Mapping, repo_root: Path = REPO_ROOT) -> CollectorConfig:
    """Valida el dict de ``walk_collector`` y construye la configuración."""
    w = "walk_collector."
    vendor = str(_get(raw, "vendor", w))
    model = str(_get(raw, "model", w))
    regex = str(_get(raw, "expect_sysdescr_regex", w))
    try:
        re.compile(regex)
    except re.error as exc:
        raise ConfigError(f"expect_sysdescr_regex inválida: {exc}") from None

    s = _section(raw, "snmp", w)
    version = str(_get(s, "version", w + "snmp."))
    if version.lower() != "2c":
        raise ConfigError(f"snmp.version '{version}' no soportada: solo SNMPv2c ('2c')")
    snmp = SnmpCfg(
        version="2c",
        host_env=str(_get(s, "host_env", w + "snmp.")),
        port_env=str(_get(s, "port_env", w + "snmp.")),
        community_env=str(_get(s, "community_env", w + "snmp.")),
        default_port=_get(s, "default_port", w + "snmp.", int),
        timeout_s=_get(s, "timeout_s", w + "snmp.", float),
        max_repetitions=_get(s, "max_repetitions", w + "snmp.", int),
        min_repetitions=_get(s, "min_repetitions", w + "snmp.", int),
        preflight_attempts=_get(s, "preflight_attempts", w + "snmp.", int),
    )
    if snmp.max_repetitions > MAX_REPETITIONS_HARD_CAP:
        log.warning("snmp.max_repetitions=%d supera el tope duro; se recorta a %d "
                    "(con más, los datagramas superan 1472 B y se pierden)",
                    snmp.max_repetitions, MAX_REPETITIONS_HARD_CAP)
        snmp.max_repetitions = MAX_REPETITIONS_HARD_CAP
    if snmp.min_repetitions < 1 or snmp.min_repetitions > snmp.max_repetitions:
        raise ConfigError("snmp.min_repetitions debe estar entre 1 y max_repetitions")
    if snmp.timeout_s <= 0 or snmp.preflight_attempts < 1:
        raise ConfigError("snmp.timeout_s y snmp.preflight_attempts deben ser positivos")

    p = _section(raw, "pacing", w)
    pacing = PacingCfg(
        inter_request_delay_ms=_get(p, "inter_request_delay_ms", w + "pacing.", float),
        inter_task_delay_s=_get(p, "inter_task_delay_s", w + "pacing.", float),
        checkpoint_every_requests=_get(p, "checkpoint_every_requests", w + "pacing.", int),
        checkpoint_every_s=_get(p, "checkpoint_every_s", w + "pacing.", float),
    )
    r = _section(raw, "retry", w)
    retry = RetryCfg(
        max_attempts_per_request=_get(r, "max_attempts_per_request", w + "retry.", int),
        backoff_base_s=_get(r, "backoff_base_s", w + "retry.", float),
        backoff_max_s=_get(r, "backoff_max_s", w + "retry.", float),
        jitter=_get(r, "jitter", w + "retry.", float),
        final_retry_rounds=_get(r, "final_retry_rounds", w + "retry.", int),
        max_stall_pdus=_get(r, "max_stall_pdus", w + "retry.", int),
        max_bumps_per_task=_get(r, "max_bumps_per_task", w + "retry.", int),
    )
    if retry.max_attempts_per_request < 1 or retry.max_stall_pdus < 1 or retry.max_bumps_per_task < 1:
        raise ConfigError("retry.* de límites debe ser >= 1")
    o = _section(raw, "outage", w)
    outage = OutageCfg(
        sanity_oid=parse_oid(str(_get(o, "sanity_oid", w + "outage."))),
        wait_s=tuple(_get(o, "wait_s", w + "outage.", lambda v: [float(x) for x in v])),
        max_outage_min=_get(o, "max_outage_min", w + "outage.", float),
    )
    if not outage.wait_s:
        raise ConfigError("outage.wait_s no puede estar vacío")
    sf = _section(raw, "safety", w)
    safety = SafetyCfg(
        latency_window=_get(sf, "latency_window", w + "safety.", int),
        baseline_samples=_get(sf, "baseline_samples", w + "safety.", int),
        degrade_factor=_get(sf, "degrade_factor", w + "safety.", float),
        degrade_min_ms=_get(sf, "degrade_min_ms", w + "safety.", float),
        sustain_checks=_get(sf, "sustain_checks", w + "safety.", int),
        pause_s=_get(sf, "pause_s", w + "safety.", float),
        max_safety_pauses=_get(sf, "max_safety_pauses", w + "safety.", int),
        max_runtime_min=_get(sf, "max_runtime_min", w + "safety.", float),
    )

    outs_raw = _section(raw, "outputs", w)
    outputs: dict[str, OutputCfg] = {}
    for name, body in outs_raw.items():
        if not isinstance(body, Mapping):
            raise ConfigError(f"outputs.{name} debe ser un mapa")
        roots = _oid_list(_get(body, "roots", f"{w}outputs.{name}."), f"outputs.{name}.roots")
        if not roots:
            raise ConfigError(f"outputs.{name}.roots no puede estar vacío")
        outputs[str(name)] = OutputCfg(
            name=str(name), suffix=str(_get(body, "suffix", f"{w}outputs.{name}.")),
            roots=roots, discover=bool(_get(body, "discover", f"{w}outputs.{name}.")))
    if not outputs:
        raise ConfigError("walk_collector.outputs está vacío")

    dsc = _section(raw, "discovery", w)
    discovery = DiscoveryCfg(
        base_depth=_get(dsc, "base_depth", w + "discovery.", int),
        expand=_oid_list(_get(dsc, "expand", w + "discovery."), "discovery.expand"),
        max_children=_get(dsc, "max_children", w + "discovery.", int),
    )
    pa = _section(raw, "paths", w)
    paths = PathsCfg(
        state_dir=_resolve_path(str(_get(pa, "state_dir", w + "paths.")), repo_root),
        publish_dir=_resolve_path(str(_get(pa, "publish_dir", w + "paths.")), repo_root),
    )
    pub = _section(raw, "publish", w)
    red = _section(raw, "redaction", w)
    mode = str(_get(red, "mode", w + "redaction."))
    if mode not in ("none", "prefixes"):
        raise ConfigError("redaction.mode debe ser 'none' o 'prefixes'")
    redaction = RedactionCfg(mode=mode, prefixes=_oid_list(
        _get(red, "prefixes", w + "redaction.", required=False, default=[]), "redaction.prefixes"))
    return CollectorConfig(
        vendor=vendor, model=model, expect_sysdescr_regex=regex, snmp=snmp, pacing=pacing,
        retry=retry, outage=outage, safety=safety, outputs=outputs, discovery=discovery,
        paths=paths, allow_incomplete=bool(_get(pub, "allow_incomplete", w + "publish.")),
        redaction=redaction)


def _resolve_path(value: str, repo_root: Path) -> Path:
    """Expande ``%VAR%``/``$VAR`` y ``~``; lo relativo cuelga de la raíz del repo."""
    p = Path(os.path.expanduser(os.path.expandvars(value)))
    return p if p.is_absolute() else (repo_root / p)


def load_collector_config(path: str | Path = DEFAULT_CONFIG, overrides: Mapping | None = None,
                          repo_root: Path = REPO_ROOT) -> CollectorConfig:
    """Lee ``walk_collector`` de ``pipeline.yaml``; ``overrides`` (mapa anidado) se fusiona encima."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except OSError as exc:
        raise ConfigError(f"no se pudo leer la configuración {path}: {exc.strerror}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML inválido en {path}: {exc}") from None
    if not isinstance(data, Mapping) or "walk_collector" not in data:
        raise ConfigError(f"falta la sección 'walk_collector' en {path}")
    raw = copy.deepcopy(dict(data["walk_collector"]))
    if overrides:
        _deep_merge(raw, overrides)
    return parse_collector_config(raw, repo_root)


def lower_max_repetitions(cfg: CollectorConfig, n: int) -> CollectorConfig:
    """``--max-repetitions``: SOLO puede bajar el valor (nunca superar el configurado ni 20)."""
    if n < 1:
        raise ConfigError("--max-repetitions debe ser >= 1")
    if n > cfg.snmp.max_repetitions:
        log.warning("--max-repetitions %d ignorado: solo puede bajar (actual %d, tope duro %d)",
                    n, cfg.snmp.max_repetitions, MAX_REPETITIONS_HARD_CAP)
        return cfg
    snmp = dataclasses.replace(cfg.snmp, max_repetitions=n,
                               min_repetitions=min(cfg.snmp.min_repetitions, n))
    return dataclasses.replace(cfg, snmp=snmp)


# --- credenciales ------------------------------------------------------------
@dataclass
class Credentials:
    host: str
    port: int
    community: Secret

    def masked_host(self) -> str:
        return mask_host(self.host)

    @property
    def target_id(self) -> str:
        return target_id(self.host, self.port)


def target_id(host: str, port: int) -> str:
    return hashlib.sha256(f"{host}:{port}".encode()).hexdigest()[:16]


def mask_host(host: str) -> str:
    """``10.20.30.239`` → ``x.x.x.239``; nombres DNS → ``***`` + último tramo."""
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return "x.x.x." + parts[-1]
    return "***" + (("." + parts[-1]) if len(parts) > 1 else "")


def env_presence(cfg: CollectorConfig, environ: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Presencia (NO valor) de las variables SNMP — para ``--dry-run``."""
    env = os.environ if environ is None else environ
    return {name: bool(env.get(name, "").strip()) for name in
            (cfg.snmp.host_env, cfg.snmp.port_env, cfg.snmp.community_env)}


def load_credentials(cfg: CollectorConfig, *, no_prompt: bool = False,
                     environ: Mapping[str, str] | None = None,
                     getpass: Callable[[str], str] = _getpass.getpass,
                     isatty: Callable[[], bool] | None = None) -> Credentials:
    """Host/puerto/community desde el entorno. Community vacía → prompt oculto.

    Sin tty o con ``no_prompt`` la community vacía es un error (nombra la variable).
    """
    env = os.environ if environ is None else environ
    host = env.get(cfg.snmp.host_env, "").strip()
    if not host:
        raise ConfigError(f"falta la variable de entorno {cfg.snmp.host_env} (host de la OLT)")
    port_txt = env.get(cfg.snmp.port_env, "").strip()
    try:
        port = int(port_txt) if port_txt else cfg.snmp.default_port
    except ValueError:
        raise ConfigError(f"{cfg.snmp.port_env} debe ser un entero") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"{cfg.snmp.port_env} fuera de rango")
    comm = env.get(cfg.snmp.community_env, "")
    if not comm.strip():
        if isatty is None:
            isatty = sys.stdin.isatty
        if no_prompt or not isatty():
            raise ConfigError(f"falta la variable de entorno {cfg.snmp.community_env} "
                              "(community) y no hay prompt disponible (--no-prompt o sin tty)")
        comm = getpass("SNMP community (no se muestra): ")
        if not comm.strip():
            raise ConfigError("community vacía")
    return Credentials(host=host, port=port, community=Secret(comm.strip()))
