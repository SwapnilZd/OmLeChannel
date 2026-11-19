"""Typed contracts for elearning.course.author, video.manim.render, and elearning.bundle.assemble.

All tool boundaries use logical ArtifactRefs — never raw filesystem Paths,
container paths, or temporary provider URLs.

Slot representation
-------------------
The e-learning authoring pipeline uses VideoSlotScreen (defined in pipeline/src/schema.py)
as an intermediate placeholder inside the CourseContent JSON.  The bundle assembler
replaces every VideoSlotScreen with a final VideoPlayerScreen before rendering HTML.

Output convenience fields
-------------------------
Both ElearningAuthorOutput and ManimVideoOutput carry a plain ``_uri`` string
alongside the full ArtifactRef so that BuildPlan TaskOutputInput bindings can
reference the URI without needing to traverse a nested dict.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.runtime.artifact_store import ArtifactRef

_SLOT_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_SUPPORTED_VIDEO_TYPES = frozenset({"video/mp4"})
_SUPPORTED_CAPTION_TYPES = frozenset({"text/vtt", "text/srt"})
_SUPPORTED_POSTER_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_UNSAFE_PATH_RE = re.compile(r"(^|/)\.\.(/|$)|[\\]|\x00")


# ── Course structure requirements ──────────────────────────────────────────────


class LearnerAction(StrEnum):
    """Learner behavior a planned screen must support."""

    CONSUME = "consume"
    REVEAL = "reveal"
    CHOOSE = "choose"
    REFLECT = "reflect"


_ACTION_BY_SCREEN_TYPE: dict[str, LearnerAction] = {
    "concept_flip_card": LearnerAction.REVEAL,
    "tabbed_content": LearnerAction.REVEAL,
    "disclosure_list": LearnerAction.REVEAL,
    "scenario_setup": LearnerAction.CHOOSE,
    "knowledge_check": LearnerAction.CHOOSE,
    "reflection_prompt": LearnerAction.REFLECT,
}


def natural_learner_action(screen_type: str) -> LearnerAction:
    """Return the single learner action supported by an authored component."""
    return _ACTION_BY_SCREEN_TYPE.get(screen_type, LearnerAction.CONSUME)


def resolved_learner_action(requirement: "AuthoredScreenRequirement") -> LearnerAction:
    """Use an explicit planned action or derive one for older persisted briefs."""
    return requirement.learner_action or natural_learner_action(requirement.screen_type)


class AuthoredScreenRequirement(FrozenModel):
    """Declares one content screen that the LLM must author.

    The LLM receives this entry and returns exactly one AuthoredScreenDraft
    with matching screen_id and screen_type.
    """

    kind: Literal["authored_screen"] = "authored_screen"
    screen_id: str = Field(..., description="Stable identifier for this content screen.")
    screen_type: str = Field(
        ..., description="Screen type from AUTHORABLE_SCREEN_TYPES that the LLM must produce."
    )
    source_scene_ids: tuple[str, ...] = Field(
        ..., description="Modality-plan scene IDs this screen covers (lineage)."
    )
    content_direction: str = Field(
        ..., description="Authoring guidance: tone, depth, key points to cover."
    )
    learner_action: LearnerAction | None = Field(
        default=None,
        description=(
            "Explicit learner behavior supported by this screen. Newly planned "
            "workflows must set it; older persisted briefs derive it from screen_type."
        ),
    )

    @field_validator("screen_id")
    @classmethod
    def _not_blank_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("screen_id must not be blank")
        return v

    @field_validator("screen_type")
    @classmethod
    def _not_blank_type(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("screen_type must not be blank")
        return v

    @field_validator("source_scene_ids")
    @classmethod
    def _non_empty_scenes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("source_scene_ids must not be empty")
        return v

    @field_validator("content_direction")
    @classmethod
    def _not_blank_direction(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content_direction must not be blank")
        return v


class VideoSlotRequirement(FrozenModel):
    """Declares a video slot position in the course sequence.

    Used in both ElearningAuthoringBrief.screen_requirements and
    ElearningBundleAssemblyInput.required_slots.
    """

    kind: Literal["video_slot"] = "video_slot"
    screen_id: str = Field(..., description="Stable screen identifier, e.g. 'screen-intro-video'.")
    slot_id: str = Field(..., description="Stable identifier for this video slot.")
    source_scene_ids: tuple[str, ...] = Field(
        ..., description="Modality-plan scene IDs this slot covers (lineage)."
    )
    title: str = Field(..., description="Human-readable slot title.")
    required: bool = Field(True, description="Whether this slot must be filled for assembly to succeed.")
    captions_required: bool = Field(True, description="Whether captions are mandatory for this slot.")
    poster_required: bool = Field(False, description="Whether a poster image is mandatory for this slot.")

    @field_validator("screen_id")
    @classmethod
    def _not_blank_screen_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("screen_id must not be blank")
        return v

    @field_validator("slot_id")
    @classmethod
    def _slot_id_safe(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("slot_id must not be blank")
        if not _SLOT_ID_RE.match(v):
            raise ValueError(
                f"slot_id must contain only alphanumerics, hyphens, or underscores; got {v!r}"
            )
        return v

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v

    @field_validator("source_scene_ids")
    @classmethod
    def _non_empty_scenes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("source_scene_ids must not be empty")
        return v


CourseStructureRequirement = Annotated[
    AuthoredScreenRequirement | VideoSlotRequirement,
    Field(discriminator="kind"),
]


# ── Bundle asset reference (logical path + artifact) ──────────────────────────


class BundleAssetRef(FrozenModel):
    """Maps a relative bundle path to a stored artifact."""

    logical_path: str = Field(
        ...,
        description=(
            "Relative POSIX path within the bundle, e.g. 'assets/generated-image.png'. "
            "Must not be absolute, contain '..', or start with '/'"
        ),
    )
    artifact: ArtifactRef

    @field_validator("logical_path")
    @classmethod
    def _safe_logical_path(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("logical_path must not be blank")
        if v.startswith("/"):
            raise ValueError(f"logical_path must be relative, not absolute: {v!r}")
        if _UNSAFE_PATH_RE.search(v):
            raise ValueError(
                f"logical_path must not contain '..', backslashes, or null bytes: {v!r}"
            )
        return v


# ── Slot preservation report ───────────────────────────────────────────────────


class SlotPreservationReport(FrozenModel):
    """Result of CourseSlotValidator.validate() — included in authoring trace and assembler output."""

    required_slot_ids: tuple[str, ...]
    discovered_slot_ids: tuple[str, ...]
    missing_slot_ids: tuple[str, ...]
    duplicate_slot_ids: tuple[str, ...]
    unexpected_slot_ids: tuple[str, ...]
    valid: bool

    @classmethod
    def build(
        cls,
        required: tuple[str, ...],
        discovered: list[str],
    ) -> "SlotPreservationReport":
        from collections import Counter
        counts = Counter(discovered)
        discovered_set = set(counts)
        required_set = set(required)
        missing = tuple(sorted(required_set - discovered_set))
        duplicates = tuple(sorted(s for s, n in counts.items() if n > 1))
        unexpected = tuple(sorted(discovered_set - required_set))
        valid = not missing and not duplicates
        return cls(
            required_slot_ids=required,
            discovered_slot_ids=tuple(sorted(discovered_set)),
            missing_slot_ids=missing,
            duplicate_slot_ids=duplicates,
            unexpected_slot_ids=unexpected,
            valid=valid,
        )


# ── Elearning authoring brief (input to elearning.course.author) ──────────────


class ElearningAuthoringBrief(FrozenModel):
    """Frozen contract passed to elearning.course.author.

    All pedagogical decisions have already been made upstream by the Modality
    Planner.  The authoring agent must not re-design the course structure;
    it must populate the required sequence and preserve all slot IDs.
    """

    deliverable_id: str
    source_plan_id: str

    resolved_context_uri: str = Field(
        ..., description="ArtifactRef URI for the resolved RLO context JSON."
    )
    resolved_context_sha256: str = Field(
        ..., description="SHA-256 of the resolved context, for idempotency."
    )

    screen_requirements: tuple[CourseStructureRequirement, ...] = Field(
        ...,
        description=(
            "Ordered course structure: AuthoredScreenRequirement and VideoSlotRequirement entries. "
            "Must be non-empty and contain at least one AuthoredScreenRequirement."
        ),
    )

    theme: str = Field("deloitte-green", description="Reveal.js theme ID.")
    brand_contract: dict[str, str] = Field(default_factory=dict)
    accessibility_requirements: tuple[str, ...] = ()
    authoring_direction: str = Field(
        "", description="Free-text authoring guidance from the Workflow Planner."
    )

    @field_validator("deliverable_id")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("deliverable_id must not be blank")
        return v

    @model_validator(mode="after")
    def _validate_requirements(self) -> "ElearningAuthoringBrief":
        reqs = self.screen_requirements
        if not reqs:
            raise ValueError("screen_requirements must not be empty")
        authored = [r for r in reqs if isinstance(r, AuthoredScreenRequirement)]
        if not authored:
            raise ValueError(
                "screen_requirements must contain at least one AuthoredScreenRequirement"
            )
        screen_ids = [r.screen_id for r in reqs]
        if len(screen_ids) != len(set(screen_ids)):
            raise ValueError("screen_requirements must have unique screen_ids")
        slot_ids = [r.slot_id for r in reqs if isinstance(r, VideoSlotRequirement)]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError(
                "screen_requirements must have unique slot_ids among VideoSlotRequirements"
            )
        return self


def video_slot_requirements(
    brief: ElearningAuthoringBrief,
) -> tuple[VideoSlotRequirement, ...]:
    """Derive the ordered list of VideoSlotRequirements from brief.screen_requirements."""
    return tuple(
        r for r in brief.screen_requirements if isinstance(r, VideoSlotRequirement)
    )


# ── Elearning author output ────────────────────────────────────────────────────


class ElearningAuthorOutput(FrozenModel):
    """Output contract for elearning.course.author.

    course_json_uri is a convenience alias for course_json.uri, included so
    BuildPlan TaskOutputInput bindings can reference it as a top-level string key.
    """

    course_json: ArtifactRef = Field(
        ..., description="Intermediate CourseContent JSON (may contain VideoSlotScreens)."
    )
    course_json_uri: str = Field(
        ..., description="Convenience alias for course_json.uri (for TaskOutputInput bindings)."
    )
    assets: tuple[BundleAssetRef, ...] = Field(
        ..., description="All adjacent assets referenced by the intermediate course JSON."
    )
    slot_report: SlotPreservationReport
    preview_html: ArtifactRef | None = Field(
        None, description="Optional preview HTML (slots shown as placeholders)."
    )
    trace_uri: str | None = None

    @model_validator(mode="after")
    def _uri_consistency(self) -> "ElearningAuthorOutput":
        if self.course_json_uri != self.course_json.uri:
            raise ValueError(
                "course_json_uri must equal course_json.uri"
            )
        return self


# ── Manim animation brief (input to video.manim.render) ───────────────────────


class AnimationBrief(FrozenModel):
    """Typed input contract for the future bounded video.manim.render agent.

    The real executor will invoke the Manim container with isolated credentials.
    Phase 14A uses FakeManimVideoExecutor only.
    """

    animation_id: str
    source_scene_ids: tuple[str, ...] = Field(
        ..., description="Modality-plan scene IDs this animation covers."
    )
    learning_objective: str
    teaching_purpose: str
    visual_direction: str
    narration_script: str = Field(
        min_length=1,
        description="Required spoken narration synchronized to the animation.",
    )

    resolved_context_uri: str
    resolved_context_sha256: str

    target_duration_seconds: int | None = None
    quality_profile: str = "standard"
    voice_profile: str | None = Field(
        None, description="Logical voice profile for narration synthesis, e.g. 'default' or 'instructor'."
    )

    brand_contract: dict[str, str] = Field(default_factory=dict)
    accessibility_requirements: tuple[str, ...] = ()

    @field_validator("animation_id")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("animation_id must not be blank")
        return v

    @field_validator("narration_script")
    @classmethod
    def _narration_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("narration_script must not be blank")
        return v

    @field_validator("source_scene_ids")
    @classmethod
    def _non_empty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("source_scene_ids must not be empty")
        return v


# ── Manim video output ─────────────────────────────────────────────────────────


class ManimVideoOutput(FrozenModel):
    """Output contract for video.manim.render.

    video_uri is a convenience alias for video.uri so that BuildPlan
    TaskOutputInput bindings can reference it as a top-level string key.
    """

    video: ArtifactRef = Field(..., description="Rendered MP4 artifact.")
    video_uri: str = Field(
        ..., description="Convenience alias for video.uri (for TaskOutputInput bindings)."
    )
    captions: ArtifactRef | None = Field(None, description="Optional WebVTT captions artifact.")
    captions_uri: str | None = Field(None, description="Convenience alias for captions.uri.")
    captions_media_type: str | None = Field(
        None,
        description="Media type of captions artifact (e.g. 'text/vtt'). "
                    "Always None when captions is None; always set when captions is set. "
                    "Exposed as a TaskOutputInput binding key for the bundle assembler.",
    )
    poster: ArtifactRef | None = Field(None, description="Optional poster image artifact.")
    poster_uri: str | None = Field(None, description="Convenience alias for poster.uri.")
    generated_source: ArtifactRef | None = Field(
        None, description="Generated Manim Python source file (for audit and retry)."
    )
    render_log: ArtifactRef | None = Field(None, description="Manim render stdout/stderr log.")
    narration: ArtifactRef | None = Field(
        None, description="Pre-synthesised narration WAV artifact (retained for checkpoint reuse)."
    )
    result_manifest: ArtifactRef | None = Field(
        None, description="Machine-readable result manifest JSON listing all artifacts."
    )
    trace_uri: str | None = None

    @model_validator(mode="after")
    def _uri_consistency(self) -> "ManimVideoOutput":
        if self.video_uri != self.video.uri:
            raise ValueError("video_uri must equal video.uri")
        if self.captions is not None and self.captions_uri != self.captions.uri:
            raise ValueError("captions_uri must equal captions.uri when captions is set")
        if self.captions is None and self.captions_uri is not None:
            raise ValueError("captions_uri must be None when captions is None")
        if self.captions is None and self.captions_media_type is not None:
            raise ValueError("captions_media_type must be None when captions is None")
        if self.captions is not None and self.captions_media_type is None:
            raise ValueError("captions_media_type must be set when captions is set")
        if self.poster is not None and self.poster_uri != self.poster.uri:
            raise ValueError("poster_uri must equal poster.uri when poster is set")
        if self.poster is None and self.poster_uri is not None:
            raise ValueError("poster_uri must be None when poster is None")
        return self


# ── Video insertion (resolved assembler input) ─────────────────────────────────


class VideoInsertion(FrozenModel):
    """Resolved video to be inserted at a named slot during bundle assembly.

    Built from task-output bindings in the BuildPlan — the assembler receives
    one VideoInsertion per video-producing job.
    """

    slot_id: str
    source_scene_ids: tuple[str, ...]
    video_uri: str
    video_media_type: str = "video/mp4"
    captions_uri: str | None = None
    captions_media_type: str | None = None
    poster_uri: str | None = None
    poster_media_type: str | None = None
    title: str | None = None

    @field_validator("slot_id")
    @classmethod
    def _slot_id_safe(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("slot_id must not be blank")
        return v

    @field_validator("video_uri")
    @classmethod
    def _video_uri_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("video_uri must not be blank")
        return v

    @field_validator("video_media_type")
    @classmethod
    def _supported_video_type(cls, v: str) -> str:
        if v not in _SUPPORTED_VIDEO_TYPES:
            raise ValueError(
                f"Unsupported video media type {v!r}; supported: {sorted(_SUPPORTED_VIDEO_TYPES)}"
            )
        return v

    @model_validator(mode="after")
    def _caption_consistency(self) -> "VideoInsertion":
        if (self.captions_uri is None) != (self.captions_media_type is None):
            raise ValueError("captions_uri and captions_media_type must both be set or both be None")
        if self.captions_media_type is not None and self.captions_media_type not in _SUPPORTED_CAPTION_TYPES:
            raise ValueError(
                f"Unsupported caption media type {self.captions_media_type!r}; "
                f"supported: {sorted(_SUPPORTED_CAPTION_TYPES)}"
            )
        if (self.poster_uri is None) != (self.poster_media_type is None):
            raise ValueError("poster_uri and poster_media_type must both be set or both be None")
        if self.poster_media_type is not None and self.poster_media_type not in _SUPPORTED_POSTER_TYPES:
            raise ValueError(
                f"Unsupported poster media type {self.poster_media_type!r}; "
                f"supported: {sorted(_SUPPORTED_POSTER_TYPES)}"
            )
        return self

    @model_validator(mode="after")
    def _source_scenes_not_empty(self) -> "VideoInsertion":
        if not self.source_scene_ids:
            raise ValueError("source_scene_ids must not be empty")
        return self


# ── Bundle assembly input / output ────────────────────────────────────────────


class ElearningBundleAssemblyInput(FrozenModel):
    """Input contract for elearning.bundle.assemble (deterministic, no LLM)."""

    deliverable_id: str
    course_json_uri: str = Field(..., description="ArtifactRef URI for intermediate CourseContent JSON.")
    author_assets: tuple[BundleAssetRef, ...] = Field(
        ..., description="All adjacent assets declared by elearning.course.author."
    )
    required_slots: tuple[VideoSlotRequirement, ...] = Field(
        ..., description="The same slot requirements supplied to elearning.course.author."
    )
    video_insertions: tuple[VideoInsertion, ...] = Field(
        ..., description="One resolved VideoInsertion per video-producing job."
    )
    output_filename: str = Field("index.html", description="Entry HTML filename within the bundle.")

    @model_validator(mode="after")
    def _unique_insertion_slots(self) -> "ElearningBundleAssemblyInput":
        ids = [vi.slot_id for vi in self.video_insertions]
        if len(ids) != len(set(ids)):
            raise ValueError("video_insertions must have unique slot_ids")
        return self

    @model_validator(mode="after")
    def _unique_required_slots(self) -> "ElearningBundleAssemblyInput":
        ids = [s.slot_id for s in self.required_slots]
        if len(ids) != len(set(ids)):
            raise ValueError("required_slots must have unique slot_ids")
        return self


class ElearningBundleAssemblyOutput(FrozenModel):
    """Output contract for elearning.bundle.assemble."""

    entry_html: ArtifactRef = Field(..., description="Final Reveal.js HTML artifact.")
    course_json: ArtifactRef = Field(..., description="Final CourseContent JSON (no VideoSlotScreens).")
    asset_manifest: ArtifactRef = Field(..., description="Machine-readable asset manifest JSON.")
    bundle_zip: ArtifactRef = Field(..., description="Portable ZIP bundle (entry HTML + assets).")

    screen_count: int = Field(..., description="Total screen count in the final CourseContent.")
    video_count: int = Field(..., description="Number of VideoPlayerScreens in the final output.")
    unresolved_slot_count: int = Field(
        ..., description="Number of VideoSlotScreens remaining after assembly (should be 0)."
    )
