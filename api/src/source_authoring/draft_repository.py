"""Postgres persistence and source loading for grounded RLO drafts."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, or_, select
from sqlalchemy.orm import declarative_base

from src.source_ingestion.contracts import ArtifactManifest, ExtractedDocument, SourceSegment
from src.source_ingestion.repository import (
    SourceDocumentRow,
    SourceProcessingRunRow,
    SourceVersionRow,
    get_session,
)
from src.storage import get_storage

from .cell_scope import authoring_scope_error, candidate_scope_error
from .draft_contracts import (
    RLODraftJob,
    RLODraftRequest,
    RLODraftState,
    RLOGenerationBatch,
    RLOGenerationBatchState,
    RLOGenerationCheckpoint,
    RLOGenerationPromptRun,
    RLOPendingRevision,
    RLOReviewRecord,
)


Base = declarative_base()


class RLOGenerationBatchRow(Base):
    __tablename__ = "source_rlo_generation_batches"
    batch_id = Column(String, primary_key=True)
    objective_job_id = Column(String, nullable=False, unique=True)
    workspace_id = Column(String, nullable=False)
    workspace_revision = Column(Integer, nullable=False)
    collection_id = Column(String, nullable=False)
    state = Column(String, nullable=False)
    finalized = Column(Integer, nullable=False, default=0)
    collection_validation_started_at = Column(DateTime(timezone=True), nullable=True)
    collection_validated_at = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class RLODraftJobRow(Base):
    __tablename__ = "source_rlo_draft_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "workspace_revision",
            "candidate_id",
            "rlo_id",
            "rlo_version",
        ),
    )
    job_id = Column(String, primary_key=True)
    batch_id = Column(
        String,
        ForeignKey("source_rlo_generation_batches.batch_id", ondelete="RESTRICT"),
        nullable=True,
    )
    workspace_id = Column(String, nullable=False)
    workspace_revision = Column(Integer, nullable=False)
    candidate_id = Column(String, nullable=False)
    rlo_id = Column(String, nullable=False)
    rlo_version = Column(String, nullable=False)
    state = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    current_operation = Column(String, nullable=True)
    completed_operations = Column(Integer, nullable=False, default=0)
    attempt = Column(Integer, nullable=False, default=0)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)


class RLODraftRevisionRow(Base):
    __tablename__ = "source_rlo_draft_revisions"
    job_id = Column(
        String,
        ForeignKey("source_rlo_draft_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision = Column(Integer, primary_key=True)
    payload = Column(JSON, nullable=False)
    findings = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class RLODraftReviewRow(Base):
    __tablename__ = "source_rlo_draft_reviews"
    review_id = Column(String, primary_key=True)
    job_id = Column(
        String,
        ForeignKey("source_rlo_draft_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    revision = Column(Integer, nullable=False)
    action = Column(String, nullable=False)
    reviewer = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class PublishedSourceDependencyRow(Base):
    __tablename__ = "source_published_rlo_dependencies"
    job_id = Column(
        String,
        ForeignKey("source_rlo_draft_jobs.job_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_version_id = Column(
        String,
        primary_key=True,
    )
    rlo_id = Column(String, nullable=False)
    rlo_version = Column(String, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)


class RLOGenerationCheckpointRow(Base):
    __tablename__ = "source_rlo_generation_checkpoints"
    job_id = Column(
        String,
        ForeignKey("source_rlo_draft_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    operation = Column(String, primary_key=True)
    sequence = Column(Integer, nullable=False)
    input_hash = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class RLOGenerationPromptRunRow(Base):
    __tablename__ = "source_rlo_generation_prompt_runs"
    prompt_run_id = Column(String, primary_key=True)
    job_id = Column(
        String,
        ForeignKey("source_rlo_draft_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation = Column(String, nullable=False)
    prompt_id = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False)
    prompt_sha256 = Column(String, nullable=False)
    prompt_filename = Column(String, nullable=False)
    prompt_snapshot = Column(Text, nullable=False)
    model_alias = Column(String, nullable=False)
    input_snapshot = Column(Text, nullable=False)
    output_schema = Column(String, nullable=False)
    output_snapshot = Column(Text, nullable=False)
    usage = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class DraftStateConflict(ValueError):
    pass


_ACTIVE_STATES = {
    RLODraftState.PLANNING,
    RLODraftState.MAPPING_SOURCE,
    RLODraftState.ENRICHING_KNOWLEDGE,
    RLODraftState.GENERATING_PARTS,
    RLODraftState.ASSEMBLING,
    RLODraftState.VALIDATING,
    RLODraftState.REPAIRING,
    RLODraftState.GENERATING,
}


def _safe_rlo_id(candidate_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate_id).strip("-.")
    if not value:
        raise ValueError("candidate ID cannot produce an RLO ID")
    return f"rlo-{value}"


def create_generation_batch(
    package,
    *,
    created_by: str | None = None,
    finalized: bool = False,
) -> RLOGenerationBatch:
    """Create or extend a batch with one child per newly approved objective."""

    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.scalar(
            select(RLOGenerationBatchRow)
            .where(RLOGenerationBatchRow.objective_job_id == package.job_id)
            .with_for_update()
        )
        if row:
            if row.collection_id != package.collection_id:
                raise ValueError("RLO generation batch source collection cannot change")
            batch = RLOGenerationBatch.model_validate(row.payload)
            batch_id = batch.batch_id
            existing_children = session.scalars(
                select(RLODraftJobRow).where(RLODraftJobRow.batch_id == batch_id)
            ).all()
        else:
            batch_id = str(uuid.uuid4())
            existing_children = []

        existing_candidate_ids = {child.candidate_id for child in existing_children}
        child_jobs = []
        for candidate in package.objectives:
            if candidate.candidate_id in existing_candidate_ids:
                continue
            request = RLODraftRequest(
                workspace_id=package.workspace_id,
                workspace_revision=package.workspace_revision,
                candidate_id=candidate.candidate_id,
                rlo_id=_safe_rlo_id(candidate.candidate_id),
                rlo_version="0.1.0",
            )
            scope_error = candidate_scope_error(candidate)
            child_jobs.append(
                RLODraftJob(
                    job_id=str(uuid.uuid4()),
                    batch_id=batch_id,
                    objective_job_id=package.job_id,
                    state=(RLODraftState.FAILED if scope_error else RLODraftState.QUEUED),
                    request=request,
                    created_by=created_by,
                    error_message=(
                        f"Objective is outside POC2 authoring scope: {scope_error}"
                        if scope_error
                        else None
                    ),
                    current_operation=("POC2 scope check" if scope_error else None),
                    retryable=False if scope_error else None,
                )
            )

        child_job_ids = [child.job_id for child in existing_children] + [
            job.job_id for job in child_jobs
        ]
        has_new_queued_child = any(
            job.state == RLODraftState.QUEUED for job in child_jobs
        )
        if row:
            if batch.finalized and child_jobs:
                raise DraftStateConflict(
                    "finalized RLO generation batches cannot accept more objectives"
                )
            batch = batch.model_copy(
                update={
                    "workspace_revision": package.workspace_revision,
                    "finalized": batch.finalized or finalized,
                    "state": (
                        RLOGenerationBatchState.QUEUED
                        if has_new_queued_child
                        else batch.state
                    ),
                    "child_job_ids": child_job_ids,
                    "updated_at": now.isoformat(),
                }
            )
            row.workspace_revision = package.workspace_revision
            row.finalized = int(batch.finalized)
            row.state = str(batch.state)
            row.payload = batch.model_dump(mode="json")
            row.updated_at = now
        else:
            state = (
                RLOGenerationBatchState.QUEUED
                if has_new_queued_child
                else RLOGenerationBatchState.COMPLETE
            )
            batch = RLOGenerationBatch(
                batch_id=batch_id,
                objective_job_id=package.job_id,
                workspace_id=package.workspace_id,
                workspace_revision=package.workspace_revision,
                collection_id=package.collection_id,
                state=state,
                finalized=finalized,
                child_job_ids=child_job_ids,
                created_by=created_by,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            session.add(
                RLOGenerationBatchRow(
                    batch_id=batch_id,
                    objective_job_id=package.job_id,
                    workspace_id=package.workspace_id,
                    workspace_revision=package.workspace_revision,
                    collection_id=package.collection_id,
                    state=str(state),
                    finalized=int(finalized),
                    payload=batch.model_dump(mode="json"),
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()

        for job in child_jobs:
            request = job.request
            session.add(
                RLODraftJobRow(
                    job_id=job.job_id,
                    batch_id=batch_id,
                    workspace_id=request.workspace_id,
                    workspace_revision=request.workspace_revision,
                    candidate_id=request.candidate_id,
                    rlo_id=request.rlo_id,
                    rlo_version=request.rlo_version,
                    state=str(job.state),
                    payload=job.model_dump(mode="json"),
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                    current_operation=job.current_operation,
                    completed_operations=0,
                    attempt=0,
                    error_message=job.error_message,
                )
            )
    return batch


def get_generation_job_for_candidate(
    objective_job_id: str, candidate_id: str
) -> RLODraftJob | None:
    with get_session() as session:
        row = session.scalar(
            select(RLODraftJobRow)
            .join(
                RLOGenerationBatchRow,
                RLOGenerationBatchRow.batch_id == RLODraftJobRow.batch_id,
            )
            .where(
                RLOGenerationBatchRow.objective_job_id == objective_job_id,
                RLODraftJobRow.candidate_id == candidate_id,
            )
        )
        return RLODraftJob.model_validate(row.payload) if row else None


def get_generation_batch(batch_id: str) -> RLOGenerationBatch | None:
    with get_session() as session:
        row = session.get(RLOGenerationBatchRow, batch_id)
        return RLOGenerationBatch.model_validate(row.payload) if row else None


def get_generation_batch_for_objective_job(
    objective_job_id: str,
) -> RLOGenerationBatch | None:
    with get_session() as session:
        row = session.scalar(
            select(RLOGenerationBatchRow).where(
                RLOGenerationBatchRow.objective_job_id == objective_job_id
            )
        )
        return RLOGenerationBatch.model_validate(row.payload) if row else None


def list_generation_batches() -> list[RLOGenerationBatch]:
    with get_session() as session:
        rows = session.scalars(
            select(RLOGenerationBatchRow).order_by(
                RLOGenerationBatchRow.updated_at.desc()
            )
        ).all()
        return [RLOGenerationBatch.model_validate(row.payload) for row in rows]


def _batch_state(children: list[RLODraftJobRow]) -> RLOGenerationBatchState:
    states = [
        RLODraftState(child.state)
        for child in children
        if not (
            RLODraftState(child.state) == RLODraftState.FAILED
            and child.current_operation == "POC2 scope check"
        )
    ]
    if not states or all(state == RLODraftState.PUBLISHED for state in states):
        return RLOGenerationBatchState.COMPLETE
    if any(state in _ACTIVE_STATES or state == RLODraftState.QUEUED for state in states):
        return RLOGenerationBatchState.RUNNING
    reviewable = {
        RLODraftState.IN_REVIEW,
        RLODraftState.VALIDATION_FAILED,
        RLODraftState.SOURCE_INSUFFICIENT,
        RLODraftState.REVISION_REQUESTED,
        RLODraftState.APPROVED,
        RLODraftState.PUBLISHED,
    }
    if all(state in reviewable for state in states):
        return RLOGenerationBatchState.IN_REVIEW
    if any(state in {RLODraftState.FAILED, RLODraftState.REJECTED} for state in states):
        return RLOGenerationBatchState.PARTIAL
    return RLOGenerationBatchState.PARTIAL


def refresh_generation_batch(batch_id: str) -> RLOGenerationBatch:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(RLOGenerationBatchRow, batch_id, with_for_update=True)
        if row is None:
            raise KeyError(batch_id)
        children = session.scalars(
            select(RLODraftJobRow).where(RLODraftJobRow.batch_id == batch_id)
        ).all()
        state = _batch_state(children)
        batch = RLOGenerationBatch.model_validate(row.payload).model_copy(
            update={"state": state, "updated_at": now.isoformat()}
        )
        row.state = str(state)
        row.payload = batch.model_dump(mode="json")
        row.updated_at = now
        return batch


def claim_next_collection_validation_batch(
    *, stale_after_seconds: int = 300
) -> RLOGenerationBatch | None:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=stale_after_seconds)
    with get_session() as session, session.begin():
        row = session.scalar(
            select(RLOGenerationBatchRow)
            .where(
                RLOGenerationBatchRow.finalized == 1,
                RLOGenerationBatchRow.state.in_(
                    [
                        str(RLOGenerationBatchState.IN_REVIEW),
                        str(RLOGenerationBatchState.COMPLETE),
                    ]
                ),
                RLOGenerationBatchRow.collection_validated_at.is_(None),
                or_(
                    RLOGenerationBatchRow.collection_validation_started_at.is_(None),
                    RLOGenerationBatchRow.collection_validation_started_at < stale_before,
                ),
            )
            .order_by(RLOGenerationBatchRow.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        batch = RLOGenerationBatch.model_validate(row.payload).model_copy(
            update={"collection_validation_started_at": now.isoformat()}
        )
        row.collection_validation_started_at = now
        row.payload = batch.model_dump(mode="json")
        row.updated_at = now
        return batch


def complete_collection_validation(
    batch_id: str, findings: list
) -> RLOGenerationBatch:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(RLOGenerationBatchRow, batch_id, with_for_update=True)
        if row is None:
            raise KeyError(batch_id)
        batch = RLOGenerationBatch.model_validate(row.payload).model_copy(
            update={
                "findings": findings,
                "collection_validated_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        )
        row.collection_validated_at = now
        row.payload = batch.model_dump(mode="json")
        row.updated_at = now
        return batch


def claim_next_draft_job(*, lease_seconds: int = 300) -> RLODraftJob | None:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.scalar(
            select(RLODraftJobRow)
            .where(
                or_(
                    RLODraftJobRow.state == str(RLODraftState.QUEUED),
                    (
                        RLODraftJobRow.state.in_([str(state) for state in _ACTIVE_STATES])
                        & (RLODraftJobRow.lease_expires_at < now)
                    ),
                )
            )
            .order_by(RLODraftJobRow.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        job = RLODraftJob.model_validate(row.payload).model_copy(
            update={
                "state": RLODraftState.PLANNING,
                "current_operation": "Planning RLO generation",
                "attempt": row.attempt + 1,
                "retryable": None,
                "error_message": None,
            }
        )
        row.state = str(job.state)
        row.payload = job.model_dump(mode="json")
        row.current_operation = job.current_operation
        row.attempt = job.attempt
        row.error_message = None
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.updated_at = now
        return job


def update_draft_job_progress(
    job_id: str,
    *,
    state: RLODraftState,
    operation: str,
    completed_operations: int,
    lease_seconds: int = 300,
) -> RLODraftJob:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(RLODraftJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        current = RLODraftJob.model_validate(row.payload)
        job = current.model_copy(
            update={
                "state": state,
                "current_operation": operation,
                "completed_operations": completed_operations,
            }
        )
        row.state = str(state)
        row.payload = job.model_dump(mode="json")
        row.current_operation = operation
        row.completed_operations = completed_operations
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.updated_at = now
        return job


def save_generation_checkpoint(
    job_id: str,
    *,
    operation: str,
    sequence: int,
    input_hash: str,
    payload: dict,
) -> RLOGenerationCheckpoint:
    now = datetime.now(timezone.utc)
    checkpoint = RLOGenerationCheckpoint(
        job_id=job_id,
        operation=operation,
        sequence=sequence,
        input_hash=input_hash,
        payload=payload,
        created_at=now.isoformat(),
    )
    with get_session() as session, session.begin():
        row = session.get(RLOGenerationCheckpointRow, (job_id, operation))
        if row is None:
            session.add(
                RLOGenerationCheckpointRow(
                    job_id=job_id,
                    operation=operation,
                    sequence=sequence,
                    input_hash=input_hash,
                    payload=payload,
                    created_at=now,
                )
            )
        elif row.input_hash != input_hash:
            row.sequence = sequence
            row.input_hash = input_hash
            row.payload = payload
            row.created_at = now
    return checkpoint


def list_generation_checkpoints(job_id: str) -> list[RLOGenerationCheckpoint]:
    with get_session() as session:
        rows = session.scalars(
            select(RLOGenerationCheckpointRow)
            .where(RLOGenerationCheckpointRow.job_id == job_id)
            .order_by(RLOGenerationCheckpointRow.sequence)
        ).all()
        return [
            RLOGenerationCheckpoint(
                job_id=row.job_id,
                operation=row.operation,
                sequence=row.sequence,
                input_hash=row.input_hash,
                payload=row.payload,
                created_at=row.created_at.replace(tzinfo=timezone.utc).isoformat()
                if row.created_at.tzinfo is None
                else row.created_at.isoformat(),
            )
            for row in rows
        ]


def record_generation_prompt_run(run: RLOGenerationPromptRun) -> None:
    with get_session() as session, session.begin():
        session.add(
            RLOGenerationPromptRunRow(
                prompt_run_id=run.prompt_run_id,
                job_id=run.job_id,
                operation=run.operation,
                prompt_id=run.prompt_id,
                prompt_version=run.prompt_version,
                prompt_sha256=run.prompt_sha256,
                prompt_filename=run.prompt_filename,
                prompt_snapshot=run.prompt_snapshot,
                model_alias=run.model_alias,
                input_snapshot=run.input_snapshot,
                output_schema=run.output_schema,
                output_snapshot=run.output_snapshot,
                usage=run.usage,
                created_at=datetime.fromisoformat(run.created_at),
            )
        )


def list_generation_prompt_runs(job_id: str) -> list[RLOGenerationPromptRun]:
    with get_session() as session:
        rows = session.scalars(
            select(RLOGenerationPromptRunRow)
            .where(RLOGenerationPromptRunRow.job_id == job_id)
            .order_by(RLOGenerationPromptRunRow.created_at)
        ).all()
        return [
            RLOGenerationPromptRun(
                prompt_run_id=row.prompt_run_id,
                job_id=row.job_id,
                operation=row.operation,
                prompt_id=row.prompt_id,
                prompt_version=row.prompt_version,
                prompt_sha256=row.prompt_sha256,
                prompt_filename=row.prompt_filename,
                prompt_snapshot=row.prompt_snapshot,
                model_alias=row.model_alias,
                input_snapshot=row.input_snapshot,
                output_schema=row.output_schema,
                output_snapshot=row.output_snapshot,
                usage=row.usage,
                created_at=row.created_at.replace(tzinfo=timezone.utc).isoformat()
                if row.created_at.tzinfo is None
                else row.created_at.isoformat(),
            )
            for row in rows
        ]


def create_draft_job(
    request: RLODraftRequest,
    *,
    created_by: str | None = None,
    batch_id: str | None = None,
    objective_job_id: str | None = None,
) -> RLODraftJob:
    from . import repository as objective_repository

    workspace = objective_repository.get_objective_workspace(
        request.workspace_id, request.workspace_revision
    )
    candidate = next(
        (
            item
            for item in workspace.candidates
            if item.candidate_id == request.candidate_id
        ),
        None,
    ) if workspace else None
    if candidate is None:
        raise ValueError("objective candidate does not exist")
    scope_error = candidate_scope_error(candidate)
    if scope_error:
        raise ValueError(f"Objective is outside POC2 authoring scope: {scope_error}")
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        existing = session.scalar(
            select(RLODraftJobRow).where(
                RLODraftJobRow.workspace_id == request.workspace_id,
                RLODraftJobRow.workspace_revision == request.workspace_revision,
                RLODraftJobRow.candidate_id == request.candidate_id,
                RLODraftJobRow.rlo_id == request.rlo_id,
                RLODraftJobRow.rlo_version == request.rlo_version,
            )
        )
        if existing:
            return RLODraftJob.model_validate(existing.payload)
        job = RLODraftJob(
            job_id=str(uuid.uuid4()),
            batch_id=batch_id,
            objective_job_id=objective_job_id,
            state=RLODraftState.QUEUED,
            request=request,
            created_by=created_by,
        )
        session.add(
            RLODraftJobRow(
                job_id=job.job_id,
                batch_id=batch_id,
                workspace_id=request.workspace_id,
                workspace_revision=request.workspace_revision,
                candidate_id=request.candidate_id,
                rlo_id=request.rlo_id,
                rlo_version=request.rlo_version,
                state=str(job.state),
                payload=job.model_dump(mode="json"),
                created_by=created_by,
                created_at=now,
                updated_at=now,
                completed_operations=0,
                attempt=0,
            )
        )
    return job


def save_draft_job(
    job: RLODraftJob,
    *,
    expected_state: RLODraftState,
    save_revision: bool = False,
) -> RLODraftJob:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(RLODraftJobRow, job.job_id, with_for_update=True)
        if row is None:
            raise ValueError("draft job does not exist")
        if row.state != str(expected_state):
            raise DraftStateConflict(
                f"draft job is {row.state!r}, expected {str(expected_state)!r}"
            )
        row.state = str(job.state)
        row.payload = job.model_dump(mode="json")
        row.updated_at = now
        row.current_operation = job.current_operation
        row.completed_operations = job.completed_operations
        row.attempt = job.attempt
        row.error_message = job.error_message
        if job.state not in {
            RLODraftState.PLANNING,
            RLODraftState.MAPPING_SOURCE,
            RLODraftState.ENRICHING_KNOWLEDGE,
            RLODraftState.GENERATING_PARTS,
            RLODraftState.ASSEMBLING,
            RLODraftState.VALIDATING,
            RLODraftState.REPAIRING,
            RLODraftState.GENERATING,
        }:
            row.lease_expires_at = None
        if save_revision:
            existing = session.get(RLODraftRevisionRow, (job.job_id, job.revision))
            if existing is not None:
                raise DraftStateConflict("draft revision already exists")
            session.add(
                RLODraftRevisionRow(
                    job_id=job.job_id,
                    revision=job.revision,
                    payload={
                        "authoring": job.authoring.model_dump(mode="json")
                        if job.authoring
                        else None,
                        "catalog": job.draft.model_dump(mode="json") if job.draft else None,
                    },
                    findings=[item.model_dump(mode="json") for item in job.findings],
                    created_at=now,
                )
            )
    return job


def record_draft_review(job_id: str, review: RLOReviewRecord) -> None:
    with get_session() as session, session.begin():
        session.add(
            RLODraftReviewRow(
                review_id=str(uuid.uuid4()),
                job_id=job_id,
                revision=review.revision,
                action=str(review.action),
                reviewer=review.reviewer,
                note=review.note,
                payload=review.model_dump(mode="json"),
                created_at=datetime.fromisoformat(review.reviewed_at),
            )
        )


def get_draft_job(job_id: str) -> RLODraftJob | None:
    with get_session() as session:
        row = session.get(RLODraftJobRow, job_id)
        return RLODraftJob.model_validate(row.payload) if row else None


def list_draft_jobs(batch_id: str | None = None) -> list[RLODraftJob]:
    with get_session() as session:
        query = select(RLODraftJobRow)
        if batch_id is not None:
            query = query.where(RLODraftJobRow.batch_id == batch_id)
        rows = session.scalars(query.order_by(RLODraftJobRow.updated_at.desc())).all()
        return [RLODraftJob.model_validate(row.payload) for row in rows]


def retry_draft_job(job_id: str) -> RLODraftJob:
    from . import repository as objective_repository

    now = datetime.now(timezone.utc)
    retryable_states = {
        RLODraftState.FAILED,
        RLODraftState.VALIDATION_FAILED,
        RLODraftState.SOURCE_INSUFFICIENT,
        RLODraftState.REVISION_REQUESTED,
    }
    with get_session() as session, session.begin():
        row = session.get(RLODraftJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        job = RLODraftJob.model_validate(row.payload)
        workspace = objective_repository.get_objective_workspace(
            job.request.workspace_id, job.request.workspace_revision
        )
        candidate = (
            next(
                (
                    item
                    for item in workspace.candidates
                    if item.candidate_id == job.request.candidate_id
                ),
                None,
            )
            if workspace
            else None
        )
        scope_error = (
            candidate_scope_error(candidate)
            if candidate
            else "Objective candidate does not exist."
        )
        if scope_error:
            raise DraftStateConflict(
                f"Objective is outside POC2 authoring scope: {scope_error}"
            )
        if job.state not in retryable_states:
            raise DraftStateConflict("RLO generation job is not retryable in its current state")
        queued = job.model_copy(
            update={
                "state": RLODraftState.QUEUED,
                "current_operation": "Waiting for RLO worker",
                "error_message": None,
                "retryable": None,
            }
        )
        row.state = str(queued.state)
        row.payload = queued.model_dump(mode="json")
        row.current_operation = queued.current_operation
        row.error_message = None
        row.lease_expires_at = None
        row.updated_at = now
        return queued


def queue_scoped_revision(job_id: str, revision: RLOPendingRevision) -> RLODraftJob:
    now = datetime.now(timezone.utc)
    allowed_states = {
        RLODraftState.IN_REVIEW,
        RLODraftState.VALIDATION_FAILED,
        RLODraftState.REVISION_REQUESTED,
    }
    with get_session() as session, session.begin():
        row = session.get(RLODraftJobRow, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        job = RLODraftJob.model_validate(row.payload)
        if job.state not in allowed_states:
            raise DraftStateConflict(
                "RLO is not available for a reviewer-directed revision"
            )
        if job.authoring is None:
            raise DraftStateConflict("RLO has no reviewable authoring artifact")
        scope_error = authoring_scope_error(job.authoring)
        if scope_error:
            raise DraftStateConflict(
                f"RLO is outside POC2 authoring scope: {scope_error}"
            )
        if job.pending_revision is not None:
            raise DraftStateConflict("RLO already has an active revision")
        queued = job.model_copy(
            update={
                "state": RLODraftState.QUEUED,
                "current_operation": "Waiting for scoped RLO revision",
                "pending_revision": revision,
                "error_message": None,
                "retryable": None,
            }
        )
        row.state = str(queued.state)
        row.payload = queued.model_dump(mode="json")
        row.current_operation = queued.current_operation
        row.error_message = None
        row.lease_expires_at = None
        row.updated_at = now
        return queued


def mark_published(job_id: str, *, rlo_id: str, rlo_version: str) -> RLODraftJob:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        row = session.get(RLODraftJobRow, job_id, with_for_update=True)
        if row is None:
            raise ValueError("draft job does not exist")
        job = RLODraftJob.model_validate(row.payload)
        if job.state != RLODraftState.APPROVED or job.draft is None:
            raise DraftStateConflict("only an approved draft can be published")
        scope_error = authoring_scope_error(job.authoring)
        if scope_error:
            raise DraftStateConflict(
                f"RLO is outside POC2 authoring scope: {scope_error}"
            )
        published = job.model_copy(
            update={
                "state": RLODraftState.PUBLISHED,
                "published_rlo_id": rlo_id,
                "published_rlo_version": rlo_version,
            }
        )
        row.state = str(published.state)
        row.payload = published.model_dump(mode="json")
        row.updated_at = now
        for source_version_id in dict.fromkeys(
            source.source_version_id for source in published.draft.sources
        ):
            if source_version_id is None:
                continue
            session.add(
                PublishedSourceDependencyRow(
                    job_id=job_id,
                    source_version_id=source_version_id,
                    rlo_id=rlo_id,
                    rlo_version=rlo_version,
                    published_at=now,
                )
            )
    return published


def published_dependencies(source_version_id: str) -> list[dict]:
    with get_session() as session:
        rows = session.scalars(
            select(PublishedSourceDependencyRow).where(
                PublishedSourceDependencyRow.source_version_id == source_version_id
            )
        ).all()
        return [
            {
                "job_id": row.job_id,
                "rlo_id": row.rlo_id,
                "rlo_version": row.rlo_version,
                "published_at": row.published_at.isoformat(),
            }
            for row in rows
        ]


def source_has_published_dependencies(source_id: str) -> bool:
    with get_session() as session:
        return (
            session.scalar(
                select(PublishedSourceDependencyRow.job_id)
                .join(
                    SourceVersionRow,
                    SourceVersionRow.source_version_id
                    == PublishedSourceDependencyRow.source_version_id,
                )
                .where(SourceVersionRow.source_id == source_id)
                .limit(1)
            )
            is not None
        )


def load_source_materials(candidate) -> list:
    """Load exact immutable extraction artifacts for a selected objective."""

    version_ids = list(dict.fromkeys(item.source_version_id for item in candidate.evidence))
    return _load_source_versions(version_ids)


def load_collection_source_materials(collection_id: str) -> list:
    """Load every immutable extraction in an objective package's source collection."""

    from src.source_ingestion.repository import get_source_collection

    collection = get_source_collection(collection_id)
    if collection is None:
        raise ValueError("source collection does not exist")
    return _load_source_versions(
        [member.source_version_id for member in collection.members]
    )


def _load_source_versions(version_ids: list[str]) -> list:
    """Load and checksum exact extracted documents for the supplied versions."""

    from .drafting import DraftSourceMaterial

    storage = get_storage()
    materials = []
    with get_session() as session:
        for source_version_id in version_ids:
            version = session.get(SourceVersionRow, source_version_id)
            if version is None:
                raise ValueError(f"source version '{source_version_id}' does not exist")
            source = session.get(SourceDocumentRow, version.source_id)
            run = session.scalar(
                select(SourceProcessingRunRow)
                .where(
                    SourceProcessingRunRow.source_version_id == source_version_id,
                    SourceProcessingRunRow.status == "ready",
                    SourceProcessingRunRow.artifact_manifest_object_key.is_not(None),
                )
                .order_by(SourceProcessingRunRow.attempt.desc())
                .limit(1)
            )
            if run is None:
                raise ValueError(f"source version '{source_version_id}' has no ready extraction")
            manifest = ArtifactManifest.model_validate_json(
                storage.get(run.artifact_manifest_object_key)
            )
            document_entry = next(
                (entry for entry in manifest.artifacts if entry.kind == "document"), None
            )
            if document_entry is None:
                raise ValueError(f"source version '{source_version_id}' has no document artifact")
            body = storage.get(document_entry.object_key)
            if hashlib.sha256(body).hexdigest() != document_entry.sha256:
                raise ValueError("extracted document artifact checksum mismatch")
            segments_entry = next(
                (entry for entry in manifest.artifacts if entry.kind == "segments"), None
            )
            segments = None
            if segments_entry is not None:
                segments_body = storage.get(segments_entry.object_key)
                if hashlib.sha256(segments_body).hexdigest() != segments_entry.sha256:
                    raise ValueError("source segment artifact checksum mismatch")
                segments = [
                    SourceSegment.model_validate(item)
                    for item in json.loads(segments_body)
                ]
            materials.append(
                DraftSourceMaterial(
                    source_id=version.source_id,
                    source_version_id=source_version_id,
                    title=source.title,
                    filename=version.original_filename,
                    checksum=version.checksum,
                    document=ExtractedDocument.model_validate_json(body),
                    segments=segments,
                )
            )
    return materials
