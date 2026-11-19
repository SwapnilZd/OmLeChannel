"""
PostgreSQL-backed RunSnapshot store.

Implements the same interface as FileRunStateStore so DAGRunner can use
either without knowing which is active.  save() and load() are async;
runner.py calls them via coroutine detection in _save().
"""

from __future__ import annotations

import asyncpg

from learning_pipeline.runtime.persistence import RunSnapshot


class PostgresRunStateStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(self, snapshot: RunSnapshot) -> None:
        json_str = snapshot.model_dump_json()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_run_state (workflow_id, snapshot_json, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (workflow_id)
                DO UPDATE SET snapshot_json = EXCLUDED.snapshot_json,
                              updated_at    = now()
                """,
                snapshot.workflow_id,
                json_str,
            )

    async def load(self, workflow_id: str) -> RunSnapshot:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT snapshot_json FROM workflow_run_state WHERE workflow_id = $1",
                workflow_id,
            )
        if row is None:
            raise KeyError(f"no run state for workflow {workflow_id!r}")
        return RunSnapshot.model_validate_json(row["snapshot_json"])
