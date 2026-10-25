#!/usr/bin/env python3
"""Extrae la definición de un MIB desde su página en mibs.observium.org a JSON.

Sirve cuando NO se puede conseguir el archivo .mib original: la página
``/mib/<MODULO>/`` lista en un solo HTML todos los objetos con nombre, OID, tipo
(node/table/row/column/scalar), sintaxis, rangos, índices, acceso r/w y
descripción. Es una vista de TERCEROS del MIB, no la fuente del fabricante:
lo extraído entra al catálogo como ``documented`` a lo sumo y solo pasa a
``verified`` cuando un walk real lo confirma.

Limitaciones de la página: solo marca ``r/w`` (read-only / read-create /
not-accessible no se distinguen) y los enums solo aparecen en la descripción.

Uso:
    python scripts/observium_mib_extract.py HUAWEI-GPON-MIB [HUAWEI-XPON-MIB ...]
    python scripts/observium_mib_extract.py --html pagina.html HUAWEI-GPON-MIB
Salida: docs/huawei/ma5608t/observium/<MODULO>.json (cambiar con --out-dir).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://mibs.observium.org/mib/{}/"
UA = "Mozilla/5.0 (telecom-knowledge-extractor; mib-extract)"
ROW_SPLIT = re.compile(r'<tr\s+data-object-type=')
ENUM_RE = re.compile(r"\b([A-Za-z][\w-]*)\((-?\d+)\)")


def _text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in html.unescape(fragment).split("\n"))
    return "\n".join(ln for ln in lines if ln)


def fetch(module: str) -> str:
    req = urllib.request.Request(BASE.format(module), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (URL fija https)
        return r.read().decode("utf-8", "replace")


def parse(page: str) -> list[dict]:
    start = page.find('id="mib-object-table"')
    if start < 0:
        raise ValueError("no se encontró la tabla de objetos (¿cambió el layout?)")
    out: list[dict] = []
    for row in ROW_SPLIT.split(page[start:])[1:]:
        kind = re.match(r'"(\w+)"', row).group(1)
        name = re.search(r'id="([^"]+)"\s+class="oid-name-link"', row).group(1)
        oid = re.search(r"<code>\.?([\d.]+)</code>", row).group(1)
        depth = re.search(r"width:(\d+)px", row)
        pop = re.search(r'data-bs-content="([^"]*)"', row)
        pop_html = html.unescape(pop.group(1)) if pop else ""
        obj: dict = {"name": name, "oid": oid, "kind": kind,
                     "depth": int(depth.group(1)) // 16 if depth else 0}

        syn = re.search(r"Syntax:</strong><br><span[^>]*>([^<]*)</span>", pop_html)
        if syn:
            obj["syntax"] = syn.group(1)
        # TC importada (módulo + tipo) viene en la celda de sintaxis, fuera del popover
        grp = re.search(r'oid-syntax-badges"><span class="oid-syntax-badges"><span class="badge-group">'
                        r'<span class="badge bg-info"[^>]*><a[^>]*>([^<]+)</a></span>'
                        r'<span class="badge bg-primary"[^>]*><a[^>]*>([^<]+)</a>', row)
        if grp:
            obj["syntax_module"], obj["syntax_type"] = grp.group(1), grp.group(2)
        rng = re.search(r"Constraints:</strong><br><code>([^<]*)</code>", pop_html)
        if rng:
            obj["constraints"] = rng.group(1)
        idx = re.search(r"Indexes:</strong>(.*?)</div></div>", pop_html, re.S)
        if idx:
            # cada índice va en su propio <div>; el prefijo MIB:: solo aparece si es importado
            obj["indexes"] = [(m.group(1) or "") + m.group(2) for m in
                              re.finditer(r'(?:<span class="text-muted">([^<]*)</span>)?<code>([^<]*)</code>',
                                          idx.group(1))]
        desc = re.search(r"Description:</strong><br><div[^>]*>(.*)</div></div>$", pop_html, re.S)
        if desc:
            obj["description"] = _text(desc.group(1))
            enums = {int(v): n for n, v in ENUM_RE.findall(obj["description"])}
            if enums and obj.get("syntax") == "Enumeration":
                obj["enum_from_description"] = {str(k): enums[k] for k in sorted(enums)}
        if 'access-rw' in row:
            obj["access"] = "read-write"
        flags = re.findall(r'badge bg-secondary">(deprecated|obsolete)<', row)
        if flags:
            obj["status"] = flags[0]
        out.append(obj)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("modules", nargs="+", help="nombre(s) del MIB, ej. HUAWEI-GPON-MIB")
    ap.add_argument("--html", help="HTML ya descargado (solo con un módulo)")
    ap.add_argument("--out-dir", default="docs/huawei/ma5608t/observium")
    a = ap.parse_args()
    if a.html and len(a.modules) != 1:
        ap.error("--html admite un solo módulo")
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for mod in a.modules:
        page = Path(a.html).read_text(errors="replace") if a.html else fetch(mod)
        objs = parse(page)
        kinds: dict[str, int] = {}
        for o in objs:
            kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
        doc = {
            "module": mod,
            "source": BASE.format(mod),
            "source_kind": "third_party_rendering",   # NO es el .mib del fabricante
            "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "root_oid": objs[0]["oid"] if objs else None,
            "counts": kinds,
            "objects": objs,
        }
        dest = out_dir / f"{mod}.json"
        dest.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{mod}: {len(objs)} objetos {kinds} → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
