import asyncpg
from fastapi import APIRouter, Depends

from ..auth import Caller, get_caller
from ..db import get_conn
from ..events import log_event
from ..models import ComponentOut, HeartbeatIn

router = APIRouter(tags=["components"])

_SELECT = """
SELECT c.id, c.kind::text AS kind, c.name, r.name AS resource, c.status::text AS status,
       c.version, c.last_heartbeat_at
  FROM components c LEFT JOIN resources r ON r.id = c.resource_id
"""


# All components with status
@router.get("/components", response_model=list[ComponentOut])
async def list_components(caller: Caller = Depends(get_caller), conn: asyncpg.Connection = Depends(get_conn)):
    return [dict(r) for r in await conn.fetch(_SELECT + " ORDER BY c.kind, c.name")]

# Heartbeat of a component -> Status RUNNING
@router.post("/components/heartbeat", response_model=ComponentOut)
async def heartbeat(
    body: HeartbeatIn,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    async with conn.transaction():
        old = await conn.fetchrow(
            "SELECT status::text AS status, last_heartbeat_at FROM components WHERE id = $1 FOR UPDATE",
            caller.id,
        )
        await conn.execute(
            """
            UPDATE components
               SET status = 'RUNNING', last_heartbeat_at = now(), version = COALESCE($2, version)
             WHERE id = $1
            """,
            caller.id, body.version,
        )
        if old["last_heartbeat_at"] is None:
            await log_event(conn, "component.registered", component_id=caller.id,
                            message=f"{caller.name} hat sich zum ersten Mal gemeldet")
        if old["status"] != "RUNNING":
            await log_event(conn, "component.status_changed", component_id=caller.id,
                            message=f"{caller.name}: {old['status']} -> RUNNING",
                            data={"old": old["status"], "new": "RUNNING"})
    return dict(await conn.fetchrow(_SELECT + " WHERE c.id = $1", caller.id))
