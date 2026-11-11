import asyncpg
from fastapi import APIRouter, Depends

from ..auth import Caller, get_caller, require_admin
from ..db import get_conn
from ..errors import ApiError
from ..models import IdentityIn, UserCreateIn, UserOut, UserRolesIn, UserUpdateIn

router = APIRouter(tags=["users"])

_SELECT = """
SELECT u.id, u.display_name, u.is_admin, u.is_active, u.note,
       COALESCE((SELECT jsonb_agg(jsonb_build_object('provider', i.provider, 'external_id', i.external_id,
                                                     'external_name', i.external_name)
                                  ORDER BY i.provider, i.external_id)
                   FROM user_identities i WHERE i.user_id = u.id), '[]'::jsonb) AS identities,
       COALESCE((SELECT array_agg(r.name ORDER BY r.name)
                   FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id),
                '{}') AS roles
  FROM users u
"""

async def fetch_user(conn: asyncpg.Connection, user_id: int) -> dict:
    row = await conn.fetchrow(_SELECT + " WHERE u.id = $1", user_id)
    if row is None:
        raise ApiError(404, "user_not_found", f"User {user_id} gibt es nicht.")
    return dict(row)

async def _set_roles(conn: asyncpg.Connection, user_id: int, role_names: list[str]) -> None:
    role_ids = await conn.fetch("SELECT id, name FROM roles WHERE name = ANY($1::text[])", role_names)
    missing = set(role_names) - {r["name"] for r in role_ids}
    if missing:
        raise ApiError(404, "role_not_found", f"Rollen gibt es nicht: {', '.join(sorted(missing))}")
    await conn.execute("DELETE FROM user_roles WHERE user_id = $1", user_id)
    await conn.executemany("INSERT INTO user_roles (user_id, role_id) VALUES ($1, $2)",
                           [(user_id, r["id"]) for r in role_ids])

async def _add_identity(conn: asyncpg.Connection, user_id: int, identity: IdentityIn) -> None:
    try:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO user_identities (user_id, provider, external_id, external_name)
                VALUES ($1, $2, $3, $4)
                """,
                user_id, identity.provider, identity.external_id, identity.external_name,
            )
    except asyncpg.UniqueViolationError:
        raise ApiError(409, "identity_already_linked",
                       f"{identity.provider}:{identity.external_id} gehört bereits einem User.") from None

@router.get("/users", response_model=list[UserOut])
async def list_users(caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    return [dict(r) for r in await conn.fetch(_SELECT + " ORDER BY u.display_name")]

@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreateIn, caller: Caller = Depends(require_admin),
                      conn: asyncpg.Connection = Depends(get_conn)):
    async with conn.transaction():
        user_id = await conn.fetchval(
            "INSERT INTO users (display_name, is_admin, note) VALUES ($1, $2, $3) RETURNING id",
            body.display_name, body.is_admin, body.note,
        )
        for identity in body.identities:
            await _add_identity(conn, user_id, identity)
        await _set_roles(conn, user_id, body.roles)
    return await fetch_user(conn, user_id)

@router.get("/users/by-identity/{provider}/{external_id}", response_model=UserOut)
async def get_user_by_identity(provider: str, external_id: str, caller: Caller = Depends(get_caller),
                               conn: asyncpg.Connection = Depends(get_conn)):
    user_id = await conn.fetchval(
        "SELECT user_id FROM user_identities WHERE provider = $1 AND external_id = $2", provider, external_id,
    )
    if user_id is None:
        raise ApiError(404, "user_not_found", "Dieses Konto ist keinem User zugeordnet.")
    return await fetch_user(conn, user_id)

@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, caller: Caller = Depends(require_admin),
                   conn: asyncpg.Connection = Depends(get_conn)):
    return await fetch_user(conn, user_id)

# delete user = is_active -> false
@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdateIn, caller: Caller = Depends(require_admin),
                      conn: asyncpg.Connection = Depends(get_conn)):
    current = await fetch_user(conn, user_id)
    fields = {**current, **body.model_dump(exclude_unset=True)}
    await conn.execute(
        "UPDATE users SET display_name = $2, is_admin = $3, is_active = $4, note = $5 WHERE id = $1",
        user_id, fields["display_name"], fields["is_admin"], fields["is_active"], fields["note"],
    )
    return await fetch_user(conn, user_id)

@router.put("/users/{user_id}/roles", response_model=UserOut)
async def set_user_roles(user_id: int, body: UserRolesIn, caller: Caller = Depends(require_admin),
                         conn: asyncpg.Connection = Depends(get_conn)):
    await fetch_user(conn, user_id)
    async with conn.transaction():
        await _set_roles(conn, user_id, body.roles)
    return await fetch_user(conn, user_id)

@router.post("/users/{user_id}/identities", response_model=UserOut, status_code=201)
async def add_identity(user_id: int, body: IdentityIn, caller: Caller = Depends(require_admin),
                       conn: asyncpg.Connection = Depends(get_conn)):
    await fetch_user(conn, user_id)
    await _add_identity(conn, user_id, body)
    return await fetch_user(conn, user_id)

@router.delete("/users/{user_id}/identities/{provider}/{external_id}", response_model=UserOut)
async def remove_identity(user_id: int, provider: str, external_id: str,
                          caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    deleted = await conn.fetchval(
        "DELETE FROM user_identities WHERE user_id = $1 AND provider = $2 AND external_id = $3 RETURNING id",
        user_id, provider, external_id,
    )
    if deleted is None:
        raise ApiError(404, "identity_not_found", f"{provider}:{external_id} gehört nicht zu User {user_id}.")
    return await fetch_user(conn, user_id)
