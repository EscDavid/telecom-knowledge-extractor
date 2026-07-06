-- =============================================================================
-- Usuario dedicado del Loader (tkc_loader) + grants acotados
-- Correr como ADMIN (root u otro con GRANT OPTION). Password: elegir uno FUERTE
-- y ponerlo en el .env del repo como TKC_DB_PASSWORD (NO usar root en el .env).
-- =============================================================================

-- Host: restringir al equipo que corre el loader. Ejemplos:
--   'tkc_loader'@'localhost'      si el loader corre en la misma maquina que MySQL
--   'tkc_loader'@'157.137.210.%'  si corre desde la red de ese rango
--   'tkc_loader'@'%'              cualquier host (menos seguro; solo si es necesario)
CREATE USER IF NOT EXISTS 'tkc_loader'@'%' IDENTIFIED BY 'CAMBIAR_POR_PASSWORD_FUERTE';

-- Escritura acotada SOLO al catalogo (DML; el loader hace INSERT/UPDATE/DELETE por
-- la carga idempotente y las sesiones). NO se dan DROP/CREATE/ALTER: el schema lo
-- despliega el admin aparte (ispm_tkc.sql).
GRANT SELECT, INSERT, UPDATE, DELETE ON ispm_tkc.* TO 'tkc_loader'@'%';

-- Lectura minima para el factor 1 (validar superadmin). Solo la tabla users.
GRANT SELECT ON db_auth.users TO 'tkc_loader'@'%';

FLUSH PRIVILEGES;

-- Verificar:  SHOW GRANTS FOR 'tkc_loader'@'%';
--
-- Revocar (si hiciera falta):
--   DROP USER 'tkc_loader'@'%';
