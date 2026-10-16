import asyncio
import asyncpg
import json
import logging

from . import db
from .events import log_event

log = logging.getLogger("hs-api.monitor")

CHECK_INTERVAL_SECONDS = 15
DEFAULT_COMPONENT_DEAD_AFTER_SECONDS = 90

async def get_dead_after_seconds(conn) -> int:
    raw = await conn.fetchval(
        "SELECT value FROM settings WHERE key = 'component_dead_after_seconds'"
    )
    return int(json.loads(raw)) if raw is not None else DEFAULT_COMPONENT_DEAD_AFTER_SECONDS

async def check_components(conn: asyncpg.Connection) -> None:
    dead_after = await get_dead_after_seconds(conn)

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
            log.warning("%s meldet sich seit $s s nicht mehr -> DEAD", component["name"], dead_after)
            await log_event(
                conn, "component.status_changed",
                severity="warning",
                component_id=component["id"],
                message=f"{component['name']}: RUNNING -> DEAD",
                data={"old": "RUNNING", "new": "DEAD"}
                )

        # If agent dies, host status is UNKNOWN
        if component["kind"] == "host_agent" and component["resource_id"] is not None:
            await conn.execute(
                """
                    UPDATE resources
                       SET status = CASE WHEN status = 'STOPPING'
                                         THEN 'OFF'::resource_status
                                         ELSE 'UNKNOWN'::resource_status
                                    END,
                           status_detail = 'Host Agent meldet sich nicht mehr'
                     WHERE id = $1 AND status <> 'OFF'
                    """,
                    component["resource_id"]
            )

async def run_monitor() -> None:
    async with db.pool().aquire() as conn:
        grace = await get_dead_after_seconds(conn)
    log.info("Monitor startet nach %s s Gnadenfrist", grace)
    await asyncio.sleep(grace)

    while True:
        try:
            async with db.pool().aquire() as conn:
                await check_components(conn)
        except Exception:
            log.exception("Monitor-Run fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)