"""Immutable contracts for self-service learning commissioning."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, computed_field, model_validator

from learning_pipeline.contracts.common import (
    Modality,
    PROFICIENCY_ORDER,
    FrozenModel,
    TopicProficiency,
)

DeloitteLevel = Literal[25, 35, 45, 55, 65]


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must contain unique values")
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain blank values")


class AudienceProfile(FrozenModel):
    """Available learner attributes used to tailor discovery and generation."""

    roles: tuple[str, ...] = ()
    deloitte_levels: tuple[DeloitteLevel, ...] = ()
    current_proficiency: TopicProficiency
    target_proficiency: TopicProficiency
    industries: tuple[str, ...] = ()
    service_lines: tuple[str, ...] = ()
    business_context: dict[str, str] = Field(default_factory=dict)
    language: str = Field(default="en", min_length=2)
    locale: str = Field(default="en-US", min_length=2)

    @model_validator(mode="after")
    def _validate(self) -> "AudienceProfile":
        for name in ("roles", "industries", "service_lines"):
            _require_unique(getattr(self, name), name)
        if len(self.deloitte_levels) != len(set(self.deloitte_levels)):
            raise ValueError("deloitte_levels must contain unique values")
        if PROFICIENCY_ORDER[self.target_proficiency] < PROFICIENCY_ORDER[self.current_proficiency]:
            raise ValueError("target_proficiency cannot be below current_proficiency")
        if any(not key.strip() or not value.strip() for key, value in self.business_context.items()):
            raise ValueError("business_context keys and values must not be blank")
        return self


class LearningCommissionRequest(FrozenModel):
    """Authoritative input supplied by a learning requester."""

    request_id: str = Field(min_length=1)
    request_text: str = Field(min_length=1)
    audience: AudienceProfile
    stated_goals: tuple[str, ...] = ()
    duration_limit_minutes: int | None = Field(default=None, gt=0)
    required_rlo_ids: tuple[str, ...] = ()
    excluded_rlo_ids: tuple[str, ...] = ()
    minimum_target_proficiency: TopicProficiency | None = None
    brand_contract: dict[str, str] = Field(default_factory=dict)
    industry_filter_mode: Literal["boost", "required"] = "boost"

    @model_validator(mode="after")
    def _validate(self) -> "LearningCommissionRequest":
        if not self.request_id.strip() or not self.request_text.strip():
            raise ValueError("request_id and request_text must not be blank")
        for name in ("stated_goals", "required_rlo_ids", "excluded_rlo_ids"):
            _require_unique(getattr(self, name), name)
        overlap = set(self.required_rlo_ids) & set(self.excluded_rlo_ids)
        if overlap:
            raise ValueError(f"required and excluded RLO IDs cannot overlap: {sorted(overlap)}")
        if (
            self.minimum_target_proficiency is not None
            and PROFICIENCY_ORDER[self.minimum_target_proficiency]
            < PROFICIENCY_ORDER[self.audience.current_proficiency]
        ):
            raise ValueError("minimum_target_proficiency cannot be below current proficiency")
        return self


class LearningSearchIntent(FrozenModel):
    """Validated semantic interpretation; never contains retrieval internals."""

    primary_subject: str = Field(min_length=1)
    requested_modality: Modality | None = None
    subject_facets: tuple[str, ...] = Field(min_length=1, max_length=4)
    skills: tuple[str, ...] = ()
    desired_outcomes: tuple[str, ...] = ()
    required_concepts: tuple[str, ...] = ()
    excluded_concepts: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    search_queries: tuple[str, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _validate(self) -> "LearningSearchIntent":
        if len(self.subject_facets) != len(self.search_queries):
            raise ValueError("subject_facets and search_queries must have the same length")
        for name in (
            "subject_facets",
            "skills",
            "desired_outcomes",
            "required_concepts",
            "excluded_concepts",
            "ambiguities",
            "search_queries",
        ):
            _require_unique(getattr(self, name), name)
        overlap = set(self.required_concepts) & set(self.excluded_concepts)
        if overlap:
            raise ValueError(f"required and excluded concepts cannot overlap: {sorted(overlap)}")
        return self


class SearchInterpretationTrace(FrozenModel):
    request_hash: str = Field(min_length=1)
    intent_hash: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    model: str | None = None
    provider_request_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    warnings: tuple[str, ...] = ()
    fallback_reason: str | None = None


class RelevanceBand(StrEnum):
    STRONG = "strong"
    ACCEPTABLE = "acceptable"
    WEAK = "weak"
    FORBIDDEN = "forbidden"


class RLOCandidateMatch(FrozenModel):
    rlo_id: str = Field(min_length=1)
    rlo_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    level: str = Field(min_length=1)
    estimated_duration_minutes: int = Field(gt=0)
    governance_status: str = Field(min_length=1)
    vector_scores: dict[str, float] = Field(default_factory=dict)
    reciprocal_rank_fusion_score: float = Field(ge=0)
    facet_boost_score: float = 0.0
    final_score: float
    relevance_band: RelevanceBand
    match_reasons: tuple[str, ...] = Field(min_length=1)
    source_query_ids: tuple[str, ...] = Field(min_length=1)
    required_as_prerequisite_for: tuple[str, ...] = ()
    storage_uri: str = Field(min_length=1)
    index_revision: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate(self) -> "RLOCandidateMatch":
        _require_unique(self.match_reasons, "match_reasons")
        _require_unique(self.source_query_ids, "source_query_ids")
        _require_unique(
            self.required_as_prerequisite_for,
            "required_as_prerequisite_for",
        )
        return self


class CurationRecommendation(StrEnum):
    INCLUDE = "include"
    OPTIONAL = "optional"
    EXCLUDE = "exclude"


class CandidateCurationDecision(FrozenModel):
    rlo_id: str = Field(min_length=1)
    rlo_version: str = Field(min_length=1)
    recommendation: CurationRecommendation
    conceptual_framework: str | None = None
    coverage_contribution: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)
    relationship_to_other_candidates: str | None = None


class CandidateCurationReview(FrozenModel):
    strategy_summary: str = Field(min_length=1)
    framework_approach: str = Field(min_length=1)
    decisions: tuple[CandidateCurationDecision, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> "CandidateCurationReview":
        keys = [(decision.rlo_id, decision.rlo_version) for decision in self.decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("curation decision ID/version pairs must be unique")
        return self


class CandidateCurationTrace(FrozenModel):
    prompt_version: str = Field(min_length=1)
    model: str | None = None
    provider_request_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reviewed_candidate_count: int = Field(ge=0)
    fallback_reason: str | None = None


class GapSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class ContentGap(FrozenModel):
    subject: str = Field(min_length=1)
    desired_outcome: str | None = None
    severity: GapSeverity
    explanation: str = Field(min_length=1)
    nearest_candidate_ids: tuple[str, ...] = ()
    filters_responsible: tuple[str, ...] = ()
    recommendation: str = Field(min_length=1)


class ContentGapReport(FrozenModel):
    sufficient: bool
    covered_subject_facets: tuple[str, ...] = ()
    covered_goals: tuple[str, ...] = ()
    gaps: tuple[ContentGap, ...] = ()
    retrieval_policy_version: str = Field(min_length=1)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate(self) -> "ContentGapReport":
        has_blocking = any(gap.severity == GapSeverity.BLOCKING for gap in self.gaps)
        if self.sufficient and has_blocking:
            raise ValueError("a sufficient report cannot contain blocking gaps")
        if not self.sufficient and not has_blocking:
            raise ValueError("an insufficient report must contain at least one blocking gap")
        return self


class LearningRequestPreview(FrozenModel):
    preview_id: str = Field(min_length=1)
    preview_hash: str = Field(min_length=1)
    request: LearningCommissionRequest
    intent: LearningSearchIntent
    candidates: tuple[RLOCandidateMatch, ...]
    gap_report: ContentGapReport
    interpretation_trace: SearchInterpretationTrace
    curation_review: CandidateCurationReview | None = None
    curation_trace: CandidateCurationTrace | None = None
    compatibility_errors: tuple[str, ...] = ()
    retrieval_policy_version: str = Field(min_length=1)
    index_revision: str = Field(min_length=1)
    created_at: datetime

    @computed_field
    @property
    def confirmation_allowed(self) -> bool:
        return self.gap_report.sufficient and any(
            candidate.relevance_band in (RelevanceBand.STRONG, RelevanceBand.ACCEPTABLE)
            for candidate in self.candidates
        )


class RLOCandidateDisposition(StrEnum):
    INCLUDE = "include"
    REQUIRED = "required"
    EXCLUDE = "exclude"


class ConfirmedRLOCandidate(FrozenModel):
    rlo_id: str = Field(min_length=1)
    rlo_version: str = Field(min_length=1)
    disposition: RLOCandidateDisposition


class LearningRequestConfirmation(FrozenModel):
    preview_hash: str = Field(min_length=1)
    confirmed_course_goal: str = Field(min_length=1)
    candidates: tuple[ConfirmedRLOCandidate, ...] = Field(min_length=1)
    confirmation_actor: str = Field(min_length=1)
    requester_notes: str | None = None


class ConfirmedLearningRequest(FrozenModel):
    request_id: str = Field(min_length=1)
    preview_id: str = Field(min_length=1)
    preview_hash: str = Field(min_length=1)
    confirmed_course_goal: str = Field(min_length=1)
    candidates: tuple[ConfirmedRLOCandidate, ...] = Field(min_length=1)
    confirmation_actor: str = Field(min_length=1)
    confirmed_at: datetime
    requester_notes: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ConfirmedLearningRequest":
        keys = [(candidate.rlo_id, candidate.rlo_version) for candidate in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("confirmed candidate ID/version pairs must be unique")
        ids = [candidate.rlo_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("only one version of each RLO may be confirmed")
        if not any(
            candidate.disposition in (RLOCandidateDisposition.INCLUDE, RLOCandidateDisposition.REQUIRED)
            for candidate in self.candidates
        ):
            raise ValueError("at least one candidate must be included or required")
        return self


class CommissioningJobState(StrEnum):
    DRAFT = "draft"
    INTERPRETING = "interpreting"
    RETRIEVING = "retrieving"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    BLOCKED_CONTENT_GAP = "blocked_content_gap"
    QUEUED_FOR_ASSEMBLY = "queued_for_assembly"
    ASSEMBLING_BLUEPRINT = "assembling_blueprint"
    SELECTING_FORMAT = "selecting_format"
    PLANNING_MODALITY = "planning_modality"
    PLANNING_WORKFLOW = "planning_workflow"
    QUEUED_FOR_EXECUTION = "queued_for_execution"
    # Kept for rows produced by the blueprint-only implementation.
    ASSEMBLING = "assembling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CommissioningJobRecord(FrozenModel):
    job_id: str = Field(min_length=1)
    preview_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    confirmed_request_hash: str | None = None
    state: CommissioningJobState
    course_assembly_request_uri: str | None = None
    blueprint_uri: str | None = None
    assembly_report_uri: str | None = None
    planning_trace_uri: str | None = None
    selected_modality: Modality | None = None
    workflow_id: str | None = None
    planning_started_at: datetime | None = None
    execution_submitted_at: datetime | None = None
    error_code: str | None = None
    error_summary: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> "CommissioningJobRecord":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        if self.state == CommissioningJobState.FAILED and not self.error_code:
            raise ValueError("failed jobs require an error_code")
        if self.state != CommissioningJobState.FAILED and self.error_code:
            raise ValueError("only failed jobs may carry an error_code")
        return self


class CommissioningJobView(FrozenModel):
    """Joined, browser-facing view of commissioning and workflow execution."""

    job_id: str
    request_id: str
    course_goal: str
    state: CommissioningJobState
    status: str
    stage_label: str
    selected_modality: Modality | None = None
    workflow_id: str | None = None
    completed_tasks: int = Field(default=0, ge=0)
    total_tasks: int = Field(default=0, ge=0)
    downloadable: bool = False
    blueprint_available: bool = False
    error_summary: str | None = None
    created_at: datetime
    updated_at: datetime
    poll_after_ms: int | None = Field(default=None, ge=250)


class DeliverableDescriptor(FrozenModel):
    deliverable_id: str
    filename: str
    media_type: str
    size_bytes: int | None = Field(default=None, ge=0)
    primary: bool = False
    download_url: str
