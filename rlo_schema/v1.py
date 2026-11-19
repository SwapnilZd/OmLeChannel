"""
Reusable Learning Object (RLO) — Unified Schema
================================================

A hybrid schema combining:
- The concept-first, CDT-typed, misconception-threaded pedagogical model
  from our authored ADKAR / Kotter RLOs
- The governance, lifecycle, accessibility, and targeting metadata from the
  G&D RLO-1284 template

Design principles:
- One enabling_objective per RLO (composability constraint)
- Content is format-agnostic (delivery formats are spec-layer, not RLO-layer)
- Misconceptions are first-class and threaded from concept -> component ->
  assessment option (diagnostic feedback depends on this chain)
- No rendered narrative prose; no personalization slots (both spec-layer)
- Governance and accessibility are RLO-layer concerns and are represented
  as first-class fields

Serialization target: JSON. All string enums use snake_case values suitable
for direct JSON output.

Pydantic v2.
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================


class BloomLevel(str, Enum):
    """Bloom's Taxonomy (revised) cognitive process dimension."""

    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class ContentType(str, Enum):
    """
    Merrill Component Display Theory content classification.

    Describes what kind of thing the RLO is teaching. Distinct from
    content_type_recommendations, which describes recommended delivery formats.
    """

    FACT = "fact"
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    PROCESS = "process"
    PRINCIPLE = "principle"


class PerformanceLevel(str, Enum):
    """
    Behavioral performance the learner should produce.

    Complements bloom_level: Bloom asks "what cognitive process?", performance
    level asks "what observable behavior?". Both are useful and answer
    different questions.
    """

    RECALL = "recall"      # produce from memory
    FIND = "find"          # locate / identify in context
    DO = "do"              # perform the action
    DECIDE = "decide"      # choose between options with justification
    CREATE = "create"      # produce new output


class Level(str, Enum):
    """Approximate audience level."""

    INTRODUCTORY = "introductory"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class CDTType(str, Enum):
    """
    Component Display Theory categorization of instructional components.

    Every component in the RLO must declare its instructional role. This
    is what makes the RLO composable across delivery formats and diagnosable
    for coverage gaps.
    """

    HOOK = "hook"                    # salience / attention / motivation
    RULE = "rule"                    # generalization / definition / principle
    EXAMPLE = "example"              # positive instance
    NON_EXAMPLE = "non_example"      # negative instance / counter-case
    RECALL_PROMPT = "recall_prompt"  # elicit performance / self-check


class AssessmentType(str, Enum):
    """
    Assessment item types.

    Multiple choice single-answer is the primary autograded type. Open-response
    items are supported for higher Bloom levels where MCQ is too constrained,
    but require rubric-based scoring downstream.
    """

    MULTIPLE_CHOICE_SINGLE = "multiple_choice_single"
    MULTIPLE_CHOICE_MULTI = "multiple_choice_multi"
    OPEN_RESPONSE = "open_response"


class ExampleVariantType(str, Enum):
    """Whether an example is the canonical treatment or a tagged variant."""

    CANONICAL = "canonical"
    VARIANT = "variant"


class SourceAuthority(str, Enum):
    """How authoritative a source is for the content it supports."""

    PRIMARY = "primary"          # originating source (e.g., framework's canonical text)
    SECONDARY = "secondary"      # scholarly or professional treatment of the primary
    REFERENCE = "reference"      # general reference material


class EvidenceRole(str, Enum):
    """How source evidence may be used in the RLO."""

    OBJECTIVE_DEFINING = "objective_defining"
    SUPPORTING_CONTEXT = "supporting_context"


class RLOStatus(str, Enum):
    """Lifecycle state of the RLO."""

    DRAFT = "draft"              # in authoring
    IN_REVIEW = "in_review"      # under SME review
    APPROVED = "approved"        # approved for production use
    SIGNED = "signed"            # legacy synonym accepted for migration
    DEPRECATED = "deprecated"    # superseded or retired
    ARCHIVED = "archived"        # historical only, not delivered


class WCAGConformance(str, Enum):
    """WCAG conformance level claimed for the RLO."""

    A_2_2 = "A (2.2)"
    AA_2_2 = "AA (2.2)"
    AAA_2_2 = "AAA (2.2)"
    A_2_1 = "A (2.1)"
    AA_2_1 = "AA (2.1)"
    AAA_2_1 = "AAA (2.1)"


class ScaffoldingLevel(str, Enum):
    """How much support the learner needs at this level of the sequence."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContentRecommendationPriority(str, Enum):
    """How strongly a delivery format is recommended for this RLO."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    OPTIONAL = "optional"


# =============================================================================
# SUPPORTING MODELS
# =============================================================================


class Source(BaseModel):
    """A reference source supporting concept content."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Local ID for cross-reference from concepts (e.g. 'src-01').")
    title: str
    reference: str = Field(..., description="Full citation string (author, year, work, publisher).")
    authority: SourceAuthority
    note: Optional[str] = Field(None, description="Optional note about how the source is used.")
    ingested_source_id: Optional[str] = Field(
        None, description="Stable identity of the ingested source document."
    )
    source_version_id: Optional[str] = Field(
        None, description="Immutable source version used to create this RLO."
    )
    checksum: Optional[str] = Field(
        None,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 checksum of the immutable ingested source version.",
    )
    canonical_locator: Optional[str] = Field(
        None,
        description="Optional public or human-meaningful locator; never an internal object-store path.",
    )

    @model_validator(mode="after")
    def _complete_ingested_identity(self) -> "Source":
        identity = (self.ingested_source_id, self.source_version_id, self.checksum)
        if any(identity) and not all(identity):
            raise ValueError(
                "ingested_source_id, source_version_id, and checksum must be supplied together"
            )
        return self


class Evidence(BaseModel):
    """Portable reference to exact extracted nodes supporting an RLO claim."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    source_ref: str = Field(..., min_length=1, description="Local Source.id reference.")
    source_version_id: str = Field(..., min_length=1)
    node_ids: list[str] = Field(..., min_length=1)
    segment_ids: list[str] = Field(default_factory=list)
    locator: str = Field(
        ...,
        min_length=1,
        description="Human-readable location such as 'pages 4-5' or 'slide 8'.",
    )
    role: EvidenceRole
    excerpt: Optional[str] = None
    excerpt_sha256: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$")
    usage_note: Optional[str] = None

    @model_validator(mode="after")
    def _valid_excerpt_and_nodes(self) -> "Evidence":
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError(f"Evidence {self.id}: node IDs must be unique.")
        if len(self.segment_ids) != len(set(self.segment_ids)):
            raise ValueError(f"Evidence {self.id}: segment IDs must be unique.")
        if (self.excerpt is None) != (self.excerpt_sha256 is None):
            raise ValueError(
                f"Evidence {self.id}: excerpt and excerpt_sha256 must be supplied together."
            )
        if self.excerpt is not None:
            digest = hashlib.sha256(self.excerpt.encode("utf-8")).hexdigest()
            if digest != self.excerpt_sha256:
                raise ValueError(f"Evidence {self.id}: excerpt_sha256 does not match excerpt.")
        return self


class Misconception(BaseModel):
    """
    A specific wrong-model that learners commonly hold.

    Misconceptions are embedded in concepts (each misconception belongs to one
    concept). They are referenced by components (misconceptions_addressed) and
    by assessment options (misconception_targeted) to thread diagnostic
    feedback through the RLO.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Local ID unique within this RLO (e.g. 'm-01').")
    statement: str = Field(..., description="The wrong-model, stated as the learner would hold it.")
    correction: str = Field(..., description="Why the misconception is wrong and what is actually true.")
    evidence_refs: list[str] = Field(default_factory=list)


class Concept(BaseModel):
    """
    A single conceptual atom the RLO teaches.

    Concepts carry definitions, elaborations, source references, and their
    embedded misconceptions. Components reference concepts; assessments
    reference concepts. The concept graph is what makes the RLO diagnosable.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Local ID (e.g. 'c-01').")
    name: str
    definition: str = Field(..., description="Precise, format-agnostic definition.")
    elaboration: str = Field(..., description="Additional context, nuance, and 'why this matters'.")
    source_refs: list[str] = Field(
        default_factory=list, description="IDs of Source entries supporting this concept."
    )
    evidence_refs: list[str] = Field(
        default_factory=list, description="Evidence IDs supporting this concept's claims."
    )
    misconceptions: list[Misconception] = Field(
        default_factory=list, description="Wrong-models learners hold about this concept."
    )


class Component(BaseModel):
    """
    A single instructional component of the RLO.

    Every component declares its CDT type (hook / rule / example / non-example
    / recall_prompt), the concepts it references, and (where relevant) the
    misconceptions it addresses.

    canonical_content is intentionally typed as Any: it may be a string, a
    structured dict (as in most of our examples), or a list of structured
    dicts. Downstream spec-layer tooling knows how to render each shape.
    Authors should not put rendered narrative prose here; content should be
    structured or atomic so downstream delivery formats can compose from it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Local ID (e.g. 'comp-hook-01').")
    cdt_type: CDTType
    title: Optional[str] = Field(None, description="Optional short label for the component.")
    concepts_referenced: list[str] = Field(
        ..., min_length=1, description="Concept IDs this component addresses."
    )
    misconceptions_addressed: list[str] = Field(
        default_factory=list,
        description="Misconception IDs this component corrects. Typical for non_example and example components.",
    )
    evidence_refs: list[str] = Field(default_factory=list)
    canonical_content: Any = Field(
        ...,
        description=(
            "The component's substance. May be a string, structured dict, or list. "
            "Format-agnostic — downstream spec layer handles delivery-format rendering."
        ),
    )


class AssessmentOption(BaseModel):
    """
    One option in a multiple-choice assessment item.

    Each option carries its own correctness flag, targeted misconception (if
    any), and specific feedback. This is what enables diagnostic autograding:
    a wrong answer maps to a specific misconception, and the learner sees
    feedback calibrated to that specific error.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Local option ID within the item (e.g. 'A', 'B').")
    text: str
    correct: bool
    misconception_targeted: Optional[str] = Field(
        None, description="Misconception ID this option represents, if any."
    )
    feedback: str = Field(..., description="Learner-facing feedback specific to this option.")
    evidence_refs: list[str] = Field(default_factory=list)


class AssessmentItem(BaseModel):
    """
    A single assessment item.

    MCQ items use options[] with per-option feedback. Open-response items use
    correct_response + scoring_criteria + feedback_guidance for rubric-based
    grading downstream.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    stem: str = Field(..., description="The question or scenario presented to the learner.")
    type: AssessmentType
    concepts_assessed: list[str] = Field(
        ..., min_length=1, description="Concept IDs this item assesses."
    )
    evidence_refs: list[str] = Field(default_factory=list)

    # MCQ-specific
    options: Optional[list[AssessmentOption]] = Field(
        None, description="Required for MCQ types. Must include at least one correct option."
    )

    # Open-response-specific
    correct_response: Optional[str] = Field(
        None, description="Required for open_response items. Rubric-style description of a full-credit answer."
    )
    scoring_criteria: Optional[str] = Field(
        None, description="For open_response items: how to award partial credit."
    )
    feedback_guidance: Optional[str] = Field(
        None, description="For open_response items: guidance to a human or model scorer on how to respond to common errors."
    )

    aligned_to_performance_level: Optional[PerformanceLevel] = Field(
        None, description="Optional: the performance level this item specifically targets."
    )

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> "AssessmentItem":
        if self.type in {AssessmentType.MULTIPLE_CHOICE_SINGLE, AssessmentType.MULTIPLE_CHOICE_MULTI}:
            if not self.options or len(self.options) < 2:
                raise ValueError(f"Item {self.id}: MCQ items require at least 2 options.")
            correct_count = sum(1 for opt in self.options if opt.correct)
            if correct_count == 0:
                raise ValueError(f"Item {self.id}: MCQ items require at least one correct option.")
            if self.type == AssessmentType.MULTIPLE_CHOICE_SINGLE and correct_count != 1:
                raise ValueError(
                    f"Item {self.id}: multiple_choice_single requires exactly one correct option "
                    f"(found {correct_count})."
                )
        elif self.type == AssessmentType.OPEN_RESPONSE:
            if not self.correct_response:
                raise ValueError(f"Item {self.id}: open_response items require correct_response.")
        return self


class EnablingObjective(BaseModel):
    """
    The single enabling objective for this RLO.

    Exactly one per RLO — this is the composability constraint that keeps RLOs
    atomic and recombinable.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str = Field(..., description="What the learner will be able to do after this RLO.")
    bloom_level: BloomLevel
    concepts_addressed: list[str] = Field(
        ..., min_length=1, description="Concept IDs this objective covers."
    )
    evidence_refs: list[str] = Field(default_factory=list)


class DesignBrief(BaseModel):
    """
    Authoring guidance for downstream spec-layer authors.

    Not delivered to learners. Describes the intended tone, scaffolding,
    feedback policy, and shape of examples and practice so that spec-layer
    tooling (or human authors converting to a delivery format) preserves
    the pedagogical intent.
    """

    model_config = ConfigDict(extra="forbid")

    tone: str = Field(..., description="Intended voice and register of the delivered content.")
    scaffolding_level: ScaffoldingLevel
    scaffolding_notes: str = Field(..., description="What prior knowledge to assume; what to re-teach vs. not.")
    feedback_policy: str = Field(
        ..., description="How feedback should be constructed — what it must name and what it must not do."
    )
    example_shape_hints: list[str] = Field(
        default_factory=list,
        description="Guidance on how examples should be structured or what they must cover.",
    )
    practice_shape_hints: list[str] = Field(
        default_factory=list,
        description="Guidance on how practice items should be structured.",
    )
    salience_hook_description: str = Field(
        ..., description="What the hook should establish for the learner and why."
    )


class GagneEventMapping(BaseModel):
    """
    Mapping from Gagne's Nine Events of Instruction to component IDs.

    Each event either references a component ID / list of IDs, references a
    top-level RLO field (e.g., 'terminal_objective'), or contains a note
    explaining how the event is handled elsewhere (typically at learning-path
    level for events like 'enhance retention and transfer').
    """

    model_config = ConfigDict(extra="forbid")

    event_1_gain_attention: str | list[str] | None = None
    event_2_inform_objective: str | list[str] | None = None
    event_3_stimulate_recall: str | list[str] | None = None
    event_4_present_content: str | list[str] | None = None
    event_5_provide_guidance: str | list[str] | None = None
    event_6_elicit_performance: str | list[str] | None = None
    event_7_provide_feedback: str | list[str] | None = None
    event_8_assess_performance: str | list[str] | None = None
    event_9_enhance_retention: str | list[str] | None = None


class ContentTypeRecommendation(BaseModel):
    """
    A recommended delivery format for this RLO with rationale.

    Distinct from RLO-level content_type (Merrill classification of substance):
    this describes how the substance is best delivered downstream.
    """

    model_config = ConfigDict(extra="forbid")

    format: str = Field(
        ...,
        description=(
            "Free-text format name, e.g. 'flashcard_deck', 'short_video', 'diagnostic_case_module'. "
            "Kept as free text because delivery format inventory evolves faster than schema."
        ),
    )
    rationale: str
    priority: ContentRecommendationPriority


class VariantExampleAnnotation(BaseModel):
    """A structured annotation on a variant example."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., description="e.g. 'signals_present', 'scope_implication'.")
    text: str


class VariantExample(BaseModel):
    """
    An optional pre-authored variant of a canonical example, tagged for
    downstream selection by industry, service line, or role.

    Distinct from examples embedded inside components (which are the canonical
    treatment). Variants are opt-in: authors may add them when specific audience
    tailoring is worth authoring upstream rather than deferring to the spec
    layer.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    type: ExampleVariantType
    concepts_referenced: list[str] = Field(
        ..., min_length=1, description="Concept IDs this example illustrates."
    )
    industry_tags: list[str] = Field(default_factory=list)
    service_line_tags: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    content: Any = Field(..., description="The example itself (string or structured).")
    annotations: list[VariantExampleAnnotation] = Field(default_factory=list)


class Governance(BaseModel):
    """
    Lifecycle, ownership, and review metadata.

    Adopted from G&D's schema. Kept as a nested block so pedagogical authors
    can focus on the substance while governance owners maintain this block
    separately.
    """

    model_config = ConfigDict(extra="forbid")

    status: RLOStatus
    authoring_sme: str
    reviewing_sme: Optional[str] = None
    signoff_date: Optional[date] = None
    signoff_authority: Optional[str] = None
    review_cadence_months: Optional[int] = Field(None, ge=1)
    next_review_date: Optional[date] = None
    change_history: str = Field(
        ..., description="Human-readable arrow-chained version history."
    )

    @model_validator(mode="after")
    def _validate_signoff_consistency(self) -> "Governance":
        if self.status in (RLOStatus.APPROVED, RLOStatus.SIGNED):
            if not self.signoff_date or not self.signoff_authority:
                raise ValueError(
                    "status='approved' requires both signoff_date and signoff_authority."
                )
        return self


class Accessibility(BaseModel):
    """Accessibility claims for the RLO."""

    model_config = ConfigDict(extra="forbid")

    features: list[str] = Field(
        default_factory=list,
        description=(
            "e.g. 'plain_language', 'alt_text_provided', "
            "'screen_reader_optimised_structure', 'captions_available'."
        ),
    )
    wcag_conformance: Optional[WCAGConformance] = None


class Rights(BaseModel):
    """IP, usage rights, and sharing constraints."""

    model_config = ConfigDict(extra="forbid")

    rights: str = Field(..., description="Usage rights, e.g. 'internal_use_all_service_lines'.")
    sharing_constraints: str = Field(
        ..., description="Distribution constraints, e.g. 'internal only, not for external distribution'."
    )


# =============================================================================
# TOP-LEVEL RLO
# =============================================================================


class RLO(BaseModel):
    """
    Reusable Learning Object.

    Combines:
    - Substance: concepts, components (CDT-typed), misconceptions,
      assessments (with diagnostic per-option feedback), canonical + variant
      examples
    - Pedagogical scaffolding: single enabling objective, design brief,
      Gagne mapping, authoring rationale
    - Targeting: content type (Merrill), performance level, Bloom level,
      audience level, role/industry/service-line/competency/regulatory tags
    - Governance: status, signoff, review cadence, change history
    - Accessibility & rights

    Design invariants (enforced by model_validator below):
    - Exactly one enabling_objective
    - All ID references (source_refs, concepts_referenced, concepts_addressed,
      concepts_assessed, misconceptions_addressed, misconception_targeted,
      component IDs referenced from gagne_event_mapping) resolve to declared IDs
    - Component and concept IDs are unique within the RLO
    - MCQ assessment items are structurally valid (see AssessmentItem)
    - approved RLOs have signoff metadata (see Governance)
    """

    model_config = ConfigDict(extra="forbid")

    # --- Identity ---
    id: str = Field(..., description="RLO identifier, e.g. 'rlo-adkar-04-awareness'.")
    version: str = Field(..., description="Semver, e.g. '1.0.0'.")
    schema_version: str = Field(
        default="1.0.0",
        description="Version of this RLO schema the document conforms to.",
    )
    authoring_revision_id: Optional[str] = Field(
        None,
        description="Immutable seven-part authoring revision used to publish this catalog RLO.",
    )
    language: str = Field(default="en", description="ISO 639-1 language code.")
    locale: str = Field(default="en-US", description="BCP 47 locale.")

    # --- Descriptive ---
    title: str
    topic: str = Field(..., description="Human-readable topic label.")
    domain: str = Field(..., description="Subject domain, e.g. 'Organizational Change Management'.")
    level: Level
    audience: list[str] = Field(
        default_factory=list, description="Free-text audience descriptors."
    )
    estimated_duration_minutes: Optional[int] = Field(None, ge=1)

    # --- Classification (multiple orthogonal taxonomies) ---
    content_type: ContentType = Field(
        ..., description="Merrill classification: what kind of thing this RLO teaches."
    )
    performance_level: Optional[PerformanceLevel] = Field(
        None, description="Behavioral performance level. Complements bloom_level in enabling_objective."
    )

    # --- Sequencing ---
    prerequisites: list[str] = Field(
        default_factory=list, description="RLO IDs the learner should complete first."
    )
    corequisites: list[str] = Field(
        default_factory=list, description="RLO IDs the learner should engage alongside this one."
    )
    follow_ons: list[str] = Field(
        default_factory=list, description="RLO IDs recommended after this one."
    )
    related_rlos: list[str] = Field(
        default_factory=list,
        description="RLO IDs that are topically related but not prerequisite / corequisite / follow-on.",
    )

    # --- Sources ---
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Claim-level evidence ledger; source_refs remains bibliographic.",
    )

    # --- Objectives ---
    terminal_objective: Optional[str] = Field(
        None,
        description=(
            "Optional broader outcome this RLO supports. The enabling objective remains "
            "the RLO's assessable boundary."
        ),
    )
    performance_context: str = Field(
        ..., description="Where and when the learner would apply this in real work."
    )
    enabling_objective: EnablingObjective = Field(
        ..., description="Exactly one enabling objective per RLO (composability constraint)."
    )

    # --- Substance ---
    concepts: list[Concept] = Field(..., min_length=1)
    components: list[Component] = Field(..., min_length=1)
    assessment_items: list[AssessmentItem] = Field(..., min_length=1)

    # --- Optional pre-authored variants ---
    variant_examples: list[VariantExample] = Field(
        default_factory=list,
        description=(
            "Optional pre-authored variant examples tagged for downstream selection. "
            "Authors may leave this empty and defer all variant selection to the spec layer."
        ),
    )

    # --- Authoring scaffolding ---
    design_brief: DesignBrief
    gagne_event_mapping: GagneEventMapping
    content_type_recommendations: list[ContentTypeRecommendation] = Field(
        default_factory=list,
        description="Recommended delivery formats for this RLO.",
    )
    authoring_rationale: str = Field(
        ..., description="Why this RLO exists and what its specific instructional payload is."
    )

    # --- Targeting ---
    role_tags: list[str] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    service_line_tags: list[str] = Field(default_factory=list)
    competency_map: list[str] = Field(default_factory=list)
    regulatory_tags: list[str] = Field(default_factory=list)

    # --- Governance, accessibility, rights ---
    governance: Governance
    accessibility: Accessibility = Field(default_factory=Accessibility)
    rights: Optional[Rights] = None

    # -------------------------------------------------------------------------
    # Structural validators — enforce the diagnostic-thread invariants
    # -------------------------------------------------------------------------

    @field_validator("concepts")
    @classmethod
    def _concept_ids_unique(cls, v: list[Concept]) -> list[Concept]:
        ids = [c.id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Concept IDs must be unique within the RLO.")
        # Misconception IDs must be unique across the RLO (not just per concept),
        # since they are referenced globally from components and assessment options.
        misc_ids = [m.id for c in v for m in c.misconceptions]
        if len(misc_ids) != len(set(misc_ids)):
            raise ValueError("Misconception IDs must be unique across the RLO.")
        return v

    @field_validator("components")
    @classmethod
    def _component_ids_unique(cls, v: list[Component]) -> list[Component]:
        ids = [c.id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Component IDs must be unique within the RLO.")
        return v

    @field_validator("assessment_items")
    @classmethod
    def _assessment_ids_unique(cls, v: list[AssessmentItem]) -> list[AssessmentItem]:
        ids = [a.id for a in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Assessment item IDs must be unique within the RLO.")
        return v

    @field_validator("evidence")
    @classmethod
    def _evidence_ids_unique(cls, v: list[Evidence]) -> list[Evidence]:
        ids = [item.id for item in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique within the RLO.")
        return v

    @field_validator("sources")
    @classmethod
    def _source_ids_unique(cls, v: list[Source]) -> list[Source]:
        ids = [source.id for source in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Source IDs must be unique within the RLO.")
        return v

    @model_validator(mode="after")
    def _cross_reference_integrity(self) -> "RLO":
        concept_ids = {c.id for c in self.concepts}
        misconception_ids = {m.id for c in self.concepts for m in c.misconceptions}
        component_ids = {c.id for c in self.components}
        source_ids = {s.id for s in self.sources}
        evidence_by_id = {item.id: item for item in self.evidence}
        source_by_id = {source.id: source for source in self.sources}

        for item in self.evidence:
            source = source_by_id.get(item.source_ref)
            if source is None:
                raise ValueError(
                    f"Evidence {item.id} references unknown source '{item.source_ref}'."
                )
            if source.source_version_id is None:
                raise ValueError(
                    f"Evidence {item.id} requires ingested identity on source '{item.source_ref}'."
                )
            if item.source_version_id != source.source_version_id:
                raise ValueError(
                    f"Evidence {item.id} source version does not match source '{item.source_ref}'."
                )

        def _check_evidence_refs(owner: str, refs: list[str], *, assessable: bool = False) -> None:
            for evidence_ref in refs:
                evidence = evidence_by_id.get(evidence_ref)
                if evidence is None:
                    raise ValueError(f"{owner} references unknown evidence '{evidence_ref}'.")
                if assessable and evidence.role != EvidenceRole.OBJECTIVE_DEFINING:
                    raise ValueError(
                        f"{owner} cannot use supporting-context evidence '{evidence_ref}' "
                        "to define assessment scope."
                    )

        _check_evidence_refs(
            "enabling_objective", self.enabling_objective.evidence_refs, assessable=True
        )

        # Concepts -> sources
        for c in self.concepts:
            for sref in c.source_refs:
                if sref not in source_ids:
                    raise ValueError(
                        f"Concept {c.id} references unknown source '{sref}'."
                    )
            _check_evidence_refs(f"Concept {c.id}", c.evidence_refs)
            for misconception in c.misconceptions:
                _check_evidence_refs(
                    f"Misconception {misconception.id}", misconception.evidence_refs
                )

        # Enabling objective -> concepts
        for cref in self.enabling_objective.concepts_addressed:
            if cref not in concept_ids:
                raise ValueError(
                    f"enabling_objective references unknown concept '{cref}'."
                )

        # Components -> concepts, misconceptions
        for comp in self.components:
            _check_evidence_refs(f"Component {comp.id}", comp.evidence_refs)
            for cref in comp.concepts_referenced:
                if cref not in concept_ids:
                    raise ValueError(
                        f"Component {comp.id} references unknown concept '{cref}'."
                    )
            for mref in comp.misconceptions_addressed:
                if mref not in misconception_ids:
                    raise ValueError(
                        f"Component {comp.id} references unknown misconception '{mref}'."
                    )

        # Assessment items -> concepts; options -> misconceptions
        for item in self.assessment_items:
            _check_evidence_refs(f"Assessment {item.id}", item.evidence_refs, assessable=True)
            for cref in item.concepts_assessed:
                if cref not in concept_ids:
                    raise ValueError(
                        f"Assessment {item.id} references unknown concept '{cref}'."
                    )
            for opt in item.options or []:
                _check_evidence_refs(
                    f"Assessment {item.id} option {opt.id}",
                    opt.evidence_refs,
                    assessable=True,
                )
                if opt.misconception_targeted and opt.misconception_targeted not in misconception_ids:
                    raise ValueError(
                        f"Assessment {item.id} option {opt.id} targets unknown misconception "
                        f"'{opt.misconception_targeted}'."
                    )

        # Variant examples -> concepts
        for ve in self.variant_examples:
            for cref in ve.concepts_referenced:
                if cref not in concept_ids:
                    raise ValueError(
                        f"Variant example {ve.id} references unknown concept '{cref}'."
                    )

        # Gagne mapping -> component IDs (only when the value looks like a component ID)
        # Values may be component IDs, top-level field names (e.g. 'terminal_objective'),
        # or free-text notes. We only validate ID-shaped strings that look like component references.
        def _check_gagne_ref(value: str | list[str] | None) -> None:
            if value is None:
                return
            candidates = value if isinstance(value, list) else [value]
            for cand in candidates:
                # Heuristic: if the string starts with 'comp-' or matches a known component ID exactly,
                # it must resolve to a declared component ID.
                if cand.startswith("comp-") and cand not in component_ids:
                    raise ValueError(
                        f"gagne_event_mapping references unknown component '{cand}'."
                    )

        for evt in (
            self.gagne_event_mapping.event_1_gain_attention,
            self.gagne_event_mapping.event_2_inform_objective,
            self.gagne_event_mapping.event_3_stimulate_recall,
            self.gagne_event_mapping.event_4_present_content,
            self.gagne_event_mapping.event_5_provide_guidance,
            self.gagne_event_mapping.event_6_elicit_performance,
            self.gagne_event_mapping.event_7_provide_feedback,
            self.gagne_event_mapping.event_8_assess_performance,
            self.gagne_event_mapping.event_9_enhance_retention,
        ):
            _check_gagne_ref(evt)

        return self
