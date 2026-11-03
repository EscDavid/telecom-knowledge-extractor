# Escrituras certificadas en vivo en ZXA10 C300 y C320 (2026-11-03)

Evidencia de los comandos de ESCRITURA de las clásicas, ejecutados por los scripts de ISP Management
(`scripts/certificacion/*`: certificar-onu-clasica, verificar-pon-vlan, verificar-olt-clasica) en dos OLT reales con firmware V2.1.0:
`popular-c300` (OLT Unete Popular, ZXA10 C300) y `primavera-c320` (OLT PRIMAVERA, ZXA10 C320).

Cada paso: comando enviado por las plantillas de la aplicación (gate + auditoría), verificación releyendo el equipo y restauración
al estado original (comparación exacta con una captura previa). Los JSON salen ya ENMASCARADOS: serial → `<SN>`, posición →
`<PON>:<ONU>`, nombre/descripción/SSID → `<TEXTO>`. No hay datos de clientes.

Archivos por OLT: ONU (lecturas, descripción, velocidad, VLAN, reinicio, baja y alta), `write`, configuración de la ONU (CATV,
Ethernet, WiFi), puerto PON y VLAN, y perfiles/tipo de ONU/alta nueva con serial falso.

Hallazgos que no son `verified` (ver CHANGELOG_catalog.md 1.4.0): `wifi {enable|disable}` falla en una ONU ZP_CABLE (`unknown ME`),
`traffic-limit eth_0/N cir` falló en 4 de 4 ONU (no se cataloga), SSID sin ONU que lo publique.
