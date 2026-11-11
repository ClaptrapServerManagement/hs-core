from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, Query

from ..auth import Caller, get_caller
from ..command_service import source_for, validate_action
from ..common import get_resource_row, get_setting, resolve_user
from ..db import get_conn
from ..errors import ApiError
from ..events import log_event
from ..models import ActorIn, AnnouncedIn, PostponeIn, ScheduledActionIn, ScheduledActionOut, ScheduledActionStatus
from ..permissions import check_permission
from ..scheduling import cancel_scheduled, create_scheduled, execute_scheduled

router = APIRouter(tags=["scheduled actions"])

_SELECT = """
SELECT sa.id, sa.action_key AS action, sa.action_key, r.name AS target, sa.target_id, sa.reason,
       sa.status::text AS status, sa.execute_at, sa.original_execute_at, sa.postpone_count,
       sa.announced_at, sa.discord_message_id, cu.display_name AS created_by,
       xu.display_name AS cancelled_by, sa.cancel_reason, sa.created_at,
       (SELECT c.id FROM commands c WHERE c.scheduled_action_id = sa.id ORDER BY c.id DESC LIMIT 1) AS command_id
  FROM scheduled_actions sa
  JOIN resources r ON r.id = sa.target_id
  LEFT JOIN users cu ON cu.id = sa.created_by_user_id
  LEFT JOIN users xu ON xu.id = sa.cancelled_by_user_id
"""

async def _fetch(conn: asyncpg.Connection, sa_id: int, *, lock: bool = False) -> asyncpg.Record:
    row = await conn.fetchrow(_SELECT + " WHERE sa.id = $1" + (" FOR UPDATE OF sa" if lock else ""), sa_id)
    if row is None:
        raise ApiError(404, "scheduled_action_not_found", f"Scheduled Action {sa_id} gibt es nicht.")
    return row

async def _fetch_active(conn: asyncpg.Connection, sa_id: int) -> asyncpg.Record:
    row = await _fetch(conn, sa_id, lock=True)
    if row["status"] != "scheduled":
        raise ApiError(409, "scheduled_action_not_active",
                       f"Scheduled Action {sa_id} ist bereits {row['status']}.")
    return row

@router.get("/scheduled-actions", response_model=list[ScheduledActionOut])
async def list_scheduled_actions(
    status: ScheduledActionStatus | None = None,
    target: str | None = None,
    needs_announcement: bool = Query(default=False, description=(
        "Nur aktive, noch nicht angekündigte, deren Ausführung in weniger als "
        "shutdown_announce_minutes bevorsteht. Für den Discord Bot.")),
    limit: int = Query(default=50, ge=1, le=500),
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    announce_minutes = await get_setting(conn, "shutdown_announce_minutes", 10)
    rows = await conn.fetch(
        _SELECT + """
         WHERE ($1::scheduled_action_status IS NULL OR sa.status = $1::scheduled_action_status)
           AND ($2::text IS NULL OR r.name = $2)
           AND (NOT $3 OR (sa.status = 'scheduled' AND sa.announced_at IS NULL
                           AND sa.execute_at <= now() + ($4::int * interval '1 minute')))
         ORDER BY sa.execute_at DESC LIMIT $5""",
        status, target, needs_announcement, announce_minutes, limit,
    )
    return [dict(r) for r in rows]

# schedule action
@router.post("/scheduled-actions", response_model=ScheduledActionOut, status_code=201)
async def create_scheduled_action(body: ScheduledActionIn, caller: Caller = Depends(get_caller),
                                  conn: asyncpg.Connection = Depends(get_conn)):
    if (body.execute_at is None) == (body.in_minutes is None):
        raise ApiError(422, "invalid_schedule", "Genau eines von execute_at oder in_minutes angeben.")

    target = await get_resource_row(conn, body.target)
    await validate_action(conn, body.action, target)
    user = await resolve_user(conn, caller, body.requested_by)
    (await check_permission(conn, user, body.action, target["id"], "request")).raise_if_denied()

    if body.in_minutes is not None:
        execute_at = await conn.fetchval("SELECT now() + ($1::int * interval '1 minute')", body.in_minutes)
    else:
        execute_at = body.execute_at if body.execute_at.tzinfo else body.execute_at.replace(tzinfo=timezone.utc)
        if execute_at <= datetime.now(timezone.utc):
            raise ApiError(422, "invalid_schedule", "Der Zeitpunkt liegt in der Vergangenheit.")

    sa_id = await create_scheduled(conn, action_key=body.action, target=target, reason="user_request",
                                   execute_at=execute_at, user_id=user["id"] if user else None)
    return dict(await _fetch(conn, sa_id))


@router.get("/scheduled-actions/{sa_id}", response_model=ScheduledActionOut)
async def get_scheduled_action(sa_id: int, caller: Caller = Depends(get_caller),
                               conn: asyncpg.Connection = Depends(get_conn)):
    return dict(await _fetch(conn, sa_id))

# postpone
@router.post("/scheduled-actions/{sa_id}/postpone", response_model=ScheduledActionOut)
async def postpone(sa_id: int, body: PostponeIn, caller: Caller = Depends(get_caller),
                   conn: asyncpg.Connection = Depends(get_conn)):
    user = await resolve_user(conn, caller, body.requested_by)
    minutes = body.minutes or await get_setting(conn, "default_postpone_minutes", 30)
    async with conn.transaction():
        sa = await _fetch_active(conn, sa_id)
        decision = await check_permission(conn, user, sa["action_key"], sa["target_id"], "postpone")
        decision.raise_if_denied()
        if decision.max_postpones is not None and sa["postpone_count"] >= decision.max_postpones:
            raise ApiError(403, "max_postpones_reached",
                           f"Schon {sa['postpone_count']}-mal aufgeschoben, mehr ist nicht erlaubt.")
        new_time = await conn.fetchval(
            """
            UPDATE scheduled_actions
               SET execute_at = greatest(execute_at, now()) + ($2::int * interval '1 minute'),
                   postpone_count = postpone_count + 1
             WHERE id = $1 RETURNING execute_at
            """,
            sa_id, minutes,
        )
        await log_event(conn, "scheduled_action.postponed", scheduled_action_id=sa_id,
                        resource_id=sa["target_id"], user_id=user["id"] if user else None,
                        message=f"{sa['action_key']} um {minutes} min aufgeschoben",
                        data={"minutes": minutes, "execute_at": new_time.isoformat()})
    return dict(await _fetch(conn, sa_id))

@router.post("/scheduled-actions/{sa_id}/cancel", response_model=ScheduledActionOut)
async def cancel(sa_id: int, body: ActorIn, caller: Caller = Depends(get_caller),
                 conn: asyncpg.Connection = Depends(get_conn)):
    user = await resolve_user(conn, caller, body.requested_by)
    async with conn.transaction():
        sa = await _fetch_active(conn, sa_id)
        (await check_permission(conn, user, sa["action_key"], sa["target_id"], "cancel")).raise_if_denied()
        await cancel_scheduled(conn, sa_id, reason="user", user_id=user["id"] if user else None)
    return dict(await _fetch(conn, sa_id))

# run scheduled action now
@router.post("/scheduled-actions/{sa_id}/execute-now", response_model=ScheduledActionOut)
async def execute_now(sa_id: int, body: ActorIn, caller: Caller = Depends(get_caller),
                      conn: asyncpg.Connection = Depends(get_conn)):
    user = await resolve_user(conn, caller, body.requested_by)
    async with conn.transaction():
        sa = await _fetch_active(conn, sa_id)
        (await check_permission(conn, user, sa["action_key"], sa["target_id"], "execute_now")).raise_if_denied()
        command_id = await execute_scheduled(conn, sa, source=source_for(caller.kind),
                                             user_id=user["id"] if user else None)
    if command_id is None:
        raise ApiError(409, "command_already_open", "Am Ziel läuft bereits ein Command, die Ausführung ist fehlgeschlagen.")
    return dict(await _fetch(conn, sa_id))

# action was anncounced by bot
@router.post("/scheduled-actions/{sa_id}/announced", response_model=ScheduledActionOut)
async def mark_announced(sa_id: int, body: AnnouncedIn, caller: Caller = Depends(get_caller), conn: asyncpg.Connection = Depends(get_conn)):
    async with conn.transaction():
        sa = await _fetch(conn, sa_id, lock=True)
        await conn.execute(
            "UPDATE scheduled_actions SET announced_at = now(), discord_message_id = $2 WHERE id = $1",
            sa_id, body.discord_message_id,
        )
        await log_event(conn, "scheduled_action.announced", scheduled_action_id=sa_id,
                        resource_id=sa["target_id"], component_id=caller.id,
                        message=f"{sa['action_key']} angekündigt")
    return dict(await _fetch(conn, sa_id))
