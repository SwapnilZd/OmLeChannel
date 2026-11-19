"""
Curriculum Assembly contracts — Phase 12.

Separation of concerns
-----------------------
AssemblyRLOCandidate    — input reference: rlo_id + version + required flag
CourseAssemblyConstraints — hard constraints on the assembly
CourseAssemblyRequest   — full assembly request
RLOAssemblyContext      — deterministic projection of one RLODocument for the agent
TailoredRLODraft        — per-RLO LLM selection decision
OmittedRLODecision      — explicit omission record
CourseAssemblyDraft     — top-level LLM structured output
PrerequisiteBridge      — typed bridge for a missing prerequisite
RLOAssemblyDecision     — per-RLO disposition in the audit report
CourseAssemblyReport    — full auditable assembly record
AssemblyPlanningTrace   — immutable trace for one assembly operation
CourseAssemblyResult    — surface returned to the caller
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .assembly import RLOContentSelection
from .common import ContentDepth, FrozenModel, TopicProficiency
from .learner import LearnerContext
from .rlo import (
    AssessmentItem,
    Concept,
    ContentTypeRecommendation,
    DesignBrief,
    EnablingObjective,
    InstructionalComponent,
)


# ── Assembly request ──────────────────────────────────────────────────────────


class AssemblyRLOCandidate(FrozenModel):
    """Reference to a candidate RLO that the assembly agent may select."""

    rlo_id: str = Field(min_length=1)
    rlo_version: str = Field(min_length=1)
    required: bool = False


class CourseAssemblyConstraints(FrozenModel):
    """Hard constraints that the assembly agent must respect."""

    required_rlo_ids: tuple[str, ...] = ()
    excluded_rlo_ids: tuple[str, ...] = ()
    required_content_ids: tuple[str, ...] = ()
    maximum_duration_minutes: int | None = None
    minimum_target_proficiency: TopicProficiency | None = None

    @model_validator(mode="after")
    def _validate(self) -> CourseAssemblyConstraints:
        if self.maximum_duration_minutes is not None and self.maximum_duration_minutes <= 0:
            raise ValueError("maximum_duration_minutes must be positive")
        required_set = set(self.required_rlo_ids)
        excluded_set = set(self.excluded_rlo_ids)
        overlap = required_set & excluded_set
        if overlap:
            raise ValueError(
                f"required_rlo_ids and excluded_rlo_ids cannot overlap: {overlap}"
            )
        if len(self.required_rlo_ids) != len(required_set):
            raise ValueError("required_rlo_ids must be unique")
        if len(self.excluded_rlo_ids) != len(excluded_set):
            raise ValueError("excluded_rlo_ids must be unique")
        seen = set[str]()
        for cid in self.required_content_ids:
            if not cid:
                raise ValueError("required_content_ids must not contain empty strings")
            if cid in seen:
                raise ValueError(f"required_content_ids must be unique, duplicate: {cid!r}")
            seen.add(cid)
        return self


class CourseAssemblyRequest(FrozenModel):
    """Full curriculum assembly request from an external agent or user."""

    request_id: str = Field(min_length=1)
    learner: LearnerContext
    candidates: tuple[AssemblyRLOCandidate, ...]
    course_goal: str = Field(min_length=1)
    constraints: CourseAssemblyConstraints = Field(
        default_factory=CourseAssemblyConstraints
    )
    brand_contract: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> CourseAssemblyRequest:
        if not self.candidates:
            raise ValueError("candidates must not be empty")

        # Unique (rlo_id, rlo_version) pairs
        seen: set[tuple[str, str]] = set()
        ids: set[str] = set()
        for c in self.candidates:
            key = (c.rlo_id, c.rlo_version)
            if key in seen:
                raise ValueError(
                    f"Duplicate candidate (rlo_id, rlo_version): {key}"
                )
            seen.add(key)
            ids.add(c.rlo_id)

        candidate_ids = {c.rlo_id for c in self.candidates}

        for rid in self.constraints.required_rlo_ids:
            if rid not in candidate_ids:
                raise ValueError(
                    f"required_rlo_id '{rid}' is not among the candidates"
                )
        for rid in self.constraints.excluded_rlo_ids:
            if rid not in candidate_ids:
                raise ValueError(
                    f"excluded_rlo_id '{rid}' is not among the candidates"
                )
        return self


# ── Assembly context (deterministic projection for the agent) ─────────────────


class RLOAssemblyContext(FrozenModel):
    """Deterministic, read-only projection of an RLODocument for assembly planning.

    Reuses typed RLO model classes. Does not copy mutable state or add inferences.
    The agent uses this to make content selection decisions.
    """

    rlo_id: str
    rlo_version: str
    title: str
    topic: str
    domain: str
    level: str
    audience: tuple[str, ...]
    estimated_duration_minutes: int

    prerequisites: tuple[str, ...]
    corequisites: tuple[str, ...]
    follow_ons: tuple[str, ...]

    terminal_objective: str | None
    enabling_objective: EnablingObjective
    concepts: tuple[Concept, ...]
    components: tuple[InstructionalComponent, ...]
    assessment_items: tuple[AssessmentItem, ...]

    design_brief: DesignBrief
    content_type_recommendations: tuple[ContentTypeRecommendation, ...]

    role_tags: tuple[str, ...]
    industry_tags: tuple[str, ...]
    service_line_tags: tuple[str, ...]
    competency_map: tuple[str, ...]
    regulatory_tags: tuple[str, ...]

    governance_status: str
    source_ids: tuple[str, ...]


# ── Assembly draft (LLM structured output) ────────────────────────────────────


class TailoredRLODraft(FrozenModel):
    """Per-RLO selection decision from the assembly agent.

    The LLM sets: order, selected content IDs, proficiency targets, depth,
    relevance rationale, sequencing rationale, adaptation instructions.

    Deterministic code derives: starting proficiency, source version traceability,
    blueprint hash, estimated duration.
    """

    rlo_id: str = Field(min_length=1)
    rlo_version: str = Field(min_length=1)
    order: int = Field(ge=1)

    selected_content: RLOContentSelection

    target_proficiency: TopicProficiency
    content_depth: ContentDepth

    role_relevance: str = Field(min_length=1)
    example_context: str | None = None
    personalization_rationale: str = Field(min_length=1)
    sequencing_rationale: str = Field(min_length=1)
    adaptation_instructions: tuple[str, ...] = ()


class OmittedRLODecision(FrozenModel):
    """Explicit record when the agent decides not to include a candidate RLO."""

    rlo_id: str = Field(min_length=1)
    rlo_version: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class PrerequisiteBridge(FrozenModel):
    """Documents why a prerequisite RLO not in the blueprint is acceptable."""

    bridge_id: str = Field(min_length=1)
    before_rlo_id: str = Field(min_length=1)
    prerequisite_topic: str = Field(min_length=1)
    learning_direction: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class CourseAssemblyDraft(FrozenModel):
    """Top-level LLM structured output for curriculum assembly.

    The LLM makes semantic decisions: which RLOs to include, in what order,
    with what content depth, and with what personalization direction.
    Deterministic code does everything structural: ID validation, proficiency
    derivation, duration calculation, blueprint construction.

    Every eligible candidate must appear in exactly one of:
      ordered_rlo_drafts (included)
      omitted_rlos (explicitly omitted)
    """

    draft_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    learning_outcomes: tuple[str, ...] = Field(min_length=1)

    ordered_rlo_drafts: tuple[TailoredRLODraft, ...] = Field(min_length=0)
    omitted_rlos: tuple[OmittedRLODecision, ...] = ()

    prerequisite_bridges: tuple[PrerequisiteBridge, ...] = ()
    sequencing_rationale: str = Field(min_length=1)
    assessment_strategy: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate(self) -> CourseAssemblyDraft:
        orders = [d.order for d in self.ordered_rlo_drafts]
        if len(set(orders)) != len(orders):
            raise ValueError("TailoredRLODraft order values must be unique")
        included_ids = {(d.rlo_id, d.rlo_version) for d in self.ordered_rlo_drafts}
        omitted_ids = {(d.rlo_id, d.rlo_version) for d in self.omitted_rlos}
        overlap = included_ids & omitted_ids
        if overlap:
            raise ValueError(
                f"Same RLO cannot be both included and omitted: {overlap}"
            )
        outcomes = list(self.learning_outcomes)
        if len(set(outcomes)) != len(outcomes):
            raise ValueError("learning_outcomes must be unique")
        bridge_ids = [b.bridge_id for b in self.prerequisite_bridges]
        if len(set(bridge_ids)) != len(bridge_ids):
            raise ValueError("PrerequisiteBridge bridge_ids must be unique")
        return self


# ── Assembly report ───────────────────────────────────────────────────────────


class RLOAssemblyDecision(FrozenModel):
    """Per-RLO disposition in the assembly audit report."""

    rlo_id: str
    rlo_version: str
    disposition: str  # "included" | "omitted" | "rejected_by_governance"
    rationale: str
    starting_proficiency_source: str | None = None
    automatically_added_content_ids: tuple[str, ...] = ()


class CourseAssemblyReport(FrozenModel):
    """Full auditable record for one curriculum assembly operation."""

    request_id: str
    blueprint_id: str

    candidate_decisions: tuple[RLOAssemblyDecision, ...]
    prerequisite_findings: tuple[str, ...]
    outcome_coverage: dict[str, tuple[str, ...]]
    duration_estimate_minutes: int
    duration_policy_version: str
    warnings: tuple[str, ...] = ()


# ── Trace ─────────────────────────────────────────────────────────────────────


class AssemblyPlanningTrace(FrozenModel):
    """Immutable audit record for one curriculum assembly planning operation."""

    assembly_request_id: str
    blueprint_id: str
    candidate_snapshot_hash: str
    learner_hash: str
    constraints_hash: str
    context_hash: str
    prompt_version: str
    model: str | None
    draft_hash: str
    blueprint_hash: str
    assembly_policy_version: str
    duration_policy_version: str
    input_hash: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


# ── Service result ────────────────────────────────────────────────────────────


class CourseAssemblyResult(FrozenModel):
    """Surface returned to the caller of CourseAssemblyService."""

    blueprint: "CourseBlueprint"  # type: ignore[name-defined]  # noqa: F821
    report: CourseAssemblyReport
    trace: AssemblyPlanningTrace
    from_cache: bool = False


# Deferred import to avoid circular import with assembly.py
from .assembly import CourseBlueprint  # noqa: E402
CourseAssemblyResult.model_rebuild()
