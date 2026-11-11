import asyncpg

from .auth import Caller
from .errors import ApiError
from .models import IdentifyRef

USER_REQUIRED_KINDS = {"discord_bot"}

async def get_setting(conn: asyncpg.Connection, key: str, default=None):
    value = await conn.fetchval("SELECT value FROM settings WHERE key = $1", key)
    return default if value is None else value

async def get_resource_row(conn: asyncpg.Connection, name: str) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT id, kind::text AS kind, name, parent_id, status::text AS status "
        "FROM resources WHERE name = $1 AND enabled",
        name,
    )
    if row is None:
        raise ApiError(404, "resource_not_found", f"Ressource '{name}' gibt es nicht.")
    return row

# Returns acting user (None = no user -> component | Bots forward user as proxy)
async def resolve_user(conn: asyncpg.Connection, caller: Caller, ref: IdentityRef | None):
    if ref is None:
        if caller.kind in USER_REQUIRED_KINDS:
            raise ApiError(422, "requested_by_required",
                           f"'{caller.name}' muss angeben, für welchen User gehandelt wird.")
        return None
    row = await conn.fetchrow(
        """
        SELECT u.id, u.display_name, u.is_admin
          FROM user_identities i JOIN users u ON u.id = i.user_id
         WHERE i.provider = $1 AND i.external_id = $2 AND u.is_active
        """,
        ref.provider, ref.external_id,
    )
    if row is None:
        raise ApiError(403, "user_not_found", "Dieses Konto ist keinem aktiven User zugeordnet.")
    return row

# Is agent allowed to access component
async def resource_in_scope(conn: asyncpg.Connection, caller: Caller, resource_id: int) -> bool:
    if caller.resource_id is None:
        return True
    return await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM resources r LEFT JOIN resources p ON p.id = r.parent_id
             WHERE r.id = $1 AND $2 IN (r.id, r.parent_id, p.parent_id)
        )
        """,
        resource_id, caller.resource_id,
    )
