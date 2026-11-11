import asyncpg
from fastapi import APIRouter, Depends, Response

from ..auth import Caller, get_caller, require_admin
from ..common import get_resource_row, resolve_user
from ..db import get_conn
from ..errors import ApiError
from ..models import PermissionCheckIn, PermissionCheckOut, PermissionIn, PermissionOut
from ..permissions import check_permission, check_target_cooldown

router = APIRouter(tags=["permissions"])

_SELECT = """
SELECT p.id, ro.name AS role, p.user_id, u.display_name AS "user", p.action_key AS action,
       r.name AS target, p.can_request, p.can_postpone, p.can_cancel, p.can_execute_now,
       p.user_cooldown_seconds, p.max_postpones,
       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                     'iso_weekday', w.iso_weekday,
                     'start', to_char(w.start_time, 'HH24:MI'),
                     'end', to_char(w.end_time, 'HH24:MI'))
                     ORDER BY w.iso_weekday, w.start_time)
                   FROM permission_time_windows w WHERE w.permission_id = p.id), '[]'::jsonb) AS time_windows
  FROM permissions p
  LEFT JOIN roles ro ON ro.id = p.role_id
  LEFT JOIN users u ON u.id = p.user_id
  LEFT JOIN resources r ON r.id = p.resource_id
"""

async def _fetch(conn: asyncpg.Connection, permission_id: int) -> dict:
    row = await conn.fetchrow(_SELECT + "WHERE p.id = $1", permission_id)
    if row is None:
        raise ApiError(404, "permission_not_found", f"Permission {permission_id} gibt es nicht.")
    return dict(row)

async def _resolve_refs(conn: asyncpg.Connection, body: PermissionIn) -> tuple:
    # check roles and targets
    if (body.role is None) == (body.user_id is None):
        raise ApiError(422, "invalid_permission_subject", "Genau eines von role oder user_id angeben.")
    role_id = None
    if body.role is not None:
        role_id = await conn.fetchval("SELECT id FROM roles WHERE name = $1", body.role)
        if role_id is None:
            raise ApiError(404, "role_not_found", f"Rolle '{body.role}' gibt es nicht.")
    if body.user_id is not None and not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM users WHERE id = $1)", body.user_id):
        raise ApiError(404, "user_not_found", f"User {body.user_id} gibt es nicht.")
    target_kind = await conn.fetchval("SELECT target_kind::text FROM actions WHERE key = $1", body.action)
    if target_kind is None:
        raise ApiError(404, "action_not_found", f"Action '{body.action}' gibt es nicht.")
    resource_id = None
    if body.target is not None:
        target = await get_resource_row(conn, body.target)
        if target["kind"] != target_kind:
            raise ApiError(422, "action_target_mismatch", f"'{body.action}' passt nicht zu '{body.target}'.")
        resource_id = target["id"]
    return role_id, resource_id

async def _write_windows(conn: asyncpg.Connection, permission_id: int, body: PermissionIn) -> None:
    await conn.execute("DELETE FROM permission_time_windows WHERE permission_id = $1", permission_id)
    await conn.executemany(
        """
        INSERT INTO permission_time_windows (permission_id, iso_weekday, start_time, end_time)
        VALUES ($1, $2, $3::text::time, $4::text::time)
        """,
        [(permission_id, w.iso_weekday, w.start, w.end) for w in body.time_windows],
    )

# List permissions
@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(role: str | None = None, user_id: int | None = None, action: str | None = None, caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    rows = await conn.fetch(
        _SELECT + """
         WHERE ($1::text IS NULL OR ro.name = $1)
           AND ($2::bigint IS NULL OR p.user_id = $2)
           AND ($3::text IS NULL OR p.action_key = $3)
         ORDER BY p.action_key, ro.name NULLS LAST, p.user_id""",
        role, user_id, action,
    )
    return [dict(r) for r in rows]

# Insert permission
@router.post("/permissions", response_model=PermissionOut, status_code=201)
async def create_permission(body: PermissionIn, caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    async with conn.transaction():
        role_id, resource_id = await _resolve_refs(conn, body)
        permission_id = await conn.fetchval(
            """
            INSERT INTO permissions (role_id, user_id, action_key, resource_id, can_request, can_postpone,
                                     can_cancel, can_execute_now, user_cooldown_seconds, max_postpones)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id
            """,
            role_id, body.user_id, body.action, resource_id, body.can_request, body.can_postpone,
            body.can_cancel, body.can_execute_now, body.user_cooldown_seconds, body.max_postpones,
        )
        await _write_windows(conn, permission_id, body)
    return await _fetch(conn, permission_id)

# Edit permission
@router.put("/permissions/{permission_id}", response_model=PermissionOut)
async def replace_permission(permission_id: int, body: PermissionIn, caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    """Ersetzt eine Permission vollständig, inklusive Zeitfenstern."""
    await _fetch(conn, permission_id)
    async with conn.transaction():
        role_id, resource_id = await _resolve_refs(conn, body)
        await conn.execute(
            """
            UPDATE permissions
               SET role_id = $2, user_id = $3, action_key = $4, resource_id = $5, can_request = $6,
                   can_postpone = $7, can_cancel = $8, can_execute_now = $9,
                   user_cooldown_seconds = $10, max_postpones = $11
             WHERE id = $1
            """,
            permission_id, role_id, body.user_id, body.action, resource_id, body.can_request,
            body.can_postpone, body.can_cancel, body.can_execute_now, body.user_cooldown_seconds,
            body.max_postpones,
        )
        await _write_windows(conn, permission_id, body)
    return await _fetch(conn, permission_id)

# Delete Permission
@router.delete("/permissions/{permission_id}", status_code=204)
async def delete_permission(permission_id: int, caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    if await conn.fetchval("DELETE FROM permissions WHERE id = $1 RETURNING id", permission_id) is None:
        raise ApiError(404, "permission_not_found", f"Permission {permission_id} gibt es nicht.")
    return Response(status_code=204)

# Check for permission
@router.post("/permissions/check", response_model=PermissionCheckOut)
async def check(body: PermissionCheckIn, caller: Caller = Depends(get_caller), conn: asyncpg.Connection = Depends(get_conn)):
    """Prüft, ob ein User etwas darf, ohne es auszuführen. Für den Bot, z.B. um zu
    entscheiden, welche Buttons er unter einer Ankündigung anzeigt."""
    target = await get_resource_row(conn, body.target)
    user = await resolve_user(conn, caller, body.requested_by)
    decision = await check_permission(conn, user, body.action, target["id"], body.operation)
    if decision.allowed and body.operation == "request":
        cooldown = await check_target_cooldown(conn, user, body.action, target["id"])
        if not cooldown.allowed:
            decision = cooldown
    return {"allowed": decision.allowed, "code": decision.code, "message": decision.message,
            "retry_after_seconds": decision.retry_after_seconds, "max_postpones": decision.max_postpones}
