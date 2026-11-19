"""Persistence boundary for immutable commissioning previews."""

from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
from typing import Protocol

import asyncpg
from learning_pipeline.db.migrate import run_migrations

from .contracts import (
    CommissioningJobRecord,
    CommissioningJobState,
    CommissioningJobView,
    ConfirmedLearningRequest,
    LearningRequestPreview,
)


def _confirmation_hash(confirmation: ConfirmedLearningRequest) -> str:
    payload = confirmation.model_dump(mode="json")
    payload.pop("confirmed_at", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _job_id(preview_id: str) -> str:
    return "assembly-" + hashlib.sha256(preview_id.encode()).hexdigest()[:24]


class PreviewRepository(Protocol):
    async def get_preview(self, preview_id: str) -> LearningRequestPreview | None: ...
    async def get_preview_by_hash(self, preview_hash: str) -> LearningRequestPreview | None: ...
    async def put_preview(self, preview: LearningRequestPreview) -> None: ...
    async def put_confirmation(self, confirmation: ConfirmedLearningRequest) -> None: ...
    async def get_confirmation(self, preview_id: str) -> ConfirmedLearningRequest | None: ...
    async def enqueue_job(self, confirmation: ConfirmedLearningRequest) -> CommissioningJobRecord: ...
    async def get_job(self, job_id: str) -> CommissioningJobRecord | None: ...
    async def get_job_by_preview(self, preview_id: str) -> CommissioningJobRecord | None: ...
    async def get_job_artifact(self, job_id: str, column: str) -> dict | None: ...
    async def list_job_views(
        self,
        *,
        limit: int = 50,
        before_created_at: datetime | None = None,
        before_job_id: str | None = None,
    ) -> list[CommissioningJobView]: ...
    async def get_job_view(self, job_id: str) -> CommissioningJobView | None: ...
    async def rerun_failed_job(self, job_id: str) -> None: ...
    async def cancel_job(self, job_id: str) -> None: ...


class JobNotRerunnableError(RuntimeError):
    """Raised when a job is missing or is not currently failed."""


class JobNotCancelableError(RuntimeError):
    """Raised when a job has no pending or running execution to cancel."""


class InMemoryPreviewRepository:
    """Reference/demo repository; production wiring will use durable storage."""

    def __init__(self) -> None:
        self._previews: dict[str, LearningRequestPreview] = {}
        self._preview_ids_by_hash: dict[str, str] = {}
        self._confirmations: dict[str, ConfirmedLearningRequest] = {}
        self._jobs: dict[str, CommissioningJobRecord] = {}
        self._job_ids_by_preview: dict[str, str] = {}
        self._artifacts: dict[str, dict[str, dict]] = {}

    async def get_preview(self, preview_id: str) -> LearningRequestPreview | None:
        return self._previews.get(preview_id)

    async def get_preview_by_hash(self, preview_hash: str) -> LearningRequestPreview | None:
        preview_id = self._preview_ids_by_hash.get(preview_hash)
        return self._previews.get(preview_id) if preview_id else None

    async def put_preview(self, preview: LearningRequestPreview) -> None:
        self._previews.setdefault(preview.preview_id, preview)
        self._preview_ids_by_hash.setdefault(preview.preview_hash, preview.preview_id)

    async def put_confirmation(self, confirmation: ConfirmedLearningRequest) -> None:
        self._confirmations.setdefault(confirmation.preview_id, confirmation)

    async def get_confirmation(self, preview_id: str) -> ConfirmedLearningRequest | None:
        return self._confirmations.get(preview_id)

    async def enqueue_job(self, confirmation: ConfirmedLearningRequest) -> CommissioningJobRecord:
        existing = await self.get_job_by_preview(confirmation.preview_id)
        if existing:
            return existing
        now = datetime.now(UTC)
        record = CommissioningJobRecord(
            job_id=_job_id(confirmation.preview_id),
            preview_id=confirmation.preview_id,
            request_id=confirmation.request_id,
            confirmed_request_hash=_confirmation_hash(confirmation),
            state=CommissioningJobState.QUEUED_FOR_ASSEMBLY,
            created_at=now,
            updated_at=now,
        )
        self._jobs[record.job_id] = record
        self._job_ids_by_preview[record.preview_id] = record.job_id
        return record

    async def get_job(self, job_id: str) -> CommissioningJobRecord | None:
        return self._jobs.get(job_id)

    async def get_job_by_preview(self, preview_id: str) -> CommissioningJobRecord | None:
        job_id = self._job_ids_by_preview.get(preview_id)
        return self._jobs.get(job_id) if job_id else None

    async def get_job_artifact(self, job_id: str, column: str) -> dict | None:
        return self._artifacts.get(job_id, {}).get(column)

    async def get_workflow_result_json(self, job_id: str) -> tuple[str | None, str | None]:
        return None, None

    async def get_job_view(self, job_id: str) -> CommissioningJobView | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        confirmation = self._confirmations.get(job.preview_id)
        active = job.state not in {CommissioningJobState.SUCCEEDED, CommissioningJobState.FAILED}
        status = (
            "blueprint_ready"
            if job.state == CommissioningJobState.SUCCEEDED
            else "failed"
            if job.state == CommissioningJobState.FAILED
            else job.state.value
        )
        return CommissioningJobView(
            job_id=job.job_id,
            request_id=job.request_id,
            course_goal=confirmation.confirmed_course_goal if confirmation else job.request_id,
            state=job.state,
            status=status,
            stage_label=job.state.value.replace("_", " ").title(),
            selected_modality=job.selected_modality,
            workflow_id=job.workflow_id,
            blueprint_available=bool(job.blueprint_uri),
            error_summary=job.error_summary,
            created_at=job.created_at,
            updated_at=job.updated_at,
            poll_after_ms=2000 if active else None,
        )

    async def rerun_failed_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.state != CommissioningJobState.FAILED:
            raise JobNotRerunnableError(job_id)
        now = datetime.now(UTC)
        self._jobs[job_id] = job.model_copy(
            update={
                "state": CommissioningJobState.QUEUED_FOR_ASSEMBLY,
                "error_code": None,
                "error_summary": None,
                "updated_at": now,
            }
        )

    async def cancel_job(self, job_id: str) -> None:
        raise JobNotCancelableError(job_id)

    async def list_job_views(
        self,
        *,
        limit: int = 50,
        before_created_at: datetime | None = None,
        before_job_id: str | None = None,
    ) -> list[CommissioningJobView]:
        records = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
        if before_created_at is not None and before_job_id is not None:
            records = [
                item for item in records
                if (item.created_at, item.job_id) < (before_created_at, before_job_id)
            ]
        views = [await self.get_job_view(item.job_id) for item in records[:limit]]
        return [view for view in views if view is not None]


class PostgresPreviewRepository:
    """Durable commissioning-owned storage in the shared application database."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def create(cls, dsn: str) -> "PostgresPreviewRepository":
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        await run_migrations(pool)
        repository = cls(pool)
        await repository._migrate()
        return repository

    async def _migrate(self) -> None:
        result = await self.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS commissioning_previews (
                preview_id TEXT PRIMARY KEY,
                preview_hash TEXT NOT NULL UNIQUE,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            );
            CREATE TABLE IF NOT EXISTS commissioning_confirmations (
                preview_id TEXT PRIMARY KEY REFERENCES commissioning_previews(preview_id),
                payload JSONB NOT NULL,
                confirmed_at TIMESTAMPTZ NOT NULL
            );
            CREATE TABLE IF NOT EXISTS commissioning_jobs (
                job_id TEXT PRIMARY KEY,
                preview_id TEXT NOT NULL UNIQUE REFERENCES commissioning_confirmations(preview_id),
                request_id TEXT NOT NULL,
                confirmed_request_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                worker_id TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                course_assembly_request_uri TEXT,
                blueprint_uri TEXT,
                assembly_report_uri TEXT,
                planning_trace_uri TEXT,
                assembly_request JSONB,
                adapter_trace JSONB,
                blueprint JSONB,
                assembly_report JSONB,
                planning_trace JSONB,
                error_code TEXT,
                error_summary TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            );
            CREATE INDEX IF NOT EXISTS commissioning_jobs_claim_idx
                ON commissioning_jobs (state, created_at);
            ALTER TABLE commissioning_jobs
                ADD COLUMN IF NOT EXISTS selected_modality TEXT,
                ADD COLUMN IF NOT EXISTS format_selection JSONB,
                ADD COLUMN IF NOT EXISTS modality_plan JSONB,
                ADD COLUMN IF NOT EXISTS modality_trace JSONB,
                ADD COLUMN IF NOT EXISTS production_plan JSONB,
                ADD COLUMN IF NOT EXISTS build_plan JSONB,
                ADD COLUMN IF NOT EXISTS workflow_planning_trace JSONB,
                ADD COLUMN IF NOT EXISTS workflow_id TEXT UNIQUE,
                ADD COLUMN IF NOT EXISTS planning_started_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS execution_submitted_at TIMESTAMPTZ;
            """
        )

    async def close(self) -> None:
        await self.pool.close()

    async def get_preview(self, preview_id: str) -> LearningRequestPreview | None:
        value = await self.pool.fetchval(
            "SELECT payload::text FROM commissioning_previews WHERE preview_id = $1",
            preview_id,
        )
        return self._load_preview(value)

    async def get_preview_by_hash(self, preview_hash: str) -> LearningRequestPreview | None:
        value = await self.pool.fetchval(
            "SELECT payload::text FROM commissioning_previews WHERE preview_hash = $1",
            preview_hash,
        )
        return self._load_preview(value)

    @staticmethod
    def _load_preview(value: str | None) -> LearningRequestPreview | None:
        if not value:
            return None
        payload = json.loads(value)
        # Pydantic computed fields were included by an early reference build.
        payload.pop("confirmation_allowed", None)
        return LearningRequestPreview.model_validate(payload)

    async def put_preview(self, preview: LearningRequestPreview) -> None:
        await self.pool.execute(
            """
            INSERT INTO commissioning_previews (preview_id, preview_hash, payload, created_at)
            VALUES ($1, $2, $3::jsonb, $4)
            ON CONFLICT (preview_id) DO NOTHING
            """,
            preview.preview_id,
            preview.preview_hash,
            preview.model_dump_json(exclude_computed_fields=True),
            preview.created_at,
        )

    async def put_confirmation(self, confirmation: ConfirmedLearningRequest) -> None:
        await self.pool.execute(
            """
            INSERT INTO commissioning_confirmations (preview_id, payload, confirmed_at)
            VALUES ($1, $2::jsonb, $3)
            ON CONFLICT (preview_id) DO NOTHING
            """,
            confirmation.preview_id,
            confirmation.model_dump_json(),
            confirmation.confirmed_at,
        )

    async def get_confirmation(self, preview_id: str) -> ConfirmedLearningRequest | None:
        value = await self.pool.fetchval(
            "SELECT payload::text FROM commissioning_confirmations WHERE preview_id = $1",
            preview_id,
        )
        return ConfirmedLearningRequest.model_validate_json(value) if value else None

    @staticmethod
    def _load_job(row: asyncpg.Record | None) -> CommissioningJobRecord | None:
        if row is None:
            return None
        return CommissioningJobRecord(
            job_id=row["job_id"],
            preview_id=row["preview_id"],
            request_id=row["request_id"],
            confirmed_request_hash=row["confirmed_request_hash"],
            state=row["state"],
            course_assembly_request_uri=row["course_assembly_request_uri"],
            blueprint_uri=row["blueprint_uri"],
            assembly_report_uri=row["assembly_report_uri"],
            planning_trace_uri=row["planning_trace_uri"],
            selected_modality=row["selected_modality"],
            workflow_id=row["workflow_id"],
            planning_started_at=row["planning_started_at"],
            execution_submitted_at=row["execution_submitted_at"],
            error_code=row["error_code"],
            error_summary=row["error_summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def enqueue_job(self, confirmation: ConfirmedLearningRequest) -> CommissioningJobRecord:
        now = datetime.now(UTC)
        job_id = _job_id(confirmation.preview_id)
        await self.pool.execute(
            """
            INSERT INTO commissioning_jobs (
                job_id, preview_id, request_id, confirmed_request_hash, state, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $6)
            ON CONFLICT (preview_id) DO NOTHING
            """,
            job_id,
            confirmation.preview_id,
            confirmation.request_id,
            _confirmation_hash(confirmation),
            CommissioningJobState.QUEUED_FOR_ASSEMBLY.value,
            now,
        )
        record = await self.get_job_by_preview(confirmation.preview_id)
        if record is None:
            raise RuntimeError("failed to create or retrieve commissioning job")
        return record

    async def ensure_jobs_for_confirmations(self) -> int:
        rows = await self.pool.fetch(
            """
            SELECT c.payload::text
            FROM commissioning_confirmations c
            LEFT JOIN commissioning_jobs j ON j.preview_id = c.preview_id
            WHERE j.preview_id IS NULL
            """
        )
        for row in rows:
            await self.enqueue_job(ConfirmedLearningRequest.model_validate_json(row["payload"]))
        return len(rows)

    async def get_job(self, job_id: str) -> CommissioningJobRecord | None:
        row = await self.pool.fetchrow("SELECT * FROM commissioning_jobs WHERE job_id = $1", job_id)
        return self._load_job(row)

    async def get_job_by_preview(self, preview_id: str) -> CommissioningJobRecord | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM commissioning_jobs WHERE preview_id = $1", preview_id
        )
        return self._load_job(row)

    @staticmethod
    def _load_job_view(row: asyncpg.Record | None) -> CommissioningJobView | None:
        if row is None:
            return None
        workflow_status = row["workflow_status"]
        state = CommissioningJobState(row["state"])
        completed_tasks = 0
        total_tasks = 0
        snapshot_text = row["snapshot_json"]
        if snapshot_text:
            snapshot = json.loads(snapshot_text)
            statuses = snapshot.get("statuses", {})
            total_tasks = len(statuses)
            completed_tasks = sum(value == "succeeded" for value in statuses.values())
        elif row["plan_json"]:
            total_tasks = len(json.loads(row["plan_json"]).get("tasks", []))

        if workflow_status == "running":
            status, stage = "executing", "Generating content"
        elif workflow_status == "cancel_requested":
            status, stage = "canceling", "Canceling generation"
        elif workflow_status == "canceled":
            status, stage = "canceled", "Generation canceled"
        elif workflow_status == "succeeded":
            status, stage = "completed", "Content ready"
        elif workflow_status == "failed":
            status, stage = "failed", "Generation failed"
        else:
            status = state.value
            stage = {
                CommissioningJobState.QUEUED_FOR_ASSEMBLY: "Queued for blueprint assembly",
                CommissioningJobState.ASSEMBLING_BLUEPRINT: "Assembling course blueprint",
                CommissioningJobState.ASSEMBLING: "Assembling course blueprint",
                CommissioningJobState.SELECTING_FORMAT: "Selecting delivery format",
                CommissioningJobState.PLANNING_MODALITY: "Planning learning experience",
                CommissioningJobState.PLANNING_WORKFLOW: "Planning content production",
                CommissioningJobState.QUEUED_FOR_EXECUTION: "Queued for generation",
                CommissioningJobState.FAILED: "Planning failed",
                CommissioningJobState.SUCCEEDED: "Blueprint ready (legacy job)",
            }.get(state, state.value.replace("_", " ").title())
            if state == CommissioningJobState.SUCCEEDED:
                status = "blueprint_ready"
        active = status not in {"completed", "failed", "canceled", "blueprint_ready"}
        result_json = row["result_json"] or ""
        downloadable = workflow_status == "succeeded" and "artifact://" in result_json
        return CommissioningJobView(
            job_id=row["job_id"],
            request_id=row["request_id"],
            course_goal=row["course_goal"] or row["request_id"],
            state=state,
            status=status,
            stage_label=stage,
            selected_modality=row["selected_modality"],
            workflow_id=row["workflow_id"],
            completed_tasks=completed_tasks,
            total_tasks=total_tasks,
            downloadable=downloadable,
            blueprint_available=row["blueprint"] is not None,
            error_summary=row["workflow_error"] or row["error_summary"],
            created_at=row["created_at"],
            updated_at=max(row["updated_at"], row["workflow_updated_at"] or row["updated_at"]),
            poll_after_ms=2000 if active else None,
        )

    async def get_job_view(self, job_id: str) -> CommissioningJobView | None:
        row = await self.pool.fetchrow(self._job_view_query() + " WHERE j.job_id = $1", job_id)
        return self._load_job_view(row)

    async def rerun_failed_job(self, job_id: str) -> None:
        """Atomically requeue either a failed workflow or failed planning job."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                job = await connection.fetchrow(
                    "SELECT state, workflow_id FROM commissioning_jobs WHERE job_id = $1 FOR UPDATE",
                    job_id,
                )
                if job is None:
                    raise JobNotRerunnableError(job_id)

                workflow = None
                if job["workflow_id"]:
                    workflow = await connection.fetchrow(
                        "SELECT status FROM workflow_runs WHERE workflow_id = $1 FOR UPDATE",
                        job["workflow_id"],
                    )

                if workflow and workflow["status"] in {"failed", "canceled"}:
                    await connection.execute(
                        """
                        UPDATE workflow_runs SET
                            status = 'pending', result_json = NULL, error_message = NULL,
                            claimed_at = NULL, claimed_by = NULL, completed_at = NULL,
                            updated_at = NOW()
                        WHERE workflow_id = $1 AND status IN ('failed', 'canceled')
                        """,
                        job["workflow_id"],
                    )
                    await connection.execute(
                        "UPDATE commissioning_jobs SET updated_at = NOW() WHERE job_id = $1",
                        job_id,
                    )
                    return

                if job["state"] != CommissioningJobState.FAILED.value or job["workflow_id"]:
                    raise JobNotRerunnableError(job_id)

                await connection.execute(
                    """
                    UPDATE commissioning_jobs SET
                        state = $2, worker_id = NULL,
                        selected_modality = NULL, format_selection = NULL,
                        modality_plan = NULL, modality_trace = NULL,
                        production_plan = NULL, build_plan = NULL,
                        workflow_planning_trace = NULL,
                        planning_started_at = NULL, execution_submitted_at = NULL,
                        error_code = NULL, error_summary = NULL,
                        updated_at = NOW()
                    WHERE job_id = $1
                    """,
                    job_id,
                    CommissioningJobState.QUEUED_FOR_ASSEMBLY.value,
                )

    async def cancel_job(self, job_id: str) -> None:
        """Request cooperative cancellation for a pending or running workflow."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                job = await connection.fetchrow(
                    "SELECT workflow_id FROM commissioning_jobs WHERE job_id = $1 FOR UPDATE",
                    job_id,
                )
                if job is None or not job["workflow_id"]:
                    raise JobNotCancelableError(job_id)
                result = await connection.execute(
                    """
                    UPDATE workflow_runs SET
                        status = CASE WHEN status = 'pending' THEN 'canceled'
                                      ELSE 'cancel_requested' END,
                        error_message = 'Canceled by user.',
                        completed_at = CASE WHEN status = 'pending' THEN NOW()
                                            ELSE completed_at END,
                        updated_at = NOW()
                    WHERE workflow_id = $1 AND status IN ('pending', 'running')
                    """,
                    job["workflow_id"],
                )
                if result == "UPDATE 0":
                    raise JobNotCancelableError(job_id)
                await connection.execute(
                    "UPDATE commissioning_jobs SET updated_at = NOW() WHERE job_id = $1",
                    job_id,
                )

    async def list_job_views(
        self,
        *,
        limit: int = 50,
        before_created_at: datetime | None = None,
        before_job_id: str | None = None,
    ) -> list[CommissioningJobView]:
        query = self._job_view_query()
        if before_created_at is not None and before_job_id is not None:
            query += " WHERE (j.created_at, j.job_id) < ($1, $2)"
            args = (before_created_at, before_job_id, limit)
            query += " ORDER BY j.created_at DESC, j.job_id DESC LIMIT $3"
        else:
            args = (limit,)
            query += " ORDER BY j.created_at DESC, j.job_id DESC LIMIT $1"
        rows = await self.pool.fetch(query, *args)
        return [view for row in rows if (view := self._load_job_view(row)) is not None]

    @staticmethod
    def _job_view_query() -> str:
        return """
            SELECT j.*, c.payload->>'confirmed_course_goal' AS course_goal,
                   w.status AS workflow_status, w.plan_json, w.result_json,
                   w.error_message AS workflow_error,
                   w.updated_at AS workflow_updated_at,
                   s.snapshot_json
            FROM commissioning_jobs j
            JOIN commissioning_confirmations c ON c.preview_id = j.preview_id
            LEFT JOIN workflow_runs w ON w.workflow_id = j.workflow_id
            LEFT JOIN workflow_run_state s ON s.workflow_id = j.workflow_id
        """

    async def claim_next_job(self, worker_id: str) -> CommissioningJobRecord | None:
        row = await self.pool.fetchrow(
            """
            WITH candidate AS (
                SELECT job_id FROM commissioning_jobs
                WHERE state = $1
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE commissioning_jobs j
            SET state = $2, worker_id = $3, attempt_count = attempt_count + 1,
                updated_at = NOW()
            FROM candidate
            WHERE j.job_id = candidate.job_id
            RETURNING j.*
            """,
            CommissioningJobState.QUEUED_FOR_ASSEMBLY.value,
            CommissioningJobState.ASSEMBLING_BLUEPRINT.value,
            worker_id,
        )
        return self._load_job(row)

    async def complete_job(
        self,
        job_id: str,
        *,
        assembly_request: str,
        adapter_trace: str,
        blueprint: str,
        assembly_report: str,
        planning_trace: str,
        course_assembly_request_uri: str,
        blueprint_uri: str,
        assembly_report_uri: str,
        planning_trace_uri: str,
    ) -> None:
        result = await self.pool.execute(
            """
            UPDATE commissioning_jobs SET
                state = $2,
                assembly_request = $3::jsonb,
                adapter_trace = $4::jsonb,
                blueprint = $5::jsonb,
                assembly_report = $6::jsonb,
                planning_trace = $7::jsonb,
                course_assembly_request_uri = $8,
                blueprint_uri = $9,
                assembly_report_uri = $10,
                planning_trace_uri = $11,
                error_code = NULL,
                error_summary = NULL,
                updated_at = NOW()
            WHERE job_id = $1 AND state IN ($12, $13)
            """,
            job_id,
            CommissioningJobState.SELECTING_FORMAT.value,
            assembly_request,
            adapter_trace,
            blueprint,
            assembly_report,
            planning_trace,
            course_assembly_request_uri,
            blueprint_uri,
            assembly_report_uri,
            planning_trace_uri,
            CommissioningJobState.ASSEMBLING_BLUEPRINT.value,
            CommissioningJobState.ASSEMBLING.value,
        )
        if result != "UPDATE 1":
            raise RuntimeError(f"blueprint persistence transition rejected for {job_id!r}")

    async def transition_job(
        self,
        job_id: str,
        *,
        expected: CommissioningJobState,
        target: CommissioningJobState,
    ) -> None:
        result = await self.pool.execute(
            """
            UPDATE commissioning_jobs
            SET state = $3, updated_at = NOW()
            WHERE job_id = $1 AND state = $2
            """,
            job_id,
            expected.value,
            target.value,
        )
        if result != "UPDATE 1":
            raise RuntimeError(
                f"job {job_id!r} did not transition from {expected.value!r}"
            )

    async def save_format_selection(self, job_id: str, result_json: str, modality: str) -> None:
        result = await self.pool.execute(
            """
            UPDATE commissioning_jobs SET
                state = $2, selected_modality = $3,
                format_selection = $4::jsonb,
                planning_started_at = COALESCE(planning_started_at, NOW()),
                updated_at = NOW()
            WHERE job_id = $1 AND state = $5
            """,
            job_id,
            CommissioningJobState.PLANNING_MODALITY.value,
            modality,
            result_json,
            CommissioningJobState.SELECTING_FORMAT.value,
        )
        if result != "UPDATE 1":
            raise RuntimeError(f"format selection transition rejected for {job_id!r}")

    async def save_modality_plan(self, job_id: str, plan_json: str, trace_json: str) -> None:
        result = await self.pool.execute(
            """
            UPDATE commissioning_jobs SET
                state = $2, modality_plan = $3::jsonb,
                modality_trace = $4::jsonb, updated_at = NOW()
            WHERE job_id = $1 AND state = $5
            """,
            job_id,
            CommissioningJobState.PLANNING_WORKFLOW.value,
            plan_json,
            trace_json,
            CommissioningJobState.PLANNING_MODALITY.value,
        )
        if result != "UPDATE 1":
            raise RuntimeError(f"modality planning transition rejected for {job_id!r}")

    async def save_workflow_plan(
        self,
        job_id: str,
        *,
        production_plan: str,
        build_plan: str,
        planning_trace: str,
    ) -> None:
        result = await self.pool.execute(
            """
            UPDATE commissioning_jobs SET
                production_plan = $2::jsonb, build_plan = $3::jsonb,
                workflow_planning_trace = $4::jsonb, updated_at = NOW()
            WHERE job_id = $1 AND state = $5
            """,
            job_id,
            production_plan,
            build_plan,
            planning_trace,
            CommissioningJobState.PLANNING_WORKFLOW.value,
        )
        if result != "UPDATE 1":
            raise RuntimeError(f"workflow planning persistence rejected for {job_id!r}")

    async def link_workflow(self, job_id: str, workflow_id: str) -> None:
        result = await self.pool.execute(
            """
            UPDATE commissioning_jobs SET
                state = $2, workflow_id = $3,
                execution_submitted_at = COALESCE(execution_submitted_at, NOW()),
                updated_at = NOW()
            WHERE job_id = $1 AND state = $4
              AND (workflow_id IS NULL OR workflow_id = $3)
            """,
            job_id,
            CommissioningJobState.QUEUED_FOR_EXECUTION.value,
            workflow_id,
            CommissioningJobState.PLANNING_WORKFLOW.value,
        )
        if result != "UPDATE 1":
            existing = await self.get_job(job_id)
            if not existing or existing.workflow_id != workflow_id:
                raise RuntimeError(f"workflow link rejected for {job_id!r}")

    async def fail_job(self, job_id: str, *, error_code: str, error_summary: str) -> None:
        await self.pool.execute(
            """
            UPDATE commissioning_jobs SET state = $2, error_code = $3,
                error_summary = $4, updated_at = NOW()
            WHERE job_id = $1
            """,
            job_id,
            CommissioningJobState.FAILED.value,
            error_code,
            error_summary[:1000],
        )

    async def get_job_artifact(self, job_id: str, column: str) -> dict | None:
        allowed = {
            "assembly_request", "adapter_trace", "blueprint", "assembly_report", "planning_trace"
        }
        if column not in allowed:
            raise ValueError(f"unknown job artifact: {column}")
        value = await self.pool.fetchval(
            f"SELECT {column}::text FROM commissioning_jobs WHERE job_id = $1", job_id
        )
        return json.loads(value) if value else None

    async def get_workflow_result_json(self, job_id: str) -> tuple[str | None, str | None]:
        row = await self.pool.fetchrow(
            """
            SELECT w.status, w.result_json
            FROM commissioning_jobs j
            LEFT JOIN workflow_runs w ON w.workflow_id = j.workflow_id
            WHERE j.job_id = $1
            """,
            job_id,
        )
        if row is None:
            return None, None
        return row["status"], row["result_json"]
