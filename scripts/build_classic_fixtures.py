"""Fixtures ANONIMIZADAS de las OLT clásicas ZTE (C320 y C300) para la puerta de contrato y el importador.

Salida: docs/fixtures/zte-real/<c320|c300>-20261001/{snmp/*.txt, README.md}.
Fuente (solo lectura): docs/walks/ZTE_C3x0.txt (rama 1012.3.50.11/12). Muestra de ONU: todas las de potencia con signo,
algunas sin señal (65535) y 30 normales. Seriales: se conserva el prefijo de fabricante de 4 bytes y se sustituyen los 4 restantes
de forma determinista. No se incluye ningún nombre/descripción/IP de abonado ni credenciales.
Uso: python scripts/build_classic_fixtures.py
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = "1.3.6.1.4.1.3902.1012.3.50."
COLS = {"onu_status.txt": "11.2.1.8", "onu_rx_power.txt": "12.1.1.10", "onu_tx_power.txt": "12.1.1.14",
        "onu_serial.txt": "11.2.1.3", "onu_type.txt": "11.2.1.17", "onu_vendor_id.txt": "11.2.1.1"}


def hexbytes(v):
    m = re.match(r'(Hex-STRING|STRING): (.*)', v)
    if m.group(1) == "Hex-STRING":
        return bytes(int(x, 16) for x in m.group(2).split())
    return m.group(2).strip().strip('"').encode("latin-1", "replace")


def build(model):
    cols = {c: {} for c in COLS.values()}
    for line in open(ROOT / f"docs/walks/ZTE_{model}.txt", errors="ignore"):
        m = re.match(r"^\.?" + re.escape(P) + r"(\d+\.\d+\.\d+\.\d+)\.(\d+\.\d+)(?:\.1)? = (.*)$", line.rstrip("\n"))
        if m and m.group(1) in cols:
            cols[m.group(1)][m.group(2)] = m.group(3)
    rx = {k: int(re.search(r"-?\d+", v).group()) for k, v in cols["12.1.1.10"].items() if "INTEGER" in v}
    neg = sorted(k for k, v in rx.items() if 32768 <= v < 65535)
    nosig = sorted(k for k, v in rx.items() if v == 65535)[:5]
    normal = sorted(k for k, v in rx.items() if v < 32768 and k not in neg)[:30]
    keys = sorted(set(neg + nosig + normal), key=lambda s: tuple(int(x) for x in s.split(".")))
    out = ROOT / f"docs/fixtures/zte-real/{model.lower()}-20261001"
    (out / "snmp").mkdir(parents=True, exist_ok=True)
    for fname, col in COLS.items():
        lines = []
        for k in keys:
            v = cols[col].get(k)
            if v is None:
                continue
            if col == "11.2.1.3":
                b = hexbytes(v)
                fake = hashlib.sha256(b).digest()[:4]
                v = "Hex-STRING: " + " ".join(f"{x:02X}" for x in b[:4] + fake) + " "
            suffix = ".1" if col.startswith("12.") else ""
            lines.append(f".{P}{col}.{k}{suffix} = {v}")
        (out / "snmp" / fname).write_text("\n".join(lines) + "\n")
    (out / "snmp" / "onu_rx_power_signed.txt").write_text(
        "# filas reales de rx con raw >= 32768 (entero de 16 bits con signo); 65535 = sin señal\n" +
        "".join(f".{P}12.1.1.10.{k}.1 = {cols['12.1.1.10'][k]}\n" for k in neg))
    (out / "README.md").write_text(
        f"# Fixtures ZTE {model} (20261001)\nColumnas SNMP `1012.3.50.11/12` de {len(keys)} ONU de una OLT {model} real, **anonimizadas** "
        "(seriales con el prefijo de fabricante y 4 bytes sintéticos; sin nombres/IP/descripciones de abonado ni credenciales).\n"
        f"- Incluye las {len(neg)} ONU con potencia de recepción con signo (raw >= 32768), {len(nosig)} sin señal (65535) y {len(normal)} normales.\n"
        "- Índice de ONU: `<ifIndex del puerto PON>.<nº de ONU>` (potencias con `.1` final). Serial = 8 bytes (4 de fabricante + 4).\n"
        "- Muestra de UNA OLT por modelo; no prueba otros firmwares. Walk del 2026-10-01.\n")
    print(model, "ONU", len(keys), "con signo", len(neg), "sin señal", len(nosig))


for m in ("C320", "C300"):
    build(m)
