"""Puerta de contrato: el catálogo C6xx publicado cumple el contrato de consumo (se omite si no hay catálogo generado)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fam", ["c620", "c600", "c320", "c300"])
def test_contrato_de_consumo(fam):
    import json
    ver = json.load(open(ROOT / "docs/validation/consumer_contract.json"))["families"][f"ZXA10 {fam.upper()}"]["version"]
    if not (ROOT / f"catalog/zte/zxa10-{fam}/catalog-{ver}").exists():
        pytest.skip("catálogo no generado")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/catalog_contract_check.py"), fam], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
