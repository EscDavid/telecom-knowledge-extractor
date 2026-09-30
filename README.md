# Telecom Knowledge Compiler (TKC)

Compilador de conocimiento que transforma documentación técnica de fabricantes de
OLTs (PDFs, archivos MIB) en catálogos estructurados.

## Fase actual — generación de catálogos JSON

El pipeline lee los documentos de `docs/`, los procesa y escribe catálogos JSON en
`catalog/`. **No hay inserción en BD todavía** (el Loader/MySQL es fase futura; el
schema vive en [`database/tkc_schema.sql`](database/tkc_schema.sql) como referencia).

```
docs/ → Classifier → Extractor → Normalizer → Correlator → Validator → Writer
      → catalog/{vendor}/{family}/catalog-{version}/
            ├── manifest.json
            ├── entities/{entity}.json
            ├── commands/{category}/{command}.json
            ├── oids/{entity}.json
            ├── relations/{entity}.json
            └── alarms/{entity}.json
```

## Estructura

| Ruta | Rol |
|------|-----|
| `src/classifier/` | Identifica vendor/family/firmware/doc_type (3 capas, `schemas/classifier_spec.json`) |
| `src/extractor/`  | Un extractor por doc_type: MIB, comandos, entidades, alarmas |
| `src/normalizer/` | Unifica aliases y construye IDs canónicos (`schemas/alias_policy.json`) |
| `src/correlator/` | Cruza fuentes, deriva relaciones, calcula confidence (`schemas/confidence_model.json`) |
| `src/validator/`  | Penalizaciones, status final, conflictos/huérfanos, manifest |
| `src/writer/`     | Escribe los JSON del catálogo (reemplaza al Loader en esta fase) |
| `schemas/`        | Contratos JSON del pipeline |
| `config/pipeline.yaml` | Rutas + vendor/family/firmware objetivo |

## Uso

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Coloca los documentos del fabricante en docs/{vendor}/{family}/
#   ej: docs/zte/zxa10-c320/{mib.my,command_reference.pdf,...}

python main.py --config config/pipeline.yaml
```

El catálogo queda en `catalog/<vendor>/<family>/catalog-<version>/`.
Los conflictos y huérfanos detectados se escriben en `results.json` (estilo
`tkc_results`, para la fase de carga futura).

## Recolector de walks (`src/walk_collector`)

Genera automáticamente los snmpwalks de una OLT **ZTE C620** para la Fase 2 (SNMPv2c, solo
lectura, una petición en vuelo, reanudable). Detalle y política de publicación en
[`docs/walks/README.md`](docs/walks/README.md).

```bash
pip install -r requirements.txt            # incluye pysnmp
# .env (ver .env.example): TKC_SNMP_HOST, TKC_SNMP_PORT, TKC_SNMP_COMMUNITY
py -m src.walk_collector --dry-run         # valida todo sin tocar la red
py -m src.walk_collector --discover-only   # preflight + plan
py -m src.walk_collector --resume --only entities
py -m src.walk_collector --resume --only ifnames
py -m src.walk_collector --resume --only enterprise
py -m src.walk_collector --help            # todas las opciones
```

Los walks completos se publican en `docs/walks/` y `main.py` los procesa como cualquier otro.
Códigos de salida: 0 completo · 1 con tareas fallidas/parciales · 2 uso/config · 3 detenido
(reanudable) · 4 preflight/auth/modelo · 5 E/S · 130 interrumpido.

## Tests

```bash
pip install pytest
python -m pytest -q
```

Los tests corren el pipeline completo sobre fixtures de texto en
`tests/fixtures/docs/` (no requieren `pdfplumber`).

## Fase futura (no implementada)

`src/loader/` (MySQL), delta processing por hash y `src/completeness/`
(reportes de completitud). Ver instrucciones del proyecto.
