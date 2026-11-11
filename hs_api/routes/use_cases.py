import asyncpg
from fastapi import APIRouter, Depends, Query

from ..auth import Caller, get_caller, require_agent
from ..common import get_resource_row, resource_in_scope
from ..db import get_conn
from ..errors import ApiError
from ..events import log_event
from ..models import UseCaseOut, UseCaseSyncIn
from ..scheduling import cancel_auto_shutdowns_for_host

router = APIRouter(tags=["use cases"])

_SELECT = """
SELECT u.id, r.name AS resource, u.kind, u.identifier, u.started_at, u.last_seen_at, u.ended_at
  FROM use_cases u JOIN resources r ON r.id = u.resource_id
"""

@router.get("/use-cases", response_model=list[UseCaseOut])
async def list_use_cases(
    active: bool = True,
    resource: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    rows = await conn.fetch(
        _SELECT + """
         WHERE (NOT $1 OR u.ended_at IS NULL)
           AND ($2::text IS NULL OR r.name = $2)
         ORDER BY u.started_at DESC LIMIT $3""",
        active, resource, limit,
    )
    return [dict(r) for r in rows]

# Agend gives full list of uses, recall at heartbeat ?
@router.put("/resources/{name}/use-cases", response_model=list[UseCaseOut])
async def sync_use_cases(name: str, body: UseCaseSyncIn, caller: Caller = Depends(require_agent), conn: asyncpg.Connection = Depends(get_conn)):
    target = await get_resource_row(conn, name)
    if not await resource_in_scope(conn, caller, target["id"]):
        raise ApiError(403, "forbidden", f"'{caller.name}' ist für '{name}' nicht zuständig.")

    reported = {(uc.kind, uc.identifier) for uc in body.use_cases}

    async with conn.transaction():
        active = await conn.fetch(
            "SELECT id, kind, identifier FROM use_cases WHERE resource_id = $1 AND ended_at IS NULL FOR UPDATE",
            target["id"],
        )
        known = {(r["kind"], r["identifier"]): r["id"] for r in active}

        started = False
        for kind, identifier in reported - known.keys():
            uc_id = await conn.fetchval(
                """
                INSERT INTO use_cases (resource_id, kind, identifier, reported_by_component_id)
                VALUES ($1, $2, $3, $4) RETURNING id
                """,
                target["id"], kind, identifier, caller.id,
            )
            await log_event(conn, "use_case.started", resource_id=target["id"], component_id=caller.id,
                            message=f"{kind} {identifier} auf {name}".strip(),
                            data={"use_case_id": uc_id, "kind": kind, "identifier": identifier})
            started = True

        still_active = [known[key] for key in reported & known.keys()]
        if still_active:
            await conn.execute("UPDATE use_cases SET last_seen_at = now() WHERE id = ANY($1::bigint[])",
                               still_active)

        for key in known.keys() - reported:
            await conn.execute("UPDATE use_cases SET ended_at = now() WHERE id = $1", known[key])
            await log_event(conn, "use_case.ended", resource_id=target["id"], component_id=caller.id,
                            message=f"{key[0]} {key[1]} auf {name} beendet".strip(),
                            data={"use_case_id": known[key], "reason": "reported"})

        if started:
            host_id = await conn.fetchval("SELECT host_id FROM resource_hosts WHERE resource_id = $1",
                                          target["id"])
            if host_id is not None:
                await cancel_auto_shutdowns_for_host(conn, host_id)

    rows = await conn.fetch(_SELECT + " WHERE u.resource_id = $1 AND u.ended_at IS NULL ORDER BY u.started_at",
                            target["id"])
    return [dict(r) for r in rows]
