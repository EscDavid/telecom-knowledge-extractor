# Fase 2 — snmpwalks reales

Coloca aquí los walks de producción. El pipeline los detecta y procesa automáticamente
tras la Fase 1 (ver `main.py` → Fase 2 y `config/pipeline.yaml` → `walk_validator`).

## Convención de nombres (obligatoria)

    {VENDOR}_{MODELO}[_tipo].txt

- `VENDOR` debe existir en `classifier.known_vendors`.
- `MODELO` debe estar mapeado en `FAMILY_MAP` (`src/walk_validator/walk_validator.py`):
  `C300 → ZXA10 C300`, `C320 → ZXA10 C320`, etc.
- Sin firmware ni fecha en el nombre.

### Tipos de walk (sufijo → extractor)

Un mismo modelo puede aportar varios walks complementarios; **todos convergen en un
único catálogo** (se agrupan por `VENDOR_MODELO`):

    ZTE_C320.txt          → enterprise    (rama 3902.*)      → enriquece OIDs + poda
    ZTE_C320_entities.txt → entity_table  (entPhysicalTable) → confirma entidades hardware
    ZTE_C320_ifnames.txt  → if_table      (ifXTable ifName)  → confirma puertos + valida bit_calculation

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
