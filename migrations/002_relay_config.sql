-- =====================================================================
-- Homeserver Manager – Migration 002: Relaiskonfiguration pro Host
-- Ausführen als hs_owner:
--   psql -h localhost -U hs_owner -d homeserver -v ON_ERROR_STOP=1 -f 002_relay_config.sql
-- =====================================================================

BEGIN;

ALTER TABLE hosts
    -- true = Relais schaltet bei HIGH, false = bei LOW
    ADD COLUMN relay_active_high  boolean NOT NULL DEFAULT true,
    -- Kurzer Druck: Einschalten (bei laufendem PC = sauberes Herunterfahren)
    ADD COLUMN power_on_press_ms  integer NOT NULL DEFAULT 100
        CHECK (power_on_press_ms BETWEEN 50 AND 2000),
    -- Langer Druck: Force-Off (Mainboards brauchen meist > 4 s)
    ADD COLUMN force_off_press_ms integer NOT NULL DEFAULT 8000
        CHECK (force_off_press_ms BETWEEN 4000 AND 15000),
    -- Ein GPIO-Pin darf nur ein Relais steuern
    ADD CONSTRAINT hosts_relay_pin_uq UNIQUE (relay_gpio_pin),
    -- Schalt- und Sense-Pin dürfen nicht derselbe sein
    ADD CONSTRAINT hosts_relay_sense_distinct
        CHECK (relay_gpio_pin IS DISTINCT FROM power_sense_gpio_pin OR relay_gpio_pin IS NULL);

COMMIT;