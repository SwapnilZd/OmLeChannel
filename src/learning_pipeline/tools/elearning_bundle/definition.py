"""Production tool definitions for the three e-learning capabilities.

Registers:
    elearning.course.author   — bounded agentic; Phase 14B real executor available
    video.manim.render        — bounded agentic; Phase 14C real executor available
    elearning.bundle.assemble — deterministic; real implementation in Phase 14A

HTML rendering (elearning.html.render) is intentionally NOT registered as a
planner-visible capability.  It remains an internal service used by the assembler.

Executor selection follows PIPELINE_MODE (the project-wide convention):
    reference (default): FakeElearningCourseAuthorExecutor; no credentials required
    real:                RealElearningCourseAuthorExecutor; requires ELEARNING_LITELLM_* env vars
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.tools.manifest import ProductionToolDefinition, ToolManifest
from learning_pipeline.tools.elearning_bundle.contracts import (
    AnimationBrief,
    ElearningAuthoringBrief,
    ElearningAuthorOutput,
    ElearningBundleAssemblyInput,
    ElearningBundleAssemblyOutput,
    ManimVideoOutput,
)

# ── Capability names ──────────────────────────────────────────────────────────

CAP_AUTHOR = "elearning.course.author"
CAP_MANIM = "video.manim.render"
CAP_ASSEMBLE = "elearning.bundle.assemble"

CONTRACT_VERSION = "1.0"


# ── elearning.course.author ───────────────────────────────────────────────────


def elearning_course_author_tool_definition() -> ProductionToolDefinition:
    """Return the planner-safe definition for ``elearning.course.author``."""
    manifest = ToolManifest(
        capability=CAP_AUTHOR,
        contract_version=CONTRACT_VERSION,
        task_type=CAP_AUTHOR,
        description=(
            "Bounded agentic capability that creates structured e-learning course content "
            "from a frozen ElearningAuthoringBrief.  Uses CourseStructureRequirement sequence "
            "to author content screens via LLM, then inserts VideoSlotScreens deterministically. "
            "Validates all content against registered screen schemas and runs slot-preservation "
            "checks.  Returns intermediate CourseContent JSON, adjacent asset artifacts, a "
            "slot-preservation report, and an authoring trace.  "
            "Phase 14B: real executor available (PIPELINE_MODE=real). "
            "Default mode is reference (no credentials required).  "
            "Does not invoke Manim, HeyGen, or bundle assembly."
        ),
        supported_modalities=(Modality.ELEARNING,),
        input_schema=ElearningAuthoringBrief.model_json_schema(),
        output_schema=ElearningAuthorOutput.model_json_schema(),
        constraints={
            "bounded_agentic": True,
            "phase_14a_fake_only": True,
            "note": (
                "The authoring agent must not re-plan screen sequence or slot positions. "
                "Slot IDs are stable; the assembler depends on them."
            ),
        },
    )
    return ProductionToolDefinition(
        manifest=manifest,
        input_model=ElearningAuthoringBrief,
        output_model=ElearningAuthorOutput,
    )


# ── video.manim.render ────────────────────────────────────────────────────────


def manim_video_tool_definition() -> ProductionToolDefinition:
    """Return the planner-safe definition for ``video.manim.render``."""
    manifest = ToolManifest(
        capability=CAP_MANIM,
        contract_version=CONTRACT_VERSION,
        task_type=CAP_MANIM,
        description=(
            "Bounded agentic capability that creates an instructional animation from an "
            "AnimationBrief. Uses LLM-generated Manim Python scenes with required, "
            "synchronized TTS narration, rendered via an isolated Manim container. "
            "Returns an MP4 artifact "
            "and optional WebVTT captions, generated source, narration WAV, and render log.  "
            "Phase 14C: real executor available (PIPELINE_MODE=real with MANIM_* env vars). "
            "Default mode is reference (FakeManimVideoExecutor; no credentials required). "
            "Generated Python is executed only inside the isolated render container — never "
            "in the API process or main worker."
        ),
        supported_modalities=(Modality.ELEARNING,),
        input_schema=AnimationBrief.model_json_schema(),
        output_schema=ManimVideoOutput.model_json_schema(),
        constraints={
            "bounded_agentic": True,
            "requires_isolated_container": True,
            "note": (
                "Real execution requires the Manim container. "
                "Do not add Manim system dependencies to the main worker image. "
                "Generated source must not execute in any process that holds provider credentials."
            ),
        },
    )
    return ProductionToolDefinition(
        manifest=manifest,
        input_model=AnimationBrief,
        output_model=ManimVideoOutput,
    )


# ── elearning.bundle.assemble ─────────────────────────────────────────────────


def elearning_bundle_assemble_tool_definition() -> ProductionToolDefinition:
    """Return the planner-safe definition for ``elearning.bundle.assemble``."""
    manifest = ToolManifest(
        capability=CAP_ASSEMBLE,
        contract_version=CONTRACT_VERSION,
        task_type=CAP_ASSEMBLE,
        description=(
            "Deterministic capability that assembles the final e-learning bundle.  "
            "Reads the intermediate CourseContent JSON, validates slot preservation, "
            "replaces every VideoSlotScreen with a VideoPlayerScreen, stages all "
            "adjacent assets, renders final HTML without an LLM, and produces a "
            "portable ZIP bundle (HTML + assets + manifest).  "
            "No LLM, Manim, HeyGen, or provider calls.  Real implementation in Phase 14A."
        ),
        supported_modalities=(Modality.ELEARNING,),
        input_schema=ElearningBundleAssemblyInput.model_json_schema(),
        output_schema=ElearningBundleAssemblyOutput.model_json_schema(),
        constraints={
            "deterministic": True,
            "no_llm": True,
            "no_provider_calls": True,
            "note": (
                "Assembly depends on elearning.course.author and all video-producing jobs. "
                "Videos must be adjacent relative assets — no base64 embedding."
            ),
        },
    )
    return ProductionToolDefinition(
        manifest=manifest,
        input_model=ElearningBundleAssemblyInput,
        output_model=ElearningBundleAssemblyOutput,
    )
