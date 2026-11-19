"""
Typed contracts for the audio.assemble production tool.

AudioAssemblyInput describes an ordered sequence of speech segments to assemble
into a single podcast WAV.  AudioAssemblyOutput carries the logical artifact
URIs for the final WAV and its usage/cost JSON report.

Both contracts are the source of truth for the tool manifest schemas.
The same contracts apply in EXECUTOR_MODE=fake and EXECUTOR_MODE=real.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.tools.speech.contracts import SpeechUsage

_UNSAFE_PATH_RE = re.compile(r"[/\\]|\.\.")


class AudioAssemblySegment(FrozenModel):
    """Metadata for one WAV segment to include in the assembled podcast."""

    segment_id: str = Field(..., description="Stable identifier for this segment.")
    audio_uri: str = Field(..., description="Logical artifact URI for the segment WAV.")
    speaker: str | None = Field(None, description="Speaker role (e.g. 'Host').")
    pause_after_seconds: float = Field(
        0.0,
        ge=0.0,
        description="Explicit cognitive pause to insert after this segment.",
    )
    usage: SpeechUsage | None = Field(
        None,
        description="Per-segment cost/usage record from the speech executor.",
    )

    @field_validator("segment_id")
    @classmethod
    def _segment_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("segment_id must not be blank")
        return v

    @field_validator("audio_uri")
    @classmethod
    def _audio_uri_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("audio_uri must not be blank")
        return v


class AudioAssemblyInput(FrozenModel):
    """Input contract for audio.assemble.

    Segments must be in narrative order.  The executor preserves this order
    regardless of which speech tasks finish first.
    """

    deliverable_id: str = Field(..., description="Stable ID for the final deliverable.")
    segments: tuple[AudioAssemblySegment, ...] = Field(
        ..., description="Ordered sequence of WAV segments."
    )
    default_gap_seconds: float = Field(
        0.35,
        ge=0.0,
        description="Default silence between adjacent segments (added to explicit pause).",
    )
    output_filename: str | None = Field(
        None,
        description="Optional WAV filename override (must not contain path separators).",
    )

    @field_validator("deliverable_id")
    @classmethod
    def _deliverable_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("deliverable_id must not be blank")
        return v

    @field_validator("output_filename")
    @classmethod
    def _safe_filename(cls, v: str | None) -> str | None:
        if v is not None and _UNSAFE_PATH_RE.search(v):
            raise ValueError(
                "output_filename must not contain path separators or '..' components"
            )
        return v

    @model_validator(mode="after")
    def _validate_segments(self) -> AudioAssemblyInput:
        if not self.segments:
            raise ValueError("at least one segment is required")
        seen: set[str] = set()
        for seg in self.segments:
            if seg.segment_id in seen:
                raise ValueError(f"duplicate segment_id: {seg.segment_id!r}")
            seen.add(seg.segment_id)
        return self


class PodcastUsageSummary(FrozenModel):
    """Aggregated cost and timing summary for the assembled podcast."""

    total_input_characters: int
    total_input_tokens_estimate: float
    total_audio_duration_seconds: float
    total_pause_duration_seconds: float
    total_input_cost_usd: float
    total_output_cost_usd: float
    total_cost_usd: float


class AudioAssemblyOutput(FrozenModel):
    """Output contract for audio.assemble."""

    deliverable_id: str
    audio_uri: str = Field(..., description="Logical artifact URI for the final WAV.")
    costs_uri: str = Field(..., description="Logical artifact URI for the costs/usage JSON.")
    media_type: Literal["audio/wav"] = "audio/wav"
    duration_seconds: float
    segment_count: int
    usage: PodcastUsageSummary
