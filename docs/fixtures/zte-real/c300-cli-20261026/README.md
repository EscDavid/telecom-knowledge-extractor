# Fixtures de CLI ZTE ZXA10 C300 V2.1.0 (20261026)
Salida cruda de una OLT clásica real, **anonimizada** (seriales, MAC, IPv4 y `Name`/`Description` de ONU, que en clásicas salen EN CLARO).
- Sintaxis de clásicas: `gpon-olt_1/3/1`, `gpon-onu_1/3/1:2`. La de C6 (`gpon_olt-…`) da `Invalid input`. `show version` es ambiguo (`_AMBIGUO`): usar `show version-running`.
- `…_INVALIDO` documenta un comando que NO existe. `show gpon onu uncfg` devuelve `No related information to show` con 0 ONU (válido).
- `ground_truth.json`: potencia por CLI de ONU concretas (el SNMP crudo esperado se confirma con `snmpget`).
- Muestra de UNA OLT; no prueba otros firmwares ni la C320 (misma plataforma, no ejecutada).
