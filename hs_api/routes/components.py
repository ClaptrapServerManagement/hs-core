import asyncpg
from fastapi import APIRouter, Depends

from ..auth import Caller, get_caller
from ..db import get_conn
from ..events import log_event
from ..models import ComponentOut, HeartbeatIn

router = APIRouter(tags=["components"])

@router.post("/components/heartbeat", response_model=ComponentOut)
async def heartbeat(
    body: HeartbeatIn,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # If component has heartbeat, status -> RUNNING
    async with conn.transaction():
        old = await conn.fetchrow(
            "SELECT status::text AS status, last_heartbeat_at FROM components WHERE id = $1 FOR UPDATE",
            caller.id,
        )
        row = await conn.fetchrow(
            """
            UPDATE components
               SET status = 'RUNNING', last_heartbeat_at = now(),
                   version = COALESCE($2, version)
             WHERE id = $1
            RETURNING id, kind::text AS kind, name, status::text AS status,
                      version, last_heartbeat_at
            """,
            caller.id, body.version,
        )
        if old["last_heartbeat_at"] is None:
            await log_event(conn, "component.registered", component_id=caller.id,
                            message=f"{caller.name} hat sich zum ersten mal gemeldet")
            if old["status"] != "RUNNING":
                await log_event(conn, "component.status_changed", component_id=caller.id,
                                message=f"{caller.name}: {old['status']} -> RUNNING",
                                data={"old": old["status"], "new": "RUNNING"})
        return dict(row)