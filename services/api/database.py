"""Async Postgres access via asyncpg with a lazily-initialised connection pool.

A thin `db` facade exposes fetch / fetchrow / fetchval / execute and registers
the pgvector codec on every new connection so VECTOR columns round-trip as
Python lists.
"""
from __future__ import annotations

import json

import asyncpg
from pgvector.asyncpg import register_vector

from services.config import settings


def _asyncpg_dsn() -> str:
    # asyncpg wants a plain postgresql:// DSN (strip any SQLAlchemy driver suffix).
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    # Let asyncpg accept/return Python dicts for json/jsonb columns.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


class Database:
    """Lazily-initialised asyncpg pool wrapper."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                _asyncpg_dsn(),
                min_size=1,
                max_size=10,
                init=_init_connection,
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetch(self, query: str, *args):
        pool = await self.pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        pool = await self.pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        pool = await self.pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args) -> str:
        pool = await self.pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)


db = Database()
