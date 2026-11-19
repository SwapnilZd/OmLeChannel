"""
PostgreSQL-backed workflow repository.

Persistent state machine for workflow records:
  pending → running (claimed_at, claimed_by set)
  running → succeeded (result_json set, completed_at set)
  running → failed   (error_message set, completed_at set)

Claim is atomic: SELECT ... FOR UPDATE SKIP LOCKED prevents two workers
from claiming the same pending row even when multiple workers poll concurrently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

import asyncpg
from pydantic import BaseModel

from learning_pipeline.contracts import BuildPlan, WorkflowResult


class PersistentWorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"


class DuplicateWorkflowError(ValueError):
    def __init__(self, workflow_id: str) -> None:
        super().__init__(f"workflow {workflow_id!r} already exists")
        self.workflow_id = workflow_id


class WorkflowRecord(BaseModel):
    workflow_id: str
    plan_json: str
    plan_hash: str
    status: PersistentWorkflowStatus
    result_json: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    claimed_at: datetime | None
    claimed_by: str | None
    completed_at: datetime | None
    required_task_types: tuple[str, ...] = ()
    modality: str | None = None


class WorkflowRepository(Protocol):
    async def create_pending(self, plan: BuildPlan, plan_hash: str) -> None: ...
    async def get(self, workflow_id: str) -> WorkflowRecord | None: ...
    async def claim_next_pending(
        self,
        worker_id: str,
        supported_task_types: frozenset[str] | None = None,
        supported_modalities: frozenset[str] | None = None,
    ) -> WorkflowRecord | None: ...
    async def mark_succeeded(self, workflow_id: str, result: WorkflowResult) -> None: ...
    async def mark_failed(self, workflow_id: str, error_message: str) -> None: ...
    async def heartbeat(self, workflow_id: str) -> None: ...
    async def request_cancel(self, workflow_id: str) -> None: ...
    async def mark_canceled(self, workflow_id: str) -> None: ...


def _record_from_row(row: asyncpg.Record) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=row["workflow_id"],
        plan_json=row["plan_json"],
        plan_hash=row["plan_hash"],
        status=PersistentWorkflowStatus(row["status"]),
        result_json=row["result_json"],
        error_message=row["error_message"],
        created_at=row["created_at"].replace(tzinfo=timezone.utc),
        updated_at=row["updated_at"].replace(tzinfo=timezone.utc),
        claimed_at=(row["claimed_at"].replace(tzinfo=timezone.utc) if row["claimed_at"] else None),
        claimed_by=row["claimed_by"],
        completed_at=(row["completed_at"].replace(tzinfo=timezone.utc) if row["completed_at"] else None),
        required_task_types=tuple(row.get("required_task_types") or ()),
        modality=row.get("modality"),
    )


class PostgresWorkflowRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_pending(self, plan: BuildPlan, plan_hash: str) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO workflow_runs
                        (workflow_id, plan_json, plan_hash, status, required_task_types, modality)
                    VALUES ($1, $2, $3, 'pending', $4, $5)
                    """,
                    plan.workflow_id,
                    plan.model_dump_json(),
                    plan_hash,
                    sorted({task.task_type for task in plan.tasks}),
                    plan.modality.value,
                )
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateWorkflowError(plan.workflow_id) from exc

    async def get(self, workflow_id: str) -> WorkflowRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_runs WHERE workflow_id = $1",
                workflow_id,
            )
        return _record_from_row(row) if row else None

    async def claim_next_pending(
        self,
        worker_id: str,
        supported_task_types: frozenset[str] | None = None,
        supported_modalities: frozenset[str] | None = None,
    ) -> WorkflowRecord | None:
        """
        Atomically claim one pending workflow.

        Uses SELECT FOR UPDATE SKIP LOCKED so concurrent workers cannot claim
        the same row.  The UPDATE is committed before any executor runs.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE workflow_runs
                    SET status = 'running',
                        claimed_at = now(),
                        claimed_by = $1,
                        updated_at = now()
                    WHERE workflow_id = (
                        SELECT workflow_id FROM workflow_runs
                        WHERE status = 'pending'
                          AND ($2::text[] IS NULL OR required_task_types <@ $2::text[])
                          AND ($3::text[] IS NULL OR modality = ANY($3::text[]))
                        ORDER BY created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                    """,
                    worker_id,
                    sorted(supported_task_types) if supported_task_types is not None else None,
                    sorted(supported_modalities) if supported_modalities is not None else None,
                )
        return _record_from_row(row) if row else None

    async def mark_succeeded(self, workflow_id: str, result: WorkflowResult) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflow_runs
                SET status       = 'succeeded',
                    result_json  = $2,
                    completed_at = now(),
                    updated_at   = now()
                WHERE workflow_id = $1 AND status = 'running'
                """,
                workflow_id,
                result.model_dump_json(),
            )

    async def mark_failed(self, workflow_id: str, error_message: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflow_runs
                SET status        = 'failed',
                    error_message = $2,
                    completed_at  = now(),
                    updated_at    = now()
                WHERE workflow_id = $1 AND status = 'running'
                """,
                workflow_id,
                error_message,
            )

    async def heartbeat(self, workflow_id: str) -> None:
        """Record that a claimed workflow is still actively being processed."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflow_runs SET updated_at = now()
                WHERE workflow_id = $1 AND status = 'running'
                """,
                workflow_id,
            )

    async def request_cancel(self, workflow_id: str) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE workflow_runs SET
                    status = CASE WHEN status = 'pending' THEN 'canceled'
                                  ELSE 'cancel_requested' END,
                    error_message = 'Canceled by user.',
                    completed_at = CASE WHEN status = 'pending' THEN now()
                                        ELSE completed_at END,
                    updated_at = now()
                WHERE workflow_id = $1 AND status IN ('pending', 'running')
                """,
                workflow_id,
            )
        if result == "UPDATE 0":
            raise ValueError(f"workflow {workflow_id!r} is not cancelable")

    async def mark_canceled(self, workflow_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflow_runs SET
                    status = 'canceled', error_message = 'Canceled by user.',
                    completed_at = now(), updated_at = now()
                WHERE workflow_id = $1 AND status = 'cancel_requested'
                """,
                workflow_id,
            )
