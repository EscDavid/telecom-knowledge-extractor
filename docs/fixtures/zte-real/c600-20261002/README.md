# Fixtures ZTE C600 (20261002)
Salida cruda de una OLT ZTE ZXA10 C600 real, **anonimizada** (seriales, MAC, IPv4; sin nombres/direcciones de abonado, sin credenciales ni comunidades SNMP).
- **Modelo/firmware:** ver `snmp/system.txt` (`sysDescr`, `sysObjectID`) y `cli/show_software.txt`.
- **CLI:** `cli/` — un archivo por comando (nombre = comando con `_`); salida sin editar salvo la anonimización. `show version` NO existe (usar `show software 1`).
  Los `Name`/`Description` de ONU aparecen como `********` (enmascarados por la OLT para la cuenta de lectura).
- **SNMP:** `snmp/` — columnas por ONU de las primeras 8 ONU del puerto 1 (`onu_*_pon1.txt`), perfiles de service-port, tarjetas, VLAN, perfiles de velocidad, `ifName`/`ifTable`, `system` e `ifX`.
  Índice de ONU: `<ifIndex del puerto PON>.<nº de ONU>` (potencias con `.1` final). `ground_truth.json` da la ubicación CLI y el estado de cada ONU de muestra.
- **Comandos usados:** los de `cli/` más los del catálogo `docs/validation/commands/zte_c6xx_verified_commands.json`.
- **Aviso:** muestra de UNA OLT por modelo; no prueba otros firmwares.
