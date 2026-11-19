"""Postgres persistence and transitions for objective extraction jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    func,
    select,
    update,
)
from sqlalchemy.orm import declarative_base

from src.source_ingestion.repository import InvalidStateTransition, get_session

from .contracts import ObjectiveDecisionStatus, PractitionerInstructions
from .job_contracts import (
    ObjectiveJob,
    ObjectiveJobEvent,
    ObjectiveJobReview,
    ObjectiveJobStage,
    ObjectiveProcessingStatus,
    ObjectiveReviewKind,
    PromptRun,
)


Base = declarative_base()


class ObjectiveJobRow(Base):
    __tablename__ = "source_objective_jobs"
    job_id = Column(String, primary_key=True)
    source_run_id = Column(String, nullable=False)
    collection_id = Column(String, nullable=False)
    workspace_id = Column(String, nullable=True)
    workspace_revision = Column(Integer, nullable=True)
    workflow_stage = Column(String, nullable=False)
    processing_status = Column(String, nullable=False)
    instructions = Column(JSON, nullable=True)
    created_by = Column(String, nullable=True)
    worker_id = Column(String, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempt = Column(Integer, nullable=False)
    retryable = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)
    current_operation = Column(Text, nullable=True)
    completed_operations = Column(Integer, nullable=False)
    progress_detail = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ObjectiveJobEventRow(Base):
    __tablename__ = "source_objective_job_events"
    event_id = Column(String, primary_key=True)
    job_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    from_stage = Column(String, nullable=True)
    to_stage = Column(String, nullable=True)
    actor = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ObjectiveJobReviewRow(Base):
    __tablename__ = "source_objective_job_reviews"
    review_id = Column(String, primary_key=True)
    job_id = Column(String, nullable=False)
    workspace_revision = Column(Integer, nullable=False)
    candidate_id = Column(String, nullable=False)
    review_kind = Column(String, nullable=False)
    status = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    decided_by = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class PromptRunRow(Base):
    __tablename__ = "source_objective_prompt_runs"
    prompt_run_id = Column(String, primary_key=True)
    job_id = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    prompt_id = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False)
    prompt_sha256 = Column(String, nullable=False)
    prompt_filename = Column(String, nullable=False)
    prompt_snapshot = Column(Text, nullable=False)
    model_alias = Column(String, nullable=False)
    input_sha256 = Column(String, nullable=False)
    input_snapshot = Column(Text, nullable=False)
    input_artifact_ref = Column(Text, nullable=True)
    output_schema = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ObjectiveModelCheckpointRow(Base):
    __tablename__ = "source_objective_model_checkpoints"
    job_id = Column(String, primary_key=True)
    operation = Column(String, primary_key=True)
    model_alias = Column(String, nullable=False)
    prompt_sha256 = Column(String, nullable=False)
    input_sha256 = Column(String, nullable=True)
    output_schema = Column(String, nullable=False)
    output_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _job(row: ObjectiveJobRow) -> ObjectiveJob:
    return ObjectiveJob(
        job_id=row.job_id,
        source_run_id=row.source_run_id,
        collection_id=row.collection_id,
        workspace_id=row.workspace_id,
        workspace_revision=row.workspace_revision,
        workflow_stage=row.workflow_stage,
        processing_status=row.processing_status,
        instructions=PractitionerInstructions.model_validate(row.instructions)
        if row.instructions
        else None,
        created_by=row.created_by,
        attempt=row.attempt,
        retryable=row.retryable,
        error_message=row.error_message,
        current_operation=row.current_operation,
        completed_operations=row.completed_operations,
        progress_detail=dict(row.progress_detail or {}),
        version=row.version,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
        completed_at=_aware(row.completed_at),
    )


def _event(
    session,
    row: ObjectiveJobRow,
    event_type: str,
    *,
    actor: str | None = None,
    note: str | None = None,
    from_stage: str | None = None,
    to_stage: str | None = None,
    payload: dict | None = None,
) -> None:
    session.add(
        ObjectiveJobEventRow(
            event_id=str(uuid.uuid4()),
            job_id=row.job_id,
            event_type=event_type,
            from_stage=from_stage,
            to_stage=to_stage,
            actor=actor,
            note=note,
            payload=payload or {},
            created_at=datetime.now(timezone.utc),
        )
    )


def create_objective_job(
    source_run_id: str,
    collection_id: str,
    *,
    instructions: PractitionerInstructions | None = None,
    created_by: str | None = None,
    job_id: str | None = None,
) -> ObjectiveJob:
    now = datetime.now(timezone.utc)
    job_id = job_id or str(uuid.uuid4())
    with get_session() as session, session.begin():
        row = ObjectiveJobRow(
            job_id=job_id,
            source_run_id=source_run_id,
            collection_id=collection_id,
            workflow_stage=ObjectiveJobStage.DRAFT,
            processing_status=ObjectiveProcessingStatus.QUEUED,
            instructions=instructions.model_dump(mode="json") if instructions else None,
            created_by=created_by,
            attempt=1,
            completed_operations=0,
            progress_detail={},
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        _event(session, row, "created", actor=created_by, to_stage=ObjectiveJobStage.DRAFT)
        session.flush()
        return _job(row)


def get_objective_job(job_id: str) -> ObjectiveJob | None:
    with get_session() as session:
        row = session.get(ObjectiveJobRow, job_id)
        return _job(row) if row else None


def load_model_checkpoint(
    job_id: str,
    *,
    operation: str,
    model_alias: str,
    prompt_sha256: str,
    input_sha256: str,
    output_schema: str,
) -> dict | None:
    """Return an exact completed model result, binding an imported result on first use."""

    with get_session() as session, session.begin():
        row = session.get(ObjectiveModelCheckpointRow, (job_id, operation))
        if row is None:
            return None
        if (
            row.model_alias != model_alias
            or row.prompt_sha256 != prompt_sha256
            or row.output_schema != output_schema
            or row.input_sha256 not in (None, input_sha256)
        ):
            return None
        if row.input_sha256 is None:
            row.input_sha256 = input_sha256
        return dict(row.output_payload)


def save_model_checkpoint(
    job_id: str,
    *,
    operation: str,
    model_alias: str,
    prompt_sha256: str,
    input_sha256: str | None,
    output_schema: str,
    output_payload: dict,
) -> None:
    """Persist one successful structured response for restart-safe replay."""

    with get_session() as session, session.begin():
        row = session.get(ObjectiveModelCheckpointRow, (job_id, operation))
        if row is not None:
            if not (
                row.model_alias != model_alias
                or row.prompt_sha256 != prompt_sha256
                or row.output_schema != output_schema
                or row.input_sha256 not in (None, input_sha256)
            ):
                return
            row.model_alias = model_alias
            row.prompt_sha256 = prompt_sha256
            row.input_sha256 = input_sha256
            row.output_schema = output_schema
            row.output_payload = output_payload
            row.created_at = datetime.now(timezone.utc)
            return
        session.add(
            ObjectiveModelCheckpointRow(
                job_id=job_id,
                operation=operation,
                model_alias=model_alias,
                prompt_sha256=prompt_sha256,
                input_sha256=input_sha256,
                output_schema=output_schema,
                output_payload=output_payload,
                created_at=datetime.now(timezone.utc),
            )
        )


def list_objective_jobs() -> list[ObjectiveJob]:
    with get_session() as session:
        rows = session.scalars(
            select(ObjectiveJobRow).order_by(ObjectiveJobRow.updated_at.desc())
        ).all()
        return [_job(row) for row in rows]


def claim_next_objective_job(
    worker_id: str = "source-worker", lease_seconds: int = 900
) -> ObjectiveJob | None:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.scalars(
            select(ObjectiveJobRow)
            .where(ObjectiveJobRow.processing_status == ObjectiveProcessingStatus.QUEUED)
            .order_by(ObjectiveJobRow.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if row is None:
            return None
        row.processing_status = ObjectiveProcessingStatus.RUNNING
        row.current_operation = "Starting objective processing"
        row.worker_id = worker_id
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.updated_at = now
        row.version += 1
        _event(session, row, "processing_started", actor=worker_id)
        session.flush()
        return _job(row)


def complete_decomposition(
    job_id: str,
    *,
    workspace_id: str,
    workspace_revision: int,
    prompt_runs: list[dict],
) -> ObjectiveJob:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(ObjectiveJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        if row.workflow_stage != ObjectiveJobStage.DRAFT or row.processing_status != ObjectiveProcessingStatus.RUNNING:
            raise InvalidStateTransition("decomposition job is not running in draft")
        previous = row.workflow_stage
        row.workspace_id = workspace_id
        row.workspace_revision = workspace_revision
        row.workflow_stage = ObjectiveJobStage.OBJECTIVE_REVIEW
        row.processing_status = ObjectiveProcessingStatus.SUCCEEDED
        row.current_operation = None
        row.worker_id = None
        row.lease_expires_at = None
        row.retryable = None
        row.error_message = None
        row.updated_at = now
        row.version += 1
        for value in prompt_runs:
            session.add(
                PromptRunRow(
                    prompt_run_id=value.get("prompt_run_id") or str(uuid.uuid4()),
                    job_id=job_id,
                    operation=value["operation"],
                    prompt_id=value["prompt_id"],
                    prompt_version=value["prompt_version"],
                    prompt_sha256=value["prompt_sha256"],
                    prompt_filename=value["prompt_filename"],
                    prompt_snapshot=value["prompt_snapshot"],
                    model_alias=value["model_alias"],
                    input_sha256=value["input_sha256"],
                    input_snapshot=value["input_snapshot"],
                    input_artifact_ref=value.get("input_artifact_ref"),
                    output_schema=value["output_schema"],
                    created_at=now,
                )
            )
        _event(
            session,
            row,
            "decomposition_completed",
            from_stage=previous,
            to_stage=row.workflow_stage,
            payload={"workspace_id": workspace_id, "workspace_revision": workspace_revision},
        )
        session.flush()
        return _job(row)


def fail_objective_job(job_id: str, error: str, *, retryable: bool) -> ObjectiveJob:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(ObjectiveJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        if row.processing_status != ObjectiveProcessingStatus.RUNNING:
            raise InvalidStateTransition("only a running objective job can fail")
        row.processing_status = ObjectiveProcessingStatus.FAILED
        row.error_message = error
        row.current_operation = "Processing failed"
        row.retryable = retryable
        row.worker_id = None
        row.lease_expires_at = None
        row.updated_at = now
        row.version += 1
        _event(session, row, "processing_failed", note=error)
        session.flush()
        return _job(row)


def retry_objective_job(job_id: str, *, actor: str | None = None) -> ObjectiveJob:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(ObjectiveJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        if row.processing_status != ObjectiveProcessingStatus.FAILED:
            raise InvalidStateTransition("only a failed objective job can be retried")
        if row.attempt >= 3:
            raise InvalidStateTransition("maximum objective job attempts reached")
        row.processing_status = ObjectiveProcessingStatus.QUEUED
        row.error_message = None
        row.current_operation = "Waiting for a worker"
        row.completed_operations = 0
        row.progress_detail = {}
        row.retryable = None
        row.attempt += 1
        row.updated_at = now
        row.version += 1
        _event(session, row, "retry_queued", actor=actor)
        session.flush()
        return _job(row)


def update_objective_job_progress(
    job_id: str,
    *,
    operation: str,
    completed_operations: int,
    progress_detail: dict | None = None,
    lease_seconds: int = 900,
) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(ObjectiveJobRow, job_id, with_for_update=True)
        if row is None or row.processing_status != ObjectiveProcessingStatus.RUNNING:
            return
        row.current_operation = operation
        row.completed_operations = completed_operations
        row.progress_detail = {
            **dict(row.progress_detail or {}),
            **dict(progress_detail or {}),
        }
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.updated_at = now


def record_review(
    job_id: str,
    *,
    candidate_id: str,
    review_kind: ObjectiveReviewKind,
    status: ObjectiveDecisionStatus,
    decided_by: str,
    note: str | None = None,
) -> ObjectiveJobReview:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        job = session.get(ObjectiveJobRow, job_id, with_for_update=True)
        if job is None:
            raise KeyError(job_id)
        if review_kind != ObjectiveReviewKind.OBJECTIVE:
            raise InvalidStateTransition("only objective review decisions are accepted")
        expected_stage = ObjectiveJobStage.OBJECTIVE_REVIEW
        if job.workflow_stage != expected_stage:
            raise InvalidStateTransition(
                f"{review_kind} decisions require stage {expected_stage}"
            )
        if job.workspace_revision is None:
            raise InvalidStateTransition("objective job has no workspace revision")
        row = ObjectiveJobReviewRow(
            review_id=str(uuid.uuid4()),
            job_id=job_id,
            workspace_revision=job.workspace_revision,
            candidate_id=candidate_id,
            review_kind=review_kind,
            status=status,
            note=note,
            decided_by=decided_by,
            created_at=now,
        )
        session.add(row)
        job.updated_at = now
        job.version += 1
        _event(
            session,
            job,
            "review_recorded",
            actor=decided_by,
            note=note,
            payload={
                "candidate_id": candidate_id,
                "review_kind": str(review_kind),
                "status": str(status),
            },
        )
        session.flush()
        return _review(row)


def _review(row: ObjectiveJobReviewRow) -> ObjectiveJobReview:
    return ObjectiveJobReview(
        review_id=row.review_id,
        job_id=row.job_id,
        workspace_revision=row.workspace_revision,
        candidate_id=row.candidate_id,
        review_kind=row.review_kind,
        status=row.status,
        note=row.note,
        decided_by=row.decided_by,
        created_at=_aware(row.created_at),
    )


def list_latest_reviews(
    job_id: str,
    review_kind: ObjectiveReviewKind | None = None,
    workspace_revision: int | None = None,
) -> list[ObjectiveJobReview]:
    with get_session() as session:
        query = select(ObjectiveJobReviewRow).where(ObjectiveJobReviewRow.job_id == job_id)
        if review_kind is not None:
            query = query.where(ObjectiveJobReviewRow.review_kind == review_kind)
        if workspace_revision is not None:
            query = query.where(
                ObjectiveJobReviewRow.workspace_revision == workspace_revision
            )
        rows = session.scalars(query.order_by(ObjectiveJobReviewRow.created_at)).all()
        latest = {}
        for row in rows:
            latest[(row.candidate_id, row.review_kind)] = row
        return [_review(row) for row in latest.values()]


def advance_objective_job(
    job_id: str,
    *,
    expected_version: int,
    actor: str,
    note: str | None = None,
) -> ObjectiveJob:
    transitions = {ObjectiveJobStage.OBJECTIVE_REVIEW: ObjectiveJobStage.COMPLETE}
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(ObjectiveJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        if row.version != expected_version:
            raise InvalidStateTransition("objective job was updated; reload before advancing")
        destination = transitions.get(ObjectiveJobStage(row.workflow_stage))
        if destination is None:
            raise InvalidStateTransition(f"job cannot advance from {row.workflow_stage}")
        previous = row.workflow_stage
        row.workflow_stage = destination
        row.processing_status = ObjectiveProcessingStatus.SUCCEEDED
        if destination == ObjectiveJobStage.COMPLETE:
            row.completed_at = now
        row.updated_at = now
        row.version += 1
        _event(
            session,
            row,
            "stage_advanced",
            actor=actor,
            note=note,
            from_stage=previous,
            to_stage=destination,
        )
        session.flush()
        return _job(row)


def update_job_workspace_revision(
    job_id: str, *, workspace_revision: int, expected_version: int
) -> ObjectiveJob:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(ObjectiveJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        if row.version != expected_version:
            raise InvalidStateTransition("objective job was updated; reload before editing")
        row.workspace_revision = workspace_revision
        row.updated_at = now
        row.version += 1
        _event(
            session,
            row,
            "workspace_revised",
            payload={"workspace_revision": workspace_revision},
        )
        session.flush()
        return _job(row)


def list_job_events(job_id: str) -> list[ObjectiveJobEvent]:
    with get_session() as session:
        rows = session.scalars(
            select(ObjectiveJobEventRow)
            .where(ObjectiveJobEventRow.job_id == job_id)
            .order_by(ObjectiveJobEventRow.created_at)
        ).all()
        return [
            ObjectiveJobEvent(
                event_id=row.event_id,
                job_id=row.job_id,
                event_type=row.event_type,
                from_stage=row.from_stage,
                to_stage=row.to_stage,
                actor=row.actor,
                note=row.note,
                payload=row.payload,
                created_at=_aware(row.created_at),
            )
            for row in rows
        ]


def list_prompt_runs(job_id: str) -> list[PromptRun]:
    with get_session() as session:
        rows = session.scalars(
            select(PromptRunRow)
            .where(PromptRunRow.job_id == job_id)
            .order_by(PromptRunRow.created_at)
        ).all()
        return [
            PromptRun(
                prompt_run_id=row.prompt_run_id,
                job_id=row.job_id,
                operation=row.operation,
                prompt_id=row.prompt_id,
                prompt_version=row.prompt_version,
                prompt_sha256=row.prompt_sha256,
                prompt_filename=row.prompt_filename,
                prompt_snapshot=row.prompt_snapshot,
                model_alias=row.model_alias,
                input_sha256=row.input_sha256,
                input_snapshot=row.input_snapshot,
                input_artifact_ref=row.input_artifact_ref,
                output_schema=row.output_schema,
                created_at=_aware(row.created_at),
            )
            for row in rows
        ]


def append_prompt_runs(job_id: str, prompt_runs: list[dict]) -> None:
    """Persist additional audited prompt runs produced during objective review."""

    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        for value in prompt_runs:
            session.add(
                PromptRunRow(
                    prompt_run_id=value.get("prompt_run_id") or str(uuid.uuid4()),
                    job_id=job_id,
                    operation=value["operation"],
                    prompt_id=value["prompt_id"],
                    prompt_version=value["prompt_version"],
                    prompt_sha256=value["prompt_sha256"],
                    prompt_filename=value["prompt_filename"],
                    prompt_snapshot=value["prompt_snapshot"],
                    model_alias=value["model_alias"],
                    input_sha256=value["input_sha256"],
                    input_snapshot=value["input_snapshot"],
                    input_artifact_ref=value.get("input_artifact_ref"),
                    output_schema=value["output_schema"],
                    created_at=now,
                )
            )


def get_prompt_run(job_id: str, prompt_run_id: str) -> PromptRun | None:
    with get_session() as session:
        row = session.get(PromptRunRow, prompt_run_id)
        if row is None or row.job_id != job_id:
            return None
        return PromptRun(
            prompt_run_id=row.prompt_run_id,
            job_id=row.job_id,
            operation=row.operation,
            prompt_id=row.prompt_id,
            prompt_version=row.prompt_version,
            prompt_sha256=row.prompt_sha256,
            prompt_filename=row.prompt_filename,
            prompt_snapshot=row.prompt_snapshot,
            model_alias=row.model_alias,
            input_sha256=row.input_sha256,
            input_snapshot=row.input_snapshot,
            input_artifact_ref=row.input_artifact_ref,
            output_schema=row.output_schema,
            created_at=_aware(row.created_at),
        )


def count_prompt_runs(job_id: str) -> int:
    with get_session() as session:
        return session.scalar(
            select(func.count())
            .select_from(PromptRunRow)
            .where(PromptRunRow.job_id == job_id)
        ) or 0


def list_prompt_run_summaries(job_id: str) -> list[dict]:
    with get_session() as session:
        rows = session.execute(
            select(
                PromptRunRow.prompt_run_id,
                PromptRunRow.operation,
                PromptRunRow.prompt_id,
                PromptRunRow.prompt_version,
                PromptRunRow.prompt_sha256,
                PromptRunRow.prompt_filename,
                PromptRunRow.model_alias,
                PromptRunRow.input_sha256,
                PromptRunRow.input_artifact_ref,
                PromptRunRow.output_schema,
                PromptRunRow.created_at,
            )
            .where(PromptRunRow.job_id == job_id)
            .order_by(PromptRunRow.created_at)
        ).all()
        return [
            {
                "prompt_run_id": row.prompt_run_id,
                "job_id": job_id,
                "operation": row.operation,
                "prompt_id": row.prompt_id,
                "prompt_version": row.prompt_version,
                "prompt_sha256": row.prompt_sha256,
                "prompt_filename": row.prompt_filename,
                "model_alias": row.model_alias,
                "input_sha256": row.input_sha256,
                "input_artifact_ref": row.input_artifact_ref,
                "output_schema": row.output_schema,
                "created_at": _aware(row.created_at),
            }
            for row in rows
        ]


def recover_stale_objective_jobs(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        result = session.execute(
            update(ObjectiveJobRow)
            .where(
                ObjectiveJobRow.processing_status == ObjectiveProcessingStatus.RUNNING,
                ObjectiveJobRow.lease_expires_at < now,
            )
            .values(
                processing_status=ObjectiveProcessingStatus.QUEUED,
                worker_id=None,
                lease_expires_at=None,
                updated_at=now,
                version=ObjectiveJobRow.version + 1,
            )
        )
        return result.rowcount
