"""Fixtures de CLI ANONIMIZADAS de la OLT clásica (ZXA10 C300 V2.1.0) para el importador, a partir de la sonda de solo lectura del 2026-10-26.

Salida: docs/fixtures/zte-real/c300-cli-20261026/{cli/*.txt, ground_truth.json, README.md}.
Fuentes (solo lectura, ignoradas por git): docs/walks/diagnostics/ZTE_C320_cli_reads_20261026.txt (ronda 1) y *_ronda2.txt / *_cmd.txt.
Anonimización: seriales (4 letras + 8 hex), MAC, IPv4, y las líneas Name/Description/name/description de ONU (PII en claro en clásicas).
Después de generar comprueba que NINGÚN serial, MAC o nombre de la fuente aparece en la salida. Uso: python scripts/build_classic_cli_fixtures.py"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "docs/walks/diagnostics"
OUT = ROOT / "docs/fixtures/zte-real/c300-cli-20261026"
SEP = "=" * 78
WANT = {   # cabecera "[grupo/variante] comando" (con índices del equipo) -> archivo
    "show clock": "show_clock", "show card": "show_card", "show gpon onu state": "show_gpon_onu_state",
    "show gpon onu uncfg": "show_gpon_onu_uncfg", "show onu-type": "show_onu-type", "show vlan summary": "show_vlan_summary",
    "show gpon profile tcont": "show_gpon_profile_tcont", "show gpon profile traffic": "show_gpon_profile_traffic",
    "show logging alarm": "show_logging_alarm", "show version-running": "show_version-running", "show system-group": "show_system-group",
    "show card-temperature": "show_card-temperature", "show card-power": "show_card-power",
    "show gpon onu baseinfo gpon-olt_1/3/1": "show_gpon_onu_baseinfo", "show pon power olt-rx gpon-olt_1/3/1": "show_pon_power_olt-rx",
    "show interface gpon-olt_1/3/1": "show_interface_gpon-olt",
    "show gpon onu detail-info gpon-onu_1/3/1:2": "show_gpon_onu_detail-info", "show gpon onu distance gpon-onu_1/3/1:2": "show_gpon_onu_distance",
    "show pon onu information gpon-onu_1/3/1:2": "show_pon_onu_information", "show pon power attenuation gpon-onu_1/3/1:2": "show_pon_power_attenuation",
    "show pon power onu-rx gpon-onu_1/3/1:2": "show_pon_power_onu-rx", "show pon power onu-tx gpon-onu_1/3/1:2": "show_pon_power_onu-tx",
    "show service-port interface gpon-onu_1/3/1:2": "show_service-port_interface", "show gpon remote-onu equip gpon-onu_1/3/1:2": "show_gpon_remote-onu_equip",
    "show gpon remote-onu capability gpon-onu_1/3/1:2": "show_gpon_remote-onu_capability",
    "show gpon remote-onu interface eth gpon-onu_1/3/1:2": "show_gpon_remote-onu_interface_eth",
    "show gpon remote-onu sys-attr gpon-onu_1/3/1:2": "show_gpon_remote-onu_sys-attr",
    "show version": "show_version_AMBIGUO", "show software 1": "show_software_1_INVALIDO",
}
SN = re.compile(r"\b[A-Za-z]{4}[0-9A-Fa-f]{8}\b")
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4}\b|\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
PII_LINE = re.compile(r"^([ \t]*)(Name|Description|name|description)([ \t]*:?[ \t]*)(?!is none)([^\s:].*)$", re.M)
secrets = set()


def fake_sn(sn):
    return (sn[:4] if sn[:4].isalpha() else "FAKE") + hashlib.sha256(sn.encode()).hexdigest()[:8].upper()


def anon(text):
    for m in SN.findall(text):
        secrets.add(m)
    for m in MAC.findall(text):
        secrets.add(m)
    for m in PII_LINE.finditer(text):
        secrets.add(m.group(4).strip())
    text = SN.sub(lambda m: fake_sn(m.group(0)), text)
    text = MAC.sub("0000.0000.0000", text)
    text = IP.sub(lambda m: m.group(0) if m.group(0).startswith("1.") and len(m.group(0)) < 8 else "0.0.0.0", text)
    return PII_LINE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}<anonimizado>", text)


def blocks():
    out = {}
    for f in sorted(DIAG.glob("ZTE_C320_cli_reads_20261026*.txt")):
        for b in re.split(rf"\n{SEP}\n## ", f.read_text(errors="replace"))[1:]:
            h, _, rest = b.partition("\n")
            cmd = re.sub(r"^\[[^\]]*\]\s*", "", h.strip())
            out.setdefault(cmd, rest.split(SEP + "\n", 1)[-1].strip("\n"))
    return out


def main():
    bl = blocks()
    (OUT / "cli").mkdir(parents=True, exist_ok=True)
    done = []
    for cmd, name in WANT.items():
        if cmd in bl:
            (OUT / "cli" / f"{name}.txt").write_text(anon(bl[cmd]) + "\n")
            done.append(cmd)
    # verdad de terreno de potencia (CLI); el valor SNMP crudo se completa cuando se lea el OID en esta OLT
    gt = {"olt": "ZXA10 C300 V2.1.0 (103 ONU, un módulo GTGHG)", "date": "2026-10-26",
          "power_samples": [{"onu": "1/3/1:2", "up_rx_dbm": -22.644, "up_tx_dbm": 2.398, "down_rx_dbm": -19.788, "snmp_raw_expected": 3678},
                            {"onu": "1/3/1:3", "olt_rx_dbm": -33.666, "snmp_raw_expected": 63703,
                             "nota": "< -30 dBm: el raw sin signo es 63703; confirmar con snmpget 1012.3.50.12.1.1.10.268632320.3.1"},
                            {"onu": "1/3/1:4", "olt_rx_dbm": -21.387, "snmp_raw_expected": 4306}],
          "snmp_raw_confirmed": False}
    (OUT / "ground_truth.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1))
    (OUT / "README.md").write_text(
        "# Fixtures de CLI ZTE ZXA10 C300 V2.1.0 (20261026)\nSalida cruda de una OLT clásica real, **anonimizada** (seriales, MAC, IPv4 y `Name`/`Description` de ONU, que en clásicas salen EN CLARO).\n"
        "- Sintaxis de clásicas: `gpon-olt_1/3/1`, `gpon-onu_1/3/1:2`. La de C6 (`gpon_olt-…`) da `Invalid input`. `show version` es ambiguo (`_AMBIGUO`): usar `show version-running`.\n"
        "- `…_INVALIDO` documenta un comando que NO existe. `show gpon onu uncfg` devuelve `No related information to show` con 0 ONU (válido).\n"
        "- `ground_truth.json`: potencia por CLI de ONU concretas (el SNMP crudo esperado se confirma con `snmpget`).\n- Muestra de UNA OLT; no prueba otros firmwares ni la C320 (misma plataforma, no ejecutada).\n")
    # control: nada de lo anonimizado debe quedar
    text = "".join(p.read_text() for p in (OUT / "cli").glob("*.txt"))
    left = [s for s in secrets if len(s) >= 6 and s in text and not re.fullmatch(r"[\d.:]+", s)]
    assert not left, f"quedan {len(left)} datos sin anonimizar: {[(s[:2] + '…', len(s)) for s in left]}"
    print("fixtures:", len(done), "comandos;", len(secrets), "datos anonimizados; sin restos")
    print("sin salida en la fuente:", [c for c in WANT if c not in bl])


main()
