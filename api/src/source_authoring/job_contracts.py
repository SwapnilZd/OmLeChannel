"""Contracts for durable learning-objective extraction jobs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from src.source_ingestion.contracts import StrictModel

from .contracts import ObjectiveDecisionStatus, PractitionerInstructions


class ObjectiveJobStage(StrEnum):
    DRAFT = "draft"
    OBJECTIVE_REVIEW = "objective_review"
    # Retained only so existing POC rows remain readable after the workflow change.
    OBJECTIVES_APPROVED = "objectives_approved"
    DETAIL_ENRICHMENT = "detail_enrichment"
    DETAIL_REVIEW = "detail_review"
    DETAILS_APPROVED = "details_approved"
    COMPLETE = "complete"


class ObjectiveProcessingStatus(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ObjectiveReviewKind(StrEnum):
    OBJECTIVE = "objective"
    DETAIL = "detail"  # Legacy POC audit rows remain readable; new reviews cannot use it.


class ObjectiveJob(StrictModel):
    job_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    collection_id: str = Field(min_length=1)
    workspace_id: str | None = None
    workspace_revision: int | None = Field(default=None, ge=1)
    workflow_stage: ObjectiveJobStage
    processing_status: ObjectiveProcessingStatus
    instructions: PractitionerInstructions | None = None
    created_by: str | None = None
    attempt: int = Field(ge=1)
    retryable: bool | None = None
    error_message: str | None = None
    current_operation: str | None = None
    completed_operations: int = Field(default=0, ge=0)
    progress_detail: dict = Field(default_factory=dict)
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ObjectiveJobEvent(StrictModel):
    event_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    from_stage: ObjectiveJobStage | None = None
    to_stage: ObjectiveJobStage | None = None
    actor: str | None = None
    note: str | None = None
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class ObjectiveJobReview(StrictModel):
    review_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=1)
    candidate_id: str = Field(min_length=1)
    review_kind: ObjectiveReviewKind
    status: ObjectiveDecisionStatus
    note: str | None = None
    decided_by: str = Field(min_length=1)
    created_at: datetime


class PromptRun(StrictModel):
    prompt_run_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    prompt_filename: str = Field(min_length=1)
    prompt_snapshot: str = Field(min_length=1)
    model_alias: str = Field(min_length=1)
    input_sha256: str = Field(min_length=64, max_length=64)
    input_snapshot: str = Field(min_length=1)
    input_artifact_ref: str | None = None
    output_schema: str = Field(min_length=1)
    created_at: datetime
