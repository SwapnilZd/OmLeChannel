"""Production tool definition for video.avatar.render.

Returns a ProductionToolDefinition with a planner-safe ToolManifest whose
input_schema and output_schema are derived from typed Pydantic models.

The manifest must NOT expose:
- The API key or any credentials
- Raw HeyGen URLs or endpoint paths
- Provider client classes or polling behavior
- Physical artifact paths
- Provider-specific avatar or voice IDs
- Internal asset IDs
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.tools.manifest import ProductionToolDefinition, ToolManifest
from learning_pipeline.tools.avatar_video.contracts import (
    AvatarVideoRenderInput,
    AvatarVideoRenderOutput,
)

CAPABILITY = "video.avatar.render"
TASK_TYPE = "video.avatar.render"
CONTRACT_VERSION = "1.0"


def avatar_video_tool_definition() -> ProductionToolDefinition:
    """Return the planner-safe definition for ``video.avatar.render``."""
    manifest = ToolManifest(
        capability=CAPABILITY,
        contract_version=CONTRACT_VERSION,
        task_type=TASK_TYPE,
        description=(
            "Creates an avatar-led instructional video from an ordered sequence "
            "of scripted scenes.  Each scene specifies a spoken script, a "
            "background (solid colour or image), and optional metadata.  "
            "The avatar speaks the script while the background is displayed.  "
            "Accepts solid-colour and image backgrounds; supports optional "
            "caption/subtitle generation.  Returns an MP4 artifact URI, an "
            "optional subtitle artifact URI, and a JSON cost-report artifact URI.  "
            "This is an asynchronous, potentially long-running provider operation "
            "that may take several minutes per scene; submit one task per complete "
            "video deliverable, not one per scene.  "
            "May incur duration-based provider costs proportional to total video "
            "length and asset upload operations."
        ),
        supported_modalities=(Modality.VIDEO, Modality.ELEARNING),
        input_schema=AvatarVideoRenderInput.model_json_schema(),
        output_schema=AvatarVideoRenderOutput.model_json_schema(),
        constraints={
            "async_operation": True,
            "max_scenes": 20,
            "supported_backgrounds": ["color", "image"],
            "note": (
                "Avatar and voice profiles are logical names resolved by the executor. "
                "Provider IDs must not appear in BuildPlan inputs. "
                "Temporary provider download URLs are never returned as deliverable URIs."
            ),
        },
    )
    return ProductionToolDefinition(
        manifest=manifest,
        input_model=AvatarVideoRenderInput,
        output_model=AvatarVideoRenderOutput,
    )
