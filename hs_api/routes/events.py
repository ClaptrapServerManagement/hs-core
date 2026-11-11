from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends, Query

from ..auth import Caller, get_caller
from ..db import get_conn
from ..models import EventOut

router = APIRouter(tags=["events"])

@router.get("/events", response_model=list[EventOut])
async def list_events(
    after_id: int | None = Query(default=None, description=(
        "Nur Events mit größerer ID, aufsteigend sortiert. Zum Mitlesen: "
        "letzte bekannte ID merken und regelmäßig nachfragen.")),
    event_type: str | None = Query(default=None, description="Exakt oder mit Präfix, z.B. 'command.'"),
    resource: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    order = "ASC" if after_id is not None else "DESC"
    rows = await conn.fetch(
        f"""
        SELECT e.id, e.occurred_at, e.event_type, e.severity::text AS severity, r.name AS resource,
               e.command_id, e.scheduled_action_id, u.display_name AS user, c.name AS component,
               e.message, e.data
          FROM events e
          LEFT JOIN resources r ON r.id = e.resource_id
          LEFT JOIN users u ON u.id = e.user_id
          LEFT JOIN components c ON c.id = e.component_id
         WHERE ($1::bigint IS NULL OR e.id > $1)
           AND ($2::text IS NULL OR e.event_type = $2
                OR (right($2, 1) = '.' AND e.event_type LIKE $2 || '%'))
           AND ($3::text IS NULL OR r.name = $3)
           AND ($4::timestamptz IS NULL OR e.occurred_at >= $4)
         ORDER BY e.id {order}
         LIMIT $5
        """,
        after_id, event_type, resource, since, limit,
    )
    return [dict(r) for r in rows]