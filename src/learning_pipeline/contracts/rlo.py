from __future__ import annotations

from typing import Any

from pydantic import field_validator

from .common import FrozenModel


class Source(FrozenModel):
    """A bibliographic reference attached to an RLO or one of its concepts."""

    id: str
    title: str
    reference: str
    authority: str
    note: str | None = None
    ingested_source_id: str | None = None
    source_version_id: str | None = None
    checksum: str | None = None
    canonical_locator: str | None = None


class Evidence(FrozenModel):
    id: str
    source_ref: str
    source_version_id: str
    node_ids: tuple[str, ...]
    segment_ids: tuple[str, ...] = ()
    locator: str
    role: str
    excerpt: str | None = None
    excerpt_sha256: str | None = None
    usage_note: str | None = None


class Misconception(FrozenModel):
    id: str
    statement: str
    correction: str
    evidence_refs: tuple[str, ...] = ()


class EnablingObjective(FrozenModel):
    id: str
    statement: str
    bloom_level: str
    concepts_addressed: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()


class Concept(FrozenModel):
    id: str
    name: str
    definition: str
    elaboration: str
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    misconceptions: tuple[Misconception, ...] = ()


class InstructionalComponent(FrozenModel):
    """
    One CDT instructional unit within an RLO.

    canonical_content is either a plain string (for rule and hook types)
    or a structured dict (for example, non_example, and recall_prompt types).
    """

    id: str
    cdt_type: str
    title: str | None = None
    concepts_referenced: tuple[str, ...] = ()
    misconceptions_addressed: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    canonical_content: str | dict[str, Any]


class AssessmentOption(FrozenModel):
    id: str
    text: str
    correct: bool
    misconception_targeted: str | None
    feedback: str
    evidence_refs: tuple[str, ...] = ()


class AssessmentItem(FrozenModel):
    id: str
    stem: str
    type: str
    concepts_assessed: tuple[str, ...]
    options: tuple[AssessmentOption, ...]
    evidence_refs: tuple[str, ...] = ()


class DesignBrief(FrozenModel):
    tone: str
    scaffolding_level: str
    scaffolding_notes: str
    feedback_policy: str
    example_shape_hints: tuple[str, ...]
    practice_shape_hints: tuple[str, ...]
    salience_hook_description: str


class GagneEventMapping(FrozenModel):
    """
    Maps each of the nine Gagné events to component or assessment IDs.

    Every event is normalized to a tuple because the canonical RLO schema
    permits either one reference or a list of references for all nine events.
    """

    event_1_gain_attention: tuple[str, ...] = ()
    event_2_inform_objective: tuple[str, ...] = ()
    event_3_stimulate_recall: tuple[str, ...] = ()
    event_4_present_content: tuple[str, ...] = ()
    event_5_provide_guidance: tuple[str, ...] = ()
    event_6_elicit_performance: tuple[str, ...] = ()
    event_7_provide_feedback: tuple[str, ...] = ()
    event_8_assess_performance: tuple[str, ...] = ()
    event_9_enhance_retention: tuple[str, ...] = ()

    @field_validator("*", mode="before")
    @classmethod
    def _normalize_references(cls, value: object) -> object:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        return value


class ContentTypeRecommendation(FrozenModel):
    format: str
    rationale: str
    priority: str


class Governance(FrozenModel):
    status: str
    authoring_sme: str | None = None
    reviewing_sme: str | None = None
    signoff_date: str | None = None
    signoff_authority: str | None = None
    review_cadence_months: int | None = None
    next_review_date: str | None = None
    change_history: str | None = None


class Accessibility(FrozenModel):
    features: tuple[str, ...] = ()
    wcag_conformance: str | None = None


class RLODocument(FrozenModel):
    """
    Complete, immutable source learning object.

    Created by:
        RLO ingestion (authored offline, loaded from course-definitions/rlos/).

    Consumed by:
        Curriculum assembly (CurriculumPlanner) to build a CourseBlueprint.
        ModalityContextResolver to populate source_rlos in ModalityPlanningContext.

    Contains:
        Full instructional structure — concepts, misconceptions, CDT components,
        assessment items, Gagné event mapping, design guidance, governance,
        and accessibility metadata. Versioned so downstream tailoring always
        references an exact snapshot.

    Does not contain:
        Learner context, delivery format decisions, production capabilities,
        or rendered assets. RLODocuments are read-only inputs; they are never
        modified by downstream planners.
    """

    id: str
    version: str
    schema_version: str
    language: str
    locale: str
    title: str
    topic: str
    domain: str
    level: str
    audience: tuple[str, ...]
    estimated_duration_minutes: int
    content_type: str
    performance_level: str
    prerequisites: tuple[str, ...] = ()
    corequisites: tuple[str, ...] = ()
    follow_ons: tuple[str, ...] = ()
    related_rlos: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    terminal_objective: str | None = None
    performance_context: str
    enabling_objective: EnablingObjective
    concepts: tuple[Concept, ...]
    components: tuple[InstructionalComponent, ...]
    assessment_items: tuple[AssessmentItem, ...]
    variant_examples: tuple[dict[str, Any], ...] = ()
    design_brief: DesignBrief
    gagne_event_mapping: GagneEventMapping
    content_type_recommendations: tuple[ContentTypeRecommendation, ...] = ()
    authoring_rationale: str
    role_tags: tuple[str, ...] = ()
    industry_tags: tuple[str, ...] = ()
    service_line_tags: tuple[str, ...] = ()
    competency_map: tuple[str, ...] = ()
    regulatory_tags: tuple[str, ...] = ()
    governance: Governance
    accessibility: Accessibility
