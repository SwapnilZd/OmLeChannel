"""Typed request and response models for the HeyGen REST API.

These models represent the HeyGen wire format and are private to the
heygen provider package.  They must not appear in BuildPlan inputs or
in the planner-safe tool manifest.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from learning_pipeline.contracts.common import FrozenModel


# ── Provider status enum ───────────────────────────────────────────────────────


class ProviderVideoStatus(StrEnum):
    PENDING = "pending"
    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


# ── HeyGen request models ──────────────────────────────────────────────────────


class HeyGenAvatarCharacter(FrozenModel):
    type: Literal["avatar"] = "avatar"
    avatar_id: str
    avatar_style: str = "normal"


class HeyGenVoiceInput(FrozenModel):
    type: Literal["text"] = "text"
    input_text: str
    voice_id: str
    speed: float = 1.0


class HeyGenColorBackground(FrozenModel):
    type: Literal["color"] = "color"
    value: str  # hex color string e.g. "#1A1A2E"


class HeyGenImageBackground(FrozenModel):
    type: Literal["image"] = "image"
    image_asset_id: str
    fit: str = "cover"


HeyGenBackground = Annotated[
    HeyGenColorBackground | HeyGenImageBackground,
    Field(discriminator="type"),
]


class HeyGenVideoInputScene(FrozenModel):
    character: HeyGenAvatarCharacter
    voice: HeyGenVoiceInput
    background: HeyGenBackground


class HeyGenDimension(FrozenModel):
    width: int
    height: int


class HeyGenCreateVideoRequest(FrozenModel):
    video_inputs: tuple[HeyGenVideoInputScene, ...]
    dimension: HeyGenDimension
    caption: bool = False


# ── HeyGen response models ─────────────────────────────────────────────────────


class HeyGenUploadedAsset(FrozenModel):
    asset_id: str


class HeyGenCreateVideoResponse(FrozenModel):
    video_id: str


class HeyGenVideoStatus(FrozenModel):
    video_id: str
    status: ProviderVideoStatus
    video_url: str | None = None
    subtitle_url: str | None = None
    duration: float | None = None  # provider-reported playback duration in seconds
    error: str | None = None
