"""Typed contracts for the video.avatar.render production tool.

AvatarVideoRenderInput is the provider-neutral production request.
AvatarVideoRenderOutput carries logical artifact URIs and usage metadata.

These contracts are the canonical source of truth for the tool manifest's
input_schema and output_schema.  Both the fake and real executors validate
against them — switching executor mode never requires a BuildPlan change.

Provider-specific IDs (HeyGen avatar_id, voice_id, asset_id) must not appear
in these contracts.  Only logical profile references are accepted.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from learning_pipeline.contracts.common import FrozenModel

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
_UNSAFE_PATH_RE = re.compile(r"[/\\]|\.\.")
_ARTIFACT_URI_RE = re.compile(r"^(artifact|fake)://\S+$")
_SUPPORTED_WIDTHS = frozenset({1280, 1920, 854})
_SUPPORTED_HEIGHTS = frozenset({720, 1080, 480})
_SUPPORTED_PLAY_STYLES = frozenset({"fit_to_scene", "crop_to_scene", "fill"})


# ── Background types (discriminated union) ────────────────────────────────────


class SolidColorBackground(FrozenModel):
    kind: Literal["color"] = "color"
    color: str = Field(..., description="Hex color string, e.g. '#1A1A2E'.")

    @field_validator("color")
    @classmethod
    def _valid_hex(cls, v: str) -> str:
        if not _HEX_COLOR_RE.match(v):
            raise ValueError(
                f"color must be a 6-digit hex color (e.g. '#1A1A2E'); got {v!r}"
            )
        return v


class ImageBackground(FrozenModel):
    kind: Literal["image"] = "image"
    artifact_uri: str = Field(
        ...,
        description="Logical artifact URI for the background image asset.",
    )

    @field_validator("artifact_uri")
    @classmethod
    def _valid_uri(cls, v: str) -> str:
        if not _ARTIFACT_URI_RE.match(v):
            raise ValueError(
                f"artifact_uri must be a logical artifact:// or fake:// URI; got {v!r}"
            )
        return v


class VideoBackground(FrozenModel):
    kind: Literal["video"] = "video"
    artifact_uri: str = Field(
        ...,
        description="Logical artifact URI for the background video asset.",
    )
    play_style: str = Field(
        "fit_to_scene",
        description="How the background video is sized: fit_to_scene, crop_to_scene, fill.",
    )

    @field_validator("artifact_uri")
    @classmethod
    def _valid_uri(cls, v: str) -> str:
        if not _ARTIFACT_URI_RE.match(v):
            raise ValueError(
                f"artifact_uri must be a logical artifact:// or fake:// URI; got {v!r}"
            )
        return v

    @field_validator("play_style")
    @classmethod
    def _valid_play_style(cls, v: str) -> str:
        if v not in _SUPPORTED_PLAY_STYLES:
            raise ValueError(
                f"play_style must be one of {sorted(_SUPPORTED_PLAY_STYLES)}; got {v!r}"
            )
        return v


VideoBackgroundSpec = Annotated[
    SolidColorBackground | ImageBackground | VideoBackground,
    Field(discriminator="kind"),
]


# ── Scene ─────────────────────────────────────────────────────────────────────


class AvatarVideoScene(FrozenModel):
    """One logical scene in an avatar-led instructional video."""

    scene_id: str = Field(..., description="Stable kebab-case scene identifier.")
    source_scene_ids: tuple[str, ...] = Field(
        ...,
        description="Source ModalityPlan scene IDs this video scene covers (lineage).",
    )
    title: str | None = Field(None, description="Optional human-readable scene title.")
    script: str = Field(..., description="Avatar script text to be spoken.")
    background: VideoBackgroundSpec
    estimated_duration_seconds: float | None = Field(
        None,
        description="Estimated playback duration hint (informational; HeyGen determines actual).",
    )

    @field_validator("scene_id")
    @classmethod
    def _safe_scene_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("scene_id must not be blank")
        if _UNSAFE_PATH_RE.search(v):
            raise ValueError(
                f"scene_id must not contain path separators or '..'; got {v!r}"
            )
        return v

    @field_validator("source_scene_ids")
    @classmethod
    def _non_empty_lineage(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("source_scene_ids must have at least one entry")
        return v

    @field_validator("script")
    @classmethod
    def _script_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("script must not be blank")
        return v

    @field_validator("estimated_duration_seconds")
    @classmethod
    def _positive_duration(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("estimated_duration_seconds must be positive")
        return v


# ── Profile references (provider-neutral) ─────────────────────────────────────


class AvatarProfileRef(FrozenModel):
    profile: str = Field(
        ...,
        description="Logical avatar profile name, e.g. 'default_instructor'.",
    )

    @field_validator("profile")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("profile must not be blank")
        return v


class VoiceProfileRef(FrozenModel):
    profile: str = Field(
        ...,
        description="Logical voice profile name, e.g. 'default_instructor'.",
    )
    speed: float = Field(
        1.0,
        gt=0,
        description="Voice speed multiplier (positive).",
    )


# ── Dimensions ────────────────────────────────────────────────────────────────


class VideoDimensions(FrozenModel):
    width: int = Field(..., description="Video width in pixels.")
    height: int = Field(..., description="Video height in pixels.")

    @model_validator(mode="after")
    def _supported_dimensions(self) -> "VideoDimensions":
        if self.width not in _SUPPORTED_WIDTHS or self.height not in _SUPPORTED_HEIGHTS:
            raise ValueError(
                f"Unsupported dimensions {self.width}×{self.height}.  "
                f"Supported widths: {sorted(_SUPPORTED_WIDTHS)}, "
                f"heights: {sorted(_SUPPORTED_HEIGHTS)}."
            )
        return self


# ── Input contract ────────────────────────────────────────────────────────────


class AvatarVideoRenderInput(FrozenModel):
    """Provider-neutral render request for one avatar-led instructional video.

    The executor resolves logical avatar/voice profile names to provider-specific
    IDs.  Provider IDs must not appear directly in the BuildPlan inputs.
    """

    deliverable_id: str = Field(
        ...,
        description="Stable ID for the final video deliverable.",
    )
    scenes: tuple[AvatarVideoScene, ...] = Field(
        ...,
        description="Ordered sequence of avatar video scenes.",
    )
    avatar: AvatarProfileRef
    voice: VoiceProfileRef
    dimensions: VideoDimensions
    captions: bool = Field(False, description="Request caption/subtitle generation.")

    @field_validator("deliverable_id")
    @classmethod
    def _deliverable_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("deliverable_id must not be blank")
        if _UNSAFE_PATH_RE.search(v):
            raise ValueError(
                f"deliverable_id must not contain path separators; got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _validate_scenes(self) -> "AvatarVideoRenderInput":
        if not self.scenes:
            raise ValueError("at least one scene is required")
        seen: set[str] = set()
        for scene in self.scenes:
            if scene.scene_id in seen:
                raise ValueError(f"duplicate scene_id: {scene.scene_id!r}")
            seen.add(scene.scene_id)
        return self


# ── Usage and output contracts ────────────────────────────────────────────────


class AvatarVideoUsage(FrozenModel):
    """Cost and usage metrics for one avatar-video render operation."""

    scene_count: int
    estimated_duration_seconds: float | None = None
    actual_duration_seconds: float | None = None
    uploaded_asset_count: int
    estimated_credits: float | None = None
    estimated_cost_usd: float | None = None


class AvatarVideoRenderOutput(FrozenModel):
    """Output contract for video.avatar.render.

    All artifact references are logical URIs — never raw provider URLs,
    temporary download links, or local filesystem paths.
    """

    deliverable_id: str
    provider_operation_id: str = Field(
        ...,
        description="HeyGen video_id; retained for audit and operational support.",
    )
    video_uri: str = Field(..., description="Logical artifact URI for the MP4.")
    subtitle_uri: str | None = Field(
        None,
        description="Logical artifact URI for the subtitle file (when captions=True).",
    )
    subtitle_media_type: str | None = Field(
        None,
        description=(
            "Media type of the subtitle artifact (e.g. 'text/srt'). "
            "Always None when subtitle_uri is None; always set when subtitle_uri is set. "
            "Exposed as a TaskOutputInput binding key for the bundle assembler."
        ),
    )
    cost_report_uri: str = Field(
        ...,
        description="Logical artifact URI for the JSON cost/usage report.",
    )
    media_type: Literal["video/mp4"] = "video/mp4"
    duration_seconds: float | None = Field(
        None,
        description="Playback duration in seconds; None when unavailable.",
    )
    usage: AvatarVideoUsage

    @model_validator(mode="after")
    def _subtitle_consistency(self) -> "AvatarVideoRenderOutput":
        if self.subtitle_uri is None and self.subtitle_media_type is not None:
            raise ValueError("subtitle_media_type must be None when subtitle_uri is None")
        if self.subtitle_uri is not None and self.subtitle_media_type is None:
            raise ValueError("subtitle_media_type must be set when subtitle_uri is set")
        return self
