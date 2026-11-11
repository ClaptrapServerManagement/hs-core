-- =====================================================================
-- Homeserver Manager – Migration 005: Ausbau der API
--   1. View resource_hosts: zu welchem Host gehört eine Ressource
--   2. Neue Einstellung command_timeout_seconds
-- =====================================================================

BEGIN;

-- 1. Für jede Ressource der Host, auf dem sie letztlich läuft.
CREATE VIEW resource_hosts AS
SELECT r.id AS resource_id,
       CASE r.kind
           WHEN 'host' THEN r.id
           WHEN 'vm'   THEN r.parent_id
           ELSE p.parent_id
       END AS host_id
  FROM resources r
  LEFT JOIN resources p ON p.id = r.parent_id;

-- 2. Commands, die so lange offen sind, gelten als fehlgeschlagen
INSERT INTO settings (key, value, description) VALUES
    ('command_timeout_seconds', '300',
     'Commands, die so lange pending oder running sind, werden als failed markiert');

INSERT INTO schema_migrations (filename) VALUES ('005_api_complete.sql');

COMMIT;
