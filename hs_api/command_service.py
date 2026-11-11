import asyncpg

from .errors import ApiError
from .events import log_event

STATUS_AFTER_COMPLETED = {
    "host.power_on": "STARTING",
    "host.shutdown": "STOPPING",
    "host.force_off": "OFF",
    "vm.start": "STARTING",
    "vm.shutdown": "STOPPING",
    "vm.restart": "RESTARTING",
    "vm.force_stop": "OFF",
}

SOURCE_BY_COMPONENT_KIND = {
    "discord_bot": "discord",
    "dashboard": "dashboard",
}

def source_for(component_kind: str) -> str:
    return SOURCE_BY_COMPONENT_KIND.get(component_kind, "api")

async def validate_action(conn: asyncpg.Connection, action_key: str, target) -> asyncpg.Record:
    action = await conn.fetchrow(
        "SELECT key, target_kind::text AS target_kind, is_read_only FROM actions WHERE key = $1",
        action_key,
    )
    if action is None:
        raise ApiError(404, "action_not_found", f"Action '{action_key}' gibt es nicht.")
    if action["is_read_only"]:
        raise ApiError(422, "action_read_only", f"'{action_key}' ist eine Abfrage, dafür gibt es GET /resources.")
    if target["kind"] != action["target_kind"]:
        raise ApiError(422, "action_target_mismatch", f"'{action_key}' passt nicht zu {target['kind']} '{target['name']}'.")
    return action

async def insert_command(conn: asyncpg.Connection, *, action_key: str, target, source: str, user_id: int | None, scheduled_action_id: int | None = None, parameters: dict | None = None) -> int:
    try:
        async with conn.transaction():
            command_id = await conn.fetchval(
                """
                INSERT INTO commands (action_key, target_id, source, requested_by_user_id,
                                      scheduled_action_id, parameters)
                VALUES ($1, $2, $3::command_source, $4, $5, $6)
                RETURNING id
                """,
                action_key, target["id"], source, user_id, scheduled_action_id, parameters or {},
            )
            await log_event(conn, "command.created", command_id=command_id, resource_id=target["id"], user_id=user_id, scheduled_action_id=scheduled_action_id, message=f"{action_key} für {target['name']} angelegt ({source})")
    except asyncpg.UniqueViolationError:
        open_id = await conn.fetchval(
            "SELECT id FROM commands WHERE target_id = $1 AND status IN ('pending', 'running')",
            target["id"],
        )
        raise ApiError(409, "command_already_open", f"Für '{target['name']}' läuft bereits ein Command.", {"command_id": open_id}) from None
    return command_id

async def finish_command(conn: asyncpg.Connection, command_id: int, *, ok: bool, error_message: str | None = None, result: dict | None = None, component_id: int | None = None) -> None:
    row = await conn.fetchrow(
        """
        UPDATE commands
           SET status = $2::command_status, finished_at = now(), result = $3, error_message = $4
         WHERE id = $1
        RETURNING action_key, target_id
        """,
        command_id, "completed" if ok else "failed", result,
        None if ok else (error_message or "Ohne Fehlermeldung"),
    )
    await log_event(
        conn, "command.completed" if ok else "command.failed",
        severity="info" if ok else "error",
        command_id=command_id, component_id=component_id, resource_id=row["target_id"],
        message=f"{row['action_key']} erledigt" if ok else f"{row['action_key']}: {error_message}",
    )
    new_status = STATUS_AFTER_COMPLETED.get(row["action_key"]) if ok else None
    if new_status:
        await conn.execute(
            "UPDATE resources SET status = $2::resource_status, status_detail = NULL WHERE id = $1",
            row["target_id"], new_status,
        )
