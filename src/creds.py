"""Credenciales de OLT por vendor (y modelo) desde variables de entorno.

Convención (todas opcionales, se cargan del `.env`):

    TKC_<VENDOR>_<CLAVE>              p. ej. TKC_ZTE_RO_COMMUNITY, TKC_VSOL_HOST
    TKC_<VENDOR>_<MODELO>_<CLAVE>     override por equipo, p. ej. TKC_ZTE_C600_RO_COMMUNITY

Claves:
    HOST                 IP/host del equipo
    SNMP_PORT            puerto UDP SNMP (por defecto 161)
    RO_COMMUNITY         community SNMPv2c de solo lectura (la UNICA que usan colector y scripts)
    RW_COMMUNITY         community de lectura-escritura: solo se ALMACENA; ningun script la lee
                         para consultar (lo garantiza tests/test_creds.py)
    SNMPV3_USER, SNMPV3_AUTH_PROTO (MD5|SHA|SHA224|SHA256), SNMPV3_AUTH_PASSWORD,
    SNMPV3_PRIV_PROTO (DES|AES), SNMPV3_PRIV_PASSWORD
    CLI_HOST (por defecto HOST), CLI_PROTO (telnet|ssh), CLI_PORT, CLI_USER, CLI_PASSWORD

Precedencia: modelo → vendor → variables antiguas (TKC_SNMP_*, TKC_TELNET_*), estas
ÚLTIMAS solo para los vendors con `legacy_env: true` en config/vendors.yaml, para que
las credenciales históricas de ZTE jamás se usen contra otro fabricante.

Los valores nunca se imprimen: `describe()` solo informa nombre y presencia.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping, Optional

from .profiles import default_registry

KEYS = ("HOST", "SNMP_PORT", "RO_COMMUNITY", "RW_COMMUNITY",
        "SNMPV3_USER", "SNMPV3_AUTH_PROTO", "SNMPV3_AUTH_PASSWORD",
        "SNMPV3_PRIV_PROTO", "SNMPV3_PRIV_PASSWORD",
        "CLI_HOST", "CLI_PROTO", "CLI_PORT", "CLI_USER", "CLI_PASSWORD")
SECRET_KEYS = {"RO_COMMUNITY", "RW_COMMUNITY", "SNMPV3_AUTH_PASSWORD", "SNMPV3_PRIV_PASSWORD", "CLI_PASSWORD"}

# clave nueva → variable antigua (solo vendors con legacy_env)
LEGACY = {"HOST": "TKC_SNMP_HOST", "SNMP_PORT": "TKC_SNMP_PORT",
          "RO_COMMUNITY": "TKC_SNMP_COMMUNITY", "CLI_PORT": "TKC_TELNET_PORT",
          "CLI_USER": "TKC_TELNET_USER", "CLI_PASSWORD": "TKC_TELNET_PASSWORD",
          "CLI_HOST": "TKC_TELNET_HOST"}
# claves que, si faltan, heredan de otra clave del mismo vendor
FALLBACK_KEY = {"CLI_HOST": "HOST"}


def _tag(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


@dataclass(frozen=True)
class Resolved:
    key: str
    var: Optional[str]          # nombre de la variable de la que salió (None si no hay)
    value: Optional[str]

    @property
    def present(self) -> bool:
        return bool(self.value and self.value.strip())


def candidates(vendor: str, key: str, model: Optional[str] = None) -> list[str]:
    """Nombres de variable en orden de precedencia."""
    v = _tag(vendor)
    out = []
    if model:
        out.append(f"TKC_{v}_{_tag(model)}_{key}")
    out.append(f"TKC_{v}_{key}")
    if default_registry().get(vendor).legacy_env and key in LEGACY:
        out.append(LEGACY[key])
    return out


def resolve(vendor: str, key: str, model: Optional[str] = None,
            environ: Mapping[str, str] | None = None) -> Resolved:
    env = os.environ if environ is None else environ
    for var in candidates(vendor, key, model):
        val = env.get(var, "")
        if val and val.strip():
            return Resolved(key, var, val.strip())
    fb = FALLBACK_KEY.get(key)
    if fb:
        r = resolve(vendor, fb, model, env)
        if r.present:
            return Resolved(key, r.var, r.value)
    return Resolved(key, None, None)


def get(vendor: str, key: str, model: Optional[str] = None,
        environ: Mapping[str, str] | None = None) -> Optional[str]:
    r = resolve(vendor, key, model, environ)
    return r.value if r.present else None


def overlay(vendor: str, model: Optional[str], environ: Mapping[str, str] | None,
            names: Mapping[str, str]) -> dict[str, str]:
    """Copia del entorno donde las variables `names` (nombre configurado → CLAVE)
    toman el valor por vendor/modelo si existe. Sin variables por vendor es identidad."""
    env = dict(os.environ if environ is None else environ)
    for configured, key in names.items():
        r = resolve(vendor, key, model, env)
        if r.present:
            env[configured] = r.value
    return env


def describe(vendor: str, model: Optional[str] = None,
             environ: Mapping[str, str] | None = None) -> list[dict]:
    """Presencia (nunca el valor) de cada clave: para `--dry-run` y diagnóstico."""
    rows = []
    for key in KEYS:
        r = resolve(vendor, key, model, environ)
        rows.append({"key": key, "present": r.present, "var": r.var,
                     "secret": key in SECRET_KEYS,
                     "expected": candidates(vendor, key, model)[0 if not model else 1]})
    return rows
