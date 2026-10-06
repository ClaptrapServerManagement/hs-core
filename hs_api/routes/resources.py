import asyncpg
from fastapi import APIRouter, Depends

from ..auth import Caller, get_caller, require_agent
from ..db import get_conn
from ..errors import ApiError
from ..models import ResourceKind, ResourceOut, StatusReportIn

router = APIRouter(tags=["resources"])

_SELECT = """
SELECT r.name, r.kind::text AS kind, r.display_name, p.name AS parent,
       r.status::text AS status, r.status_detail, r.status_since, r.last_seen_at
  FROM resources r
  LEFT JOIN resources p ON p.id = r.parent_id
 WHERE r.enabled
"""

async def _fetch_one(conn: asyncpg.Connection, name: str) -> dict:
    row = await conn.fetchrow(_SELECT + " AND r.name = $1", name)
    if row is None:
        raise ApiError(404, "resource_not_found", f"Ressource '{name}' gibt es nicht.")
    return dict(row)

@router.get("/resources", response_model=list[ResourceOut])
async def list_resources(
    kind: ResourceKind | None = None,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # All resources sorted by status, optionally filtered by kind
    rows = await conn.fetch(
        _SELECT + " AND ($1::resource_kind IS NULL OR r.kind = $1::resource_kind)"
                  " ORDER BY r.kind, r.name",
        kind,
    )
    return [dict(r) for r in rows]

@router.get("resources/{name}", response_model=ResourceOut)
async def get_resource(
    name:str,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    return await _fetch_one(conn, name)

@router.get("/resources/{name}/status", response_model=ResourceOut)
async def report_status(
    name: str,
    body: StatusReportIn,
    caller: Caller = Depends(require_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # Agent is reporting status of resource
    # Database automatically updates resource.status_changed
    updated = await conn.fetchval(
        """
        UPDATE resources
           SET status = $2::resource_status, status_detail = $3, last_seen_at = now()
         WHERE name = $1 AND enabled
        RETURNING id
        """,
        name, body.status, body.detail,
    )
    if updated is None:
        raise ApiError(404, "resource_not_found", f"Ressource '{name}' gibt es nicht.")
    return await _fetch_one(conn, name)