import json
import asyncpg 

async def log_event(
        conn: asyncpg.Connection,
        event_type: str,
        *,
        severity: str = "info",
        resource_id: int | None = None,
        command_id: int | None = None,
        user_id: int | None = None,
        component_id: int | None = None,
        message: str | None = None,
        data: dict | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO events (event_type, severity, resource_id, command_id,
                            user_id, component_id, message, data)
        VALUES ($1, $2::event_severity, $3, $4, $5, $6, $7, $8::jsonb)
        """,
        event_type, severity, resource_id, command_id,
        user_id, component_id, message, json.dumps(data or {}),
    )