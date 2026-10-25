"""Genera el catálogo 1.2.0 de C300/C320 en un directorio de PRUEBA (staging/classic_build/catalog) sin tocar `catalog/`.
La semilla (catalog-1.1.0 del C320) se copia al staging; los walks se leen de docs/walks.
Después se compara con la versión publicada (scripts/catalog_diff.py) y, si es correcta, se promueve con --promote.

Uso:  python scripts/build_classic_catalog.py            # genera en staging
      python scripts/build_classic_catalog.py --promote  # copia staging -> catalog/ (solo si el destino no existe)"""
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.walk_validator import WalkValidator, model_key  # noqa: E402

STAGE = ROOT / "staging" / "classic_build"
VERSION = "1.2.0"
FAMILIES = {"c320": "ZXA10 C320", "c300": "ZXA10 C300"}


def main() -> int:
    cfg = yaml.safe_load(open(ROOT / "config/pipeline.yaml", encoding="utf-8"))
    if "--promote" in sys.argv:
        for fk in FAMILIES:
            src, dst = STAGE / "catalog/zte" / f"zxa10-{fk}" / f"catalog-{VERSION}", ROOT / "catalog/zte" / f"zxa10-{fk}" / f"catalog-{VERSION}"
            if dst.exists():
                print(f"{dst} ya existe: no se sobrescribe"); return 1
            shutil.copytree(src, dst); print("promovido", dst)
        return 0
    shutil.rmtree(STAGE, ignore_errors=True)
    seed = ROOT / "catalog/zte/zxa10-c320/catalog-1.1.0"
    shutil.copytree(seed, STAGE / "catalog/zte/zxa10-c320/catalog-1.1.0")
    cfg["paths"] = {k: (str(ROOT / v) if k != "catalog" else str(STAGE / "catalog")) for k, v in cfg["paths"].items()}
    cfg["paths"]["reports"] = str(STAGE / "reports")
    cfg["walk_validator"]["release_versions"] = {**cfg["walk_validator"].get("release_versions", {}),
                                                 "ZXA10 C320": VERSION, "ZXA10 C300": VERSION}
    walks = ROOT / "docs/walks"
    by_model = {}
    for wf in sorted(walks.glob("*.txt")):
        by_model.setdefault(model_key(wf), []).append(wf)
    for model, files in by_model.items():
        if not any(k in model.upper() for k in ("C300", "C320")):
            continue
        print("validando", model, [f.name for f in files])
        print("->", WalkValidator(cfg).run(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
