"""
Typed contracts for the speech.synthesize production tool.

SpeechSynthesisInput represents one independently synthesizable spoken segment.
SpeechSynthesisOutput provides WAV artifact metadata and usage accounting.

These contracts are the source of truth for the manifest's input_schema and
output_schema.  Both the fake and real executors validate against them so that
switching modes never requires a BuildPlan change.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from learning_pipeline.contracts.common import FrozenModel


class SpeechSynthesisInput(FrozenModel):
    """One independently synthesizable spoken segment.

    Corresponds to a single TTS call.  Pause insertion and segment ordering
    are the responsibility of the audio.assemble task, not this contract.
    """

    text: str = Field(..., description="The spoken text to synthesize.")
    speaker: str = Field(..., description="Speaker role, e.g. 'Host' or 'Expert'.")
    line_id: str = Field(..., description="Stable identifier for this spoken line.")
    voice_hint: str | None = Field(
        None,
        description="Optional explicit voice name; overrides the speaker default.",
    )
    pause_after_seconds: float = Field(
        0.0,
        ge=0.0,
        description="Silence to insert after this segment (handled by audio.assemble).",
    )

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v

    @field_validator("speaker")
    @classmethod
    def _speaker_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("speaker must not be blank")
        return v

    @field_validator("line_id")
    @classmethod
    def _line_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("line_id must not be blank")
        return v


class SpeechUsage(FrozenModel):
    """Provider cost and usage metrics for one synthesized segment."""

    input_characters: int
    input_tokens_estimate: float
    audio_duration_seconds: float
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float


class SpeechSynthesisOutput(FrozenModel):
    """WAV artifact reference and usage metadata for one synthesized segment.

    ``audio_uri`` holds the logical artifact URI (e.g. ``artifact://...`` or
    ``fake://...`` in test mode).  Raw audio bytes are never stored here.
    """

    audio_uri: str = Field(..., description="Logical artifact URI for the WAV file.")
    media_type: Literal["audio/wav"] = "audio/wav"
    duration_seconds: float
    speaker: str
    voice: str
    usage: SpeechUsage
