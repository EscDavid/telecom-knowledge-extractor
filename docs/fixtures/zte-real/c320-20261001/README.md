# Fixtures ZTE C320 (20261001)
Columnas SNMP `1012.3.50.11/12` de 39 ONU de una OLT C320 real, **anonimizadas** (seriales con el prefijo de fabricante y 4 bytes sintéticos; sin nombres/IP/descripciones de abonado ni credenciales).
- Incluye las 4 ONU con potencia de recepción con signo (raw >= 32768), 5 sin señal (65535) y 30 normales.
- Índice de ONU: `<ifIndex del puerto PON>.<nº de ONU>` (potencias con `.1` final). Serial = 8 bytes (4 de fabricante + 4).
- Muestra de UNA OLT por modelo; no prueba otros firmwares. Walk del 2026-10-01.
