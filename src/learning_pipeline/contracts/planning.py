"""
Planning contracts — Phase 9 + Phase 10 + Phase 13B.

Separation of concerns
-----------------------
ResolvedPlanningContext     — Workflow Planner input (Phase 9)
PodcastProductionDraft      — Workflow Planner LLM output (Phase 9)
PlanningTrace               — Workflow Planner audit record (Phase 9)
WorkflowPlanningResult      — WorkflowPlanningService surface (Phase 9)

NarrativeRole               — vocabulary for scene narrative roles (Phase 10)
PodcastSceneDraft           — Modality Planner LLM output, per scene (Phase 10)
PodcastModalityDraft        — Modality Planner LLM output, top-level (Phase 10)
ResolvedRLOContext          — per-RLO resolved content for the Modality Planner (Phase 10)
ModalityPlanningContext     — Modality Planner full input context (Phase 10)
ModalityCoverageReport      — coverage validation result (Phase 10)
ModalityPlanningTrace       — Modality Planner audit record (Phase 10)
ModalityPlanningResult      — ModalityPlanningService surface (Phase 10)

VideoProductionDraft        — Workflow Planner LLM output for video (Phase 13B)
AvatarVideoSceneDraft       — One scene within a VideoProductionDraft (Phase 13B)
ColorBackgroundDraft        — Solid-colour background spec (Phase 13B)
ExistingAssetBackgroundDraft — Pre-existing asset background spec (Phase 13B)
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .common import FrozenModel, Modality
from .learner import LearnerContext
from .modality import ModalityPlan, RLOContentRef
from .production import ModalityProductionPlan
from .execution import BuildPlan
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    CourseStructureRequirement,
    VideoSlotRequirement,
)


# ── Resolved planning context ─────────────────────────────────────────────────


class ResolvedContentItem(FrozenModel):
    """
    One extracted instructional element from an RLO, resolved to plain text.

    Sent to the Workflow Planner so it can make semantic decisions about
    what to include in each segment.  IDs are preserved for lineage tracing.
    """

    rlo_id: str
    rlo_version: str
    content_type: Literal["objective", "concept", "component", "assessment_item"]
    content_id: str
    title: str | None = None
    content: str
    source_refs: tuple[str, ...] = ()


class ResolvedSceneContext(FrozenModel):
    """
    The resolved instructional content for one modality scene.

    Gives the Workflow Planner a scene-level view: what the scene must
    achieve, and exactly which source content items to draw from.
    """

    scene_id: str
    learning_objective: str
    teaching_pattern: str
    target_duration_seconds: int | None = None
    content_items: tuple[ResolvedContentItem, ...]


class ResolvedPlanningContext(FrozenModel):
    """
    Complete, self-contained planning input for one WorkflowPlanner call.

    Contains learner context, brand requirements, and per-scene source
    content.  This is the only structured data the Workflow Planner
    receives — it must not retrieve additional mutable RLO content
    during planning.
    """

    blueprint_id: str
    learner: LearnerContext
    scenes: tuple[ResolvedSceneContext, ...]
    brand_contract: dict[str, str] = Field(default_factory=dict)
    accessibility_requirements: tuple[str, ...] = ()
    design_tone: str = ""
    adaptation_instructions: tuple[str, ...] = ()


# ── Podcast production draft ──────────────────────────────────────────────────


class PodcastSpeechSegmentDraft(FrozenModel):
    """
    One spoken segment as decided by the Workflow Planner.

    The LLM populates this; deterministic code converts it to a
    ProductionJob.  The LLM must not set task IDs, output keys, or
    dependency edges — those are the builder's responsibility.
    """

    segment_id: str = Field(min_length=1)
    source_scene_ids: tuple[str, ...] = Field(min_length=1)
    speaker: Literal["Host", "Expert"]
    text: str = Field(min_length=1)
    learning_purpose: str = Field(min_length=1)
    pause_after_seconds: float = Field(0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_segment(self) -> PodcastSpeechSegmentDraft:
        if not self.segment_id.strip():
            raise ValueError("segment_id must not be blank")
        if not self.text.strip():
            raise ValueError("text must not be blank")
        return self


class OmittedScene(FrozenModel):
    """
    Explicit record when the planner intentionally omits a modality scene.

    The planner must account for every scene — either by covering it in
    at least one segment or by recording a deliberate omission here.
    """

    scene_id: str
    rationale: str = Field(min_length=1)


class PodcastProductionDraft(FrozenModel):
    """
    Structured LLM output for podcast Workflow Planning.

    The LLM makes semantic decisions:
      - what each segment says;
      - which speaker delivers each segment;
      - how scenes map to segments;
      - where pauses belong.

    Deterministic code makes structural decisions:
      - job IDs and task types;
      - dependency wiring;
      - output key bindings;
      - assembly segment order.
    """

    draft_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    narrative_summary: str = Field(min_length=1)
    segments: tuple[PodcastSpeechSegmentDraft, ...] = Field(min_length=1)
    omitted_scenes: tuple[OmittedScene, ...] = ()
    default_gap_seconds: float = Field(0.35, ge=0.0, le=1.0)
    output_filename: str | None = None

    @model_validator(mode="after")
    def _validate_draft(self) -> PodcastProductionDraft:
        ids = [seg.segment_id for seg in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("segment_ids must be unique across the draft")
        if self.output_filename is not None:
            name = self.output_filename
            if any(sep in name for sep in ("/", "\\", "..")) or not name.strip():
                raise ValueError(
                    "output_filename must not contain path separators or be blank"
                )
        return self


# ── Structured planning client ────────────────────────────────────────────────


class StructuredPlanningResponse(FrozenModel):
    """
    Typed wrapper around a structured planning client response.

    Preserves provider metadata alongside the validated result for audit.
    """

    result: Any
    model: str
    prompt_version: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


# ── Planning trace ────────────────────────────────────────────────────────────


class PlanningTrace(FrozenModel):
    """
    Immutable audit record for one planning operation.

    Persisted alongside the generated plans so any planning decision can
    be reproduced from the same inputs and prompt.
    """

    planning_request_id: str
    planner_type: str
    modality: Modality
    prompt_version: str
    model: str | None
    input_hash: str
    capability_catalog_hash: str
    production_plan_hash: str
    build_plan_hash: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


# ── Service result ────────────────────────────────────────────────────────────


class WorkflowPlanningResult(FrozenModel):
    """
    Surface returned to the caller of WorkflowPlanningService.

    Contains the production plan, compiled build plan, and planning
    trace.  The caller decides whether to submit the build plan for
    execution — the service does not do so automatically.
    """

    production_plan: ModalityProductionPlan
    build_plan: BuildPlan
    trace: PlanningTrace
    from_cache: bool = False


# ── Phase 10: Modality Planner contracts ──────────────────────────────────────


class NarrativeRole(StrEnum):
    """Vocabulary for the pedagogical role a scene plays in the learning journey.

    Answers: *why does this scene exist?*  Separate from affordance_id, which
    answers *how is the scene presented in the chosen modality?*
    """

    HOOK = "hook"
    ORIENTATION = "orientation"
    ACTIVATE_PRIOR_KNOWLEDGE = "activate_prior_knowledge"
    EXPLANATION = "explanation"
    EXAMPLE = "example"
    APPLICATION = "application"
    PRACTICE = "practice"
    ASSESSMENT = "assessment"
    REFLECTION = "reflection"
    SUMMARY = "summary"
    TRANSITION = "transition"


class PodcastSceneDraft(FrozenModel):
    """
    One modality scene as decided by the Podcast Modality Planner.

    The LLM populates this; deterministic code converts it to a ModalityScene.
    The LLM must not write final dialogue, create production jobs, or reference
    executor-internal details.
    """

    scene_id: str = Field(min_length=1)
    source_content: tuple[RLOContentRef, ...] = Field(min_length=1)
    learning_objective: str = Field(min_length=1)
    narrative_role: NarrativeRole
    affordance_id: str = Field(min_length=1)
    teaching_pattern: str = Field(min_length=1)
    content_direction: str = Field(min_length=1)
    learner_engagement: str | None = None
    transition_direction: str | None = None
    target_duration_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def _validate_scene(self) -> PodcastSceneDraft:
        if not self.scene_id.strip():
            raise ValueError("scene_id must not be blank")
        return self


class PodcastModalityDraft(FrozenModel):
    """
    Structured LLM output for podcast Modality Planning.

    The LLM decides scene breakdown, narrative role, pedagogical affordance,
    content direction, and duration allocation.  It must not write final
    dialogue, create production tasks, or reference tool internals.
    """

    draft_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    scenes: tuple[PodcastSceneDraft, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_draft(self) -> PodcastModalityDraft:
        ids = [s.scene_id for s in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("scene_ids must be unique across the draft")
        return self


class ResolvedRLOContext(FrozenModel):
    """
    All resolved and selected content from one RLO, in planner-safe form.

    Built by ModalityContextResolver from a TailoredRLORef + RLODocument.
    """

    rlo_id: str
    rlo_version: str
    order: int
    title: str
    topic: str
    terminal_objective_text: str | None
    enabling_objectives: tuple[ResolvedContentItem, ...]
    concepts: tuple[ResolvedContentItem, ...]
    components: tuple[ResolvedContentItem, ...]
    assessment_items: tuple[ResolvedContentItem, ...]
    selected_objective_ids: tuple[str, ...]
    selected_concept_ids: tuple[str, ...]
    selected_component_ids: tuple[str, ...]
    selected_assessment_ids: tuple[str, ...]
    role_relevance: str
    example_context: str | None
    adaptation_instructions: tuple[str, ...]


class ModalityPlanningContext(FrozenModel):
    """
    Complete, self-contained planning input for one ModalityPlanner call.

    Contains learner context, brand requirements, and per-RLO source content
    in blueprint order.  This is the only structured data the Modality Planner
    receives — it must not retrieve additional RLO content during planning.
    """

    blueprint_id: str
    learner: LearnerContext
    rlo_contexts: tuple[ResolvedRLOContext, ...]
    prerequisite_bridges: tuple[str, ...] = ()
    assessment_strategy: str = ""
    brand_contract: dict[str, str] = Field(default_factory=dict)
    accessibility_requirements: tuple[str, ...] = ()
    design_tone: str = ""
    estimated_duration_minutes: int = 0


class ModalityCoverageReport(FrozenModel):
    """
    Result of deterministic coverage validation for a ModalityPlan.

    Records which blueprint-selected content IDs are covered by scenes and
    which are absent.  Planning fails when required content is uncovered.
    """

    covered_objective_ids: tuple[str, ...] = ()
    covered_concept_ids: tuple[str, ...] = ()
    covered_component_ids: tuple[str, ...] = ()
    covered_assessment_ids: tuple[str, ...] = ()
    uncovered_objective_ids: tuple[str, ...] = ()
    uncovered_concept_ids: tuple[str, ...] = ()
    uncovered_component_ids: tuple[str, ...] = ()
    uncovered_assessment_ids: tuple[str, ...] = ()
    duplicate_coverage_warnings: tuple[str, ...] = ()


class ModalityPlanningTrace(FrozenModel):
    """
    Immutable audit record for one Modality Planning operation.

    Persisted alongside the generated plan so any planning decision can be
    reproduced from the same inputs and prompt.
    """

    planning_request_id: str
    planner_type: str
    modality: Modality
    prompt_version: str
    model: str | None
    blueprint_hash: str
    context_hash: str
    affordance_view_hash: str
    modality_plan_hash: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    validation_summary: str = ""


class ModalityPlanningResult(FrozenModel):
    """
    Surface returned to the caller of ModalityPlanningService.

    Contains the modality plan, coverage report, and planning trace.
    The caller decides whether to pass the plan to the Workflow Planner.
    """

    modality_plan: ModalityPlan
    coverage: ModalityCoverageReport
    trace: ModalityPlanningTrace
    from_cache: bool = False


# ── Phase 13B: Video production draft ────────────────────────────────────────

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class VideoBackgroundDraft(FrozenModel):
    """Background for an avatar-video scene.

    Flat model (no discriminated union) so the JSON schema contains no ``oneOf``,
    which is required for structured-output compatibility with hosted LLM APIs.

    - kind="color":          set ``color`` to a 6-digit hex string like ``#1A1A2E``
    - kind="existing_asset": set ``asset_id`` to a logical asset identifier from
                             the planner-safe asset catalog
    """

    kind: Literal["color", "existing_asset"]
    color: str | None = None
    asset_id: str | None = None

    @model_validator(mode="after")
    def _validate_background(self) -> "VideoBackgroundDraft":
        if self.kind == "color":
            if self.color is None:
                raise ValueError("color is required when kind='color'")
            if not _HEX_COLOR_RE.match(self.color):
                raise ValueError(
                    f"color must be a 6-digit hex string like '#1A1A2E'; got '{self.color}'"
                )
        elif self.kind == "existing_asset":
            if not self.asset_id:
                raise ValueError("asset_id is required when kind='existing_asset'")
        return self




class AvatarVideoSceneDraft(FrozenModel):
    """
    One avatar-video render scene as decided by the Workflow Planner.

    The LLM populates this; deterministic code converts it to an
    AvatarVideoScene input for the video.avatar.render capability.

    The LLM must write the final spoken narration in ``script``.
    It must not insert stage directions, Markdown formatting, or
    provider-specific instructions.
    """

    scene_id: str = Field(min_length=1)
    source_scene_ids: tuple[str, ...] = Field(min_length=1)
    title: str | None = None
    script: str = Field(min_length=1)
    background: VideoBackgroundDraft
    estimated_duration_seconds: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _validate_scene(self) -> "AvatarVideoSceneDraft":
        if not self.scene_id.strip():
            raise ValueError("scene_id must not be blank")
        if not self.script.strip():
            raise ValueError("script must not be blank")
        return self


class VideoProductionDraft(FrozenModel):
    """
    Structured LLM output for video Workflow Planning — Phase 13B.

    The LLM makes semantic decisions:
      - final spoken narration for each render scene;
      - scene-to-render-scene mapping;
      - background treatment per scene;
      - logical avatar and voice profile selection;
      - caption intent;
      - estimated scene timing.

    Deterministic code makes structural decisions:
      - production job ID and capability;
      - input bindings and output keys;
      - artifact URI resolution;
      - accessibility enforcement.
    """

    draft_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    narrative_summary: str = Field(min_length=1)

    render_capability: str = Field(min_length=1)
    avatar_profile: str = Field(min_length=1)
    voice_profile: str = Field(min_length=1)

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    captions: bool = False

    scenes: tuple[AvatarVideoSceneDraft, ...] = Field(min_length=1)
    production_rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_draft(self) -> "VideoProductionDraft":
        ids = [s.scene_id for s in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("scene_ids must be unique across the draft")
        return self


# ── Phase 13C: Video modality-planner contracts ───────────────────────────────


class ModalityAssetSummary(FrozenModel):
    """
    Planner-safe summary of one approved existing visual asset.

    The Modality Planner may reference the logical asset_id in its
    presentation direction.  Physical file paths, storage credentials,
    temporary URLs, and provider-specific IDs are never included here.
    """

    asset_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    concept_ids: tuple[str, ...] = ()
    suitable_uses: tuple[str, ...] = ()
    accessibility_description: str | None = None


class VideoSceneDraft(FrozenModel):
    """
    One modality scene as decided by the Video Modality Planner.

    The LLM populates this; deterministic code converts it to a ModalityScene.
    The LLM must not write final narration, create production jobs, or reference
    provider-specific avatar or voice IDs.

    Four separate fields carry distinct semantics:
      - learning_objective: what the learner should understand or do
      - narrative_role:     why this scene exists in the learning journey
      - affordance_id:      how the scene is presented through Video
      - presentation_direction: what the viewer sees and how the visual supports teaching
    """

    scene_id: str = Field(min_length=1)
    source_content: tuple[RLOContentRef, ...] = Field(min_length=1)
    learning_objective: str = Field(min_length=1)
    narrative_role: NarrativeRole
    affordance_id: str = Field(min_length=1)
    teaching_pattern: str = Field(min_length=1)
    content_direction: str = Field(min_length=1)
    presentation_direction: str = Field(min_length=1)
    referenced_asset_id: str | None = None
    learner_engagement: str | None = None
    transition_direction: str | None = None
    target_duration_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def _validate_scene(self) -> "VideoSceneDraft":
        if not self.scene_id.strip():
            raise ValueError("scene_id must not be blank")
        if not self.presentation_direction.strip():
            raise ValueError("presentation_direction must not be blank")
        return self


class VideoModalityDraft(FrozenModel):
    """
    Structured LLM output for video Modality Planning — Phase 13C.

    The LLM decides scene breakdown, narrative role, pedagogical affordance,
    content direction, presentation direction, and duration allocation.
    It must not write final narration, create production tasks, or reference
    tool internals, provider IDs, or unavailable capabilities.
    """

    draft_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    scenes: tuple[VideoSceneDraft, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_draft(self) -> "VideoModalityDraft":
        ids = [s.scene_id for s in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("scene_ids must be unique across the draft")
        return self


# ── Phase 14E: E-learning modality-planner contracts ─────────────────────────


class ElearningSceneDraft(FrozenModel):
    """
    One modality scene as decided by the E-learning Modality Planner.

    The LLM populates this; deterministic code converts it to a ModalityScene.
    The LLM must not write final screen content, create production jobs, or
    reference provider-specific tool details.

    Four separate fields carry distinct semantics:
      - learning_objective:  what the learner should understand or do
      - narrative_role:      why this scene exists in the learning journey
      - affordance_id:       how the scene is presented in e-learning
      - content_direction:   what pedagogical content the scene should contain
    """

    scene_id: str = Field(min_length=1)
    source_content: tuple[RLOContentRef, ...] = Field(min_length=1)
    learning_objective: str = Field(min_length=1)
    narrative_role: NarrativeRole
    affordance_id: str = Field(min_length=1)
    teaching_pattern: str = Field(min_length=1)
    content_direction: str = Field(min_length=1)
    learner_engagement: str | None = None
    target_duration_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def _validate_scene(self) -> "ElearningSceneDraft":
        if not self.scene_id.strip():
            raise ValueError("scene_id must not be blank")
        return self


class ElearningModalityDraft(FrozenModel):
    """
    Structured LLM output for e-learning Modality Planning — Phase 14E.

    The LLM decides scene breakdown, narrative role, pedagogical affordance,
    content direction, and duration allocation.  It must not write final
    screen content, create production tasks, or reference tool internals,
    provider IDs, or unavailable capabilities.
    """

    draft_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    scenes: tuple[ElearningSceneDraft, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_draft(self) -> "ElearningModalityDraft":
        ids = [s.scene_id for s in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("scene_ids must be unique across the draft")
        return self


# ── Phase 14D: E-learning production draft ────────────────────────────────────


class AvatarMediaDirective(FrozenModel):
    """Directive for one avatar-video slot in an e-learning course.

    The LLM decides narration, avatar/voice profile, and visual direction.
    The builder converts this into a video.avatar.render ProductionJob.
    """

    kind: Literal["avatar_video"] = "avatar_video"
    slot_id: str = Field(min_length=1)
    narration_script: str = Field(min_length=1)
    avatar_profile: str = Field(min_length=1)
    voice_profile: str = Field(min_length=1)
    visual_direction: str = Field(min_length=1)
    target_duration_seconds: int | None = None

    @model_validator(mode="after")
    def _positive_duration(self) -> "AvatarMediaDirective":
        if self.target_duration_seconds is not None and self.target_duration_seconds <= 0:
            raise ValueError("target_duration_seconds must be positive when set")
        return self


class ManimMediaDirective(FrozenModel):
    """Directive for one Manim-animated video slot in an e-learning course.

    The LLM decides animation direction, narration, and optional visual style.
    The builder converts this into a video.manim.render ProductionJob.
    """

    kind: Literal["manim_video"] = "manim_video"
    slot_id: str = Field(min_length=1)
    narration_script: str = Field(min_length=1)
    animation_direction: str = Field(min_length=1)
    visual_style: str | None = None
    voice_profile: str | None = None
    target_duration_seconds: int | None = None

    @model_validator(mode="after")
    def _positive_duration(self) -> "ManimMediaDirective":
        if self.target_duration_seconds is not None and self.target_duration_seconds <= 0:
            raise ValueError("target_duration_seconds must be positive when set")
        return self


class ElearningProductionDraft(FrozenModel):
    """Structured LLM output for e-learning Workflow Planning — Phase 14D.

    The LLM makes semantic decisions:
      - which screens to author (authored_screens) and which are video slots (video_slots);
      - the unified course sequence via screen_order (all screen_ids in intended order);
      - which slots get avatar video vs. Manim animation;
      - narration scripts and media direction per slot;
      - overall course narrative and authoring direction.

    Deterministic code makes structural decisions:
      - job IDs and capabilities;
      - DAG edges (author + media jobs → assembler);
      - input bindings and output keys.

    All list fields use separate typed tuples (no discriminated unions) so the
    JSON schema contains no ``oneOf``, which is required for structured-output
    compatibility with hosted LLM APIs.  Use ``ordered_screens`` to reconstruct
    the unified sequence from ``screen_order`` at runtime.
    """

    draft_id: str = Field(min_length=1)
    source_modality_plan_id: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    authored_screens: tuple[AuthoredScreenRequirement, ...] = Field(min_length=1)
    video_slots: tuple[VideoSlotRequirement, ...] = ()
    screen_order: tuple[str, ...]  # all screen_ids in intended course sequence
    avatar_directives: tuple[AvatarMediaDirective, ...] = ()
    manim_directives: tuple[ManimMediaDirective, ...] = ()
    course_authoring_direction: str = Field(min_length=1)
    theme: str | None = None

    @model_validator(mode="after")
    def _validate_uniqueness(self) -> "ElearningProductionDraft":
        authored_ids = [r.screen_id for r in self.authored_screens]
        slot_screen_ids = [r.screen_id for r in self.video_slots]
        all_screen_ids = authored_ids + slot_screen_ids
        if len(all_screen_ids) != len(set(all_screen_ids)):
            raise ValueError("screen_ids must be unique across authored_screens and video_slots")
        slot_ids = [r.slot_id for r in self.video_slots]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("video_slots must have unique slot_ids")
        all_directive_slot_ids = (
            [d.slot_id for d in self.avatar_directives]
            + [d.slot_id for d in self.manim_directives]
        )
        if len(all_directive_slot_ids) != len(set(all_directive_slot_ids)):
            raise ValueError("avatar_directives and manim_directives must have unique slot_ids")
        if set(self.screen_order) != set(all_screen_ids):
            raise ValueError(
                "screen_order must contain exactly the screen_ids from authored_screens and video_slots"
            )
        return self

    @property
    def ordered_screens(self) -> tuple:
        """Screens in the intended course sequence, reconstructed from screen_order."""
        by_id = {r.screen_id: r for r in (*self.authored_screens, *self.video_slots)}
        return tuple(by_id[sid] for sid in self.screen_order)
