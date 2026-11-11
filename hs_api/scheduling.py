from datetime import datetime
import asyncpg

from .command_service import insert_command
from .errors import ApiError
from .events import log_event

async def create_scheduled(conn: asyncpg.Connection, *, action_key: str, target, reason: str, execute_at: datetime, user_id: int | None) -> int:
    try:
        async with conn.transaction():
            sa_id = await conn.fetchval(
                """
                INSERT INTO scheduled_actions (action_key, target_id, reason, created_by_user_id,
                                               execute_at, original_execute_at)
                VALUES ($1, $2, $3, $4, $5, $5)
                RETURNING id
                """,
                action_key, target["id"], reason, user_id, execute_at,
            )
            await log_event(conn, 
                "scheduled_action.created", 
                scheduled_action_id=sa_id,
                resource_id=target["id"], user_id=user_id,
                message=f"{action_key} für {target['name']} geplant ({reason})",
                data={"execute_at": execute_at.isoformat(), "reason": reason}
            )
    except asyncpg.UniqueViolationError:
        existing = await conn.fetchval(
            "SELECT id FROM scheduled_actions WHERE action_key = $1 AND target_id = $2 AND status = 'scheduled'",
            action_key, target["id"],
        )
        raise ApiError(409, "scheduled_action_already_exists",
                       f"{action_key} für '{target['name']}' ist bereits geplant.",
                       {"scheduled_action_id": existing}) from None
    return sa_id

async def cancel_scheduled(conn: asyncpg.Connection, sa_id: int, *, reason: str,
                           user_id: int | None = None) -> None:
    row = await conn.fetchrow(
        """
        UPDATE scheduled_actions
           SET status = 'cancelled', cancel_reason = $2, cancelled_by_user_id = $3
         WHERE id = $1 AND status = 'scheduled'
        RETURNING action_key, target_id
        """,
        sa_id, reason, user_id,
    )
    if row is not None:
        await log_event(conn, "scheduled_action.cancelled", scheduled_action_id=sa_id, resource_id=row["target_id"], user_id=user_id, message=f"{row['action_key']} abgebrochen ({reason})", data={"reason": reason})

async def execute_scheduled(conn: asyncpg.Connection, sa, *, source: str = "system",
                            user_id: int | None = None) -> int | None:
    target = {"id": sa["target_id"], "name": sa["target"]}
    try:
        command_id = await insert_command(conn, action_key=sa["action_key"], target=target, source=source,
                                          user_id=user_id, scheduled_action_id=sa["id"])
    except ApiError as e:
        await conn.execute("UPDATE scheduled_actions SET status = 'failed' WHERE id = $1", sa["id"])
        await log_event(conn, "scheduled_action.failed", severity="error", scheduled_action_id=sa["id"],
                        resource_id=sa["target_id"], message=f"{sa['action_key']}: {e.message}")
        return None
    await conn.execute("UPDATE scheduled_actions SET status = 'executed' WHERE id = $1", sa["id"])
    await log_event(conn, "scheduled_action.executed", scheduled_action_id=sa["id"],
                    command_id=command_id, resource_id=sa["target_id"], user_id=user_id,
                    message=f"{sa['action_key']} ausgelöst")
    return command_id

async def cancel_auto_shutdowns_for_host(conn: asyncpg.Connection, host_id: int) -> None:
    ids = await conn.fetch(
        """
        SELECT id FROM scheduled_actions
         WHERE target_id = $1 AND status = 'scheduled' AND reason = 'auto_shutdown_idle'
        """,
        host_id,
    )
    for row in ids:
        await cancel_scheduled(conn, row["id"], reason="use_case_detected")
