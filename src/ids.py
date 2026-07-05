"""Construcción de IDs canónicos y utilidades de nombres.

Los patrones de ID son los definidos en los schemas/*.json:
    entity.{vendor}.{technology}.{type}.{canonical_name_snake}
    command.{vendor}.{technology}.{entity}.{category}
    oid.{vendor}.{technology}.{entity}.{metric}
    alarm.{vendor}.{technology}.{entity}.{alarm_name_snake}
    rel.{vendor}.{technology}.{source_entity}.{relation_type}.{target_entity}
"""
from __future__ import annotations

import re


def snake(name: str) -> str:
    """Convierte un nombre a snake_case ASCII seguro para IDs y nombres de archivo."""
    name = name.strip().lower()
    name = re.sub(r"[\s\-/]+", "_", name)
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def build_entity_id(vendor: str, technology: str, entity_type: str, canonical_name: str) -> str:
    return f"entity.{vendor.lower()}.{technology.lower()}.{entity_type}.{snake(canonical_name)}"


def build_command_id(vendor: str, technology: str, entity: str, category: str) -> str:
    """`entity` es el nombre corto de la entidad (ej: 'onu') o 'global'."""
    return f"command.{vendor.lower()}.{technology.lower()}.{snake(entity)}.{category}"


def build_oid_id(vendor: str, technology: str, entity: str, metric: str) -> str:
    return f"oid.{vendor.lower()}.{technology.lower()}.{snake(entity)}.{snake(metric)}"


def build_alarm_id(vendor: str, technology: str, entity: str, alarm_name: str) -> str:
    return f"alarm.{vendor.lower()}.{technology.lower()}.{snake(entity)}.{snake(alarm_name)}"


def build_relation_id(vendor: str, technology: str, source_entity: str,
                      relation_type: str, target_entity: str) -> str:
    src = entity_short_name(source_entity)
    tgt = entity_short_name(target_entity)
    return f"rel.{vendor.lower()}.{technology.lower()}.{src}.{relation_type}.{tgt}"


def entity_short_name(entity_id: str) -> str:
    """Último segmento de un entity id. 'entity.zte.gpon.device.onu' -> 'onu'.

    Si recibe un nombre suelto lo devuelve en snake_case.
    """
    if entity_id and entity_id.startswith("entity."):
        return entity_id.split(".")[-1]
    return snake(entity_id or "")
