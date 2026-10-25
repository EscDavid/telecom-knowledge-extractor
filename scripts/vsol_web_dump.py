#!/usr/bin/env python3
"""Volcado de SOLO LECTURA del estado de la VSOL por la API de su web (un único login).

Evidencia de nivel D (estado del equipo vía web, NO OIDs). Lista cerrada de consultas:
GET de estado y los POST que la propia web usa para LEER (`select=255`, autofind por PON).
Sin ningún endpoint de configuración. Pausa entre peticiones (el equipo limita la tasa),
valores sensibles enmascarados (contraseñas, communities, LOID, descripciones/nombres).

    python3 scripts/vsol_web_dump.py                 # -> docs/walks/VSOL_V1600G2B_web.json
    python3 scripts/vsol_web_dump.py --delay 2 --no-autofind
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import creds  # noqa: E402

_spec = importlib.util.spec_from_file_location("vsol_web_probe", ROOT / "scripts" / "vsol_web_probe.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

# (nombre, método, ruta, cuerpo) — lista CERRADA, solo lectura
QUERIES = [
    ("systeminfo", "GET", "/action/systeminfo", None),
    ("oltConfigState", "GET", "/action/oltConfigState", None),
    ("oltType", "GET", "/action/oltType", None),
    ("serviceport", "GET", "/action/serviceport", None),
    ("loginaccess", "GET", "/action/loginaccess", None),
    ("ntp", "GET", "/action/ntp", None),
    ("portState", "GET", "/action/portState", None),
    ("fan", "GET", "/action/fan", None),
    ("alarm_config", "GET", "/action/alarm", None),
    ("geinfo", "GET", "/action/geinfo", None),
    ("geoptical", "GET", "/action/geoptical", None),
    ("gponinfo", "GET", "/action/gponinfo", None),
]
# PII/credenciales: contraseñas, communities, LOID, descripciones y nombres de ONU/abonado.
# Nombres de interfaz y de fabricante NO son sensibles.
_MASK = re.compile(r"pass|pwd|secret|community|cmmty|token|loid|checkcode|desc|remark|location|contact"
                   r"|onu_?name|user_?name|^name$|customer|subscriber", re.I)
_KEEP = re.compile(r"^community_table$", re.I)


def mask(obj, key=""):
    if isinstance(obj, dict):
        return {k: mask(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v, key) for v in obj]
    if isinstance(obj, str) and obj and _MASK.search(key) and not _KEEP.match(key):
        return "***"
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--delay", type=float, default=1.5, help="segundos entre peticiones")
    ap.add_argument("--no-autofind", action="store_true")
    ap.add_argument("--no-onu", action="store_true", help="omite las listas de ONU por PON")
    ap.add_argument("--pon", type=int, action="append", help="solo estos PON para las listas de ONU (1-16)")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--out", default=str(ROOT / "docs" / "walks" / "VSOL_V1600G2B_web.json"))
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    host = creds.get("VSOL", "HOST")
    port = int(creds.get("VSOL", "CLI_PORT") or 0)
    user, pw = creds.get("VSOL", "CLI_USER"), creds.get("VSOL", "CLI_PASSWORD")
    if not (host and port and user and pw):
        print("faltan TKC_VSOL_HOST / CLI_PORT / CLI_USER / CLI_PASSWORD")
        return 2
    web = probe.Web(host, port, a.timeout)

    form = urllib.parse.urlencode({"user": user, "pass": pw, "verification_code": "",
                                   "button": "Login", "who": 100})
    st, hd, body = web.request("POST", "/action/main", body=form)
    del pw, form
    cks = probe.set_cookies(hd)
    if st != 200 or not cks:
        print(f"login sin sesión (HTTP {st}, cookies {len(cks)})")
        return 1
    ck = "; ".join(c.split(";", 1)[0].strip() for c in cks)
    print("login OK (una sola sesión)")

    out = {"meta": {"source": "web API de la OLT (nivel D: estado, no OIDs)", "vendor": "VSOL",
                    "host": "(omitido)", "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "note": "valores sensibles enmascarados; reloj del equipo desfasado (2022)"},
           "results": {}}

    def run(name, method, path, data):
        nonlocal ck
        time.sleep(a.delay)
        body = urllib.parse.urlencode(data) if data else None
        try:
            st, hd, b = web.request(method, path, body=body, cookie=ck)
        except OSError as exc:
            out["results"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"  {name:16s} ERROR {type(exc).__name__}")
            return None
        nxt = probe.set_cookies(hd)
        if nxt:
            ck = "; ".join(c.split(";", 1)[0].strip() for c in nxt)
        o = probe.try_json(b)
        out["results"][name] = {"http": st, "bytes": len(b),
                                "data": mask(o) if o is not None else (b.decode("utf-8", "replace")[:300] if b else "")}
        flag = "vacío (¿sesión?)" if not b else f"{len(b)} B"
        print(f"  {name:16s} HTTP {st}  {flag}")
        return o

    for name, method, path, data in QUERIES:
        run(name, method, path, data)

    if not a.no_onu:
        print("  -- ONU registradas por PON (auth + estado)")
        onus = {}
        for p in (a.pon or range(1, 17)):
            body = {"slotid": 0, "portid": p, "port_id": p + 8}
            o1 = run(f"onuauth_pon{p}", "POST", "/action/gpononuauthinfo", body)
            o2 = run(f"onustatus_pon{p}", "POST", "/action/gpononustatusinfo", body)
            n1 = len(((o1 or {}).get("data") or {}).get("onuAuth_list") or []) if isinstance(o1, dict) else 0
            n2 = len(((o2 or {}).get("data") or {}).get("onuStatus_list") or []) if isinstance(o2, dict) else 0
            if n1 or n2:
                onus[p] = {"auth": n1, "status": n2}
        out["onu_by_pon"] = onus
        print("  ONU por PON:", onus or "ninguna")

    if not a.no_autofind:
        print("  -- autofind por PON (ONU sin autorizar)")
        auto = {}
        for p in range(1, 17):
            o = run(f"autofind_pon{p}", "POST", "/action/gpononuautofind", {"slotid": 0, "portid": p})
            lst = (o or {}).get("data", {}).get("onu_autofind_list") if isinstance(o, dict) else None
            if lst:
                auto[p] = len(lst)
        out["autofind_by_pon"] = auto

    out["summary"] = {k: ("ok" if v.get("bytes") else "vacío/error") for k, v in out["results"].items()
                      if not k.startswith(("autofind_pon", "onuauth_pon", "onustatus_pon"))}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nGuardado: {a.out}  ({Path(a.out).stat().st_size // 1024} KB; en .gitignore)")
    empty = [k for k, v in out["summary"].items() if v != "ok"]
    if empty:
        print("sin datos:", ", ".join(empty))
    return 0


if __name__ == "__main__":
    sys.exit(main())
