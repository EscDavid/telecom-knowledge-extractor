"""Redacta EN LOCAL los índices sensibles (cadenas de comunidades SNMP/cuentas en el OID) de walks, diagnósticos y catálogos ya generados.

 - Walks `.txt` (docs/walks y docs/walks/diagnostics) de C300/C320: en la tabla `1082.20.5.2.1.2.1.{2|50}.<n>.<n bytes>` la cadena se
   sustituye por un marcador de la misma longitud ("XXXXXXXXXX01"…) conservando el orden de las filas.
 - `results.json` de cada catálogo C300/C320: se eliminan los hallazgos de los prefijos sensibles y se quitan de
   `manifest.observed_firmware_strings` las cadenas decodificadas. No cambia el hash de contenido de la carga (no incluye results/manifest).
Sin --apply solo cuenta. Uso: python scripts/redact_sensitive_local.py [--apply]"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.profiles import default_registry  # noqa: E402

PREFIXES = tuple(default_registry().get("ZTE").sensitive_prefixes)
TABLE = "1082.20.5.2.1.2.1."
RX = re.compile(r"(?P<head>(?:\.|iso\.)?(?:1\.3\.6\.1\.4\.1\.3902\.)" + re.escape(TABLE) + r"(?:2|50)\.)(?P<n>\d+)\.(?P<b>(?:\d+\.){11}\d+)(?P<tail>[ .])")


def redact_walk(path: Path, apply: bool) -> int:
    text = path.read_text(errors="ignore")
    found = sorted({tuple(int(x) for x in m.group("b").split(".")) for m in RX.finditer(text) if m.group("n") == "12"})
    if not found:
        return 0
    mapping = {".".join(map(str, t)): ".".join(str(ord(c)) for c in f"XXXXXXXXXX{i + 1:02d}") for i, t in enumerate(found)}
    new, n = RX.subn(lambda m: m.group("head") + m.group("n") + "." + mapping.get(m.group("b"), m.group("b")) + m.group("tail"), text)
    if apply:
        path.write_text(new)
    return n


def redact_catalog(cdir: Path, apply: bool) -> int:
    rp = cdir / "results.json"
    if not rp.exists():
        return 0
    res = json.loads(rp.read_text())
    keep, dec = [], set()
    for x in res.get("findings", []):
        if any(str(x.get("tabla") or x.get("oid") or "").startswith(p) for p in PREFIXES):
            if x.get("decoded_value"):
                dec.add(x["decoded_value"])
        else:
            keep.append(x)
    n = len(res.get("findings", [])) - len(keep)
    if n and apply:
        res["findings"] = keep
        rp.write_text(json.dumps(res, ensure_ascii=False, indent=2))
        mp = cdir / "manifest.json"
        if mp.exists():
            m = json.loads(mp.read_text())
            m["observed_firmware_strings"] = [s for s in m.get("observed_firmware_strings", []) if s not in dec]
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2))
    return n


def main():
    apply = "--apply" in sys.argv
    tot = 0
    for m in ("C300", "C320"):
        for f in sorted(glob.glob(str(ROOT / f"docs/walks/ZTE_{m}*.txt*"))) + sorted(glob.glob(str(ROOT / f"docs/walks/diagnostics/ZTE_{m}*.txt"))):
            n = redact_walk(Path(f), apply)
            if n:
                print(f"  walk {Path(f).relative_to(ROOT)}: {n} líneas"); tot += n
        for d in sorted(glob.glob(str(ROOT / f"catalog/zte/zxa10-{m.lower()}/catalog-*"))):
            n = redact_catalog(Path(d), apply)
            if n:
                print(f"  catálogo {Path(d).relative_to(ROOT)}: {n} hallazgos"); tot += n
    print(("Aplicado: " if apply else "Simulación: ") + f"{tot} elementos")


main()
