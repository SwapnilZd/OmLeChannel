"""Strict contracts for source-grounded seven-part RLO authoring."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator
from rlo_schema import Evidence, Source
from rlo_schema.v1 import AssessmentType, BloomLevel, ContentType

from src.source_ingestion.contracts import StrictModel


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ElementOrigin(StrEnum):
    SOURCE = "source"
    MIXED = "mixed"
    LLM_DOMAIN = "llm_domain"
    INSTRUCTIONAL_SCAFFOLD = "instructional_scaffold"
    # Legacy prototype payloads remain readable.
    GENERATED = "generated"


class ClaimKnowledgeOrigin(StrEnum):
    SOURCE_DIRECT = "source_direct"
    SOURCE_SYNTHESIS = "source_synthesis"
    LLM_DOMAIN = "llm_domain"


class ClaimVerificationStatus(StrEnum):
    SOURCE_VERIFIED = "source_verified"
    UNVERIFIED = "unverified"
    REVIEW_ACCEPTED = "review_accepted"


class PartStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSENT = "absent"
    SOURCE_INSUFFICIENT = "source_insufficient"


class RLOPartKind(StrEnum):
    COVER = "cover"
    SETUP = "setup"
    TEACH = "teach"
    SHOW = "show"
    PRACTICE = "practice"
    CHECK = "check"
    SEND_OFF = "send_off"


PART_ORDER = tuple(RLOPartKind)


class GuidancePriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GuidanceStatus(StrEnum):
    ACHIEVED = "achieved"
    APPROXIMATED = "approximated"
    MISSED = "missed"
    NOT_APPLICABLE = "not_applicable"


class AuthoringElementType(StrEnum):
    METADATA = "metadata"
    HOOK = "hook"
    OBJECTIVE_PRESENTATION = "objective_presentation"
    PRIOR_KNOWLEDGE = "prior_knowledge"
    DEFINITION = "definition"
    EXPLANATION = "explanation"
    STEP = "step"
    DECISION = "decision"
    WORKED_EXAMPLE = "worked_example"
    PRACTICE_ITEM = "practice_item"
    ASSESSMENT_ITEM = "assessment_item"
    FEEDBACK = "feedback"
    TRANSFER_PROMPT = "transfer_prompt"
    RELATIONSHIP = "relationship"


class ClassificationDecision(StrictModel):
    content_type: ContentType
    bloom_level: BloomLevel
    confidence: Confidence
    rationale: str = Field(min_length=1)
    provisional: bool = False
    escalation_required: bool = False
    alternatives: list[str] = Field(default_factory=list)
    discriminator_question: str | None = None

    @model_validator(mode="after")
    def escalation_has_guidance(self) -> "ClassificationDecision":
        if self.escalation_required and (
            not self.alternatives or not self.discriminator_question
        ):
            raise ValueError(
                "an escalated classification requires alternatives and a discriminator question"
            )
        return self


class RLOClassifications(StrictModel):
    suggested: ClassificationDecision | None = None
    target: ClassificationDecision
    observed: ClassificationDecision | None = None


class MethodologyRequirement(StrictModel):
    requirement_id: str = Field(min_length=1)
    part: RLOPartKind
    description: str = Field(min_length=1)
    substantive: bool = True


class MethodologyGuidance(StrictModel):
    guidance_id: str = Field(min_length=1)
    part: RLOPartKind
    priority: GuidancePriority
    instruction: str = Field(min_length=1)
    preferred_shape: dict[str, Any] | None = None
    acceptable_approximation: str | None = None


class MethodologyProfile(StrictModel):
    profile_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_type: ContentType
    bloom_level: BloomLevel
    requirements: list[MethodologyRequirement] = Field(min_length=1)
    intent: str = ""
    guidance: list[MethodologyGuidance] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    review_dimensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def guidance_ids_are_unique(self) -> "MethodologyProfile":
        ids = [item.guidance_id for item in self.guidance]
        if len(ids) != len(set(ids)):
            raise ValueError("methodology guidance IDs must be unique")
        return self

    def guidance_for(self, *parts: RLOPartKind) -> list[MethodologyGuidance]:
        selected = set(parts)
        return [item for item in self.guidance if item.part in selected]


class AuthoringObjective(StrictModel):
    candidate_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    performance_context: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class AuthoringClaim(StrictModel):
    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    source_claim_refs: list[str] = Field(default_factory=list)
    knowledge_origin: ClaimKnowledgeOrigin = ClaimKnowledgeOrigin.SOURCE_DIRECT
    verification_status: ClaimVerificationStatus = ClaimVerificationStatus.SOURCE_VERIFIED
    llm_provenance_ref: str | None = None
    origin_rationale: str | None = None
    role: Literal["objective_defining", "supporting_context"]
    assessment_eligible: bool
    requirement_refs: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def context_is_not_assessable(self) -> "AuthoringClaim":
        if self.role == "supporting_context" and self.assessment_eligible:
            raise ValueError("supporting context cannot define an assessment answer")
        if self.knowledge_origin == ClaimKnowledgeOrigin.SOURCE_DIRECT:
            if not self.evidence_refs:
                raise ValueError("source-direct claims require evidence")
            if self.verification_status != ClaimVerificationStatus.SOURCE_VERIFIED:
                raise ValueError("source-direct claims must be source verified")
        elif self.knowledge_origin == ClaimKnowledgeOrigin.SOURCE_SYNTHESIS:
            if not self.evidence_refs or not self.source_claim_refs:
                raise ValueError("source synthesis requires source claims and evidence")
            if not self.origin_rationale:
                raise ValueError("source synthesis requires a derivation rationale")
        else:
            if self.evidence_refs:
                raise ValueError("LLM-domain claims cannot claim source evidence")
            if not self.llm_provenance_ref or not self.origin_rationale:
                raise ValueError("LLM-domain claims require provenance and rationale")
            if self.verification_status == ClaimVerificationStatus.SOURCE_VERIFIED:
                raise ValueError("LLM-domain claims cannot be source verified")
        return self


class AuthoringAssessmentOption(StrictModel):
    text: str = Field(min_length=1)
    correct: bool
    feedback: str = Field(min_length=1)
    claim_refs: list[str] = Field(default_factory=list)


class AuthoringAssessment(StrictModel):
    stem: str = Field(min_length=1)
    type: AssessmentType
    options: list[AuthoringAssessmentOption] | None = None
    correct_response: str | None = None
    scoring_criteria: str | None = None
    feedback_guidance: str | None = None
    claim_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_shape(self) -> "AuthoringAssessment":
        if self.type in {
            AssessmentType.MULTIPLE_CHOICE_SINGLE,
            AssessmentType.MULTIPLE_CHOICE_MULTI,
        }:
            if not self.options or len(self.options) < 2:
                raise ValueError("multiple-choice authoring items require at least two options")
            correct = sum(option.correct for option in self.options)
            if correct == 0:
                raise ValueError("multiple-choice authoring items require a correct option")
            if self.type == AssessmentType.MULTIPLE_CHOICE_SINGLE and correct != 1:
                raise ValueError("single-answer items require exactly one correct option")
        elif not self.correct_response:
            raise ValueError("open-response authoring items require a correct response")
        return self


class AuthoringElement(StrictModel):
    element_id: str = Field(min_length=1)
    element_type: AuthoringElementType
    content: str | dict[str, Any] | list[Any] | None = None
    assessment: AuthoringAssessment | None = None
    origin: ElementOrigin
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    generation_note: str | None = None
    requirement_refs: list[str] = Field(default_factory=list)
    guidance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_matches_type(self) -> "AuthoringElement":
        assessment_type = self.element_type in {
            AuthoringElementType.PRACTICE_ITEM,
            AuthoringElementType.ASSESSMENT_ITEM,
        }
        if assessment_type != (self.assessment is not None):
            raise ValueError("practice and assessment elements require assessment content only")
        if not assessment_type and self.content is None:
            raise ValueError("non-assessment elements require content")
        if self.origin != ElementOrigin.SOURCE and not self.generation_note:
            raise ValueError("mixed and generated elements require a generation note")
        return self


class AuthoringPart(StrictModel):
    kind: RLOPartKind
    ordinal: int = Field(ge=1, le=7)
    status: PartStatus
    requirement_refs: list[str] = Field(default_factory=list)
    elements: list[AuthoringElement] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class RLORelationships(StrictModel):
    prerequisites: list[str] = Field(default_factory=list)
    corequisites: list[str] = Field(default_factory=list)
    follow_ons: list[str] = Field(default_factory=list)
    related_rlos: list[str] = Field(default_factory=list)


class AuthoringFinding(StrictModel):
    code: str = Field(min_length=1)
    severity: Literal["warning", "error", "escalate"]
    category: Literal["schema", "grounding", "pedagogy", "classification"]
    path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    repairable: bool = False


class GuidanceAssessment(StrictModel):
    guidance_id: str = Field(min_length=1)
    status: GuidanceStatus
    explanation: str = Field(min_length=1)
    affected_paths: list[str] = Field(default_factory=list)


class GenerationProvenance(StrictModel):
    rules_version: str = Field(min_length=1)
    authoring_schema_version: str = Field(min_length=1)
    methodology_profile_id: str = Field(min_length=1)
    methodology_profile_version: str = Field(min_length=1)
    operation_ids: list[str] = Field(default_factory=list)


class LLMKnowledgeProvenance(StrictModel):
    provenance_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    model_alias: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_filename: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=1)
    input_sha256: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    verification_notice: str = (
        "Model provenance records origin and does not establish factual correctness."
    )


class AuthoringRLORevision(StrictModel):
    schema_version: Literal[
        "source-rlo-authoring-v1", "source-rlo-authoring-v2", "source-rlo-authoring-v3"
    ] = "source-rlo-authoring-v3"
    rlo_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$")
    revision: int = Field(ge=1)
    title: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    estimated_duration_minutes: int = Field(ge=1)
    objective: AuthoringObjective
    broader_outcome: str | None = None
    classifications: RLOClassifications
    methodology_profile: MethodologyProfile
    sources: list[Source] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    claims: list[AuthoringClaim] = Field(min_length=1)
    llm_knowledge_provenance: list[LLMKnowledgeProvenance] = Field(default_factory=list)
    parts: list[AuthoringPart] = Field(min_length=7, max_length=7)
    relationships: RLORelationships = Field(default_factory=RLORelationships)
    findings: list[AuthoringFinding] = Field(default_factory=list)
    guidance_assessments: list[GuidanceAssessment] = Field(default_factory=list)
    provenance: GenerationProvenance
    authoring_revision_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def reference_integrity(self) -> "AuthoringRLORevision":
        if tuple(part.kind for part in self.parts) != PART_ORDER:
            raise ValueError("authoring parts must occur exactly once in canonical order")
        if [part.ordinal for part in self.parts] != list(range(1, 8)):
            raise ValueError("authoring part ordinals must be 1 through 7")
        evidence_ids = {item.id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")
        claim_by_id = {item.claim_id: item for item in self.claims}
        if len(claim_by_id) != len(self.claims):
            raise ValueError("claim IDs must be unique")
        provenance_ids = {
            item.provenance_id for item in self.llm_knowledge_provenance
        }
        if len(provenance_ids) != len(self.llm_knowledge_provenance):
            raise ValueError("LLM provenance IDs must be unique")
        requirement_ids = {
            item.requirement_id for item in self.methodology_profile.requirements
        }
        guidance_ids = {
            item.guidance_id for item in self.methodology_profile.guidance
        }
        if (
            self.methodology_profile.content_type
            != self.classifications.target.content_type
            or self.methodology_profile.bloom_level
            != self.classifications.target.bloom_level
        ):
            raise ValueError("methodology profile must match the target classification")
        for ref in self.objective.evidence_refs:
            if ref not in evidence_ids:
                raise ValueError(f"objective references unknown evidence '{ref}'")
        for claim in self.claims:
            if not set(claim.evidence_refs) <= evidence_ids:
                raise ValueError(f"claim {claim.claim_id} references unknown evidence")
            if not set(claim.requirement_refs) <= requirement_ids:
                raise ValueError(f"claim {claim.claim_id} references unknown requirement")
            if not set(claim.source_claim_refs) <= claim_by_id.keys():
                raise ValueError(f"claim {claim.claim_id} references unknown source claims")
            if claim.claim_id in claim.source_claim_refs:
                raise ValueError(f"claim {claim.claim_id} cannot derive from itself")
            if claim.llm_provenance_ref and claim.llm_provenance_ref not in provenance_ids:
                raise ValueError(f"claim {claim.claim_id} references unknown LLM provenance")
        element_ids: set[str] = set()
        for part in self.parts:
            if not set(part.requirement_refs) <= requirement_ids:
                raise ValueError(f"part {part.kind} references unknown requirement")
            for element in part.elements:
                if element.element_id in element_ids:
                    raise ValueError("element IDs must be unique")
                element_ids.add(element.element_id)
                if not set(element.claim_refs) <= claim_by_id.keys():
                    raise ValueError(f"element {element.element_id} references unknown claim")
                derived_evidence = {
                    ref for claim_ref in element.claim_refs
                    for ref in claim_by_id[claim_ref].evidence_refs
                }
                if not set(element.evidence_refs) <= evidence_ids:
                    raise ValueError(f"element {element.element_id} references unknown evidence")
                if element.claim_refs and not set(element.evidence_refs) <= derived_evidence:
                    raise ValueError(
                        f"element {element.element_id} evidence is not supported by its claims"
                    )
                if not set(element.requirement_refs) <= requirement_ids:
                    raise ValueError(f"element {element.element_id} references unknown requirement")
                if not set(element.guidance_refs) <= guidance_ids:
                    raise ValueError(f"element {element.element_id} references unknown guidance")
                if element.assessment:
                    refs = [
                        *element.assessment.claim_refs,
                        *(ref for option in element.assessment.options or [] for ref in option.claim_refs),
                    ]
                    if not set(refs) <= set(element.claim_refs):
                        raise ValueError(
                            f"assessment element {element.element_id} must expose all "
                            "assessment claim references on the containing element"
                        )
                    for ref in refs:
                        claim = claim_by_id.get(ref)
                        if claim is None:
                            raise ValueError(
                                f"assessment element {element.element_id} references unknown claim"
                            )
                        if not claim.assessment_eligible:
                            raise ValueError(
                                f"assessment element {element.element_id} uses supporting context"
                            )
        assessed_guidance = [item.guidance_id for item in self.guidance_assessments]
        if len(assessed_guidance) != len(set(assessed_guidance)):
            raise ValueError("guidance assessments must be unique")
        if not set(assessed_guidance) <= guidance_ids:
            raise ValueError("guidance assessment references unknown guidance")
        return self
