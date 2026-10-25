"""Ensayo de carga SIN base de datos: ejecuta el Loader real contra un cursor falso que captura cada INSERT y valida
cada fila contra el esquema `database/ispm_tkc.sql` (NOT NULL, ENUM, VARCHAR(n), DECIMAL(p,s), JSON válido, PK repetida,
claves foráneas lógicas hacia filas ya insertadas en la misma carga).
Uso:  python scripts/loader_dry_run.py [c620|c600 ...]   (sale con 1 si alguna fila no cabe en la base)"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.loader import hashing, loader as L, readiness  # noqa: E402

SQL = (ROOT / "database/ispm_tkc.sql").read_text(encoding="utf-8")


def schema():
    out = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\)\s*ENGINE", SQL, re.S):
        cols, pk = {}, []
        body = re.sub(r"ENUM\(([^)]*)\)", lambda e: "ENUM(" + " ".join(e.group(1).split()) + ")", m.group(2))
        for line in body.split("\n"):
            line = re.sub(r"--.*$", "", line).strip().rstrip(",")
            c = re.match(r"^(\w+)\s+(ENUM\([^)]*\)|\w+(?:\([^)]*\))?)(.*)$", line)
            if c and c.group(1).upper() not in ("PRIMARY", "UNIQUE", "KEY", "CONSTRAINT", "FOREIGN", "INDEX"):
                t, rest = c.group(2), c.group(3).upper()
                cols[c.group(1)] = {"type": t, "notnull": "NOT NULL" in rest, "default": "DEFAULT" in rest or "AUTO_INCREMENT" in rest}
            p = re.match(r"^PRIMARY KEY \(([^)]*)\)", line)
            if p:
                pk = [x.strip() for x in p.group(1).split(",")]
        out[m.group(1)] = {"cols": cols, "pk": pk}
    return out


class FakeCur:
    def __init__(self):
        self.rows, self._id, self._last = [], 100, None
        self.lastrowid = 0

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        m = re.match(r"INSERT (?:IGNORE )?INTO (\w+) \(([^)]*)\) VALUES", s)
        if m:
            self._id += 1
            self.lastrowid = self._id
            self.rows.append((m.group(1), [c.strip() for c in m.group(2).split(",")], list(params)))
            self._last = {"id": self._id}
        elif s.startswith("SELECT id FROM"):
            self._last = {"id": self._id}
        elif "MAX(version_num)" in s:
            self._last = {"n": 1}
        elif s.startswith("SELECT id FROM tkc_catalog_versions"):
            self._last = None

    def fetchone(self):
        return self._last

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.cur = FakeCur()

    def cursor(self):
        return self.cur


def check_value(table, col, v, spec, errs):
    t = spec["type"]
    if v is None:
        if spec["notnull"] and not spec["default"]:
            errs.append(f"{table}.{col}: NULL en columna NOT NULL sin default")
        return
    if t.upper().startswith("ENUM"):
        allowed = set(re.findall(r"'([^']*)'", t))
        if str(v) not in allowed:
            errs.append(f"{table}.{col}: '{v}' no está en ENUM {sorted(allowed)}")
    elif t.upper().startswith("VARCHAR"):
        n = int(re.search(r"\((\d+)\)", t).group(1))
        if isinstance(v, str) and len(v) > n:
            errs.append(f"{table}.{col}: longitud {len(v)} > VARCHAR({n})")
    elif t.upper().startswith("DECIMAL"):
        p, sc = map(int, re.search(r"\((\d+),(\d+)\)", t).groups())
        if abs(float(v)) >= 10 ** (p - sc):
            errs.append(f"{table}.{col}: {v} fuera de rango DECIMAL({p},{sc})")
    elif t.upper() == "JSON":
        try:
            json.loads(v if isinstance(v, str) else json.dumps(v))
        except Exception:
            errs.append(f"{table}.{col}: JSON inválido")
    elif t.upper().startswith("TEXT") and isinstance(v, str) and len(v.encode("utf-8")) > 65535:
        errs.append(f"{table}.{col}: TEXT > 64 KB")


def run(fam):
    sch = schema()
    base = ROOT / "catalog/zte"
    cdir = max(glob.glob(str(base / f"zxa10-{fam}/catalog-*")))
    cdir = Path(cdir)
    conn = FakeConn()
    tier, _, _ = readiness.readiness(cdir)
    L.Loader(conn).load(cdir, "ZTE", f"ZXA10 {fam.upper()}", "gpon", cdir.name.replace("catalog-", ""), hashing.catalog_root_hash(cdir), tier)
    errs, pks, per_table = [], set(), {}
    for table, cols, vals in conn.cur.rows:
        per_table[table] = per_table.get(table, 0) + 1
        if table not in sch:
            errs.append(f"tabla inexistente en el esquema: {table}")
            continue
        spec = sch[table]
        for c, v in zip(cols, vals):
            if c not in spec["cols"]:
                errs.append(f"{table}.{c}: columna inexistente")
            else:
                check_value(table, c, v, spec["cols"][c], errs)
        for c, s in spec["cols"].items():
            if c not in cols and s["notnull"] and not s["default"]:
                errs.append(f"{table}.{c}: NOT NULL sin valor ni default")
        if spec["pk"] and all(p in cols for p in spec["pk"]):
            key = (table, tuple(vals[cols.index(p)] for p in spec["pk"]))
            if key in pks:
                errs.append(f"{table}: clave primaria repetida {key[1]}")
            pks.add(key)
    errs = sorted(set(errs))
    print(f"[{fam}] {cdir.name}: {len(conn.cur.rows)} filas en {len(per_table)} tablas {dict(sorted(per_table.items()))}")
    print(f"[{fam}] {'OK: todas las filas caben en el esquema' if not errs else str(len(errs)) + ' problemas'}")
    for e in errs[:30]:
        print("   ", e)
    return not errs


if __name__ == "__main__":
    ok = all([run(f) for f in (sys.argv[1:] or ["c620", "c600"])])
    sys.exit(0 if ok else 1)
