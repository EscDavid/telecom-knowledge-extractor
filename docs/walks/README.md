# Fase 2 — snmpwalks reales

Coloca aquí los walks de producción. El pipeline los detecta y procesa automáticamente
tras la Fase 1 (ver `main.py` → Fase 2 y `config/pipeline.yaml` → `walk_validator`).

## Convención de nombres (obligatoria)

    {VENDOR}_{MODELO}[_tipo].txt

- `VENDOR` debe existir en `classifier.known_vendors`.
- `MODELO` debe estar mapeado en `FAMILY_MAP` (`src/walk_validator/walk_validator.py`):
  `C300 → ZXA10 C300`, `C320 → ZXA10 C320`, `C620 → ZXA10 C620`, etc.
- Sin firmware ni fecha en el nombre.

### Tipos de walk (sufijo → extractor)

Un mismo modelo puede aportar varios walks complementarios; **todos convergen en un
único catálogo** (se agrupan por `VENDOR_MODELO`):

    ZTE_C320.txt          → enterprise    (rama 3902.*)      → enriquece OIDs + poda
    ZTE_C320_entities.txt → entity_table  (entPhysicalTable) → confirma entidades hardware
    ZTE_C320_ifnames.txt  → if_table      (ifTable + ifName) → confirma puertos + valida bit_calculation

> Modelos con walks hoy: C300, C320 y **C620** (este último se genera con el recolector
> automático, ver más abajo). `_ifnames` = **ifTable (`2.2.1`) + ifName (`31.1.1.1.1`)**, en
> ese orden numérico dentro del mismo archivo.

- `entity_table`: `1.3.6.1.2.1.47.1.1.1.1` — inventario físico real (chasis, tarjetas,
  fuentes, fans, sensores). Confirma `card`/`shelf`/`power_supply`/`fan`/`sensor` → `verified`.
- `if_table`: `1.3.6.1.2.1.31.1.1.1.1` — interfaces y sus `ifIndex` compuestos. Confirma
  `pon_port`/`uplink_port` → `verified` y **valida el mapa de bits** del índice compuesto
  (shelf/slot/port) decodificando los `ifIndex` reales.

## Formato

Salida estándar de `snmpbulkwalk -On` (una línea por OID):

    .1.3.6.1.4.1.3902.1082.10.1.1.7.0 = INTEGER: 1

Walks parciales concatenados con `>>` son válidos.

## Qué hace la Fase 2

Cruza el walk contra el catálogo teórico semilla (`walk_validator.seed_from_family`,
por defecto `ZXA10 C320`) y escribe un catálogo **separado por modelo** (ej.
`catalog/zte/zxa10-c300/`) donde:

- OIDs confirmados por el walk → `status: verified` (+0.15 de confianza, bloque `empirical`).
- OIDs no confirmados **read-only** → **podados** (registrados en `results.json`).
- OIDs no confirmados **writable/read-create/estructurales** → conservados como `documented`.
- Anomalías reales (OID not-increasing, índices ASCII, escalas, ramas parciales) → `results.json`.

El catálogo teórico semilla **no se modifica**.

## Gate de bloqueo (hallazgos críticos)

Algunos hallazgos son **bloqueantes**: detienen la Fase 2 y **no escriben el catálogo**
hasta que el operador confirme o rechace. Hoy aplica a `bitcalc_validation` cuando el
`bit_calculation` del catálogo NO coincide con el `ifName` real (el layout de bits era una
suposición). El pipeline:

1. Deriva el layout correcto desde los pares (ifIndex, ifName) reales (`proposed_fix`).
2. Escribe `reports/walk_review/<familia>_pending.json` con el detalle y la propuesta.
3. Se detiene con código de salida `2` sin escribir el catálogo.

Para resolver, edita **`docs/walks/resolutions.json`** y vuelve a ejecutar `python main.py`:

    { "ZXA10 C300": { "bitcalc_validation": "accept" } }

- `accept` → aplica `proposed_fix` (reescribe los bits de shelf/slot/port en los índices
  compuestos y los marca `bitcalc_validated: true`, `bitcalc_source: empirical:ifXTable`).
- `reject` → mantiene el mapa del catálogo y marca los índices `bitcalc_validated: false`.

Se desactiva con `walk_validator.halt_on_blocking: false` en `config/pipeline.yaml`.

## Recolección automática (`py -m src.walk_collector`)

Para equipos donde se puede consultar por SNMP (hoy: **ZTE C620**), el recolector genera
los tres walks (`ZTE_C620.txt`, `ZTE_C620_entities.txt`, `ZTE_C620_ifnames.txt`) sin hacer
`snmpbulkwalk` a mano. Es **solo lectura** (SNMPv2c: GET / GETNEXT / GETBULK, nunca SET),
con una sola petición en vuelo, ritmo suave y reanudación exacta tras cualquier corte.

Configuración: sección `walk_collector` de `config/pipeline.yaml` (sin secretos). Host,
puerto y community salen de `TKC_SNMP_HOST`, `TKC_SNMP_PORT` y `TKC_SNMP_COMMUNITY` en el
`.env` (plantilla en `.env.example`); si la community está vacía se pide oculta por prompt.
La community **jamás** se imprime ni se guarda (logs, estado y reportes la enmascaran).

| Output | Archivo | Raíces OID |
|---|---|---|
| `enterprise` | `ZTE_C620.txt` | `1.3.6.1.4.1.3902` (descubrimiento por ramas) |
| `entities` | `ZTE_C620_entities.txt` | `1.3.6.1.2.1.47.1.1.1.1` (entPhysicalTable) |
| `ifnames` | `ZTE_C620_ifnames.txt` | `1.3.6.1.2.1.2.2.1` (ifTable) + `1.3.6.1.2.1.31.1.1.1.1` (ifName) |

Primera corrida escalonada (recomendada):

    py -m src.walk_collector --dry-run                  # valida config/credenciales, sin red
    py -m src.walk_collector --discover-only            # preflight + plan de ramas
    py -m src.walk_collector --resume --only entities
    py -m src.walk_collector --resume --only ifnames
    py -m src.walk_collector --resume --only enterprise # el grande (~800 mil filas)

Con estado previo hay que indicar `--resume` (continuar) o `--fresh` (archivar y empezar de
cero); sin ninguno el recolector sale con código 2 para no pisar nada. `--assemble-only`
re-ensambla y publica desde los fragmentos sin tocar la red; `--simulate` ejecuta todo
contra un agente falso en memoria (nunca usa la red ni publica en `docs/walks/`).

### Política de publicación

- Un output **solo se publica aquí si está COMPLETO** (todas sus tareas terminaron). Se
  ensambla aparte (orden numérico por arcos, sin duplicados, estrictamente creciente) y se
  publica con reemplazo atómico: nunca queda un `.txt` parcial, porque la Fase 2 (`main.py`)
  procesa todo `*.txt` de esta carpeta y podaría las ramas ausentes.
- `--allow-incomplete` (o `publish.allow_incomplete: true`) publica también un output
  incompleto; su primera línea lo declara: `# tkc-walk-collector v1 model:ZTE_C620
  output:enterprise status:INCOMPLETE missing:<n> rows:... run:... roots:...`. El encabezado
  no contiene ` = `, por lo que `parse_walk` lo ignora.
- Los `Hex-STRING` salen en una sola línea (net-snmp los parte cada 16 bytes); `parse_walk`
  los lee igual.
- El estado, los fragmentos y los reportes (`report.json` / `report.md`) quedan en
  `state/walk_collector/ZTE_C620/` (ignorado por git; idealmente fuera de OneDrive).

### Aviso de PII

Los walks contienen datos de la red del operador (seriales y nombres de ONU, descripciones,
IPs). Por eso `docs/walks/*C620*` y `state/` están en `.gitignore`: **no los subas a un repo
compartido**. Con `--redact prefixes` (y `walk_collector.redaction.prefixes`) los valores
STRING bajo esos prefijos se publican como `REDACTED-<hmac8>` (estable con la misma sal,
guardada en `redaction.salt`); los fragmentos crudos no se alteran.
