"""Structured model outputs for seven-part RLO generation operations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from rlo_schema.v1 import AssessmentType

from src.source_ingestion.contracts import StrictModel

from .cell_scope import is_poc2_cell
from .authoring_contracts import (
    AuthoringAssessment,
    AuthoringElementType,
    AuthoringFinding,
    ClassificationDecision,
    GuidanceAssessment,
    PartStatus,
    RLOPartKind,
    RLORelationships,
)


class TargetPlanDraft(StrictModel):
    classification: ClassificationDecision
    relationship_candidate_ids: RLORelationships = Field(default_factory=RLORelationships)
    planning_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def target_is_in_poc2_scope(self):
        if not is_poc2_cell(
            self.classification.content_type, self.classification.bloom_level
        ):
            raise ValueError("target classification is outside the five POC2 cells")
        return self


class NodeCitationDraft(StrictModel):
    source_version_id: str = Field(min_length=1)
    segment_ids: list[str] = Field(min_length=1)


class MappedClaimDraft(StrictModel):
    local_ref: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    citations: list[NodeCitationDraft] = Field(min_length=1)
    role: str = Field(pattern="^(objective_defining|supporting_context)$")
    assessment_eligible: bool
    requirement_refs: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def supporting_context_is_not_assessable(self) -> "MappedClaimDraft":
        if self.role == "supporting_context" and self.assessment_eligible:
            raise ValueError("supporting context cannot be assessment eligible")
        return self


class RequirementCoverageDraft(StrictModel):
    requirement_id: str = Field(min_length=1)
    status: PartStatus
    claim_refs: list[str] = Field(default_factory=list)
    gap: str | None = None


class SourceMapDraft(StrictModel):
    claims: list[MappedClaimDraft] = Field(default_factory=list)
    coverage: list[RequirementCoverageDraft] = Field(default_factory=list)
    rejected_segment_ids: list[str] = Field(default_factory=list)


class MappingChallengeDraft(StrictModel):
    downgrade_requirement_ids: list[str] = Field(default_factory=list)
    missed_requirement_ids: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class LLMEnrichmentClaimDraft(StrictModel):
    local_ref: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    role: str = Field(pattern="^(objective_defining|supporting_context)$")
    assessment_eligible: bool
    requirement_refs: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    origin_rationale: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def supporting_context_is_not_assessable(cls, value):
        if (
            isinstance(value, dict)
            and value.get("role") == "supporting_context"
            and value.get("assessment_eligible") is True
        ):
            return {**value, "assessment_eligible": False}
        return value


class LLMEnrichmentDraft(StrictModel):
    claims: list[LLMEnrichmentClaimDraft] = Field(default_factory=list)
    unresolved_gaps: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class GeneratedAssessment(AuthoringAssessment):
    """Closed-response assessment shape supported by generated RLOs."""

    type: Literal[
        AssessmentType.MULTIPLE_CHOICE_SINGLE,
        AssessmentType.MULTIPLE_CHOICE_MULTI,
    ]


class GeneratedElementDraft(StrictModel):
    part: RLOPartKind
    element_type: AuthoringElementType
    content: str | None = None
    assessment: GeneratedAssessment | None = None
    claim_refs: list[str] = Field(default_factory=list)
    requirement_refs: list[str] = Field(default_factory=list)
    guidance_refs: list[str] = Field(default_factory=list)
    generation_note: str = Field(min_length=1)
    replace_element_id: str | None = None

    @model_validator(mode="after")
    def valid_content(self) -> "GeneratedElementDraft":
        assessment_type = self.element_type in {
            AuthoringElementType.PRACTICE_ITEM,
            AuthoringElementType.ASSESSMENT_ITEM,
        }
        if assessment_type != (self.assessment is not None):
            raise ValueError("practice/check drafts require assessment content only")
        if not assessment_type and self.content is None:
            raise ValueError("generated element requires content")
        return self


class PartGenerationDraft(StrictModel):
    elements: list[GeneratedElementDraft] = Field(default_factory=list)
    source_insufficient: bool = False
    insufficiency_reason: str | None = None


class AuthoringReviewDraft(StrictModel):
    findings: list[AuthoringFinding] = Field(default_factory=list)
    observed_classification: ClassificationDecision | None = None
    guidance_assessments: list[GuidanceAssessment] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def preserve_outside_scope_observation_as_finding(cls, value):
        if not isinstance(value, dict):
            return value
        observed = value.get("observed_classification")
        if observed is None:
            return value
        if isinstance(observed, ClassificationDecision):
            kind = observed.content_type.value
            bloom = observed.bloom_level.value
        elif isinstance(observed, dict):
            kind = str(observed.get("content_type", ""))
            bloom = str(observed.get("bloom_level", ""))
        else:
            return value
        if is_poc2_cell(kind, bloom):
            return value
        finding = {
            "code": "target_observed_mismatch",
            "severity": "error",
            "category": "classification",
            "path": "classifications.observed",
            "message": (
                f"The reviewer observed {kind} × {bloom}, which is outside the five "
                "POC2 cells. The RLO must remain within its approved Target cell."
            ),
            "repairable": False,
        }
        return {
            **value,
            "observed_classification": None,
            "findings": [*value.get("findings", []), finding],
        }


class CollectionReviewDraft(StrictModel):
    findings: list[AuthoringFinding] = Field(default_factory=list)
