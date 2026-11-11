import asyncpg
from fastapi import APIRouter, Depends, Response

from ..auth import Caller, require_admin
from ..db import get_conn
from ..errors import ApiError
from ..models import RoleIn, RoleOut, RoleUpdateIn

router = APIRouter(tags=["roles"])

_SELECT = """
SELECT r.id, r.name, r.description, r.discord_role_id,
       (SELECT count(*) FROM user_roles ur WHERE ur.role_id = r.id)::int AS members
  FROM roles r
"""


async def _fetch(conn: asyncpg.Connection, role_id: int) -> dict:
    row = await conn.fetchrow(_SELECT + " WHERE r.id = $1", role_id)
    if row is None:
        raise ApiError(404, "role_not_found", f"Rolle {role_id} gibt es nicht.")
    return dict(row)


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    return [dict(r) for r in await conn.fetch(_SELECT + " ORDER BY r.name")]


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(body: RoleIn, caller: Caller = Depends(require_admin),
                      conn: asyncpg.Connection = Depends(get_conn)):
    role_id = await conn.fetchval(
        "INSERT INTO roles (name, description, discord_role_id) VALUES ($1, $2, $3) RETURNING id",
        body.name, body.description, body.discord_role_id,
    )
    return await _fetch(conn, role_id)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(role_id: int, body: RoleUpdateIn, caller: Caller = Depends(require_admin),
                      conn: asyncpg.Connection = Depends(get_conn)):
    fields = {**await _fetch(conn, role_id), **body.model_dump(exclude_unset=True)}
    await conn.execute(
        "UPDATE roles SET name = $2, description = $3, discord_role_id = $4 WHERE id = $1",
        role_id, fields["name"], fields["description"], fields["discord_role_id"],
    )
    return await _fetch(conn, role_id)

# Del. role with permission & affiliation
@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(role_id: int, caller: Caller = Depends(require_admin),
                      conn: asyncpg.Connection = Depends(get_conn)):
    if await conn.fetchval("DELETE FROM roles WHERE id = $1 RETURNING id", role_id) is None:
        raise ApiError(404, "role_not_found", f"Rolle {role_id} gibt es nicht.")
    return Response(status_code=204)
