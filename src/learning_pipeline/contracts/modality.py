from __future__ import annotations

from pydantic import model_validator

from .common import FrozenModel, Modality


PresentationCapability = str
"""
A presentation format name from the active ModalityCapabilityEnvelope.
Values are format-level labels (e.g. "narrated_explanation") — never
executor task types or vendor identifiers.
"""


class RLOContentRef(FrozenModel):
    """
    Pointer from a modality scene back to the source RLO content that
    motivates it.  Enables lineage tracing from any production asset back
    to a specific instructional element in the canonical RLO.
    """

    rlo_id: str
    rlo_version: str
    objective_ids: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    component_ids: tuple[str, ...] = ()
    assessment_item_ids: tuple[str, ...] = ()


class ModalityScene(FrozenModel):
    """
    One instructional beat within a ModalityPlan.

    Contains a teaching pattern, the preferred presentation capability,
    optional fallbacks, source-content references for lineage tracing,
    and directional guidance for content generation.
    """

    id: str
    source_content: tuple[RLOContentRef, ...]

    learning_objective: str
    teaching_pattern: str
    preferred_capability: PresentationCapability
    acceptable_fallbacks: tuple[PresentationCapability, ...] = ()

    content_direction: str
    target_duration_seconds: int | None = None

    # Phase 10 — filled by PodcastModalityPlanBuilder; optional for backward compat.
    narrative_role: str | None = None
    learner_engagement: str | None = None
    transition_direction: str | None = None

    # Phase 13C — what the viewer sees; filled by VideoModalityPlanBuilder.
    presentation_direction: str | None = None

    @model_validator(mode="after")
    def source_content_not_empty(self) -> ModalityScene:
        if not self.source_content:
            raise ValueError("source_content must reference at least one RLO content item")
        return self


class ModalityPlan(FrozenModel):
    """
    Modality-specific teaching design.

    Created by:
        ModalityPlanner

    Consumed by:
        WorkflowPlanner

    Contains:
        Scenes with teaching patterns, source-content references, timing
        guidance, and preferred presentation capabilities.  The modality
        field declares the delivery channel (video, podcast, e-learning).

    Does not contain:
        Vendor API calls, credentials, executor implementations, rendered
        assets, or production job details.
    """

    plan_id: str
    modality: Modality
    narrative: str
    scenes: tuple[ModalityScene, ...]
