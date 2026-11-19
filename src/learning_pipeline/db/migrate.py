"""
Database migration runner.

Applies SQL migration files from the migrations/ subdirectory in filename order.
Each file is applied at most once; applied names are recorded in _schema_migrations.

Usage:
    python -m learning_pipeline.db.migrate
    (reads DATABASE_URL from the environment)

Or from Python:
    await run_migrations(pool)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS _schema_migrations (
    name       TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply all pending SQL migrations to the database."""
    async with pool.acquire() as conn:
        await conn.execute(_TRACKING_TABLE)

        migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            print("[migrate] No migration files found.")
            return

        for path in migration_files:
            name = path.name
            applied = await conn.fetchval(
                "SELECT 1 FROM _schema_migrations WHERE name = $1", name
            )
            if applied:
                print(f"[migrate] Already applied: {name}")
                continue

            sql = path.read_text(encoding="utf-8")
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO _schema_migrations (name) VALUES ($1) "
                "ON CONFLICT (name) DO NOTHING",
                name,
            )
            print(f"[migrate] Applied: {name}")

    print("[migrate] Migrations complete.")


async def _main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        await run_migrations(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_main())
