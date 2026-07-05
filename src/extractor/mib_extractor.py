"""MibExtractor — parseo de archivos .my/.mib (ASN.1 SMI).

Extrae cada OBJECT-TYPE como un Oid, resolviendo su OID numérico a partir de las
asignaciones `name ::= { parent N }` del módulo. Detecta índices compuestos ZTE
(32 bits) y marca bit_calculation.

Sin dependencias externas — todo regex.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..models import (QUALITY_DIRECT_NO_PAGE, Alarm, Oid, OidIndex, Source)
from ..ids import snake

log = logging.getLogger("tkc.extractor.mib")

# Raíces numéricas conocidas para resolver OIDs simbólicos.
KNOWN_ROOTS = {
    "iso": "1",
    "org": "1.3",
    "dod": "1.3.6",
    "internet": "1.3.6.1",
    "private": "1.3.6.1.4",
    "enterprises": "1.3.6.1.4.1",
}

# Palabras clave de entidad detectables en el nombre del objeto MIB.
# El orden importa: gana la primera subcadena que aparece. Las entidades
# específicas (card, onu...) van primero; las añadidas al final capturan objetos
# que de otro modo caerían al genérico "olt" (óptica, ventiladores, energía,
# sensores ambientales, service ports con nomenclatura zxAnSrvPort...).
_ENTITY_KEYWORDS = [
    ("ont", "onu"), ("onu", "onu"), ("olt", "olt"), ("gem", "gem_port"),
    ("serviceport", "service_port"), ("ponport", "pon_port"), ("pon", "pon_port"),
    ("uplink", "uplink_port"), ("card", "card"), ("shelf", "shelf"),
    ("vlan", "vlan"), ("lineprofile", "line_profile"), ("dba", "dba"),
    # --- entidades adicionales (MIB Tier 1/2) ---
    ("optical", "optical_module"), ("optmodule", "optical_module"),
    ("srvport", "service_port"),
    ("fan", "fan"),
    ("battery", "power_supply"), ("voltage", "power_supply"), ("power", "power_supply"),
    ("env", "sensor"),
]

# La cláusula IMPORTS lista símbolos (OBJECT-TYPE, MODULE-IDENTITY...) que los
# regex confunden con definiciones reales y, por su match perezoso, llegan a
# tragarse la primera definición verdadera. Se elimina antes de parsear.
_IMPORTS_RE = re.compile(r"\bIMPORTS\b.*?;", re.DOTALL)

_OBJECT_TYPE_RE = re.compile(
    r"(?P<name>[a-zA-Z][\w-]*)\s+OBJECT-TYPE\b(?P<body>.*?)::=\s*\{(?P<oid>[^}]*)\}",
    re.DOTALL,
)
_OID_ASSIGN_RE = re.compile(
    r"(?P<name>[a-zA-Z][\w-]*)\s+OBJECT\s+IDENTIFIER\s*::=\s*\{(?P<oid>[^}]*)\}",
    re.DOTALL,
)
_MODULE_IDENTITY_RE = re.compile(
    r"(?P<name>[a-zA-Z][\w-]*)\s+MODULE-IDENTITY\b.*?::=\s*\{(?P<oid>[^}]*)\}",
    re.DOTALL,
)
# OBJECT-IDENTITY ancla nodos del árbol (ej. zte, zxAnSystem en ZTE-AN-SMI).
_OBJECT_IDENTITY_RE = re.compile(
    r"(?P<name>[a-zA-Z][\w-]*)\s+OBJECT-IDENTITY\b.*?::=\s*\{(?P<oid>[^}]*)\}",
    re.DOTALL,
)
# NOTIFICATION-TYPE = trap SNMP → se materializa como alarma.
_NOTIFICATION_TYPE_RE = re.compile(
    r"(?P<name>[a-zA-Z][\w-]*)\s+NOTIFICATION-TYPE\b(?P<body>.*?)::=\s*\{(?P<oid>[^}]*)\}",
    re.DOTALL,
)

# Palabras → severidad/tipo para traps de MIB (no llevan severidad explícita).
_SEV_FAULT_RE = re.compile(r"fail|error|loss|lost|down|abnormal|critical|break|unavailable", re.I)
_SEV_WARN_RE = re.compile(r"differ|mismatch|change|exceed|threshold|warn", re.I)
# Orden por especificidad: los mas inequivocos primero. 'power' (a secas) es
# ambiguo (optical power vs power supply) → se decide por voltage/supply/battery.
_ALARM_TYPE_KEYWORDS = [
    (r"temperature|\btemp\b|humidity|environ|\benv\b", "environmental"),
    (r"voltage|supply|battery|\bpwr\b|dcpower|\bpower\s*(supply|module)", "power"),
    (r"auth|security|illegal|unauthorized|rogue", "security"),
    (r"traffic|bandwidth|congestion|overload|broadcast", "traffic"),
    (r"optical|signal|\blos\b|attenuat|\brx\b|\btx\b|opticalpower", "optical"),
    (r"board|card|chassis|hardware|\bfan\b|subcard|slot|module", "hardware"),
]

# Base de conocimiento operativo por tipo de alarma (el MIB no la trae; se cura).
# Son causas/remediaciones GENERICAS por clase; el objeto reportado da el detalle.
_ALARM_KB = {
    "optical": {
        "probable_causes": ["Corte o degradacion de la fibra",
                            "Conector optico sucio o mal insertado",
                            "Potencia optica Rx/Tx fuera de rango",
                            "ONU apagada o desconectada"],
        "remediation": ["Verificar continuidad y limpieza de la fibra",
                        "Medir potencia optica Rx/Tx en el puerto",
                        "Revisar estado y alimentacion de la ONU"]},
    "hardware": {
        "probable_causes": ["Falla o mal contacto de tarjeta/subtarjeta",
                            "Tarjeta no soportada o incompatible",
                            "Sobrecalentamiento del modulo"],
        "remediation": ["Reasentar o reemplazar la tarjeta",
                        "Verificar compatibilidad de HW/firmware",
                        "Revisar ventilacion y temperatura"]},
    "power": {
        "probable_causes": ["Falla de la fuente de alimentacion",
                            "Voltaje de entrada fuera de rango",
                            "Bateria agotada o en fallo"],
        "remediation": ["Verificar la fuente y el voltaje de entrada",
                        "Revisar o reemplazar la fuente/bateria"]},
    "environmental": {
        "probable_causes": ["Temperatura o humedad fuera de umbral",
                            "Falla de ventilacion",
                            "Obstruccion del flujo de aire"],
        "remediation": ["Revisar ventiladores y filtros",
                        "Verificar la climatizacion del sitio"]},
    "security": {
        "probable_causes": ["Intento de autenticacion fallido",
                            "ONU o serial no autorizado (rogue ONU)",
                            "Posible suplantacion"],
        "remediation": ["Verificar el registro/serial de la ONU",
                        "Revisar las politicas de autenticacion",
                        "Aislar el puerto o la ONU sospechosa"]},
    "traffic": {
        "probable_causes": ["Congestion o sobre-suscripcion",
                            "Bucle o tormenta de broadcast",
                            "Perfil de ancho de banda excedido"],
        "remediation": ["Revisar perfiles de trafico y VLAN",
                        "Buscar bucles L2",
                        "Reajustar el perfil de ancho de banda"]},
    "protocol": {
        "probable_causes": ["Cambio de estado o parametro reportado",
                            "Inconsistencia de configuracion",
                            "Evento de protocolo (registro/deregistro)"],
        "remediation": ["Correlacionar con el objeto reportado (oid_refs)",
                        "Revisar la configuracion asociada"]},
}


class MibExtractor:
    def __init__(self, vendor: str, family: str, technology: str, firmware: list[str]):
        self.vendor = vendor
        self.family = family
        self.technology = technology
        self.firmware = firmware

    def extract(self, text: str, doc_type: str = "mib_file",
                extra_assignments: Optional[dict[str, list[str]]] = None) -> list[Oid]:
        text = _IMPORTS_RE.sub(" ", text)
        assignments = self._merged_assignments(text, extra_assignments)
        oids: list[Oid] = []
        for m in _OBJECT_TYPE_RE.finditer(text):
            name = m.group("name")
            body = m.group("body")
            # un OBJECT-TYPE real declara MAX-ACCESS; descarta falsos positivos
            # como la cláusula IMPORTS (que lista el símbolo OBJECT-TYPE).
            if "MAX-ACCESS" not in body.upper():
                continue
            oid_string = self._resolve(name, assignments)
            fields = self._parse_body(body)
            entity = self._guess_entity(name)
            oid = Oid(
                oid=oid_string or "",
                name=name,
                entity_ref=entity,             # short name; el Normalizer lo canoniza
                vendor=self.vendor, family=self.family, technology=self.technology,
                firmware=list(self.firmware),
                syntax=fields["syntax"],
                mib_table=fields["mib_table"] or self._guess_table(name),
                unit=fields["unit"],
                access=fields["access"],
                enumeration=fields["enumeration"],
                description=fields["description"],
                index=fields["index"],
                metric=self._metric_name(name, entity),
                sources=[Source(doc_type=doc_type, pages=None, confidence=0.0,
                                quality=QUALITY_DIRECT_NO_PAGE)],
            )
            oids.append(oid)
        log.info("MibExtractor: %d OBJECT-TYPE extraídos", len(oids))
        return oids

    # --- NOTIFICATION-TYPE → alarmas -----------------------------------------
    def extract_notifications(self, text: str, doc_type: str = "mib_file",
                              extra_assignments: Optional[dict[str, list[str]]] = None
                              ) -> list[Alarm]:
        text = _IMPORTS_RE.sub(" ", text)
        assignments = self._merged_assignments(text, extra_assignments)
        alarms: list[Alarm] = []
        for m in _NOTIFICATION_TYPE_RE.finditer(text):
            name = m.group("name")
            body = m.group("body")
            # una NOTIFICATION-TYPE real declara STATUS; descarta falsos positivos
            if "STATUS" not in body.upper():
                continue
            oid_string = self._resolve(name, assignments) or ""
            desc = self._field(body, r'DESCRIPTION\s+"((?:[^"\\]|\\.)*)"')
            blob = name + " " + (desc or "")
            atype = self._guess_alarm_type(blob)
            kb = _ALARM_KB.get(atype, _ALARM_KB["protocol"])
            alarms.append(Alarm(
                code=oid_string or name,
                name=name,
                canonical_name=self._notif_canonical(name),
                entity_ref=self._guess_entity(name),
                vendor=self.vendor, family=self.family,
                firmware=list(self.firmware),
                severity=self._guess_severity(blob),
                type=atype,
                description=(desc or "").strip() or None,
                probable_causes=list(kb["probable_causes"]),
                remediation=list(kb["remediation"]),
                oid_trap=oid_string or None,
                oid_refs=self._parse_objects(body),
                sources=[Source(doc_type=doc_type, pages=None, confidence=0.0,
                                quality=QUALITY_DIRECT_NO_PAGE)],
            ))
        log.info("MibExtractor: %d NOTIFICATION-TYPE → alarma(s)", len(alarms))
        return alarms

    @staticmethod
    def _parse_objects(body: str) -> list[str]:
        m = re.search(r"OBJECTS\s*\{([^}]*)\}", body, re.DOTALL)
        if not m:
            return []
        return [o.strip() for o in m.group(1).split(",") if o.strip()]

    @staticmethod
    def _notif_canonical(name: str) -> str:
        spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name)   # camelCase → palabras
        return " ".join(spaced.replace("_", " ").split())

    @staticmethod
    def _guess_severity(blob: str) -> str:
        if _SEV_FAULT_RE.search(blob):
            return "major"
        if _SEV_WARN_RE.search(blob):
            return "warning"
        return "warning"

    @staticmethod
    def _guess_alarm_type(blob: str) -> str:
        for rx, t in _ALARM_TYPE_KEYWORDS:
            if re.search(rx, blob, re.IGNORECASE):
                return t
        return "protocol"

    # --- resolución de OIDs ---------------------------------------------------
    def collect_assignments(self, text: str) -> dict[str, list[str]]:
        """Expuesto para construir una tabla global de OIDs entre varios MIB."""
        return self._collect_assignments(text)

    def _merged_assignments(self, text: str,
                            extra: Optional[dict[str, list[str]]]) -> dict[str, list[str]]:
        """Asignaciones del propio módulo + las importadas de otros MIB (extra).
        Las locales tienen prioridad ante un mismo símbolo."""
        local = self._collect_assignments(text)
        if not extra:
            return local
        merged = dict(extra)
        merged.update(local)
        return merged

    def _collect_assignments(self, text: str) -> dict[str, list[str]]:
        """name -> tokens del lado derecho de ::= { ... }."""
        text = _IMPORTS_RE.sub(" ", text)
        out: dict[str, list[str]] = {}
        for rx in (_OID_ASSIGN_RE, _MODULE_IDENTITY_RE, _OBJECT_IDENTITY_RE,
                   _OBJECT_TYPE_RE, _NOTIFICATION_TYPE_RE):
            for m in rx.finditer(text):
                out[m.group("name")] = m.group("oid").split()
        return out

    def _resolve(self, name: str, assignments: dict[str, list[str]],
                 _seen: Optional[set[str]] = None) -> Optional[str]:
        _seen = _seen or set()
        if name in _seen or name not in assignments:
            return None
        _seen.add(name)
        parts: list[str] = []
        tokens = assignments[name]
        for tok in tokens:
            num = self._token_number(tok)
            if num is not None:
                parts.append(num)
                continue
            if tok in KNOWN_ROOTS:
                parts.append(KNOWN_ROOTS[tok])
            elif tok in assignments:
                resolved = self._resolve(tok, assignments, _seen)
                if resolved:
                    parts.append(resolved)
            # tokens desconocidos se ignoran
        dotted = ".".join(p for p in parts if p)
        return dotted or None

    @staticmethod
    def _token_number(tok: str) -> Optional[str]:
        if tok.isdigit():
            return tok
        m = re.fullmatch(r"[a-zA-Z][\w-]*\((\d+)\)", tok)  # ej: enterprises(1)
        return m.group(1) if m else None

    # --- parseo del cuerpo del OBJECT-TYPE -----------------------------------
    def _parse_body(self, body: str) -> dict[str, Any]:
        # Captura el SYNTAX completo, incluido el bloque { enum(1), ... } multilínea.
        # Antes cortaba en el primer \n y perdía casi todas las enumeraciones.
        syntax_raw = self._field(body, r"SYNTAX\s+(.+?)\s*(?:MAX-ACCESS|UNITS|STATUS|::=)")
        access = (self._field(body, r"MAX-ACCESS\s+([\w-]+)") or "read-only").strip()
        units = self._field(body, r'UNITS\s+"([^"]*)"')
        desc = self._field(body, r'DESCRIPTION\s+"((?:[^"\\]|\\.)*)"')
        index_block = self._field(body, r"INDEX\s*\{([^}]*)\}")
        return {
            "syntax": self._norm_syntax(syntax_raw),
            "access": access,
            "unit": units or None,
            "description": (desc or "").strip() or None,
            "enumeration": self._parse_enum(syntax_raw),
            "index": self._parse_index(index_block),
            "mib_table": None,
        }

    @staticmethod
    def _field(body: str, pattern: str) -> Optional[str]:
        m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _norm_syntax(raw: Optional[str]) -> str:
        if not raw:
            return "INTEGER"
        raw = raw.strip()
        for s in ("Counter64", "Counter32", "Gauge32", "OCTET STRING", "INTEGER"):
            if s.lower().replace(" ", "") in raw.lower().replace(" ", ""):
                return s
        return raw.split("{")[0].split("(")[0].strip() or "INTEGER"

    @staticmethod
    def _parse_enum(syntax_raw: Optional[str]) -> Optional[dict[str, str]]:
        if not syntax_raw or "{" not in syntax_raw:
            return None
        inner = syntax_raw[syntax_raw.find("{") + 1: syntax_raw.rfind("}")]
        out: dict[str, str] = {}
        for label, num in re.findall(r"([a-zA-Z][\w-]*)\s*\((\d+)\)", inner):
            out[num] = label
        return out or None

    def _parse_index(self, index_block: Optional[str]) -> OidIndex:
        if not index_block:
            return OidIndex(type="simple", bit_calculation=False)
        cols = [c.strip() for c in index_block.split(",") if c.strip()]
        composite = len(cols) > 1
        # patrón ZTE: índice compuesto de 32 bits (shelf/slot/port/onu_id)
        bit_calc = composite and self._looks_like_zte_bitindex(cols)
        components = None
        if bit_calc:
            components = self._bit_components(cols)
        return OidIndex(type="composite" if composite else "simple",
                        bit_calculation=bit_calc, components=components)

    @staticmethod
    def _looks_like_zte_bitindex(cols: list[str]) -> bool:
        joined = " ".join(cols).lower()
        hits = sum(k in joined for k in ("shelf", "slot", "port", "onu"))
        return hits >= 2

    @staticmethod
    def _bit_components(cols: list[str]) -> list[dict[str, str]]:
        # Mapa de bits por defecto del esquema ZTE de 32 bits.
        default_bits = {"shelf": "31-28", "slot": "27-24", "port": "23-20", "onu": "19-0"}
        out = []
        for c in cols:
            short = snake(c).split("_")[-1]
            label = next((k for k in default_bits if k in c.lower()), short)
            out.append({"name": label, "bits": default_bits.get(label, "")})
        return out

    # --- heurísticas de entidad/métrica --------------------------------------
    @staticmethod
    def _guess_entity(name: str) -> str:
        low = name.lower()
        for kw, entity in _ENTITY_KEYWORDS:
            if kw in low:
                return entity
        return "olt"   # por defecto, métrica a nivel de equipo

    @staticmethod
    def _metric_name(name: str, entity: str) -> str:
        s = snake(re.sub(r"(?<!^)(?=[A-Z])", "_", name))   # camelCase → snake
        for prefix in ("zx_an_gpon_", "zx_an_", "zx_", "hw_"):
            if s.startswith(prefix):
                s = s[len(prefix):]
        return s.replace(f"{entity}_", "", 1) if s.startswith(f"{entity}_") else s

    @staticmethod
    def _guess_table(name: str) -> Optional[str]:
        m = re.match(r"([a-zA-Z]+?)(?:Entry|Table)?$", name)
        return None
