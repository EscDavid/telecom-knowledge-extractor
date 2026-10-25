"""Empaqueta fixtures ANONIMIZADAS de salida cruda de las OLT ZTE C620 y C600 para el importador (network-api).

Salida: docs/fixtures/zte-real/<c620|c600>-20261002/  (un archivo por comando o subárbol SNMP + README.md + ground_truth.json).
Fuentes (solo lectura): docs/walks/diagnostics/*.txt (CLI), docs/walks/ZTE_C6x0*.txt (SNMP), staging/walk_extra/*.txt.
Anonimización determinista: seriales de ONU/tarjetas (se conserva el prefijo de fabricante de 4 letras), MAC, IPv4 y cualquier
columna de nombre/descripción/dirección del abonado (se excluyen del SNMP). Nunca se incluyen credenciales ni comunidades.
Uso: python scripts/build_c6xx_fixtures.py
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "docs/walks/diagnostics"
OUTBASE = ROOT / "docs/fixtures/zte-real"
DATE = "20261002"
SEP = "=" * 78


def blocks(path):
    out = {}
    for b in re.split(rf"\n{SEP}\n## ", path.read_text(errors="replace"))[1:]:
        h, _, rest = b.partition("\n")
        h = re.sub(r"^\[[^\]]*\]\s*", "", h.strip())
        body = rest.split(SEP + "\n", 1)[-1]
        out.setdefault(h, body.strip("\n"))
    return out


def fake_sn(sn):
    d = hashlib.sha256(sn.encode()).hexdigest().upper()
    pre = sn[:4] if re.match(r"^[A-Za-z]{4}", sn) else "FAKE"
    return pre + d[:8]


class Anon:
    def __init__(self, serials):
        self.serials = sorted({s for s in serials if len(s) >= 8}, key=len, reverse=True)

    def __call__(self, text, ips=True):
        for s in self.serials:
            text = text.replace(s, fake_sn(s))
        text = re.sub(r"\b([0-9a-fA-F]{4})\.([0-9a-fA-F]{4})\.([0-9a-fA-F]{4})\b", lambda m: "0200." + hashlib.sha256(m.group(0).encode()).hexdigest()[:8], text)
        text = re.sub(r"\b([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b", lambda m: "02:00:" + ":".join(hashlib.sha256(m.group(0).encode()).hexdigest()[i:i + 2] for i in (0, 2, 4, 6)), text)
        if ips:   # en líneas SNMP los OID parecen IPv4: no se tocan
            text = re.sub(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])",
                          lambda m: m.group(0) if m.group(0).startswith(("0.", "255.")) else "10.0.0." + str(int(hashlib.sha256(m.group(0).encode()).hexdigest()[:2], 16) % 250 + 1), text)
        return text


def collect_serials(walk, extra_files):
    ser = set()
    for line in open(walk, errors="replace"):
        m = re.match(r'\.1\.3\.6\.1\.4\.1\.3902\.1082\.500\.10\.2\.3\.3\.1\.18\.\S+ = STRING: "\d,(\S+)"', line)
        if m:
            ser.add(m.group(1))
        m = re.match(r'\.1\.3\.6\.1\.4\.1\.3902\.1082\.10\.1\.2\.4\.1\.14\.\S+ = STRING: "(\S+)"', line)
        if m:
            ser.add(m.group(1))
    for f in extra_files:
        for m in re.finditer(r"(?:SN:|sn |Serial number:\s*|by sn )\s*([A-Za-z0-9]{8,16})", f.read_text(errors="replace")):
            ser.add(m.group(1))
        for m in re.finditer(r"gpon_olt-\S+\s+\S+\s+([A-Z0-9]{12})\s", f.read_text(errors="replace")):
            ser.add(m.group(1))
    return ser


# comando -> archivo de salida
CLI = {
    "show clock": "show_clock", "show software 1": "show_software", "show card": "show_card",
    "show vlan summary": "show_vlan_summary", "show vlan 100": "show_vlan_100",
    "show pon onu uncfg": "show_pon_onu_uncfg", "show onu-type gpon": "show_onu_type_gpon",
    "show gpon profile tcont": "show_gpon_profile_tcont", "show qos traffic-profile": "show_qos_traffic_profile",
    "show gpon onu profile vlan": "show_gpon_onu_profile_vlan", "show gpon onu state": "show_gpon_onu_state_all",
    "show gpon onu state gpon_olt-1/1/1": "show_gpon_onu_state_pon",
    "show gpon onu baseinfo gpon_olt-1/1/1": "show_gpon_onu_baseinfo_pon",
    "show running-config-interface gpon_olt-1/1/5": "show_running_config_interface_olt",
    "show gpon onu detail-info gpon_onu-1/1/1:1": "show_gpon_onu_detail_info",
    "show running-config-interface gpon_onu-1/1/1:1": "show_running_config_interface_onu",
    "show running-config-interface vport-1/1/1.1:1": "show_running_config_interface_vport",
    "show service-port interface vport-1/1/1.1:1": "show_service_port_interface",
    "show mac interface gpon_onu-1/1/1:1": "show_mac_interface_onu",
    "show gpon onu distance gpon_onu-1/1/1:1": "show_gpon_onu_distance",
    "show pon power attenuation gpon_onu-1/1/1:1": "show_pon_power_attenuation",
    "show pon power olt-rx gpon_onu-1/1/1:1": "show_pon_power_olt_rx",
    "show pon power onu-rx gpon_onu-1/1/1:1": "show_pon_power_onu_rx",
    "show pon power onu-tx gpon_onu-1/1/1:1": "show_pon_power_onu_tx",
    "show pon onu information gpon_onu-1/1/1:1": "show_pon_onu_information",
    "show gpon remote-onu equip gpon_onu-1/1/1:1": "show_gpon_remote_onu_equip",
    "show gpon remote-onu capability gpon_onu-1/1/1:1": "show_gpon_remote_onu_capability",
    "show gpon remote-onu interface eth gpon_onu-1/1/1:1": "show_gpon_remote_onu_interface_eth",
    "show gpon remote-onu interface video gpon_onu-1/1/1:1": "show_gpon_remote_onu_interface_video",
    "show gpon remote-onu wifi info gpon_onu-1/1/1:1": "show_gpon_remote_onu_wifi_info",
    "show gpon remote-onu service gpon_onu-1/1/1:1": "show_gpon_remote_onu_service",
    "show gpon remote-onu sys-attr gpon_onu-1/1/1:1": "show_gpon_remote_onu_sys_attr",
    "show interface xgei-1/4/1": "show_interface_xgei", "show alarm current": "show_alarm_current",
    "show gpon onu by sn": "show_gpon_onu_by_sn",
}
SNMP_ONU = {"type_name": "1082.500.10.2.3.3.1.1", "serial": "1082.500.10.2.3.3.1.18", "status": "1082.500.10.2.3.8.1.4",
            "last_auth": "1082.500.10.2.3.8.1.5", "last_offline": "1082.500.10.2.3.8.1.6", "offline_cause": "1082.500.10.2.3.8.1.7",
            "distance": "1082.500.10.2.3.10.1.2", "model": "1082.500.20.2.1.2.1.2", "vendor_prefix": "1082.500.20.2.1.2.1.1",
            "rx_power": "1082.500.20.2.2.2.1.10", "tx_power": "1082.500.20.2.2.2.1.14", "tcont_profile": "1082.500.10.2.3.4.1.3",
            "gemport_name": "1082.500.10.2.3.5.1.2"}


def main():
    for model, walkf, ifnf, diagf, state_dir in (
            ("c620", "ZTE_C620.txt", "ZTE_C620_ifnames.txt", ["ZTE_C620_cli_reads.txt", "ZTE_C620_cli_reads_exec3.txt", "ZTE_C620_cli_reads_extra.txt", "ZTE_C620_cli_reads_rc.txt", "ZTE_C620_cli_reads_qos2.txt"], "ZTE_C620"),
            ("c600", "ZTE_C600.txt", "ZTE_C600_ifnames.txt", ["ZTE_C600_MARROQUIN_cli_reads.txt", "ZTE_C600_cli_reads_all.txt", "ZTE_C600_cli_reads_rc.txt", "ZTE_C600_cli_reads_qos.txt"], "ZTE_C600")):
        walk = ROOT / "docs/walks" / walkf
        files = [DIAG / f for f in diagf if (DIAG / f).exists()]
        anon = Anon(collect_serials(walk, files))
        out = OUTBASE / f"{model}-{DATE}"
        (out / "cli").mkdir(parents=True, exist_ok=True)
        (out / "snmp").mkdir(parents=True, exist_ok=True)
        # --- CLI
        allb = {}
        for f in files:
            for h, b in blocks(f).items():
                allb.setdefault(h, b)
        written = []
        for cmd, name in CLI.items():
            cands = [h for h in allb if h == cmd or (cmd == "show gpon onu by sn" and h.startswith("show gpon onu by sn"))]
            if not cands:
                continue
            (out / "cli" / f"{name}.txt").write_text(anon(allb[cands[0]]) + "\n")
            written.append(name)
        # ONU de configuración con CATV (video) y otras 3, desde el archivo rc
        rc = blocks(DIAG / f"ZTE_{model.upper()}_cli_reads_rc.txt") if (DIAG / f"ZTE_{model.upper()}_cli_reads_rc.txt").exists() else {}
        n = 0
        for h, b in rc.items():
            if h.startswith("show running-config-interface gpon_onu-") and "%Error" not in b and (n < 3 or "video" in b):
                (out / "cli" / f"rc_{h.split('gpon_onu-')[1].replace('/', '_').replace(':', '_')}{'_catv' if 'video' in b else ''}.txt").write_text(anon(b) + "\n")
                n += 1
        # --- SNMP
        ifn = {}
        names = {}
        for line in open(ROOT / "docs/walks" / ifnf, errors="replace"):
            m = re.match(r'\.1\.3\.6\.1\.2\.1\.31\.1\.1\.1\.1\.(\d+) = STRING: "(\S+)"', line)
            if m:
                names[m.group(1)] = m.group(2)
        (out / "snmp" / "ifName_ifTable.txt").write_text(anon("".join(open(ROOT / "docs/walks" / ifnf, errors="replace")), ips=False))
        first_pon = next(i for i, n_ in names.items() if n_.endswith("/1/1") or n_.endswith("-1/1/1"))
        wanted = {f".1.3.6.1.4.1.3902.{o}.": k for k, o in SNMP_ONU.items()}
        rows = {}
        for line in open(walk, errors="replace"):
            for pre, k in wanted.items():
                if line.startswith(pre):
                    parts = line.split(" = ")[0][len(pre):].split(".")
                    if parts[0] == first_pon and int(parts[1]) <= 8:
                        rows.setdefault(k, []).append(line.rstrip("\n"))
        for k, v in rows.items():
            (out / "snmp" / f"onu_{k}_pon1.txt").write_text(anon("\n".join(v), ips=False) + "\n")
        sp = []
        for line in open(walk, errors="replace"):
            m = re.match(r"\.1\.3\.6\.1\.4\.1\.3902\.1082\.110\.5\.2\.2\.1\.(27|28)\.(\d+)\.(\d+) ", line)
            if m and m.group(2) == first_pon and ((int(m.group(3)) >> 16) & 0xff) <= 8:
                sp.append(line.rstrip("\n"))
        (out / "snmp" / "service_port_profiles_pon1.txt").write_text("\n".join(sp) + "\n")
        for tag, pre, lim in (("cards", ".1.3.6.1.4.1.3902.1082.10.1.2.4.", 4000), ("vlan_zte", ".1.3.6.1.4.1.3902.1082.40.50.2.1.2.", 400),
                              ("traffic_profiles", ".1.3.6.1.4.1.3902.1082.50.2.2.1.1.", 400)):
            v = [ln.rstrip("\n") for ln in open(walk, errors="replace") if ln.startswith(pre)][:lim]
            (out / "snmp" / f"{tag}.txt").write_text(anon("\n".join(v), ips=False) + "\n")
        for tag in ("system", "ifx"):
            p = ROOT / f"staging/walk_extra/ZTE_{model.upper()}_{tag}.txt"
            if p.exists():
                (out / "snmp" / f"{tag}.txt").write_text(anon(p.read_text(), ips=False))
        # --- ground truth (estado real conocido de las ONU de muestra, tomado de la CLI)
        gt = {"model": model.upper(), "note": "índice SNMP <ifIndexPON>.<nº ONU>; ifIndexPON se resuelve con ifName", "onu_samples": []}
        st_file = allb.get("show gpon onu state gpon_olt-1/1/1") or ""
        for line in st_file.splitlines():
            m = re.match(r"(\d+/\d+/\d+:(\d+))\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", line)
            if m and int(m.group(2)) <= 8:
                gt["onu_samples"].append({"cli_location": m.group(1), "snmp_index": f"{first_pon}.{m.group(2)}", "admin_state": m.group(3), "omcc_state": m.group(4), "phase_state": m.group(5)})
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=1, ensure_ascii=False))
        (out / "README.md").write_text(f"""# Fixtures ZTE {model.upper()} ({DATE})
Salida cruda de una OLT ZTE ZXA10 {model.upper()} real, **anonimizada** (seriales, MAC, IPv4; sin nombres/direcciones de abonado, sin credenciales ni comunidades SNMP).
- **Modelo/firmware:** ver `snmp/system.txt` (`sysDescr`, `sysObjectID`) y `cli/show_software.txt`.
- **CLI:** `cli/` — un archivo por comando (nombre = comando con `_`); salida sin editar salvo la anonimización. `show version` NO existe (usar `show software 1`).
  Los `Name`/`Description` de ONU aparecen como `********` (enmascarados por la OLT para la cuenta de lectura).
- **SNMP:** `snmp/` — columnas por ONU de las primeras 8 ONU del puerto 1 (`onu_*_pon1.txt`), perfiles de service-port, tarjetas, VLAN, perfiles de velocidad, `ifName`/`ifTable`, `system` e `ifX`.
  Índice de ONU: `<ifIndex del puerto PON>.<nº de ONU>` (potencias con `.1` final). `ground_truth.json` da la ubicación CLI y el estado de cada ONU de muestra.
- **Comandos usados:** los de `cli/` más los del catálogo `docs/validation/commands/zte_c6xx_verified_commands.json`.
- **Aviso:** muestra de UNA OLT por modelo; no prueba otros firmwares.
""")
        print(model, "cli:", len(list((out / 'cli').glob('*.txt'))), "snmp:", len(list((out / 'snmp').glob('*.txt'))), "gt:", len(gt["onu_samples"]))


if __name__ == "__main__":
    main()
