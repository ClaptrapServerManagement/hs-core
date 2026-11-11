import asyncpg
from fastapi import APIRouter, Depends

from ..auth import Caller, get_caller, require_admin
from ..db import get_conn
from ..errors import ApiError
from ..models import SettingIn, SettingOut

router = APIRouter(tags=["settings"])

@router.get("/settings", response_model=list[SettingOut])
async def list_settings(caller: Caller = Depends(get_caller), conn: asyncpg.Connection = Depends(get_conn)):
    return [dict(r) for r in await conn.fetch("SELECT key, value, description, updated_at FROM settings ORDER BY key")]

@router.put("/settings/{key}", response_model=SettingOut)
async def update_setting(key: str, body: SettingIn, caller: Caller = Depends(require_admin),
                         conn: asyncpg.Connection = Depends(get_conn)):
    row = await conn.fetchrow(
        "UPDATE settings SET value = $2 WHERE key = $1 RETURNING key, value, description, updated_at",
        key, body.value,
    )
    if row is None:
        raise ApiError(404, "setting_not_found", f"Setting '{key}' gibt es nicht.")
    return dict(row)
