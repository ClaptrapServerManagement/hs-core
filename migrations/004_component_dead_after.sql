INSERT INTO settings (key, value, description) VALUES
    ('component_dead_after_seconds', '90',
     'Ohne Heartbeat länger als das gilt eine Komponente als DEAD');

INSERT INTO schema_migrations (filename) VALUES ('004_component_dead_after.sql');