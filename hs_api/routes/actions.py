import asyncgp
from fastapi import APIRouter, Depends


from ..auth import Caller, get_caller
from ..db import get_conn
from ..models import ActionOut

router = APIRouter(tags=["actions"])

@router.get("/actions", response_model=list[ActionOut])
async def list_actions(caller: Caller = Depends(get_caller), conn: asyncpg.Connection = Depends(get_conn)):
    rows = await conn.fetch(
        """
        SELECT key, target_kind::text AS target_kind, description, is_read_only,
               target_cooldown_seconds, executor::text AS executor
          FROM actions ORDER BY target_kind, key
        """
    )
    return [dict(r) for r in rows]
