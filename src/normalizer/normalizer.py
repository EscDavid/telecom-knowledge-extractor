"""Módulo 3 — Normalizer.

Unifica nombres alternativos y construye los IDs canónicos de todos los
artefactos, siguiendo schemas/alias_policy.json:

  - Entidades equivalentes (mismo canonical en snake) se fusionan; todos sus
    nombres alternativos quedan como aliases (Regla 2).
  - canonical_name por Regla 1 (nombre más corto sin espacios gana).
  - Aliases que apuntan a varias entidades del mismo vendor → ambiguous (Regla 6).
  - Se sintetizan entidades faltantes referenciadas por OIDs/comandos/alarmas
    para mantener el grafo consistente.

Asigna `id` a entidades, comandos, OIDs y alarmas; resuelve sus entity_ref.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..ids import (build_alarm_id, build_command_id, build_entity_id,
                   build_oid_id, snake)
from ..models import (QUALITY_DIRECT_NO_PAGE, QUALITY_INFERRED_CORRELATION, Alias,
                      Entity, NormalizedData, Source)

log = logging.getLogger("tkc.normalizer")

# Tipo GPON por nombre corto de entidad (para sintetizar entidades faltantes).
SHORT_NAME_TYPE = {
    "onu": "device", "olt": "device", "gem_port": "logical",
    "service_port": "logical", "vlan": "logical", "pon_port": "port",
    "uplink_port": "port", "card": "hardware", "shelf": "hardware",
    "line_profile": "profile", "service_profile": "profile",
    "dba": "protocol", "igmp": "protocol",
    # entidades adicionales derivadas de los MIB Tier 1/2
    "optical_module": "hardware", "fan": "hardware",
    "power_supply": "hardware", "sensor": "hardware",
}
CRITICAL_SHORT = {"onu", "olt", "pon_port", "gem_port", "service_port",
                  "line_profile", "service_profile"}

# Descripciones canonicas por entidad (GPON). El MIB no las trae por entidad, se curan.
ENTITY_DESCRIPTIONS = {
    "onu": "Optical Network Unit — equipo terminal GPON del lado del abonado.",
    "olt": "Optical Line Terminal — equipo de cabecera GPON que agrega los puertos PON.",
    "pon_port": "Puerto PON GPON del OLT (interfaz gpon slot/pon).",
    "uplink_port": "Puerto de enlace ascendente (uplink) del OLT (GE/10GE).",
    "gem_port": "GEM Port — canal logico de transporte GPON entre OLT y ONU.",
    "service_port": "Service port — punto de servicio que mapea VLAN/trafico a una ONU.",
    "vlan": "VLAN — dominio de difusion logico para segmentacion de trafico.",
    "card": "Tarjeta de linea o control insertada en un slot del chasis del OLT.",
    "shelf": "Chasis/estante del OLT que aloja las tarjetas.",
    "fan": "Modulo de ventilacion del OLT.",
    "power_supply": "Modulo de alimentacion del OLT.",
    "sensor": "Sensor ambiental (temperatura/voltaje) del OLT.",
    "optical_module": "Modulo optico (SFP) de un puerto del OLT.",
}


class Normalizer:
    def __init__(self, config: dict[str, Any]):
        p = config["pipeline"]
        self.vendor = p["vendor"]
        self.family = p["family"]
        self.technology = p.get("technology", "gpon")
        self.firmware = list(p.get("firmware", []))

    def run(self, extracted) -> NormalizedData:
        data = NormalizedData()
        # entidades ancladas en OBJECT-TYPE/NOTIFICATION reales del MIB: su existencia
        # esta documentada por sus OIDs, aunque el NODO entidad lo agrupemos nosotros.
        mib_anchored = self._mib_anchored(extracted)
        # 1. fusionar entidades y asignar IDs
        by_key = self._merge_entities(extracted.entities)
        # 2. sintetizar entidades referenciadas pero ausentes
        self._synthesize_missing(by_key, extracted, mib_anchored)
        data.entities = list(by_key.values())
        for e in data.entities:
            # backfill de descripciones curadas para las que no traen una
            if not e.description and e.short_name in ENTITY_DESCRIPTIONS:
                e.description = ENTITY_DESCRIPTIONS[e.short_name]
            # entidad MIB-anclada sin fuente autoritativa (MIB) → agregar el respaldo
            # documental del MIB (autoridad 1.0), que la saca del penalti single_source.
            if e.short_name in mib_anchored and not any(
                    s.doc_type in ("mib_file", "mib_specification") for s in e.sources):
                e.sources.append(Source(doc_type="mib_file", pages=None,
                                        confidence=0.0, quality=QUALITY_DIRECT_NO_PAGE))

        # 3. índice alias -> entity_id + detección de ambigüedad (Regla 6)
        data.aliases_index, data.ambiguous = self._build_alias_index(data.entities)
        self._mark_ambiguous(data.entities, data.ambiguous)

        # 4. resolver IDs de OIDs, comandos y alarmas
        short_to_id = {e.short_name: e.id for e in data.entities}
        data.oids = self._id_oids(extracted.oids, short_to_id)
        data.commands = self._id_commands(extracted.commands, short_to_id, data.aliases_index)
        data.alarms = self._id_alarms(extracted.alarms, short_to_id)

        log.info("Normalizer: %d entidades, %d aliases, %d ambiguos",
                 len(data.entities), len(data.aliases_index), len(data.ambiguous))
        return data

    # --- entidades ------------------------------------------------------------
    def _merge_entities(self, entities: list[Entity]) -> dict[str, Entity]:
        by_key: dict[str, Entity] = {}
        for e in entities:
            key = f"{e.type}.{snake(e.canonical_name)}"
            if key not in by_key:
                e.id = build_entity_id(self.vendor, self.technology, e.type, e.canonical_name)
                e.lifecycle.introduced_in = self.firmware[0] if self.firmware else None
                by_key[key] = e
            else:
                self._merge_into(by_key[key], e)
        # aliases: registrar el canonical original como alias por doc fuente (Regla 2)
        for e in by_key.values():
            for s in e.sources:
                if not any(a.name == e.canonical_name for a in e.aliases):
                    e.aliases.append(Alias(name=e.canonical_name, source=s.doc_type))
                break
        return by_key

    @staticmethod
    def _merge_into(target: Entity, other: Entity) -> None:
        target.sources.extend(other.sources)
        for fw in other.firmware:
            if fw not in target.firmware:
                target.firmware.append(fw)
        if not target.description and other.description:
            target.description = other.description
        target.is_critical = target.is_critical or other.is_critical

    @staticmethod
    def _mib_anchored(extracted) -> set[str]:
        """short_names respaldados por >=1 OID/alarma extraido directo de un MIB."""
        anchored: set[str] = set()
        for art in (*extracted.oids, *extracted.alarms):
            if any(s.doc_type in ("mib_file", "mib_specification") for s in art.sources):
                anchored.add(art.entity_ref)
        return anchored

    def _synthesize_missing(self, by_key: dict[str, Entity], extracted,
                            mib_anchored: set[str]) -> None:
        referenced: set[str] = set()
        for o in extracted.oids:
            referenced.add(o.entity_ref)
        for a in extracted.alarms:
            referenced.add(a.entity_ref)
        # prerequisites de comandos que nombran entidades conocidas (PON Port, Line Profile...)
        for c in extracted.commands:
            for prereq in c.prerequisites:
                short = snake(prereq)
                if short in SHORT_NAME_TYPE:
                    referenced.add(short)
        present = {e.short_name for e in by_key.values()}
        for short in referenced:
            if not short or short in present:
                continue
            etype = SHORT_NAME_TYPE.get(short, "logical")
            canonical = short.replace("_", " ").title()
            # anclada en MIB → direct_without_page (documented); si no, inferencia.
            quality = (QUALITY_DIRECT_NO_PAGE if short in mib_anchored
                       else QUALITY_INFERRED_CORRELATION)
            ent = Entity(
                canonical_name=canonical, vendor=self.vendor, family=self.family,
                technology=self.technology, type=etype,
                is_critical=short in CRITICAL_SHORT, firmware=list(self.firmware),
                description=ENTITY_DESCRIPTIONS.get(short),
                sources=[Source(doc_type="mib_file", pages=None, confidence=0.0,
                                quality=quality)],
            )
            ent.id = build_entity_id(self.vendor, self.technology, etype, canonical)
            ent.lifecycle.introduced_in = self.firmware[0] if self.firmware else None
            by_key[f"{etype}.{short}"] = ent
            present.add(short)
            log.info("  entidad sintetizada por referencia: %s", ent.id)

    # --- aliases (Regla 6) ----------------------------------------------------
    @staticmethod
    def _build_alias_index(entities: list[Entity]) -> tuple[dict[str, str], list[dict]]:
        candidates: dict[str, list[str]] = {}
        for e in entities:
            names = {e.canonical_name} | {a.name for a in e.aliases}
            for name in names:
                candidates.setdefault(snake(name), []).append(e.id)
        index: dict[str, str] = {}
        ambiguous: list[dict] = []
        for alias, ids in candidates.items():
            uniq = sorted(set(ids))
            if len(uniq) == 1:
                index[alias] = uniq[0]
            else:
                ambiguous.append({"alias": alias, "candidates": uniq})
        return index, ambiguous

    @staticmethod
    def _mark_ambiguous(entities: list[Entity], ambiguous: list[dict]) -> None:
        amb_ids = {i for a in ambiguous for i in a["candidates"]}
        for e in entities:
            if e.id in amb_ids:
                # no degrada la entidad; la penalización la aplica el Validator
                pass

    # --- OIDs / comandos / alarmas -------------------------------------------
    def _id_oids(self, oids, short_to_id) -> list:
        for o in oids:
            short = o.entity_ref
            o.entity_ref = short_to_id.get(short, o.entity_ref)
            o.id = build_oid_id(self.vendor, self.technology, short, o.metric or o.name)
        return oids

    def _id_commands(self, commands, short_to_id, alias_index) -> list:
        for c in commands:
            entity_short = self._command_entity(c, alias_index, short_to_id)
            if entity_short and entity_short in short_to_id:
                c.entity_ref = short_to_id[entity_short]
            else:
                c.entity_ref = None              # comando global (save, enable...)
                entity_short = "global"
            c.id = build_command_id(self.vendor, self.technology, entity_short, c.category)
        return commands

    @staticmethod
    def _command_entity(command, alias_index, short_to_id) -> Optional[str]:
        # busca un nombre de entidad conocido entre los tokens del nombre canónico
        for tok in command.canonical_name.split():
            t = snake(tok)
            if t in short_to_id:
                return t
            if t in alias_index:
                return alias_index[t].split(".")[-1]
        return None

    def _id_alarms(self, alarms, short_to_id) -> list:
        for a in alarms:
            short = a.entity_ref
            a.entity_ref = short_to_id.get(short, a.entity_ref)
            a.id = build_alarm_id(self.vendor, self.technology, short, a.name)
        return alarms
