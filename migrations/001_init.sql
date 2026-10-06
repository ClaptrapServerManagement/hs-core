-- =====================================================================
-- Homeserver Manager – Migration 001: Initiales Schema
BEGIN;

-- Enums
CREATE TYPE resource_kind           AS ENUM ('host', 'vm', 'service');
CREATE TYPE resource_status         AS ENUM ('ON', 'OFF', 'STARTING', 'STOPPING', 'RESTARTING', 'UNKNOWN', 'ERROR');

CREATE TYPE component_kind          AS ENUM ('api', 'discord_bot', 'power_controller', 'dashboard', 'host_agent', 'vm_agent', 'service_manager');
CREATE TYPE component_status        AS ENUM ('RUNNING', 'DEAD', 'UNKNOWN', 'ERROR');

CREATE TYPE command_status          AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');
CREATE TYPE command_source          AS ENUM ('discord', 'dashboard', 'system', 'api');

CREATE TYPE scheduled_action_status AS ENUM ('scheduled', 'executed', 'cancelled', 'failed');
CREATE TYPE event_severity          AS ENUM ('debug', 'info', 'warning', 'error');

-- Hilfsfunktion: updated_at automatisch pflegen
CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- =====================================================================
-- 1. INFRASTRUKTUR: Ressourcen (Host -> VM -> Service)
-- =====================================================================
-- Gemeinsame Basistabelle. Commands, Permissions, Events usw. zeigen
-- immer auf resources.id -> echte Fremdschlüssel statt target_type/target_id.
CREATE TABLE resources (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          resource_kind   NOT NULL,
    parent_id     bigint          REFERENCES resources(id) ON DELETE RESTRICT,
    name          text            NOT NULL,          -- stabiler technischer Name, z.B. 'pve01', 'mc-vm'
    display_name  text,                              -- Anzeigename für Discord/Dashboard
    status        resource_status NOT NULL DEFAULT 'UNKNOWN',
    status_detail text,                              -- z.B. Fehlerbeschreibung bei ERROR
    status_since  timestamptz     NOT NULL DEFAULT now(),
    last_seen_at  timestamptz,                       -- letzter erfolgreicher Kontakt
    enabled       boolean         NOT NULL DEFAULT true,
    created_at    timestamptz     NOT NULL DEFAULT now(),
    updated_at    timestamptz     NOT NULL DEFAULT now(),
    UNIQUE (kind, name),
    UNIQUE (id, kind),                               -- Ziel für die Kind-sicheren FKs unten
    CHECK ((kind = 'host') = (parent_id IS NULL))    -- nur Hosts haben keinen Parent
);
CREATE INDEX resources_parent_idx ON resources (parent_id);

-- Hierarchie prüfen: VM hängt an Host, Service hängt an VM
CREATE FUNCTION check_resource_parent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_kind resource_kind;
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        SELECT kind INTO parent_kind FROM resources WHERE id = NEW.parent_id;
        IF (NEW.kind = 'vm' AND parent_kind <> 'host')
        OR (NEW.kind = 'service' AND parent_kind <> 'vm') THEN
            RAISE EXCEPTION 'Ungültige Hierarchie: % kann nicht unter % hängen', NEW.kind, parent_kind;
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER resources_check_parent
    BEFORE INSERT OR UPDATE OF parent_id, kind ON resources
    FOR EACH ROW EXECUTE FUNCTION check_resource_parent();

-- status_since automatisch setzen, wenn sich der Status ändert
CREATE FUNCTION resources_before_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        NEW.status_since := now();
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER resources_before_update
    BEFORE UPDATE ON resources
    FOR EACH ROW EXECUTE FUNCTION resources_before_update();

-- Typspezifische Details (1:1 zu resources).
-- Die Spalte "kind" ist fest und stellt über den zusammengesetzten FK sicher,
-- dass z.B. eine hosts-Zeile nie auf eine VM-Ressource zeigt.
CREATE TABLE hosts (
    resource_id          bigint PRIMARY KEY,
    kind                 resource_kind NOT NULL DEFAULT 'host' CHECK (kind = 'host'),
    proxmox_node         text     NOT NULL,          -- Node-Name in Proxmox, z.B. 'pve'
    ip_address           inet,
    mac_address          macaddr,
    relay_gpio_pin       smallint CHECK (relay_gpio_pin BETWEEN 0 AND 27),       -- BCM-Nummer
    power_sense_gpio_pin smallint CHECK (power_sense_gpio_pin BETWEEN 0 AND 27), -- optional
    FOREIGN KEY (resource_id, kind) REFERENCES resources (id, kind) ON DELETE CASCADE
);

CREATE TABLE vms (
    resource_id  bigint PRIMARY KEY,
    kind         resource_kind NOT NULL DEFAULT 'vm' CHECK (kind = 'vm'),
    proxmox_vmid integer NOT NULL UNIQUE CHECK (proxmox_vmid >= 100),
    ip_address   inet,
    FOREIGN KEY (resource_id, kind) REFERENCES resources (id, kind) ON DELETE CASCADE
);

CREATE TABLE services (
    resource_id  bigint PRIMARY KEY,
    kind         resource_kind NOT NULL DEFAULT 'service' CHECK (kind = 'service'),
    service_type text  NOT NULL,                     -- 'minecraft', später weitere
    config       jsonb NOT NULL DEFAULT '{}',        -- service-spezifische Einstellungen
    FOREIGN KEY (resource_id, kind) REFERENCES resources (id, kind) ON DELETE CASCADE
);

-- =====================================================================
-- 2. SOFTWARE-KOMPONENTEN (Core-Dienste und Agents)
-- =====================================================================
CREATE TABLE components (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind              component_kind   NOT NULL,
    name              text             NOT NULL UNIQUE,   -- z.B. 'host-agent-pve01'
    resource_id       bigint REFERENCES resources(id) ON DELETE CASCADE, -- worauf läuft sie (NULL = Pi/Core)
    status            component_status NOT NULL DEFAULT 'UNKNOWN',
    version           text,
    last_heartbeat_at timestamptz,
    api_token_hash    text,             -- nur der Hash des Agent-Tokens, nie der Klartext
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER components_updated_at BEFORE UPDATE ON components
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 3. BENUTZER, IDENTITÄTEN, ROLLEN
-- =====================================================================
CREATE TABLE users (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    display_name text    NOT NULL,
    is_admin     boolean NOT NULL DEFAULT false,   -- Admin umgeht alle Beschränkungen
    is_active    boolean NOT NULL DEFAULT true,    -- deaktivieren statt löschen (Historie bleibt)
    note         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Die "zugeordneten IDs" eines Users: eine Zeile pro externem Konto.
-- UNIQUE (provider, external_id) garantiert, dass ein Discord-Konto
-- nie zwei Usern gleichzeitig gehören kann.
CREATE TABLE user_identities (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider      text   NOT NULL CHECK (provider IN ('discord')),  -- später erweiterbar
    external_id   text   NOT NULL,   -- Discord-Snowflake als text (64 bit, kein Rundungsproblem in JS)
    external_name text,              -- zuletzt gesehener Anzeigename, nur informativ
    linked_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, external_id)
);
CREATE INDEX user_identities_user_idx ON user_identities (user_id);

-- Bequeme Sicht: jeder User mit Array seiner IDs, z.B. {discord:123456789012345678}
CREATE VIEW users_with_identities AS
SELECT u.id,
       u.display_name,
       u.is_admin,
       u.is_active,
       COALESCE(
           array_agg(i.provider || ':' || i.external_id ORDER BY i.provider, i.external_id)
               FILTER (WHERE i.id IS NOT NULL),
           '{}'
       ) AS identities
FROM users u
LEFT JOIN user_identities i ON i.user_id = u.id
GROUP BY u.id;

CREATE TABLE roles (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL UNIQUE,         -- z.B. 'minecraft-spieler'
    description     text,
    discord_role_id text UNIQUE                   -- optional: an Discord-Rolle koppeln
);

CREATE TABLE user_roles (
    user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id bigint NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX user_roles_role_idx ON user_roles (role_id);

-- =====================================================================
-- 4. AKTIONEN UND BERECHTIGUNGEN
-- =====================================================================
-- Katalog aller Aktionen, die es im System gibt.
CREATE TABLE actions (
    key                     text PRIMARY KEY CHECK (key ~ '^[a-z_]+\.[a-z_]+$'),  -- 'host.power_on'
    target_kind             resource_kind NOT NULL,
    description             text    NOT NULL,
    is_read_only            boolean NOT NULL DEFAULT false,  -- z.B. Status abfragen, erzeugt keinen Command
    target_cooldown_seconds integer NOT NULL DEFAULT 0 CHECK (target_cooldown_seconds >= 0)
    -- ^ Hardwareschutz: Mindestabstand pro Ziel, gilt für ALLE Nutzer gemeinsam
);

-- Eine Berechtigungsregel: WER (Rolle ODER User) darf WAS (Aktion) WORAN (Ressource oder alle).
CREATE TABLE permissions (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role_id               bigint REFERENCES roles(id) ON DELETE CASCADE,
    user_id               bigint REFERENCES users(id) ON DELETE CASCADE,
    action_key            text   NOT NULL REFERENCES actions(key) ON UPDATE CASCADE,
    resource_id           bigint REFERENCES resources(id) ON DELETE CASCADE,  -- NULL = alle passenden Ressourcen
    can_request           boolean NOT NULL DEFAULT false,  -- Aktion anfordern
    can_postpone          boolean NOT NULL DEFAULT false,  -- geplante Aktion aufschieben
    can_cancel            boolean NOT NULL DEFAULT false,  -- geplante Aktion abbrechen
    can_execute_now       boolean NOT NULL DEFAULT false,  -- geplante Aktion sofort ausführen
    user_cooldown_seconds integer CHECK (user_cooldown_seconds >= 0),  -- Spamschutz pro User; NULL = keiner
    max_postpones         integer CHECK (max_postpones >= 0),          -- NULL = unbegrenzt
    created_at            timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(role_id, user_id) = 1),           -- genau eins von beiden
    UNIQUE NULLS NOT DISTINCT (role_id, user_id, action_key, resource_id)
);
CREATE INDEX permissions_role_idx   ON permissions (role_id);
CREATE INDEX permissions_user_idx   ON permissions (user_id);
CREATE INDEX permissions_action_idx ON permissions (action_key);

-- Zeitfenster einer Regel. Keine Zeile = jederzeit erlaubt.
-- Auswertung in der Zeitzone aus settings('timezone').
-- Fenster über Mitternacht = zwei Zeilen (z.B. Fr 20:00-24:00 und Sa 00:00-02:00).
CREATE TABLE permission_time_windows (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    permission_id bigint   NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    iso_weekday   smallint NOT NULL CHECK (iso_weekday BETWEEN 1 AND 7),  -- 1 = Mo ... 7 = So
    start_time    time     NOT NULL,
    end_time      time     NOT NULL,   -- '24:00' ist erlaubt
    CHECK (start_time < end_time)
);
CREATE INDEX permission_time_windows_perm_idx ON permission_time_windows (permission_id);

-- =====================================================================
-- 5. GEPLANTE AKTIONEN (z.B. Auto-Shutdown)
-- =====================================================================
CREATE TABLE scheduled_actions (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action_key           text   NOT NULL REFERENCES actions(key) ON UPDATE CASCADE,
    target_id            bigint NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    reason               text   NOT NULL,     -- z.B. 'auto_shutdown_idle'
    status               scheduled_action_status NOT NULL DEFAULT 'scheduled',
    created_by_user_id   bigint REFERENCES users(id) ON DELETE SET NULL,  -- NULL = System
    execute_at           timestamptz NOT NULL,
    original_execute_at  timestamptz NOT NULL,
    postpone_count       integer NOT NULL DEFAULT 0 CHECK (postpone_count >= 0),
    announced_at         timestamptz,         -- wann in Discord angekündigt
    discord_message_id   text,                -- Ankündigung, um sie später zu editieren
    cancelled_by_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
    cancel_reason        text,                -- 'user', 'use_case_detected', ...
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'cancelled' OR cancel_reason IS NOT NULL)
);
-- Pro Ziel und Aktion höchstens eine aktive Planung
CREATE UNIQUE INDEX scheduled_actions_one_active_uq
    ON scheduled_actions (action_key, target_id) WHERE status = 'scheduled';
CREATE INDEX scheduled_actions_due_idx
    ON scheduled_actions (execute_at) WHERE status = 'scheduled';
CREATE TRIGGER scheduled_actions_updated_at BEFORE UPDATE ON scheduled_actions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 6. COMMANDS (gewünschte Aktionen)
-- =====================================================================
CREATE TABLE commands (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action_key              text   NOT NULL REFERENCES actions(key) ON UPDATE CASCADE,
    target_id               bigint NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    source                  command_source NOT NULL,
    requested_by_user_id    bigint REFERENCES users(id) ON DELETE SET NULL,   -- NULL = System
    scheduled_action_id     bigint REFERENCES scheduled_actions(id) ON DELETE SET NULL,
    status                  command_status NOT NULL DEFAULT 'pending',
    parameters              jsonb  NOT NULL DEFAULT '{}',
    result                  jsonb,
    error_message           text,
    claimed_by_component_id bigint REFERENCES components(id) ON DELETE SET NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    started_at              timestamptz,
    finished_at             timestamptz,
    CHECK (status <> 'running' OR started_at IS NOT NULL),
    CHECK (status NOT IN ('completed', 'failed', 'cancelled') OR finished_at IS NOT NULL),
    CHECK (status <> 'failed' OR error_message IS NOT NULL)
);
-- Offene Commands schnell finden (Recovery nach Neustart)
CREATE INDEX commands_pending_idx ON commands (created_at) WHERE status = 'pending';
-- Cooldown pro User
CREATE INDEX commands_user_cooldown_idx
    ON commands (requested_by_user_id, action_key, target_id, created_at DESC);
-- Cooldown pro Ziel (Hardwareschutz)
CREATE INDEX commands_target_cooldown_idx
    ON commands (target_id, action_key, created_at DESC);
-- Pro Ziel höchstens ein offener Command -> kein Start/Stop-Wettlauf
CREATE UNIQUE INDEX commands_one_open_per_target_uq
    ON commands (target_id) WHERE status IN ('pending', 'running');

-- =====================================================================
-- 7. EVENTS (tatsächlich Eingetretenes, nur anhängen)
-- =====================================================================
CREATE TABLE events (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at         timestamptz    NOT NULL DEFAULT now(),
    event_type          text           NOT NULL,   -- 'vm.started', 'resource.status_changed', ...
    severity            event_severity NOT NULL DEFAULT 'info',
    resource_id         bigint REFERENCES resources(id)         ON DELETE SET NULL,
    command_id          bigint REFERENCES commands(id)          ON DELETE SET NULL,
    scheduled_action_id bigint REFERENCES scheduled_actions(id) ON DELETE SET NULL,
    user_id             bigint REFERENCES users(id)             ON DELETE SET NULL,
    component_id        bigint REFERENCES components(id)        ON DELETE SET NULL,
    message             text,
    data                jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX events_time_idx     ON events (occurred_at DESC);
CREATE INDEX events_resource_idx ON events (resource_id, occurred_at DESC);
CREATE INDEX events_command_idx  ON events (command_id);

-- Jede Statusänderung einer Ressource automatisch als Event protokollieren
CREATE FUNCTION log_resource_status_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO events (event_type, severity, resource_id, message, data)
    VALUES ('resource.status_changed',
            CASE WHEN NEW.status = 'ERROR' THEN 'error'::event_severity ELSE 'info'::event_severity END,
            NEW.id,
            format('%s "%s": %s -> %s', NEW.kind, NEW.name, OLD.status, NEW.status),
            jsonb_build_object('old', OLD.status, 'new', NEW.status, 'detail', NEW.status_detail));
    RETURN NULL;
END $$;

CREATE TRIGGER resources_log_status_change
    AFTER UPDATE OF status ON resources
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION log_resource_status_change();

-- =====================================================================
-- 8. USE-CASES (aktive Nutzungen -> Grundlage für Energiesparlogik)
-- =====================================================================
CREATE TABLE use_cases (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    resource_id              bigint NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    kind                     text   NOT NULL,              -- 'ssh_session', 'minecraft_player', ...
    identifier               text   NOT NULL DEFAULT '',   -- z.B. Spielername oder user@ip
    reported_by_component_id bigint REFERENCES components(id) ON DELETE SET NULL,
    started_at               timestamptz NOT NULL DEFAULT now(),
    last_seen_at             timestamptz NOT NULL DEFAULT now(),  -- veraltet = Agent tot -> als beendet werten
    ended_at                 timestamptz,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE UNIQUE INDEX use_cases_active_uq
    ON use_cases (resource_id, kind, identifier) WHERE ended_at IS NULL;
CREATE INDEX use_cases_active_idx ON use_cases (resource_id) WHERE ended_at IS NULL;

-- =====================================================================
-- 9. EINSTELLUNGEN
-- =====================================================================
CREATE TABLE settings (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    description text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER settings_updated_at BEFORE UPDATE ON settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 10. LISTEN/NOTIFY
-- =====================================================================
-- Kanal 'commands': neuer Command oder Statuswechsel
CREATE FUNCTION notify_command() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('commands', json_build_object(
        'id', NEW.id, 'action', NEW.action_key,
        'target_id', NEW.target_id, 'status', NEW.status)::text);
    RETURN NULL;
END $$;

CREATE TRIGGER commands_notify_insert
    AFTER INSERT ON commands
    FOR EACH ROW EXECUTE FUNCTION notify_command();

CREATE TRIGGER commands_notify_status
    AFTER UPDATE OF status ON commands
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION notify_command();

-- Kanal 'events': jedes neue Event (z.B. für Discord-Ankündigungen, Dashboard)
CREATE FUNCTION notify_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('events', json_build_object(
        'id', NEW.id, 'type', NEW.event_type, 'resource_id', NEW.resource_id)::text);
    RETURN NULL;
END $$;

CREATE TRIGGER events_notify
    AFTER INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION notify_event();

-- =====================================================================
-- 11. STAMMDATEN
-- =====================================================================
INSERT INTO actions (key, target_kind, description, is_read_only, target_cooldown_seconds) VALUES
    ('host.status',     'host', 'Status des Hosts abfragen',              true,    0),
    ('host.power_on',   'host', 'Host über das Relais einschalten',        false, 300),
    ('host.shutdown',   'host', 'Host sauber herunterfahren',              false, 300),
    ('host.force_off',  'host', 'Host hart über das Relais ausschalten',   false, 300),
    ('vm.status',       'vm',   'Status einer VM abfragen',                true,    0),
    ('vm.start',        'vm',   'VM starten',                              false,  60),
    ('vm.shutdown',     'vm',   'VM sauber herunterfahren',                false,  60),
    ('vm.restart',      'vm',   'VM neu starten',                          false, 120),
    ('vm.force_stop',   'vm',   'VM hart stoppen',                         false,  60);

INSERT INTO settings (key, value, description) VALUES
    ('timezone',                    '"Europe/Berlin"', 'Zeitzone für Zeitfenster und Anzeigen'),
    ('idle_shutdown_after_minutes', '15',              'Leerlaufzeit ohne Use-Case bis zur Planung eines Auto-Shutdowns'),
    ('shutdown_announce_minutes',   '10',              'Vorlauf der Discord-Ankündigung vor Ausführung'),
    ('default_postpone_minutes',    '30',              'Standarddauer beim Aufschieben'),
    ('use_case_stale_seconds',      '120',             'Ohne Meldung älter als das gilt ein Use-Case als beendet'),
    ('discord_guild_id',            'null',            'ID des Discord-Servers'),
    ('discord_announce_channel_id', 'null',            'Kanal für Ankündigungen');

-- =====================================================================
-- 12. RECHTE FÜR DIE ANWENDUNGSROLLE
-- =====================================================================
GRANT USAGE ON SCHEMA public TO hs_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hs_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hs_app;
-- Events sind eine Historie: nur anhängen, nie ändern
REVOKE UPDATE, DELETE ON events FROM hs_app;

COMMIT;