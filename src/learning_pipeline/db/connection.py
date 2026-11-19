"""asyncpg pool lifecycle helpers."""

from __future__ import annotations

import asyncpg


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn)
