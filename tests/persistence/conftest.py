"""
Shared fixtures for persistence tests.

All tests in this directory require a live PostgreSQL instance.
They are skipped automatically when DATABASE_URL is not set.

To run locally (set DATABASE_URL to your workflow-postgres connection string):
    python -m pytest tests/persistence -v

Each test gets its own asyncpg pool (function scope) to avoid event-loop
mismatch with pytest-asyncio's per-test loop model.  Cleanup runs before
yield so each test starts with an empty workflow_runs table.
"""

from __future__ import annotations

import os

import asyncpg
import pytest

from learning_pipeline.db.migrate import run_migrations

DATABASE_URL = os.getenv("DATABASE_URL", "")
needs_db = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set — PostgreSQL required for persistence tests",
)

pytestmark = needs_db


@pytest.fixture
async def db_pool() -> asyncpg.Pool:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — PostgreSQL required for persistence tests")
    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5)
    await run_migrations(pool)
    # Wipe state before each test so tests are independent
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM workflow_run_state")
        await conn.execute("DELETE FROM workflow_runs")
    yield pool
    await pool.close()
