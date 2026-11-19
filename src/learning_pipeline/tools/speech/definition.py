"""
Production tool definitions for the speech vertical slice.

Each factory function returns a ProductionToolDefinition with a planner-safe
manifest whose input_schema and output_schema are derived from typed Pydantic
models.  No executor instances are created here.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.tools.manifest import ProductionToolDefinition, ToolManifest
from learning_pipeline.tools.speech.contracts import (
    SpeechSynthesisInput,
    SpeechSynthesisOutput,
)

# audio_assembly_tool_definition lives in its own package (Phase 8).
from learning_pipeline.tools.audio_assembly.definition import (  # noqa: F401
    audio_assembly_tool_definition,
)


def speech_tool_definition() -> ProductionToolDefinition:
    """Return the planner-safe definition for ``speech.synthesize``."""
    manifest = ToolManifest(
        capability="speech.synthesize",
        contract_version="1.0",
        task_type="speech.synthesize",
        description=(
            "Converts one independently synthesizable spoken passage into a WAV "
            "audio artifact.  Accepts the script text, speaker role, and optional "
            "voice hint.  Returns a logical artifact URI, playback duration, and "
            "per-segment usage metadata.  One task per spoken segment — do not "
            "pass an entire podcast specification to a single task."
        ),
        supported_modalities=(Modality.PODCAST, Modality.VIDEO, Modality.ELEARNING),
        input_schema=SpeechSynthesisInput.model_json_schema(),
        output_schema=SpeechSynthesisOutput.model_json_schema(),
        constraints={
            "max_text_length_chars": 5_000,
            "response_format": "wav",
            "note": "pause_after_seconds is metadata for audio.assemble; this tool does not insert silence",
        },
    )
    return ProductionToolDefinition(
        manifest=manifest,
        input_model=SpeechSynthesisInput,
        output_model=SpeechSynthesisOutput,
    )
