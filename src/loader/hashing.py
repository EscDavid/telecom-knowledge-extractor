"""Hash raiz del catalogo (tipo Merkle) para deteccion de cambios local vs DB.

    hoja  = sha256(json canonico de cada artefacto, sin campos volatiles/per-run)
    grupo = sha256(concatenar hojas ordenadas por id)     # entities, oids, ...
    raiz  = sha256(concatenar grupos en orden fijo)

El `status` SI entra en el hash (documented -> verified_walk es un cambio real).
Solo se excluyen campos que cambian por-corrida (timestamps, run-ids). El hash es
determinista: mismo contenido -> mismo hash, en cualquier maquina.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# campos volatiles/per-run que NO deben afectar el hash
_VOLATILE = {"generated_at", "evaluated_at", "triggered_at", "processed_at",
             "created_at", "updated_at", "run_id"}

# grupo (subdir) -> clave de items dentro del archivo (None = el archivo ES el item)
_GROUPS = [("entities", None), ("commands", None), ("oids", "oids"),
           ("relations", "relations"), ("alarms", "alarms")]


def _strip_volatile(obj):
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in _VOLATILE}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def _canon(obj) -> str:
    return json.dumps(_strip_volatile(obj), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _group_hash(group_dir: Path, items_key) -> str:
    leaves: list[tuple[str, str]] = []
    if group_dir.exists():
        for f in sorted(group_dir.rglob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            artifacts = data.get(items_key, []) if items_key else [data]
            for art in artifacts:
                leaves.append((art.get("id", ""), _sha(_canon(art))))
    leaves.sort(key=lambda x: x[0])                 # por id -> determinista
    return _sha("".join(h for _, h in leaves))


def catalog_root_hash(catalog_dir) -> str:
    """Hash raiz (sha256 hex) de todo el contenido del catalogo."""
    catalog_dir = Path(catalog_dir)
    parts = [_group_hash(catalog_dir / name, key) for name, key in _GROUPS]
    return _sha("".join(parts))
