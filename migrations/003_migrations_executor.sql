-- =====================================================================
-- Homeserver Manager – Migration 003
--   1. Standardrechte für hs_app auf künftige Tabellen
--   2. Tabelle schema_migrations (welche Migrationen sind eingespielt)
--   3. actions.executor: welche Komponente führt eine Action aus
--   4. resources.name global eindeutig (API adressiert Ressourcen per Name)
--   5. Komponentenname des Power Controllers an Nomenklatur anpassen
--
-- Konvention ab jetzt: Jede Migration trägt sich am Ende selbst in
-- schema_migrations ein, mit exakt ihrem Dateinamen.
-- =====================================================================

BEGIN;

-- 1. Tabellen, die hs_owner künftig anlegt, darf hs_app automatisch nutzen
ALTER DEFAULT PRIVILEGES FOR ROLE hs_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hs_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hs_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO hs_app;

-- 2. Buchführung über eingespielte Migrationen
CREATE TABLE schema_migrations (
    filename   text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
-- hs_app darf hier nur lesen
REVOKE INSERT, UPDATE, DELETE ON schema_migrations FROM hs_app;

INSERT INTO schema_migrations (filename) VALUES
    ('001_init.sql'),
    ('002_relay_config.sql');

-- 3. Zuständige Komponente pro Action (NULL nur bei reinen Abfragen)
ALTER TABLE actions ADD COLUMN executor component_kind;

UPDATE actions SET executor = 'power_controller'
    WHERE key IN ('host.power_on', 'host.force_off');
UPDATE actions SET executor = 'host_agent'
    WHERE key IN ('host.shutdown', 'vm.start', 'vm.shutdown', 'vm.restart', 'vm.force_stop');

ALTER TABLE actions ADD CONSTRAINT actions_executor_required
    CHECK (is_read_only OR executor IS NOT NULL);

-- 4. Ressourcennamen eindeutig über alle Arten hinweg
ALTER TABLE resources ADD CONSTRAINT resources_name_uq UNIQUE (name);

-- 5. Nomenklatur: Komponenten heißen wie ihre systemd-Unit
UPDATE components SET name = 'hs-power-controller' WHERE name = 'power-controller';

INSERT INTO schema_migrations (filename) VALUES ('003_migrations_executor.sql');

COMMIT;
