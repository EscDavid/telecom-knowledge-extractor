"""CommandExtractor — parseo de PDF Command Reference.

Heurística sobre el texto extraído del PDF: detecta secciones de comando por su
línea de sintaxis (verbo CLI + argumentos), infiere categoría y cli_mode, y
extrae parámetros desde los tokens {obligatorio} y [opcional] de la sintaxis.

También produce dependencias (DependencyExtractor) leyendo bloques
"Prerequisite"/"Precondition" que el Correlator convierte en relaciones.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from ..models import QUALITY_DIRECT_PAGE, Command, OutputField, Param, Source

log = logging.getLogger("tkc.extractor.cmd")

# verbo CLI inicial → categoría del comando
_CATEGORY_BY_VERB = {
    "show": "show", "display": "show", "create": "create", "add": "create",
    "delete": "delete", "no": "delete", "remove": "delete",
    "set": "modify", "modify": "modify", "config": "modify", "configure": "modify",
    "enable": "enable", "disable": "disable", "reset": "reset", "reboot": "reset",
    "ping": "diagnose", "test": "diagnose", "diagnose": "diagnose",
}
# palabras de modo CLI mencionadas cerca del comando
_CLI_MODE_HINTS = [
    (r"\(config-if[^)]*\)#", "interface_config"),
    (r"\(config-pon[^)]*\)#|\(gpon[^)]*\)#", "pon_config"),
    (r"\(config[^)]*\)#", "global_config"),
    (r"[\w-]+#", "privileged_exec"),
    (r"[\w-]+>", "user_exec"),
]
_GLOBAL_COMMANDS = {"save", "enable", "reload", "reboot", "write", "exit"}

# línea que parece sintaxis de comando: empieza por un verbo conocido
_SYNTAX_RE = re.compile(
    r"^\s*(?P<syntax>(?:" + "|".join(_CATEGORY_BY_VERB) + r")\b[^\n]{0,160})$",
    re.MULTILINE | re.IGNORECASE,
)


class CommandExtractor:
    def __init__(self, vendor: str, family: str, technology: str, firmware: list[str]):
        self.vendor = vendor
        self.family = family
        self.technology = technology
        self.firmware = firmware

    def extract(self, text: str, doc_type: str = "command_reference") -> list[Command]:
        if not text:
            return []
        seen: set[str] = set()
        commands: list[Command] = []
        for m in _SYNTAX_RE.finditer(text):
            syntax = " ".join(m.group("syntax").split())
            verb = syntax.split()[0].lower()
            if not self._is_real_syntax(syntax, verb):
                continue                            # descarta lineas de OUTPUT del PDF
            canonical = self._canonical_name(syntax)
            if canonical in seen:
                continue
            seen.add(canonical)
            window = text[m.start(): m.start() + 600]
            commands.append(Command(
                canonical_name=canonical,
                vendor=self.vendor, family=self.family, technology=self.technology,
                firmware=list(self.firmware),
                category=_CATEGORY_BY_VERB.get(verb, "show"),
                cli_mode=self._detect_mode(window),
                syntax=syntax,
                entity_ref=None,                       # lo asigna el Normalizer
                description=self._description(window),
                parameters=self._parse_params(syntax),
                output_fields=self._parse_output_fields(window),
                prerequisites=self._parse_prereqs(window),
                sources=[Source(doc_type=doc_type, pages=None, confidence=0.0,
                                quality=QUALITY_DIRECT_PAGE)],
            ))
        log.info("CommandExtractor: %d comando(s)", len(commands))
        return commands

    # --- helpers --------------------------------------------------------------
    @staticmethod
    def _is_real_syntax(syntax: str, verb: str) -> bool:
        """Distingue sintaxis CLI real de lineas de OUTPUT del PDF.

        Real: comando global (save, enable...) o con tokens de parametro {..}/[..].
        Output: 'Field: value', 'state: success', 'ping-response: true' → sin params
        y con ':' → se descarta.
        """
        if ":" in syntax:                    # 'Config-Type : ...' , 'state: success'
            return False
        if verb in _GLOBAL_COMMANDS:
            return True
        return "{" in syntax or "[" in syntax  # sintaxis real declara parametros

    @staticmethod
    def _canonical_name(syntax: str) -> str:
        # nombre canónico = la "ruta" fija del comando (todos los tokens sin los
        # argumentos {..}/[..]); distingue 'show gpon onu state' de '... detail-info'.
        tokens = [t for t in syntax.split() if not t.startswith(("{", "["))]
        return " ".join(tokens).lower()

    @staticmethod
    def _detect_mode(window: str) -> str:
        for rx, mode in _CLI_MODE_HINTS:
            if re.search(rx, window):
                return mode
        return "privileged_exec"

    @staticmethod
    def _description(window: str) -> Optional[str]:
        m = re.search(r"(?:Function|Description|Purpose)\s*[:：]\s*([^\n]+)", window,
                      re.IGNORECASE)
        return m.group(1).strip()[:300] if m else None

    @staticmethod
    def _parse_params(syntax: str) -> list[Param]:
        params: list[Param] = []
        for raw, required in [(t, True) for t in re.findall(r"\{([^}]+)\}", syntax)] + \
                             [(t, False) for t in re.findall(r"\[([^\]]+)\]", syntax)]:
            name = raw.strip().split("|")[0].strip()
            ptype = "flag" if "|" not in raw and " " not in raw and required is False else "string"
            params.append(Param(name=name, type=ptype, required=required))
        return params

    @staticmethod
    def _parse_output_fields(window: str) -> list[OutputField]:
        fields: list[OutputField] = []
        for m in re.finditer(r"^\s*([A-Z][\w /-]{2,30}?)\s*[:：]\s*\S", window, re.MULTILINE):
            name = m.group(1).strip()
            if name.lower() in {"function", "description", "purpose", "prerequisite"}:
                continue
            fields.append(OutputField(name=name, type="string"))
        return fields[:20]

    @staticmethod
    def _parse_prereqs(window: str) -> list[str]:
        m = re.search(r"(?:Prerequisite|Precondition)s?\s*[:：]\s*([^\n]+)", window,
                      re.IGNORECASE)
        if not m:
            return []
        # nombres de entidad mencionados; el Normalizer los resuelve a entity ids
        return [w.strip() for w in re.split(r"[,;]", m.group(1)) if w.strip()][:5]
