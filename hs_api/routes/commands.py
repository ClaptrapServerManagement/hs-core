import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from ..auth import Caller, get_caller, require_agent
from ..command_service import finish_command, insert_command, source_for, validate_action
from ..common import get_resource_row, resolve_user
from ..db import get_conn
from ..errors import ApiError
from ..events import log_event
from ..models import ActorIn, CommandIn, CommandOut, CommandResultIn, CommandStatus
from ..permissions import check_permission, check_target_cooldown

router = APIRouter(tags=["commands"])

_SELECT = """
SELECT c.id, c.action_key AS action, r.name AS target, c.source::text AS source,
       u.display_name AS requested_by, c.scheduled_action_id, c.status::text AS status,
       c.parameters, c.result, c.error_message,
       c.created_at, c.started_at, c.finished_at
  FROM commands c
  JOIN resources r ON r.id = c.target_id
  LEFT JOIN users u ON u.id = c.requested_by_user_id
"""


async def fetch_command(conn: asyncpg.Connection, command_id: int) -> dict:
    row = await conn.fetchrow(_SELECT + " WHERE c.id = $1", command_id)
    if row is None:
        raise ApiError(404, "command_not_found", f"Command {command_id} gibt es nicht.")
    return dict(row)


@router.get("/commands", response_model=list[CommandOut])
async def list_commands(
    status: CommandStatus | None = None,
    target: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # list commands
    rows = await conn.fetch(
        _SELECT + """
         WHERE ($1::command_status IS NULL OR c.status = $1::command_status)
           AND ($2::text IS NULL OR r.name = $2)
         ORDER BY c.id DESC LIMIT $3""",
        status, target, limit,
    )
    return [dict(r) for r in rows]


@router.post("/commands", response_model=CommandOut, status_code=202)
async def create_command(
    body: CommandIn,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # Create new command
    target = await get_resource_row(conn, body.target)
    await validate_action(conn, body.action, target)
    user = await resolve_user(conn, caller, body.requested_by)

    (await check_permission(conn, user, body.action, target["id"], "request")).raise_if_denied()
    (await check_target_cooldown(conn, user, body.action, target["id"])).raise_if_denied()

    command_id = await insert_command(
        conn, action_key=body.action, target=target, source=source_for(caller.kind),
        user_id=user["id"] if user else None, parameters=body.parameters,
    )
    return await fetch_command(conn, command_id)

@router.get("/commands/next", response_model=CommandOut, responses={204: {"description": "Nichts zu tun"}})
async def next_command(
    caller: Caller = Depends(require_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # Retrun oldest open command, else 204
    async with conn.transaction():
        command_id = await conn.fetchval(
            """
            UPDATE commands
               SET status = 'running', started_at = now(), claimed_by_component_id = $1
             WHERE id = (
                   SELECT c.id
                     FROM commands c
                     JOIN actions a ON a.key = c.action_key
                     JOIN resources r ON r.id = c.target_id
                     LEFT JOIN resources p ON p.id = r.parent_id
                    WHERE c.status = 'pending'
                      AND a.executor = $2::component_kind
                      -- Agents mit eigener Ressource nur für diese und alles darunter
                      AND ($3::bigint IS NULL OR $3 IN (r.id, r.parent_id, p.parent_id))
                    ORDER BY c.created_at
                    LIMIT 1
                      FOR UPDATE OF c SKIP LOCKED
             )
            RETURNING id
            """,
            caller.id, caller.kind, caller.resource_id,
        )
        if command_id is None:
            return Response(status_code=204)
        await log_event(conn, "command.started", command_id=command_id, component_id=caller.id,
                        message=f"{caller.name} führt Command {command_id} aus")
    return await fetch_command(conn, command_id)

@router.post("/commands/{command_id}/result", response_model=CommandOut)
async def report_result(
    command_id: int,
    body: CommandResultIn,
    caller: Caller = Depends(require_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # Successs?
    if body.status not in (CommandStatus.COMPLETED, CommandStatus.FAILED):
        raise ApiError(422, "invalid_result_status", "Als Ergebnis sind nur 'completed' und 'failed' erlaubt.")

    async with conn.transaction():
        command = await conn.fetchrow(
            "SELECT status::text AS status, claimed_by_component_id FROM commands WHERE id = $1 FOR UPDATE",
            command_id,
        )
        if command is None:
            raise ApiError(404, "command_not_found", f"Command {command_id} gibt es nicht.")
        if command["status"] != "running" or command["claimed_by_component_id"] != caller.id:
            raise ApiError(409, "command_not_running", f"Command {command_id} läuft nicht bei {caller.name}.")
        await finish_command(conn, command_id, ok=body.status == CommandStatus.COMPLETED,
                             error_message=body.error_message, result=body.result, component_id=caller.id)
    return await fetch_command(conn, command_id)

@router.post("/commands/{command_id}/cancel", response_model=CommandOut)
async def cancel_command(
    command_id: int,
    body: ActorIn,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # Cancel unless pending
    user = await resolve_user(conn, caller, body.requested_by)
    async with conn.transaction():
        command = await conn.fetchrow(
            "SELECT status::text AS status, action_key, target_id FROM commands WHERE id = $1 FOR UPDATE",
            command_id,
        )
        if command is None:
            raise ApiError(404, "command_not_found", f"Command {command_id} gibt es nicht.")
        if command["status"] != "pending":
            raise ApiError(409, "command_not_pending",
                           f"Command {command_id} ist bereits {command['status']} und kann nicht mehr abgebrochen werden.")
        (await check_permission(conn, user, command["action_key"], command["target_id"], "cancel")).raise_if_denied()

        await conn.execute(
            "UPDATE commands SET status = 'cancelled', finished_at = now() WHERE id = $1", command_id,
        )
        await log_event(conn, "command.cancelled", command_id=command_id, resource_id=command["target_id"],
                        user_id=user["id"] if user else None,
                        message=f"{command['action_key']} abgebrochen")
    return await fetch_command(conn, command_id)

@router.get("/commands/{command_id}", response_model=CommandOut)
async def get_command(command_id: int, caller: Caller = Depends(get_caller),
                      conn: asyncpg.Connection = Depends(get_conn)):
    return await fetch_command(conn, command_id)
