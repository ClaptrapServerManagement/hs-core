from collections.abc import AsyncIterator

import asyncpg

import config

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
    )

async def close() -> None:
    if _pool is not None:
        await _pool.close()

async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    assert _pool is not None, "Datenbank nict verbunden"
    async with _pool.acquire() as conn:
        yield conn