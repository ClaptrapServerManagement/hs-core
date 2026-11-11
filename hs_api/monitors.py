"""
Backgroundtasks (every 15s)

1. check_components     Components without heartbeat -> DEAD
2. timeout_commands     Commands in overtime -> failed
3. end_stale_use_cases  Use cases without current notice -> end
4. plan_idle_shutdown   Host without use_cases -> Schedule auto shutdown
5. execute_due_actions  Due actions in schedule -> commands
"""

import asnycio
import logging
import asyncpg

from . import db
from .command_service import finish_command
from .common import get_setting
from .events import log_event
from .scheduling import cancel_scheduled, create_scheduled, execute_scheduled

log = logging.getLogger("hs-api.monitor")

CHECK_INTERVAL_SECONDS = 15

# ======
# 1. Components
# ======
async def check_components(conn: asyncpg.Connection) -> None:
    dead_after = await get_setting(conn, "component_dead_after_seconds", 90)
    async with conn.transaction():
        dead = await conn.fetch(
            """
            UPDATE components
               SET status = 'DEAD'
             WHERE status = 'RUNNING'
               AND last_heartbeat_at < now() - ($1::int * interval '1 second')
            RETURNING id, name, kind::text AS kind, resource_id
            """,
            dead_after,
        )
        for component in dead:
            log.warning("%s meldet sich seit %s s nicht mehr -> DEAD", component["name"], dead_after)
            await log_event(conn, "component.status_changed", severity="warning", component_id=component["id"], message=f"{component['name']}: RUNNING -> DEAD", data={"old": "RUNNING", "new": "DEAD"})

            # Host Agent dies -> No info on host
            if component["kind"] == "host_agent" and component["resource_id"] is not None:
                await conn.execute(
                    """
                    UPDATE resources
                       SET status = CASE WHEN status = 'STOPPING' THEN 'OFF'::resource_status
                                         ELSE 'UNKNOWN'::resource_status END,
                           status_detail = 'Host Agent meldet sich nicht mehr'
                     WHERE id = $1 AND status <> 'OFF'
                    """,
                    component["resource_id"],
                )

# =====
# 2. Commands
# =====
async def timeout_commands(conn: asyncpg.Connection) -> None:
    timeout = await get_setting(conn, "command_timeout_seconds", 300)
    stuck = await conn.fetch(
        """
        SELECT id, status::text AS status, claimed_by_component_id FROM commands
         WHERE status IN ('pending', 'running')
           AND created_at < now() - ($1::int * interval '1 second')
        """,
        timeout,
    )
    for command in stuck:
        reason = ("Niemand hat den Command abgeholt" if command["status"] == "pending" else "Keine Rückmeldung der ausführenden Komponente")
        log.warning("Command %s: Zeitüberschreitung (%s)", command["id"], reason)
        async with conn.transaction():
            await finish_command(conn, command["id"], ok=False, error_message=f"Zeitüberschreitung: {reason}", component_id=command["claimed_by_component_id"])

# =====
# 3. use-cases
# =====
async def end_stale_use_cases(conn: asyncpg.Connection) -> None:
    stale_after = await get_setting(conn, "use_case_stale_seconds", 120)
    async with conn.transaction():
        ended = await conn.fetch(
            """
            UPDATE use_cases SET ended_at = greatest(last_seen_at, started_at)
             WHERE ended_at IS NULL
               AND last_seen_at < now() - ($1::int * interval '1 second')
            RETURNING id, resource_id, kind, identifier
            """,
            stale_after,
        )
        for uc in ended:
            await log_event(conn, "use_case.ended", resource_id=uc["resource_id"], message=f"{uc['kind']} {uc['identifier']} nicht mehr gemeldet", data={"use_case_id": uc["id"], "reason": "stale"})

# =====
# 4. Energy saving logic
# =====
# plans idle shutdown for running hosts not used for x amount of time
# used = active use_case, open command, scheduled action
async def plan_idle_shutdowns(conn: asyncpg.Connection) -> None:
    idle_minutes = await get_setting(conn, "idle_shutdown_after_minutes", 15)
    announce_minutes = await get_setting(conn, "shutdown_announce_minutes", 10)

    hosts = await conn.fetch(
        """
        WITH subtree AS (
            SELECT host_id, resource_id FROM resource_hosts
        ),
        activity AS (
            -- Letzter Zeitpunkt, zu dem auf dem Host etwas los war
            SELECT h.id, h.name,
                   greatest(
                       h.status_since,
                       (SELECT max(u.ended_at) FROM use_cases u
                          JOIN subtree s ON s.resource_id = u.resource_id WHERE s.host_id = h.id),
                       (SELECT max(c.created_at) FROM commands c
                          JOIN subtree s ON s.resource_id = c.target_id WHERE s.host_id = h.id),
                       (SELECT max(sa.updated_at) FROM scheduled_actions sa
                          JOIN subtree s ON s.resource_id = sa.target_id
                         WHERE s.host_id = h.id AND sa.status <> 'scheduled')
                   ) AS last_activity
              FROM resources h
             WHERE h.kind = 'host' AND h.enabled AND h.status = 'ON'
               AND NOT EXISTS (SELECT 1 FROM use_cases u JOIN subtree s ON s.resource_id = u.resource_id
                                WHERE s.host_id = h.id AND u.ended_at IS NULL)
               AND NOT EXISTS (SELECT 1 FROM commands c JOIN subtree s ON s.resource_id = c.target_id
                                WHERE s.host_id = h.id AND c.status IN ('pending', 'running'))
               AND NOT EXISTS (SELECT 1 FROM scheduled_actions sa JOIN subtree s ON s.resource_id = sa.target_id
                                WHERE s.host_id = h.id AND sa.status = 'scheduled')
        )
        SELECT id, name FROM activity
         WHERE last_activity < now() - ($1::int * interval '1 minute')
        """,
        idle_minutes,
    )
    for host in hosts:
        log.info("%s ist seit %s min ungenutzt -> Shutdown wird geplant", host["name"], idle_minutes)
        execute_at = await conn.fetchval("SELECT now() + ($1::int * interval '1 minute')", announce_minutes)
        await create_scheduled(conn, action_key="host.shutdown", target=host, reason="auto_shutdown_idle", execute_at=execute_at, user_id=None)

# =====
# 5. Scheduled actions
# =====
async def execute_due_actions(conn: asyncpg.Connection) -> None:
    async with conn.transaction():
        due = await conn.fetch(
            """
            SELECT sa.id, sa.action_key, sa.target_id, sa.reason, r.name AS target,
                   r.status::text AS target_status,
                   EXISTS (SELECT 1 FROM use_cases u JOIN resource_hosts s ON s.resource_id = u.resource_id
                            WHERE s.host_id = sa.target_id AND u.ended_at IS NULL) AS in_use
              FROM scheduled_actions sa
              JOIN resources r ON r.id = sa.target_id
             WHERE sa.status = 'scheduled' AND sa.execute_at <= now()
             ORDER BY sa.execute_at
               FOR UPDATE OF sa SKIP LOCKED
            """
        )
        for sa in due:
            if sa["reason"] == "auto_shutdown_idle":
                # Final call before shutdown
                if sa["in_use"]:
                    await cancel_scheduled(conn, sa["id"], reason="use_case_detected")
                    continue
                if sa["target_status"] != "ON":
                    await cancel_scheduled(conn, sa["id"], reason="superseded")
                    continue
            log.info("Scheduled Action %s fällig: %s für %s", sa["id"], sa["action_key"], sa["target"])
            await execute_scheduled(conn, sa)

# Loop
TASKS = [check_components, timeout_commands, end_stale_use_cases, plan_idle_shutdowns, execute_due_actions]
async def run_monitor() -> None:
    async with db.pool().acquire() as conn:
        grace = await get_setting(conn, "component_dead_after_seconds", 90)
    log.info("Monitor startet nach %s s Gnadenfrist", grace)
    await asyncio.sleep(grace)

    while True:
        for task in TASKS:
            try:
                async with db.pool().acquire() as conn:
                    await task(conn)
            except Exception:
                log.exception("Hintergrundaufgabe %s fehlgeschlagen", task.__name__)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
