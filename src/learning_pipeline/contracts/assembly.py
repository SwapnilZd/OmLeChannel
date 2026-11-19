from __future__ import annotations

from pydantic import Field, model_validator

from .common import (
    PROFICIENCY_ORDER,
    ContentDepth,
    FrozenModel,
    TopicProficiency,
)
from .learner import LearnerContext


class RLOContentSelection(FrozenModel):
    """
    Reference-based overlay declaring which content items within an RLO are
    included in a tailored ref.  When all four fields are empty, the full RLO
    is selected. Once any field contains an ID, empty categories select nothing
    from those categories.
    """

    objective_ids: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    component_ids: tuple[str, ...] = ()
    assessment_item_ids: tuple[str, ...] = ()


class TailoredRLORef(FrozenModel):
    """
    Links an RLODocument to its position and instructional intent inside a
    CourseBlueprint.  References the source by ID and exact version so the
    blueprint is a deterministic snapshot.
    """

    rlo_id: str
    rlo_version: str
    order: int

    selected_content: RLOContentSelection

    starting_proficiency: TopicProficiency
    target_proficiency: TopicProficiency
    content_depth: ContentDepth = ContentDepth.WORKING

    role_relevance: str
    example_context: str | None = None
    personalization_rationale: str
    sequencing_rationale: str
    adaptation_instructions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def target_must_not_regress(self) -> TailoredRLORef:
        if PROFICIENCY_ORDER[self.target_proficiency] < PROFICIENCY_ORDER[self.starting_proficiency]:
            raise ValueError(
                f"target_proficiency '{self.target_proficiency}' cannot be lower than "
                f"starting_proficiency '{self.starting_proficiency}'"
            )
        return self


class CourseBlueprint(FrozenModel):
    """
    Personalized content scope and sequence for one learner.

    Created by:
        CurriculumPlanner

    Consumed by:
        ModalityContextResolver (to load and validate source RLOs)
        ModalityPlanner (via ModalityPlanningContext)

    Contains:
        Ordered, tailored references to RLOs; learner context; proficiency
        progression per RLO; sequencing and assessment strategy; version
        traceability for all source RLOs.

    Does not contain:
        Rendered content, modality-specific scene structures, production
        capabilities, or executor details.
    """

    blueprint_id: str
    learner: LearnerContext
    title: str
    learning_outcomes: tuple[str, ...]
    ordered_rlo_refs: tuple[TailoredRLORef, ...]
    prerequisite_bridges: tuple[str, ...] = ()
    brand_contract: dict[str, str] = Field(default_factory=dict)

    sequencing_rationale: str
    assessment_strategy: str
    estimated_duration_minutes: int = Field(gt=0)
    source_rlo_versions: dict[str, str]

    @model_validator(mode="after")
    def validate_rlo_refs(self) -> CourseBlueprint:
        orders = [ref.order for ref in self.ordered_rlo_refs]
        if len(set(orders)) != len(orders):
            raise ValueError("ordered_rlo_refs order values must be unique")
        for o in orders:
            if o <= 0:
                raise ValueError(f"ordered_rlo_refs order must be positive, got {o}")
        expected = {ref.rlo_id: ref.rlo_version for ref in self.ordered_rlo_refs}
        if dict(self.source_rlo_versions) != expected:
            raise ValueError(
                "source_rlo_versions must contain exactly {rlo_id: rlo_version} "
                "for every TailoredRLORef"
            )
        return self
