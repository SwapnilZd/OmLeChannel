"""Contracts for grounded RLO drafting and instructional-designer review."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator
from rlo_schema import Evidence, RLO, Source

from src.source_ingestion.contracts import StrictModel

from .contracts import LearningBrief, ObjectiveCandidate, SourceFeature
from .authoring_contracts import (
    AuthoringFinding,
    AuthoringRLORevision,
    ClaimKnowledgeOrigin,
    ElementOrigin,
    GuidanceAssessment,
)


class RLODraftState(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    MAPPING_SOURCE = "mapping_source"
    ENRICHING_KNOWLEDGE = "enriching_knowledge"
    GENERATING_PARTS = "generating_parts"
    ASSEMBLING = "assembling"
    VALIDATING = "validating"
    REPAIRING = "repairing"
    SOURCE_INSUFFICIENT = "source_insufficient"
    # Legacy prototype rows remain readable.
    GENERATING = "generating"
    VALIDATION_FAILED = "validation_failed"
    IN_REVIEW = "in_review"
    REVISION_REQUESTED = "revision_requested"
    REJECTED = "rejected"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    REQUEST_REVISION = "request_revision"
    REJECT = "reject"


class RLODraftRequest(StrictModel):
    workspace_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=1)
    candidate_id: str = Field(min_length=1)
    rlo_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    rlo_version: str = Field(min_length=1, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")


class DraftValidationFinding(StrictModel):
    code: str = Field(min_length=1)
    severity: Literal["warning", "error", "escalate"]
    category: Literal["schema", "grounding", "pedagogy", "classification"]
    path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    repairable: bool = False


class RLOReviewRequest(StrictModel):
    action: ReviewAction
    note: str | None = None
    authoring_sme: str | None = None
    signoff_authority: str | None = None


class RLOReviewRecord(StrictModel):
    revision: int = Field(ge=1)
    action: ReviewAction
    note: str | None = None
    reviewer: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)


class RLORevisionAction(StrEnum):
    REPAIR_CONTENT = "repair_content"
    REPAIR_ASSESSMENT = "repair_assessment"
    REPAIR_PROVENANCE = "repair_provenance"


class RLORevisionPlanRequest(StrictModel):
    action: RLORevisionAction
    selected_finding_ids: list[str] = Field(min_length=1)
    instruction: str | None = None

    @model_validator(mode="after")
    def finding_ids_are_unique(self):
        if len(self.selected_finding_ids) != len(set(self.selected_finding_ids)):
            raise ValueError("selected finding IDs must be unique")
        return self


class RLORevisionPlan(StrictModel):
    action: RLORevisionAction
    selected_finding_ids: list[str] = Field(min_length=1)
    affected_parts: list[str] = Field(default_factory=list)
    affected_element_ids: list[str] = Field(default_factory=list)
    required_validator: Literal["pedagogy", "provenance"]
    maximum_model_calls: Literal[2] = 2
    reused_operations: list[str] = Field(default_factory=list)
    executable: bool
    stop_reason: str | None = None


class RLORevisionFindingOption(StrictModel):
    finding_id: str = Field(min_length=12)
    code: str = Field(min_length=1)
    severity: Literal["warning", "error", "escalate"]
    message: str = Field(min_length=1)
    action: RLORevisionAction | None = None
    affected_parts: list[str] = Field(default_factory=list)
    affected_element_ids: list[str] = Field(default_factory=list)
    executable: bool = False
    stop_reason: str | None = None


class RLORevisionSubmission(RLORevisionPlanRequest):
    maximum_model_calls: int = Field(ge=1, le=3)


class RLOPendingRevision(StrictModel):
    revision_id: str = Field(min_length=1)
    plan: RLORevisionPlan
    instruction: str | None = None
    reviewer: str = Field(min_length=1)
    requested_at: str = Field(min_length=1)
    base_state: RLODraftState


class RLORevisionRecord(StrictModel):
    revision_id: str = Field(min_length=1)
    action: RLORevisionAction
    selected_finding_ids: list[str] = Field(min_length=1)
    affected_element_ids: list[str] = Field(min_length=1)
    maximum_model_calls: int = Field(ge=1)
    actual_model_calls: int = Field(ge=0)
    usage: dict = Field(default_factory=dict)
    status: Literal["completed", "no_change", "failed"]
    stop_reason: str | None = None
    resolved_finding_ids: list[str] = Field(default_factory=list)
    repeated_finding_ids: list[str] = Field(default_factory=list)
    requested_by: str = Field(min_length=1)
    requested_at: str = Field(min_length=1)
    completed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def stopped_revisions_explain_why(self):
        if self.status != "completed" and not self.stop_reason:
            raise ValueError("a stopped revision requires a stop reason")
        return self


class RLODraftSnapshot(StrictModel):
    schema_version: Literal["source-rlo-draft-snapshot-v1"] = (
        "source-rlo-draft-snapshot-v1"
    )
    candidate: ObjectiveCandidate
    learning_brief: LearningBrief
    sources: list[Source] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    evidence_nodes: list[dict] = Field(min_length=1)
    source_features: list[SourceFeature] = Field(default_factory=list)
    prompt_version: str = Field(min_length=1)
    model_aliases: list[str] = Field(min_length=1)


class RLODraftJob(StrictModel):
    schema_version: Literal["source-rlo-draft-job-v1"] = "source-rlo-draft-job-v1"
    job_id: str = Field(min_length=1)
    batch_id: str | None = None
    objective_job_id: str | None = None
    state: RLODraftState
    request: RLODraftRequest
    created_by: str | None = None
    revision: int = Field(default=0, ge=0)
    snapshot: RLODraftSnapshot | None = None
    draft: RLO | None = None
    authoring: AuthoringRLORevision | None = None
    findings: list[DraftValidationFinding] = Field(default_factory=list)
    reviews: list[RLOReviewRecord] = Field(default_factory=list)
    pending_revision: RLOPendingRevision | None = None
    revision_history: list[RLORevisionRecord] = Field(default_factory=list)
    model_metadata: dict = Field(default_factory=dict)
    published_rlo_id: str | None = None
    published_rlo_version: str | None = None
    error_message: str | None = None
    current_operation: str | None = None
    completed_operations: int = Field(default=0, ge=0)
    attempt: int = Field(default=0, ge=0)
    retryable: bool | None = None


class RLOContentProvenanceSummary(StrictModel):
    source_supported_claims: int = Field(ge=0)
    source_synthesis_claims: int = Field(ge=0)
    llm_domain_claims: int = Field(ge=0)
    instructional_scaffold_elements: int = Field(ge=0)
    llm_backed_assessment_ids: list[str] = Field(default_factory=list)
    llm_provenance_records: int = Field(ge=0)


class RLOInstructionalApproachSummary(StrictModel):
    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    bloom_level: str = Field(min_length=1)
    intent: str
    guidance_assessments: list[GuidanceAssessment] = Field(default_factory=list)


class RLOReviewMetadata(StrictModel):
    schema_version: Literal["source-rlo-review-metadata-v2"] = (
        "source-rlo-review-metadata-v2"
    )
    job_id: str = Field(min_length=1)
    rlo_id: str = Field(min_length=1)
    rlo_version: str = Field(min_length=1)
    authoring_revision_id: str = Field(min_length=1)
    state: RLODraftState
    content_provenance: RLOContentProvenanceSummary
    instructional_approach: RLOInstructionalApproachSummary
    reviews: list[RLOReviewRecord] = Field(default_factory=list)


def summarize_content_provenance(
    authoring: AuthoringRLORevision,
) -> RLOContentProvenanceSummary:
    llm_claim_ids = {
        claim.claim_id
        for claim in authoring.claims
        if claim.knowledge_origin == ClaimKnowledgeOrigin.LLM_DOMAIN
    }
    llm_backed_assessment_ids = [
        element.element_id
        for part in authoring.parts
        for element in part.elements
        if element.assessment is not None
        and bool(llm_claim_ids.intersection(element.claim_refs))
    ]
    return RLOContentProvenanceSummary(
        source_supported_claims=sum(
            claim.knowledge_origin == ClaimKnowledgeOrigin.SOURCE_DIRECT
            for claim in authoring.claims
        ),
        source_synthesis_claims=sum(
            claim.knowledge_origin == ClaimKnowledgeOrigin.SOURCE_SYNTHESIS
            for claim in authoring.claims
        ),
        llm_domain_claims=len(llm_claim_ids),
        instructional_scaffold_elements=sum(
            element.origin == ElementOrigin.INSTRUCTIONAL_SCAFFOLD
            for part in authoring.parts
            for element in part.elements
        ),
        llm_backed_assessment_ids=llm_backed_assessment_ids,
        llm_provenance_records=len(authoring.llm_knowledge_provenance),
    )


class RLOGenerationBatchState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    IN_REVIEW = "in_review"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


class RLOGenerationBatch(StrictModel):
    schema_version: Literal["source-rlo-generation-batch-v1"] = (
        "source-rlo-generation-batch-v1"
    )
    batch_id: str = Field(min_length=1)
    objective_job_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=1)
    collection_id: str = Field(min_length=1)
    state: RLOGenerationBatchState
    finalized: bool = False
    child_job_ids: list[str] = Field(default_factory=list)
    findings: list[AuthoringFinding] = Field(default_factory=list)
    collection_validation_started_at: str | None = None
    collection_validated_at: str | None = None
    created_by: str | None = None
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class RLOGenerationCheckpoint(StrictModel):
    job_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    input_hash: str = Field(min_length=64, max_length=64)
    payload: dict
    created_at: str = Field(min_length=1)


class RLOGenerationPromptRun(StrictModel):
    prompt_run_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    prompt_filename: str = Field(min_length=1)
    prompt_snapshot: str = Field(min_length=1)
    model_alias: str = Field(min_length=1)
    input_snapshot: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)
    output_snapshot: str = Field(min_length=1)
    usage: dict = Field(default_factory=dict)
    created_at: str = Field(min_length=1)


class DraftReviewResult(StrictModel):
    findings: list[DraftValidationFinding] = Field(default_factory=list)
