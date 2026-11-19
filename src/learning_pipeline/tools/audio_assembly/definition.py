"""
Production tool definition for audio.assemble.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.tools.audio_assembly.contracts import (
    AudioAssemblyInput,
    AudioAssemblyOutput,
)
from learning_pipeline.tools.manifest import ProductionToolDefinition, ToolManifest


def audio_assembly_tool_definition() -> ProductionToolDefinition:
    """Return the planner-safe definition for ``audio.assemble``."""
    manifest = ToolManifest(
        capability="audio.assemble",
        contract_version="1.0",
        task_type="audio.assemble",
        description=(
            "Assembles an ordered sequence of WAV speech segments into a single "
            "podcast deliverable.  Inserts deterministic silence between segments "
            "according to each segment's pause_after_seconds plus the default gap. "
            "Validates format compatibility, aggregates per-segment usage records, "
            "and writes both the final WAV and a costs/usage JSON artifact."
        ),
        supported_modalities=(Modality.PODCAST,),
        input_schema=AudioAssemblyInput.model_json_schema(),
        output_schema=AudioAssemblyOutput.model_json_schema(),
        constraints={
            "required_format": "PCM WAV (any compatible sample rate, channels, bit depth)",
            "segment_order": "preserved from input tuple — not sorted by completion time",
            "pause_policy": "between segments: pause_after + default_gap; final segment: pause_after only",
        },
    )
    return ProductionToolDefinition(
        manifest=manifest,
        input_model=AudioAssemblyInput,
        output_model=AudioAssemblyOutput,
    )
