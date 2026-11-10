"""Hook de refinamiento Huawei: deduplica ids de OID colisionados.

Huawei nombra columnas con patrones muy genéricos repetidos entre tablas distintas
(ej. "Index", "RowStatus") — al fusionar 5 módulos MIB reales (GPON/XPON/DEVICE/
ENTITY-EXTENT/HWMUSA), MibExtractor._metric_name() los recorta al mismo id aunque
sean OIDs completamente distintos (ej. "oid.huawei.gpon.onu.ont_index" x3, de tres
tablas reales diferentes: 2011.6.3.23.1.1, 2011.6.128.1.1.2.41.1.1,
2011.6.128.1.1.2.43.1.1). Eso rompe la PRIMARY KEY de tkc_oids al cargar
(IntegrityError, visto en vivo 2026-11-09).

No hay (todavía) ninguna referencia cruzada por id de OID en el catálogo Huawei
(oid_ref/command_ref) — desambiguar es seguro. El sufijo es la cola numérica REAL
del OID (nunca inventada), así que el id sigue siendo determinista y trazable al
mismo OID si se regenera.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

log = logging.getLogger("tkc.walk_validator.huawei_refinements")


def refine_catalog(target: Path, family: str, walks_dir: Path | None = None) -> dict:
    oids_dir = target / "oids"
    if not oids_dir.exists():
        return {"deduped": 0}

    by_id: dict[str, list[tuple[Path, dict, dict]]] = defaultdict(list)
    groups: dict[Path, dict] = {}
    for f in sorted(oids_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        groups[f] = data
        for o in data.get("oids", []):
            by_id[o["id"]].append((f, data, o))

    n = 0
    for oid_id, members in by_id.items():
        if len(members) < 2:
            continue
        for _f, _data, o in members:
            # el OID completo (no solo la cola): confirmado 100% único en el catálogo
            # (ver commit) — la cola de 2 arcos no bastaba, dos OIDs reales distintos
            # pueden terminar igual.
            tail = o["oid"].strip(".").replace(".", "_")
            o["id"] = f"{oid_id}-{tail}"
            n += 1
        log.info("WalkValidator(huawei): %s desambiguado en %d OIDs distintos",
                 oid_id, len(members))

    if n:
        for f, data in groups.items():
            f.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"deduped": n}
