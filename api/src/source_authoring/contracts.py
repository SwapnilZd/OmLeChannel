"""Strict contracts for learning briefs and objective-discovery workspaces."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from src.source_ingestion.contracts import StrictModel

from .cell_scope import is_poc2_cell, poc2_scope_reason


class EvidenceRole(StrEnum):
    OBJECTIVE_DEFINING = "objective_defining"
    SUPPORTING_CONTEXT = "supporting_context"
    SOURCE_ANCHOR = "source_anchor"


class ObjectiveDecisionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class ObjectiveOrigin(StrEnum):
    MODEL = "model"
    LDS = "lds"


class ObjectiveDiscoveryBasis(StrEnum):
    SOURCE_DERIVED = "source_derived"
    SOURCE_RELATED = "source_related"


class ObjectiveScopeStatus(StrEnum):
    SUPPORTED = "supported"
    OUTSIDE_POC2_SCOPE = "outside_poc2_scope"
    NEEDS_REVIEW = "needs_review"


class SourceSupportLevel(StrEnum):
    SUBSTANTIAL = "substantial"
    PARTIAL = "partial"
    ANCHOR_ONLY = "anchor_only"


class ObjectiveSupportProfile(StrictModel):
    discovery_basis: ObjectiveDiscoveryBasis
    source_support_level: SourceSupportLevel
    source_relationship: str = Field(min_length=1)
    source_contributions: list[str] = Field(min_length=1)
    missing_knowledge: list[str] = Field(default_factory=list)
    anticipated_llm_contributions: list[str] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(min_length=1)
    review_note: str | None = None

    @model_validator(mode="after")
    def support_shape_is_consistent(self) -> "ObjectiveSupportProfile":
        if self.discovery_basis == ObjectiveDiscoveryBasis.SOURCE_DERIVED:
            if self.source_support_level != SourceSupportLevel.SUBSTANTIAL:
                raise ValueError("source-derived objectives require substantial support")
            if self.missing_knowledge or self.anticipated_llm_contributions:
                raise ValueError("source-derived objectives cannot declare knowledge gaps")
        else:
            if self.source_support_level == SourceSupportLevel.SUBSTANTIAL:
                raise ValueError("source-related objectives cannot claim substantial support")
            if not self.missing_knowledge or not self.anticipated_llm_contributions:
                raise ValueError(
                    "source-related objectives require missing knowledge and LLM contributions"
                )
        return self


class CurriculumImportance(StrEnum):
    CORE = "core"
    SUPPORTING = "supporting"
    PERIPHERAL = "peripheral"


class CurriculumCoverageRole(StrEnum):
    PRIMARY = "primary"
    SUPPORTING = "supporting"
    PERIPHERAL = "peripheral"


class CurriculumCoverageState(StrEnum):
    ADEQUATE = "adequate"
    PARTIAL = "partial"
    MISSING = "missing"
    SOURCE_INSUFFICIENT = "source_insufficient"


class GapEvidenceSufficiency(StrEnum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class GapTargetAlignmentState(StrEnum):
    DIRECT = "direct"
    SUPPORTING = "supporting"
    OFF_TARGET = "off_target"


class ObjectiveConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ObjectiveContentType(StrEnum):
    FACT = "fact"
    CONCEPT = "concept"
    PROCESS = "process"
    PROCEDURE = "procedure"
    PRINCIPLE = "principle"


class ObjectiveBloomLevel(StrEnum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"


class ObjectiveKindDecision(StrictModel):
    value: ObjectiveContentType
    confidence: ObjectiveConfidence
    rationale: str = Field(min_length=1)


class ObjectiveBloomDecision(StrictModel):
    value: ObjectiveBloomLevel
    confidence: ObjectiveConfidence
    rationale: str = Field(min_length=1)
    expected_practice: str = Field(min_length=1)


class ObjectiveClassification(StrictModel):
    content_kind: ObjectiveKindDecision
    bloom: ObjectiveBloomDecision
    combined_confidence: ObjectiveConfidence
    provisional: bool = True
    escalation_required: bool = False
    plausible_alternative_cells: list[str] = Field(default_factory=list)
    rejected_cells: list[str] = Field(default_factory=list)
    discriminator_question: str | None = None
    verb_practice_mismatch: str | None = None
    rule_ids: list[str] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def derive_escalation_from_alternatives(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("plausible_alternative_cells"):
            return {**value, "escalation_required": True}
        return value

    @field_validator("provisional", mode="before")
    @classmethod
    def objective_classification_is_provisional(cls, value: bool) -> bool:
        return True

    @field_validator("plausible_alternative_cells", "rejected_cells", mode="before")
    @classmethod
    def normalize_cell_names(cls, values: list[str]) -> list[str]:
        normalized = []
        pattern = re.compile(
            r"^\s*(fact|concept|process|procedure|principle)\s*(?:-|x|×)\s*"
            r"(remember|understand|apply|analyze|evaluate)\b",
            re.IGNORECASE,
        )
        for value in values:
            match = pattern.match(value)
            normalized.append(
                f"{match.group(1).lower()}-{match.group(2).lower()}"
                if match
                else value
            )
        return normalized

    @model_validator(mode="after")
    def classification_is_consistent(self) -> "ObjectiveClassification":
        kind = ObjectiveContentType(self.content_kind.value)
        bloom = ObjectiveBloomLevel(self.bloom.value)
        valid_cells = {
            ObjectiveContentType.FACT: {
                ObjectiveBloomLevel.REMEMBER,
                ObjectiveBloomLevel.UNDERSTAND,
            },
            ObjectiveContentType.CONCEPT: {
                ObjectiveBloomLevel.UNDERSTAND,
                ObjectiveBloomLevel.APPLY,
                ObjectiveBloomLevel.ANALYZE,
            },
            ObjectiveContentType.PROCESS: {
                ObjectiveBloomLevel.UNDERSTAND,
                ObjectiveBloomLevel.APPLY,
                ObjectiveBloomLevel.ANALYZE,
            },
            ObjectiveContentType.PROCEDURE: {
                ObjectiveBloomLevel.APPLY,
                ObjectiveBloomLevel.ANALYZE,
            },
            ObjectiveContentType.PRINCIPLE: {
                ObjectiveBloomLevel.APPLY,
                ObjectiveBloomLevel.ANALYZE,
                ObjectiveBloomLevel.EVALUATE,
            },
        }
        if bloom not in valid_cells[kind]:
            raise ValueError(f"unsupported classification cell: {kind} × {bloom}")
        for value in [*self.plausible_alternative_cells, *self.rejected_cells]:
            try:
                alternative_kind, alternative_bloom = value.split("-", 1)
                alternative_kind_value = ObjectiveContentType(alternative_kind)
                alternative_bloom_value = ObjectiveBloomLevel(alternative_bloom)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid alternative classification cell: {value}") from exc
            if alternative_bloom_value not in valid_cells[alternative_kind_value]:
                raise ValueError(f"unsupported alternative classification cell: {value}")
        if any(
            not rule_id.startswith("C-")
            or not rule_id[2:].isdigit()
            or not 1 <= int(rule_id[2:]) <= 21
            for rule_id in self.rule_ids
        ):
            raise ValueError("classification rule IDs must be canonical C-1 through C-21")
        if not self.provisional:
            raise ValueError("objective-stage classification must remain provisional")
        confidence_order = {
            ObjectiveConfidence.LOW: 0,
            ObjectiveConfidence.MEDIUM: 1,
            ObjectiveConfidence.HIGH: 2,
        }
        expected = min(
            (self.content_kind.confidence, self.bloom.confidence),
            key=confidence_order.get,
        )
        if self.combined_confidence != expected:
            raise ValueError("combined confidence must be the lower axis confidence")
        if (
            self.combined_confidence == ObjectiveConfidence.LOW
            and not self.escalation_required
        ):
            raise ValueError("low-confidence classification must be escalated")
        if self.plausible_alternative_cells and not self.escalation_required:
            raise ValueError("plausible alternatives require classification escalation")
        if (
            self.combined_confidence == ObjectiveConfidence.HIGH
            and self.escalation_required
        ):
            raise ValueError("an escalated classification cannot have High confidence")
        if self.escalation_required and (
            not self.plausible_alternative_cells or not self.discriminator_question
        ):
            raise ValueError(
                "an escalated classification requires alternatives and a discriminator question"
            )
        return self


class SourceFeatureStatus(StrEnum):
    OBSERVED = "observed"
    UNCERTAIN = "uncertain"
    NOT_FOUND = "not_found"


class SourceFeatureType(StrEnum):
    EXPLICIT_OBJECTIVE = "explicit_objective"
    CORE_SUBSTANCE = "core_substance"
    WORKED_EXAMPLE = "worked_example"
    PRACTICE_ACTIVITY = "practice_activity"
    ASSESSMENT = "assessment"
    STRUCTURED_VISUAL = "structured_visual"
    PREREQUISITE_TRANSFER = "prerequisite_transfer"
    CURRENCY_SIGNAL = "currency_signal"


class PractitionerInstructions(StrictModel):
    roles: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    proficiency: str | None = None
    priorities: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    duration_minutes: int | None = Field(default=None, ge=1)
    service_line: str | None = None
    industry: str | None = None
    additional_context: str | None = None


class PractitionerLens(StrictModel):
    lens_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    practitioner_role: str = Field(min_length=1)
    relevant_tasks: list[str] = Field(min_length=1)
    decisions_or_risks: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    inferred: bool


class LearningBrief(StrictModel):
    schema_version: Literal["source-learning-brief-v1"] = "source-learning-brief-v1"
    brief_id: str = Field(min_length=1)
    collection_id: str = Field(min_length=1)
    instructions: PractitionerInstructions | None = None
    lenses: list[PractitionerLens] = Field(min_length=1, max_length=4)
    assumptions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    source_map_revision: str = Field(min_length=1)
    brief_revision: str = Field(min_length=1)


class CurriculumDomain(StrictModel):
    domain_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    importance: CurriculumImportance
    rationale: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    hierarchy_refs: list[str] = Field(default_factory=list)


class DocumentCurriculumBlueprint(StrictModel):
    schema_version: Literal["source-curriculum-blueprint-v1"] = (
        "source-curriculum-blueprint-v1"
    )
    blueprint_id: str = Field(min_length=1)
    collection_id: str = Field(min_length=1)
    source_map_revision: str = Field(min_length=1)
    central_purpose: str = Field(min_length=1)
    central_claim_ids: list[str] = Field(min_length=1)
    intended_use: str = Field(min_length=1)
    boundaries: list[str] = Field(default_factory=list)
    domains: list[CurriculumDomain] = Field(min_length=1)
    integrative_performances: list[str] = Field(default_factory=list)
    reference_topics: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_domains(self) -> "DocumentCurriculumBlueprint":
        domain_ids = [domain.domain_id for domain in self.domains]
        if len(domain_ids) != len(set(domain_ids)):
            raise ValueError("curriculum domain IDs must be unique")
        ordinals = [domain.ordinal for domain in self.domains]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("curriculum domain ordinals must be unique")
        return self


class CandidateCoverageAssignment(StrictModel):
    candidate_id: str = Field(min_length=1)
    domain_ids: list[str] = Field(default_factory=list)
    role: CurriculumCoverageRole
    contribution: str = Field(min_length=1)
    integrative: bool = False


class CurriculumGapTarget(StrictModel):
    target_id: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    performance: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_sufficiency: GapEvidenceSufficiency
    sufficiency_rationale: str = Field(min_length=1)
    search_warranted: bool

    @model_validator(mode="after")
    def search_has_sufficient_evidence(self) -> "CurriculumGapTarget":
        if self.search_warranted and (
            self.evidence_sufficiency != GapEvidenceSufficiency.SUFFICIENT
            or not self.claim_ids
        ):
            raise ValueError(
                "gap-target search requires sufficient evidence and source claims"
            )
        return self


class CurriculumDomainCoverage(StrictModel):
    domain_id: str = Field(min_length=1)
    state: CurriculumCoverageState
    candidate_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    missing_performances: list[str] = Field(default_factory=list)
    gap_targets: list[CurriculumGapTarget] = Field(default_factory=list)
    gap_discovery_warranted: bool = False
    gap_discovery_rationale: str | None = None

    @model_validator(mode="after")
    def valid_gap_eligibility(self) -> "CurriculumDomainCoverage":
        if any(target.domain_id != self.domain_id for target in self.gap_targets):
            raise ValueError("gap targets must belong to their coverage domain")
        target_ids = [target.target_id for target in self.gap_targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("curriculum gap target IDs must be unique within a domain")
        target_performances = [target.performance for target in self.gap_targets]
        if self.missing_performances != target_performances:
            raise ValueError("missing performances must be projected from gap targets")
        warranted = any(target.search_warranted for target in self.gap_targets)
        if self.gap_discovery_warranted != warranted:
            raise ValueError("domain gap eligibility must match its gap targets")
        if self.gap_discovery_warranted and not self.gap_discovery_rationale:
            raise ValueError("warranted gap discovery requires a rationale")
        if self.state in {
            CurriculumCoverageState.ADEQUATE,
            CurriculumCoverageState.SOURCE_INSUFFICIENT,
        } and self.gap_discovery_warranted:
            raise ValueError(
                "adequate or source-insufficient coverage cannot warrant gap discovery"
            )
        if self.state == CurriculumCoverageState.ADEQUATE and self.gap_targets:
            raise ValueError("adequate coverage cannot contain gap targets")
        return self


class CurriculumGapCandidateRejection(StrictModel):
    candidate_id: str = Field(min_length=1)
    reason_codes: list[str] = Field(min_length=1)


class GapTargetAlignment(StrictModel):
    target_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    alignment: GapTargetAlignmentState
    rationale: str = Field(min_length=1)
    unsupported_performance_parts: list[str] = Field(default_factory=list)
    claim_ids_used: list[str] = Field(default_factory=list)


class CurriculumGapTargetDiscoveryRecord(StrictModel):
    target: CurriculumGapTarget
    selected_for_discovery: bool
    prompt_run_ids: list[str] = Field(default_factory=list)
    proposed_candidate_ids: list[str] = Field(default_factory=list)
    alignments: list[GapTargetAlignment] = Field(default_factory=list)
    direct_candidate_ids: list[str] = Field(default_factory=list)
    supporting_candidate_ids: list[str] = Field(default_factory=list)
    rejections: list[CurriculumGapCandidateRejection] = Field(default_factory=list)
    no_candidate_found: bool = True

    @model_validator(mode="after")
    def consistent_target_result(self) -> "CurriculumGapTargetDiscoveryRecord":
        proposed_ids = set(self.proposed_candidate_ids)
        direct_ids = set(self.direct_candidate_ids)
        supporting_ids = set(self.supporting_candidate_ids)
        retained_ids = direct_ids | supporting_ids
        if direct_ids & supporting_ids:
            raise ValueError("a gap candidate cannot have two alignment outcomes")
        alignment_ids = [item.candidate_id for item in self.alignments]
        if len(alignment_ids) != len(set(alignment_ids)):
            raise ValueError("gap candidate alignments must be unique")
        alignments_by_candidate = {
            item.candidate_id: item.alignment for item in self.alignments
        }
        if any(
            alignments_by_candidate.get(candidate_id)
            != GapTargetAlignmentState.DIRECT
            for candidate_id in direct_ids
        ):
            raise ValueError("direct gap candidates require direct alignment")
        if any(
            alignments_by_candidate.get(candidate_id)
            != GapTargetAlignmentState.SUPPORTING
            for candidate_id in supporting_ids
        ):
            raise ValueError("supporting gap candidates require supporting alignment")
        if self.selected_for_discovery != self.target.search_warranted:
            raise ValueError("target selection must match its search eligibility")
        if not self.selected_for_discovery and (
            self.prompt_run_ids
            or proposed_ids
            or self.alignments
            or retained_ids
            or self.rejections
        ):
            raise ValueError("unselected gap targets cannot contain discovery results")
        if not retained_ids <= proposed_ids:
            raise ValueError("retained gap candidates must have been proposed")
        if not {item.candidate_id for item in self.alignments} <= proposed_ids:
            raise ValueError("gap alignments must reference proposed candidates")
        if any(item.target_id != self.target.target_id for item in self.alignments):
            raise ValueError("gap alignment references the wrong target")
        if not {
            rejection.candidate_id for rejection in self.rejections
        } <= proposed_ids:
            raise ValueError("rejected gap candidates must have been proposed")
        if self.no_candidate_found != (not retained_ids):
            raise ValueError("gap target empty-result status is inconsistent")
        return self


class CurriculumGapDiscoveryRecord(StrictModel):
    domain_id: str = Field(min_length=1)
    initial_state: CurriculumCoverageState
    warranted: bool
    selected_for_discovery: bool = False
    eligibility_rationale: str = Field(min_length=1)
    prompt_run_ids: list[str] = Field(default_factory=list)
    proposed_candidate_ids: list[str] = Field(default_factory=list)
    accepted_candidate_ids: list[str] = Field(default_factory=list)
    rejections: list[CurriculumGapCandidateRejection] = Field(default_factory=list)
    target_records: list[CurriculumGapTargetDiscoveryRecord] = Field(
        default_factory=list
    )
    no_candidate_found: bool = False

    @model_validator(mode="after")
    def consistent_candidates(self) -> "CurriculumGapDiscoveryRecord":
        if self.initial_state not in {
            CurriculumCoverageState.PARTIAL,
            CurriculumCoverageState.MISSING,
        }:
            raise ValueError("gap discovery records require partial or missing coverage")
        if self.selected_for_discovery and not self.warranted:
            raise ValueError("selected gap domains must be warranted")
        target_ids = [item.target.target_id for item in self.target_records]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("gap target discovery records must be unique")
        if any(
            item.target.domain_id != self.domain_id for item in self.target_records
        ):
            raise ValueError("gap target discovery record uses the wrong domain")
        target_proposed_ids = {
            candidate_id
            for item in self.target_records
            for candidate_id in item.proposed_candidate_ids
        }
        target_retained_ids = {
            candidate_id
            for item in self.target_records
            for candidate_id in [
                *item.direct_candidate_ids,
                *item.supporting_candidate_ids,
            ]
        }
        if set(self.proposed_candidate_ids) != target_proposed_ids:
            raise ValueError("domain proposals must match its gap target records")
        if set(self.accepted_candidate_ids) != target_retained_ids:
            raise ValueError("domain candidates must match its gap target records")
        if not self.selected_for_discovery and (
            self.prompt_run_ids
            or self.proposed_candidate_ids
            or self.accepted_candidate_ids
            or self.rejections
        ):
            raise ValueError("unselected gap domains cannot contain discovery results")
        if not set(self.accepted_candidate_ids) <= set(self.proposed_candidate_ids):
            raise ValueError("accepted gap candidates must have been proposed")
        if not {
            rejection.candidate_id for rejection in self.rejections
        } <= set(self.proposed_candidate_ids):
            raise ValueError("rejected gap candidates must have been proposed")
        if self.no_candidate_found != (not self.accepted_candidate_ids):
            raise ValueError("gap discovery empty-result status is inconsistent")
        return self


class CurriculumFragmentationFinding(StrictModel):
    candidate_ids: list[str] = Field(min_length=2)
    rationale: str = Field(min_length=1)


class CurriculumCoverageReport(StrictModel):
    schema_version: Literal["source-curriculum-coverage-v1"] = (
        "source-curriculum-coverage-v1"
    )
    report_id: str = Field(min_length=1)
    blueprint_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=1)
    assignments: list[CandidateCoverageAssignment] = Field(default_factory=list)
    domain_coverage: list[CurriculumDomainCoverage] = Field(min_length=1)
    peripheral_candidate_ids: list[str] = Field(default_factory=list)
    fragmentation_findings: list[CurriculumFragmentationFinding] = Field(
        default_factory=list
    )
    missing_integrative_performances: list[str] = Field(default_factory=list)
    source_insufficiencies: list[str] = Field(default_factory=list)
    reviewer_questions: list[str] = Field(default_factory=list)
    gap_candidate_ids: list[str] = Field(default_factory=list)
    gap_discovery_records: list[CurriculumGapDiscoveryRecord] = Field(
        default_factory=list
    )
    acknowledged_domain_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_coverage_entries(self) -> "CurriculumCoverageReport":
        candidate_ids = [assignment.candidate_id for assignment in self.assignments]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate coverage assignments must be unique")
        domain_ids = [coverage.domain_id for coverage in self.domain_coverage]
        if len(domain_ids) != len(set(domain_ids)):
            raise ValueError("curriculum domain coverage entries must be unique")
        discovery_domain_ids = [
            record.domain_id for record in self.gap_discovery_records
        ]
        if len(discovery_domain_ids) != len(set(discovery_domain_ids)):
            raise ValueError("curriculum gap discovery records must be unique")
        return self


class ObjectiveEvidence(StrictModel):
    evidence_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    node_ids: list[str] = Field(min_length=1)
    role: EvidenceRole
    rationale: str = Field(min_length=1)
    assessment_eligible: bool

    @model_validator(mode="after")
    def context_is_not_assessable(self) -> "ObjectiveEvidence":
        if self.role in {
            EvidenceRole.SUPPORTING_CONTEXT,
            EvidenceRole.SOURCE_ANCHOR,
        } and self.assessment_eligible:
            raise ValueError(
                "supporting context and source anchors cannot expand the assessment boundary"
            )
        return self


class SourceFeature(StrictModel):
    feature_id: str = Field(min_length=1)
    feature_type: SourceFeatureType
    status: SourceFeatureStatus
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence: list[ObjectiveEvidence] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)


class DecompositionSignal(StrictModel):
    signal_id: str = Field(min_length=1)
    rule_id: str = Field(pattern=r"^D-(?:[1-9]|1[0-9])$")
    signal_type: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    confidence: ObjectiveConfidence
    evidence: list[ObjectiveEvidence] = Field(min_length=1)


class ObjectiveCandidate(StrictModel):
    candidate_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    observable_behavior: str = Field(min_length=1)
    performance_context: str = Field(min_length=1)
    practitioner_relevance: str = Field(min_length=1)
    bloom_level: Literal[
        "remember", "understand", "apply", "analyze", "evaluate", "create"
    ] | None = None
    content_type_hint: ObjectiveContentType | None = None
    scope: str = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    confidence: ObjectiveConfidence
    confidence_rationale: str = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)
    terminal_outcome: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    expected_effort_minutes: int = Field(ge=1)
    evidence: list[ObjectiveEvidence] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    selected_reason: str = Field(min_length=1)
    rank: int = Field(ge=1)
    duplicate_group: str | None = None
    origin: ObjectiveOrigin = ObjectiveOrigin.MODEL
    source_feature_ids: list[str] = Field(default_factory=list)
    classification: ObjectiveClassification | None = None
    poc2_scope_status: ObjectiveScopeStatus | None = None
    poc2_scope_reason: str | None = None
    support_profile: ObjectiveSupportProfile | None = None

    @model_validator(mode="before")
    @classmethod
    def derive_historical_scope(cls, value: object) -> object:
        if not isinstance(value, dict) or value.get("poc2_scope_status") is not None:
            return value
        classification = value.get("classification")
        if isinstance(classification, ObjectiveClassification):
            kind = classification.content_kind.value
            bloom = classification.bloom.value
        elif isinstance(classification, dict):
            kind = (classification.get("content_kind") or {}).get("value")
            bloom = (classification.get("bloom") or {}).get("value")
        else:
            return {**value, "poc2_scope_status": ObjectiveScopeStatus.NEEDS_REVIEW}
        if kind and bloom and is_poc2_cell(kind, bloom):
            return {**value, "poc2_scope_status": ObjectiveScopeStatus.SUPPORTED}
        if kind and bloom:
            return {
                **value,
                "poc2_scope_status": ObjectiveScopeStatus.OUTSIDE_POC2_SCOPE,
                "poc2_scope_reason": value.get("poc2_scope_reason")
                or poc2_scope_reason(kind, bloom),
            }
        return {**value, "poc2_scope_status": ObjectiveScopeStatus.NEEDS_REVIEW}

    @model_validator(mode="after")
    def has_assessable_evidence(self) -> "ObjectiveCandidate":
        if self.poc2_scope_status == ObjectiveScopeStatus.SUPPORTED:
            if self.classification is None:
                raise ValueError("supported POC2 objectives require classification")
            if not is_poc2_cell(
                self.classification.content_kind.value,
                self.classification.bloom.value,
            ):
                raise ValueError("supported POC2 objectives require an approved cell")
        if self.poc2_scope_status == ObjectiveScopeStatus.OUTSIDE_POC2_SCOPE:
            if not self.poc2_scope_reason:
                raise ValueError("outside-scope objectives require a reason")
        if self.support_profile is None:
            if not any(item.assessment_eligible for item in self.evidence):
                raise ValueError("objective requires objective-defining assessment evidence")
            return self
        evidence_claim_ids = {item.claim_id for item in self.evidence}
        if not set(self.support_profile.source_claim_ids) <= evidence_claim_ids:
            raise ValueError("objective support references unknown source claims")
        if (
            self.support_profile.discovery_basis
            == ObjectiveDiscoveryBasis.SOURCE_DERIVED
            and not any(item.assessment_eligible for item in self.evidence)
        ):
            raise ValueError("objective requires objective-defining assessment evidence")
        if (
            self.support_profile.discovery_basis
            == ObjectiveDiscoveryBasis.SOURCE_RELATED
            and not any(item.role == EvidenceRole.SOURCE_ANCHOR for item in self.evidence)
        ):
            raise ValueError("source-related objectives require source-anchor evidence")
        return self


class CriticFinding(StrictModel):
    code: Literal[
        "topic_label",
        "compound_objective",
        "heading_restatement",
        "unsupported_context",
        "unobservable_behavior",
        "scope_mismatch",
        "duplicate",
    ]
    message: str = Field(min_length=1)
    severity: Literal["warning", "error"]


class ObjectiveRejection(StrictModel):
    candidate_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    reason_codes: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)


class DuplicateGroup(StrictModel):
    group_id: str = Field(min_length=1)
    candidate_ids: list[str] = Field(min_length=2)
    retained_candidate_id: str = Field(min_length=1)


class ObjectiveDecision(StrictModel):
    candidate_id: str = Field(min_length=1)
    status: ObjectiveDecisionStatus
    note: str | None = None
    decided_by: str = Field(min_length=1)


class ObjectiveWorkspace(StrictModel):
    schema_version: Literal[
        "source-objective-workspace-v1", "source-objective-workspace-v2"
    ] = (
        "source-objective-workspace-v2"
    )
    workspace_id: str = Field(min_length=1)
    collection_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    learning_brief: LearningBrief
    curriculum_blueprint: DocumentCurriculumBlueprint | None = None
    curriculum_coverage: CurriculumCoverageReport | None = None
    candidates: list[ObjectiveCandidate] = Field(default_factory=list)
    signals: list[DecompositionSignal] = Field(default_factory=list)
    source_features: list[SourceFeature] = Field(default_factory=list)
    rejected: list[ObjectiveRejection] = Field(default_factory=list)
    duplicate_groups: list[DuplicateGroup] = Field(default_factory=list)
    critic_findings: dict[str, list[CriticFinding]] = Field(default_factory=dict)
    decisions: list[ObjectiveDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def curriculum_references_resolve(self) -> "ObjectiveWorkspace":
        if self.curriculum_blueprint is None:
            if self.curriculum_coverage is not None:
                raise ValueError("curriculum coverage requires a curriculum blueprint")
            return self
        if self.curriculum_blueprint.collection_id != self.collection_id:
            raise ValueError("curriculum blueprint must match the workspace collection")
        if self.curriculum_coverage is None:
            return self
        if self.curriculum_coverage.blueprint_id != self.curriculum_blueprint.blueprint_id:
            raise ValueError("curriculum coverage must match the workspace blueprint")
        domain_ids = {
            domain.domain_id for domain in self.curriculum_blueprint.domains
        }
        domains_by_id = {
            domain.domain_id: domain for domain in self.curriculum_blueprint.domains
        }
        referenced_domain_ids = {
            domain_id
            for assignment in self.curriculum_coverage.assignments
            for domain_id in assignment.domain_ids
        } | {
            coverage.domain_id
            for coverage in self.curriculum_coverage.domain_coverage
        } | set(self.curriculum_coverage.acknowledged_domain_ids)
        referenced_domain_ids |= {
            record.domain_id
            for record in self.curriculum_coverage.gap_discovery_records
        }
        if not referenced_domain_ids <= domain_ids:
            raise ValueError("curriculum coverage references an unknown domain")
        targets = [
            target
            for finding in self.curriculum_coverage.domain_coverage
            for target in finding.gap_targets
        ] + [
            target_record.target
            for record in self.curriculum_coverage.gap_discovery_records
            for target_record in record.target_records
        ]
        target_ids = [target.target_id for target in targets]
        if len(set(target_ids)) != len(
            {
                (target.target_id, target.domain_id, target.performance)
                for target in targets
            }
        ):
            raise ValueError("curriculum gap target IDs are inconsistent")
        for target in targets:
            domain = domains_by_id.get(target.domain_id)
            if domain is None or not set(target.claim_ids) <= set(domain.claim_ids):
                raise ValueError("curriculum gap target references an unknown domain claim")
        if self.curriculum_coverage.workspace_revision == self.revision:
            candidate_ids = {candidate.candidate_id for candidate in self.candidates}
            assignment_ids = {
                assignment.candidate_id
                for assignment in self.curriculum_coverage.assignments
            }
            if assignment_ids != candidate_ids:
                raise ValueError("current curriculum coverage must assign every candidate")
            accepted_gap_ids = {
                candidate_id
                for record in self.curriculum_coverage.gap_discovery_records
                for candidate_id in record.accepted_candidate_ids
            }
            if not accepted_gap_ids <= candidate_ids:
                raise ValueError("gap discovery references an unknown accepted candidate")
            if set(self.curriculum_coverage.gap_candidate_ids) != accepted_gap_ids:
                raise ValueError(
                    "coverage gap candidates must match accepted discovery candidates"
                )
        return self


class CompletedObjectivePackage(StrictModel):
    schema_version: Literal[
        "source-objective-package-v1", "source-objective-package-v2"
    ] = "source-objective-package-v2"
    job_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=1)
    collection_id: str = Field(min_length=1)
    source_map_revision: str = Field(min_length=1)
    objectives: list[ObjectiveCandidate] = Field(default_factory=list)
    source_features: list[SourceFeature] = Field(default_factory=list)
