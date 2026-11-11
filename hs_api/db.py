import json
from collections.abc import AsyncIterator

import asyncpg

from . import config

_pool : asyncpg.Pool | None = None

async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

async def connect() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        min_size=1,
        max_size=5,
        init=_init_connection,
    )

async def close() -> None:
    if _pool is not None:
        await _pool.close()

def pool() -> asyncpg.Pool:
    assert _pool is not None, "Datenbank nicht verbunden"
    return _pool

async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    async with pool().acquire() as conn:
        yield conn