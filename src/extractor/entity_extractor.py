"""EntityExtractor — identifica sustantivos técnicos gestionables en cualquier doc.

Reconoce conceptos de un vocabulario controlado (ONU, OLT, GEM Port, VLAN, ...)
y los emite como Entity con su `type` GPON. La frecuencia de aparición ajusta la
calidad de extracción (mención directa vs. inferencia por contexto).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import (QUALITY_DIRECT_NO_PAGE, QUALITY_INFERRED_CONTEXT,
                      Entity, Source)

log = logging.getLogger("tkc.extractor.entity")

# vocabulario: (regex, canonical_name, type, is_critical)
ENTITY_VOCAB: list[tuple[str, str, str, bool]] = [
    (r"\bONUs?\b|\bONTs?\b",            "ONU",            "device",   True),
    (r"\bOLT\b",                         "OLT",            "device",   True),
    (r"\bGEM\s*ports?\b",                "GEM Port",       "logical",  True),
    (r"\bservice\s*ports?\b",            "Service Port",   "logical",  True),
    (r"\bVLANs?\b",                      "VLAN",           "logical",  False),
    (r"\bPON\s*ports?\b",                "PON Port",       "port",     True),
    (r"\buplink\s*ports?\b",             "Uplink Port",    "port",     False),
    (r"\bline\s*profiles?\b",            "Line Profile",   "profile",  True),
    (r"\bservice\s*profiles?\b",         "Service Profile","profile",  True),
    (r"\bcards?\b|\bboards?\b",          "Card",           "hardware", False),
    (r"\bshelf\b|\bchassis\b",           "Shelf",          "hardware", False),
    (r"\bDBA\b",                          "DBA",            "protocol", False),
    (r"\bIGMP\b",                         "IGMP",           "protocol", False),
]

# umbral de menciones para considerar la extracción "directa" vs "inferida"
_DIRECT_THRESHOLD = 3


class EntityExtractor:
    def __init__(self, vendor: str, family: str, technology: str, firmware: list[str]):
        self.vendor = vendor
        self.family = family
        self.technology = technology
        self.firmware = firmware

    def extract(self, text: str, doc_type: str) -> list[Entity]:
        if not text:
            return []
        entities: list[Entity] = []
        for regex, canonical, etype, critical in ENTITY_VOCAB:
            count = len(re.findall(regex, text, re.IGNORECASE))
            if count == 0:
                continue
            quality = (QUALITY_DIRECT_NO_PAGE if count >= _DIRECT_THRESHOLD
                       else QUALITY_INFERRED_CONTEXT)
            entities.append(Entity(
                canonical_name=canonical, vendor=self.vendor, family=self.family,
                technology=self.technology, type=etype, is_critical=critical,
                firmware=list(self.firmware),
                description=self._first_mention(text, regex),
                sources=[Source(doc_type=doc_type, pages=None, confidence=0.0,
                                quality=quality)],
            ))
        log.info("EntityExtractor(%s): %d entidad(es)", doc_type, len(entities))
        return entities

    @staticmethod
    def _first_mention(text: str, regex: str) -> Optional[str]:
        m = re.search(rf"([^.\n]*{regex}[^.\n]*)\.", text, re.IGNORECASE)
        if not m:
            return None
        snippet = " ".join(m.group(1).split())
        return snippet[:240] if snippet else None
