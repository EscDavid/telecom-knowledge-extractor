"""Readiness del catalogo en 4 tiers (el backend usa el tier mas alto = el "en uso").

Combina completitud (capas presentes) y confianza (avg_overall, % inferred, walk).

  Tier 1  Incompleto            falta >=1 capa  o  avg < 0.5
  Tier 2  Parcial               todas las capas, pero avg < 0.75  o  entidades inferred
  Tier 3  Casi listo            completo y confiable, pero TEORICO (sin walk) o con conflicto
  Tier 4  Listo (en uso)        confirmado contra hardware (walk) y sin conflictos -> deployable
"""
from __future__ import annotations

import json
from pathlib import Path

TIER_NAMES = {
    1: "Incompleto",
    2: "Parcial (baja confianza)",
    3: "Casi listo (validado, aun no en uso)",
    4: "Listo (en uso / produccion)",
}

_GROUPS = [("entities", None), ("commands", None), ("oids", "oids"),
           ("relations", "relations"), ("alarms", "alarms")]


def _collect(catalog_dir: Path) -> dict[str, list]:
    per: dict[str, list] = {}
    for name, key in _GROUPS:
        d = catalog_dir / name
        items: list = []
        if d.exists():
            for f in sorted(d.rglob("*.json")):
                data = json.loads(f.read_text(encoding="utf-8"))
                items += data.get(key, []) if key else [data]
        per[name] = items
    return per


def _conflicts(catalog_dir: Path) -> int:
    res = catalog_dir / "results.json"
    if not res.exists():
        return 0
    data = json.loads(res.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("findings", [])
    return sum(1 for x in items if isinstance(x, dict) and x.get("result_type") == "conflict")


def readiness(catalog_dir) -> tuple[int, str, dict]:
    """Devuelve (tier, nombre, metricas) del catalogo."""
    catalog_dir = Path(catalog_dir)
    per = _collect(catalog_dir)
    layers_ok = all(len(per[l]) > 0 for l in ("entities", "commands", "oids", "alarms"))
    all_arts = [a for items in per.values() for a in items]

    overalls = [a.get("confidence", {}).get("overall") for a in all_arts]
    overalls = [o for o in overalls if isinstance(o, (int, float))]
    avg = sum(overalls) / len(overalls) if overalls else 0.0

    ent_inferred = sum(1 for e in per["entities"] if e.get("status") == "inferred")
    verified_walk = sum(1 for a in all_arts if a.get("status") == "verified_walk")
    has_walk = verified_walk > 0 or any(a.get("empirical") for a in all_arts) \
        or any("empirical" in e for e in per["entities"])
    conflicts = _conflicts(catalog_dir)

    if not layers_ok or avg < 0.5:
        tier = 1
    elif avg < 0.75 or ent_inferred > 0:
        tier = 2
    elif has_walk and conflicts == 0:
        tier = 4                        # Listo: confirmado contra hardware (walk), sin conflictos
    else:
        tier = 3                        # Casi listo: completo pero teorico (sin walk) o con conflicto

    # clave de ranking para desempatar: tier manda; a igual tier, gana el que tiene
    # MAS evidencia empirica (verified_walk), luego mayor avg, luego menos inferred.
    rank_key = (tier, verified_walk, round(avg, 3), -ent_inferred)
    metrics = {"avg_overall": round(avg, 3), "layers_ok": layers_ok,
               "entities_inferred": ent_inferred, "verified_walk": verified_walk,
               "has_walk": has_walk, "conflicts": conflicts, "rank_key": rank_key}
    return tier, TIER_NAMES[tier], metrics
