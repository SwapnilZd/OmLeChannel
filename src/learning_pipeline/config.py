"""
Runtime composition root.

Provides:
- ProductionToolCatalog factory (build_tool_catalog)
- ExecutorRegistry factories (build_fake_registry, build_real_registry,
  build_video_real_registry, build_elearning_reference_registry,
  build_elearning_real_author_registry)
- PipelineMode enum shared by CLI and worker
- TtsSettings / load_tts_settings() for real TTS execution
- ElearningAuthoringSettings / load_elearning_author_settings()
- PlannerSettings / load_planner_settings() for real LLM planning
- build_assembly_service() for the assemble-course subcommand

All subcommands and the worker resolve the pipeline mode from PIPELINE_MODE
(default: reference) or from the --mode CLI flag, never from per-capability
env vars. The only executor-level env vars that remain are provider credentials
and storage paths (HEYGEN_API_KEY, LITE_LLM_BASE_URL, etc.).

Environment variables:

  PIPELINE_MODE             — "reference" (default) or "real"

Real TTS execution (PIPELINE_MODE=real, podcast plan):
  LITE_LLM_BASE_URL         — shared LiteLLM proxy base URL (required)
  LITE_LLM_API_KEY          — shared LiteLLM proxy API key (required)
  PODCAST_HOST_VOICE        — voice for Host speaker (default: Aoede)
  PODCAST_EXPERT_VOICE      — voice for Expert speaker (default: Charon)
  TTS_INPUT_COST_PER_TOKEN  — $/token input cost (default: 0.000001)
  TTS_OUTPUT_COST_PER_TOKEN — $/token output cost (default: 0.00002)
  ARTIFACT_STORE_BACKEND    — "minio" for deployment or "file" for local CLI
  MINIO_ARTIFACT_BUCKET     — generated artifact bucket (default: workflow-artifacts)
  ARTIFACT_STORE_ROOT       — filesystem root when backend=file (default: /artifacts)

Real HeyGen execution (PIPELINE_MODE=real, video plan):
  HEYGEN_API_KEY                   — HeyGen API key (required)
  HEYGEN_ARTIFACT_STORE_ROOT       — artifact store root
                                     (defaults to ARTIFACT_STORE_ROOT)
  HEYGEN_OPERATION_STORE_ROOT      — checkpoint store root
                                     (default: <artifact_root>/heygen-ops)
  HEYGEN_ASSET_CACHE_ROOT          — asset cache root
                                     (default: <artifact_root>/heygen-cache)
  HEYGEN_POLL_INTERVAL             — seconds between status checks (default: 15)
  HEYGEN_MAX_POLL_WAIT             — max seconds to poll (default: 1800)
  HEYGEN_AVATAR_PROFILE_*_ID       — avatar profile IDs (see profiles.py)
  HEYGEN_VOICE_PROFILE_*_ID        — voice profile IDs (see profiles.py)

Real LLM planning (PIPELINE_MODE=real):
  LITE_LLM_BASE_URL         — shared LiteLLM proxy base URL (required)
  LITE_LLM_API_KEY          — shared LiteLLM proxy API key (required)
  PLANNER_TRACE_ROOT        — directory for plan trace persistence
                              (default: /plan-traces)

Real e-learning authoring (PIPELINE_MODE=real, e-learning plan):
  LITE_LLM_BASE_URL                — LiteLLM proxy base URL (required, shared)
  LITE_LLM_API_KEY                 — LiteLLM proxy API key (required, shared)
  ELEARNING_INPUT_COST_PER_TOKEN  — $/token input (default: 0.0)
  ELEARNING_OUTPUT_COST_PER_TOKEN — $/token output (default: 0.0)
  ELEARNING_ARTIFACT_STORE_ROOT   — artifact root (defaults to ARTIFACT_STORE_ROOT)

Real Manim rendering (PIPELINE_MODE=real, e-learning plan with video slots):
  LITE_LLM_BASE_URL                — LiteLLM proxy base URL (required, shared)
  LITE_LLM_API_KEY                 — LiteLLM proxy API key (required, shared)
  MANIM_TTS_VOICE                 — TTS voice name (default: Kore)
  MANIM_DOCKER_IMAGE              — render container image (default: manim-renderer:latest)
  MANIM_CPU_LIMIT                 — container --cpus (default: 2)
  MANIM_MEMORY_LIMIT              — container --memory (default: 4g)
  MANIM_DOCKER_NETWORK            — network containing internal LiteLLM host
  MANIM_BRAND_OUTRO               — "off" disables the Deloitte tagline outro
  MANIM_RENDER_TIMEOUT_SECONDS    — per-render container wall clock (default: 900;
                                    a multi-minute scene spends real time on TTS
                                    synthesis plus frame rendering)
                                    (required for A&A / T&L content); default on
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from llm_gateway import ModelAlias, load_lite_llm_settings

from learning_pipeline.runtime.execution import ExecutorRegistry
from learning_pipeline.runtime.artifact_store import (
    ArtifactStore,
    FileArtifactStore,
    create_artifact_store,
)
from learning_pipeline.tools.catalog import ProductionToolCatalog
from learning_pipeline.tools.errors import MissingRealModeConfigError
from learning_pipeline.tools.audio_assembly.definition import audio_assembly_tool_definition
from learning_pipeline.tools.avatar_video.definition import avatar_video_tool_definition
from learning_pipeline.tools.speech.definition import speech_tool_definition
from learning_pipeline.tools.elearning_bundle.definition import (
    elearning_course_author_tool_definition,
    manim_video_tool_definition,
    elearning_bundle_assemble_tool_definition,
)


# ── Pipeline mode ─────────────────────────────────────────────────────────────


class PipelineMode(StrEnum):
    REFERENCE = "reference"
    REAL = "real"


_CAP_SPEECH = "speech.synthesize"
_CAP_AUDIO = "audio.assemble"
_CAP_VIDEO = "video.avatar.render"
_CAP_ELEARNING_AUTHOR = "elearning.course.author"
_CAP_MANIM = "video.manim.render"
_CAP_ELEARNING_ASSEMBLE = "elearning.bundle.assemble"
_DEFAULT_ARTIFACT_ROOT = "/artifacts"
_TTS_TASK_TYPES = frozenset({_CAP_SPEECH, _CAP_AUDIO})
ELEARNING_TASK_TYPES = frozenset({_CAP_ELEARNING_AUTHOR, _CAP_MANIM, _CAP_ELEARNING_ASSEMBLE})


def _coerce_artifact_store(value: Path | ArtifactStore | None) -> ArtifactStore:
    if value is None:
        return create_artifact_store()
    if isinstance(value, (str, Path)):
        return FileArtifactStore(Path(value))
    return value


# ── Tool catalog ──────────────────────────────────────────────────────────────


def build_tool_catalog() -> ProductionToolCatalog:
    """Return a catalog populated with all registered production tool definitions."""
    catalog = ProductionToolCatalog()
    catalog.register(speech_tool_definition())
    catalog.register(audio_assembly_tool_definition())
    catalog.register(avatar_video_tool_definition())
    catalog.register(elearning_course_author_tool_definition())
    catalog.register(manim_video_tool_definition())
    catalog.register(elearning_bundle_assemble_tool_definition())
    return catalog


_TOOL_CATALOG: ProductionToolCatalog = build_tool_catalog()

REGISTERED_TASK_TYPES: frozenset[str] = _TOOL_CATALOG.task_types
"""All task types known to the catalog. Used by the API validator."""

FAKE_EXECUTOR_TASK_TYPES: frozenset[str] = REGISTERED_TASK_TYPES


# ── Executor registries ───────────────────────────────────────────────────────


def build_fake_registry() -> ExecutorRegistry:
    """Return an ExecutorRegistry with no-network fake executors for all capabilities."""
    from learning_pipeline.executors.fake import FakeAudioAssemblyExecutor, FakeSpeechExecutor
    from learning_pipeline.tools.avatar_video.executor_fake import FakeAvatarVideoExecutor

    registry = ExecutorRegistry()
    registry.register(_CAP_SPEECH, FakeSpeechExecutor())
    registry.register(_CAP_AUDIO, FakeAudioAssemblyExecutor())
    registry.register(_CAP_VIDEO, FakeAvatarVideoExecutor())
    return registry


def build_real_registry(
    *, settings: "TtsSettings", artifact_store: ArtifactStore | None = None
) -> ExecutorRegistry:
    """Real TTS executors for podcast build plans. Always uses real speech and audio."""
    from learning_pipeline.tools.audio_assembly.executor import RealAudioAssemblyExecutor
    from learning_pipeline.tools.speech.client import OpenAISpeechClient
    from learning_pipeline.tools.speech.executor import RealSpeechExecutor

    store = _coerce_artifact_store(artifact_store)
    client = OpenAISpeechClient(
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
    )
    registry = ExecutorRegistry()
    registry.register(_CAP_SPEECH, RealSpeechExecutor(
        client=client,
        artifact_store=store,
        voice_map={"Host": settings.host_voice, "Expert": settings.expert_voice},
        model=settings.model,
        input_cost_per_token=settings.input_cost_per_token,
        output_cost_per_token=settings.output_cost_per_token,
    ))
    registry.register(_CAP_AUDIO, RealAudioAssemblyExecutor(artifact_store=store))
    return registry


def build_video_real_registry(*, artifact_store: ArtifactStore | None = None) -> ExecutorRegistry:
    """Real HeyGen executor for video-only build plans."""
    store = _coerce_artifact_store(artifact_store)

    registry = ExecutorRegistry()
    registry.register(_CAP_VIDEO, _build_real_avatar_video_executor(store))
    return registry


def build_elearning_reference_registry(
    artifact_store_root: Path | ArtifactStore,
    *,
    avatar_artifact_store=None,
) -> ExecutorRegistry:
    """Registry for e-learning reference mode (no LLM, no Manim, no HeyGen).

    All three e-learning executors share a single FileArtifactStore so the
    assembler can read artifacts written by the fake author and fake Manim.

    Pass avatar_artifact_store to give the fake avatar executor a real store
    so it can write subtitle artifacts readable by the assembler.
    """
    from learning_pipeline.executors.fake import FakeAudioAssemblyExecutor, FakeSpeechExecutor
    from learning_pipeline.tools.avatar_video.executor_fake import FakeAvatarVideoExecutor
    from learning_pipeline.tools.elearning_bundle.executor_bundle import RealElearningBundleAssemblerExecutor
    from learning_pipeline.tools.elearning_bundle.executor_fake_author import FakeElearningCourseAuthorExecutor
    from learning_pipeline.tools.elearning_bundle.executor_fake_manim import FakeManimVideoExecutor

    store = _coerce_artifact_store(artifact_store_root)
    registry = ExecutorRegistry()
    registry.register(_CAP_SPEECH, FakeSpeechExecutor())
    registry.register(_CAP_AUDIO, FakeAudioAssemblyExecutor())
    registry.register(_CAP_VIDEO, FakeAvatarVideoExecutor(artifact_store=avatar_artifact_store or store))
    registry.register(_CAP_ELEARNING_AUTHOR, FakeElearningCourseAuthorExecutor(artifact_store=store))
    registry.register(_CAP_MANIM, FakeManimVideoExecutor(artifact_store=store))
    registry.register(_CAP_ELEARNING_ASSEMBLE, RealElearningBundleAssemblerExecutor(artifact_store=store))
    return registry


def _build_real_avatar_video_executor(store):
    """Construct a RealAvatarVideoExecutor from current environment configuration."""
    from learning_pipeline.providers.heygen.asset_cache import (
        MinioProviderAssetCache,
        ProviderAssetCache,
    )
    from learning_pipeline.providers.heygen.client import AsyncHeyGenClient
    from learning_pipeline.providers.heygen.mapper import HeyGenSceneMapper
    from learning_pipeline.providers.heygen.operation_store import (
        ArtifactExternalOperationStore,
        FileExternalOperationStore,
    )
    from learning_pipeline.tools.avatar_video.executor_real import RealAvatarVideoExecutor
    from learning_pipeline.tools.avatar_video.pricing import load_pricing_config
    from learning_pipeline.tools.avatar_video.profiles import load_profile_settings

    api_key = os.getenv("HEYGEN_API_KEY", "").strip()
    if not api_key:
        raise MissingRealModeConfigError(
            "HEYGEN_API_KEY is required when mode=real and the plan contains video tasks"
        )

    artifact_root = os.getenv(
        "HEYGEN_ARTIFACT_STORE_ROOT",
        os.getenv("ARTIFACT_STORE_ROOT", "/artifacts"),
    ).strip()

    if os.getenv("ARTIFACT_STORE_BACKEND", "file").strip().casefold() == "minio":
        operation_store = ArtifactExternalOperationStore(store)
        asset_cache = MinioProviderAssetCache.from_env()
    else:
        op_store_root = os.getenv(
            "HEYGEN_OPERATION_STORE_ROOT", f"{artifact_root}/heygen-ops"
        ).strip()
        asset_cache_root = os.getenv(
            "HEYGEN_ASSET_CACHE_ROOT", f"{artifact_root}/heygen-cache"
        ).strip()
        operation_store = FileExternalOperationStore(Path(op_store_root))
        asset_cache = ProviderAssetCache(Path(asset_cache_root))

    return RealAvatarVideoExecutor(
        client=AsyncHeyGenClient(api_key=api_key),
        artifact_store=store,
        profile_registry=load_profile_settings(),
        operation_store=operation_store,
        asset_cache=asset_cache,
        scene_mapper=HeyGenSceneMapper(),
        pricing=load_pricing_config(),
        poll_interval=float(os.getenv("HEYGEN_POLL_INTERVAL", "15")),
        max_poll_wait=float(os.getenv("HEYGEN_MAX_POLL_WAIT", "1800")),
    )


# ── TTS settings ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TtsSettings:
    """Typed configuration for real speech synthesis."""

    litellm_base_url: str
    litellm_api_key: str
    model: str
    host_voice: str
    expert_voice: str
    input_cost_per_token: float
    output_cost_per_token: float
    artifact_store_root: Path


def load_tts_settings() -> TtsSettings:
    """Read and validate TTS configuration from the environment.

    Raises ``MissingRealModeConfigError`` if any required variable is absent.
    Only call when mode=real and the plan contains TTS tasks.
    """
    try:
        connection = load_lite_llm_settings()
    except ValueError as exc:
        raise MissingRealModeConfigError(
            f"{exc} when mode=real and the plan contains TTS tasks"
        ) from exc
    artifact_root = os.getenv("ARTIFACT_STORE_ROOT", _DEFAULT_ARTIFACT_ROOT).strip()
    return TtsSettings(
        litellm_base_url=connection.base_url,
        litellm_api_key=connection.api_key,
        model=ModelAlias.PODCAST_SPEECH_SYNTHESIS,
        host_voice=os.getenv("PODCAST_HOST_VOICE", "Aoede"),
        expert_voice=os.getenv("PODCAST_EXPERT_VOICE", "Charon"),
        input_cost_per_token=float(os.getenv("TTS_INPUT_COST_PER_TOKEN", "0.000001")),
        output_cost_per_token=float(os.getenv("TTS_OUTPUT_COST_PER_TOKEN", "0.00002")),
        artifact_store_root=Path(artifact_root),
    )


# ── Planner settings ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlannerSettings:
    """Typed LLM planning configuration. Only required when mode=real."""

    base_url: str
    api_key: str
    model: str
    trace_root: Path


def load_planner_settings(*, model: ModelAlias) -> PlannerSettings:
    """Read and validate LLM planner configuration from the environment.

    Only call when mode=real. All planners share the application-wide LiteLLM
    connection; the caller selects a purpose-specific alias from config.yaml.
    """
    try:
        connection = load_lite_llm_settings()
    except ValueError as exc:
        raise MissingRealModeConfigError(f"{exc} when mode=real") from exc
    trace_root_str = os.getenv("PLANNER_TRACE_ROOT", "/plan-traces").strip()
    return PlannerSettings(
        base_url=connection.base_url,
        api_key=connection.api_key,
        model=model,
        trace_root=Path(trace_root_str),
    )


# ── E-learning authoring settings ────────────────────────────────────────────


@dataclass(frozen=True)
class ElearningAuthoringSettings:
    """Typed configuration for real e-learning course authoring."""

    litellm_base_url: str
    litellm_api_key: str
    model_name: str
    input_cost_per_token: float
    output_cost_per_token: float
    artifact_store_root: Path


def load_elearning_author_settings() -> ElearningAuthoringSettings:
    """Read and validate e-learning authoring config from the environment.

    Raises ``MissingRealModeConfigError`` if required variables are absent.
    Only call when mode=real and the plan contains e-learning authoring tasks.
    """
    try:
        connection = load_lite_llm_settings()
    except ValueError as exc:
        raise MissingRealModeConfigError(
            f"{exc} when mode=real and the plan contains e-learning tasks"
        ) from exc
    artifact_root = os.getenv("ARTIFACT_STORE_ROOT", _DEFAULT_ARTIFACT_ROOT).strip()
    return ElearningAuthoringSettings(
        litellm_base_url=connection.base_url,
        litellm_api_key=connection.api_key,
        model_name=ModelAlias.ELEARNING_COURSE_AUTHORING,
        input_cost_per_token=0.0,
        output_cost_per_token=0.0,
        artifact_store_root=Path(artifact_root),
    )


def build_elearning_real_author_registry(
    artifact_store_root: Path | ArtifactStore,
    authoring_settings: ElearningAuthoringSettings,
) -> ExecutorRegistry:
    """Registry for --mode real elearning runs.

    Uses real executors for authoring, avatar video (HeyGen), Manim, and
    bundle assembly.  Requires HEYGEN_API_KEY in the environment in addition
    to the shared LITE_LLM_BASE_URL / LITE_LLM_API_KEY credentials.  Speech and audio assembly are not used by the
    elearning pipeline so they remain as no-op stubs.
    """
    from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
    from learning_pipeline.tools.elearning_bundle._authoring_client import (
        LiteLLMAuthoringSettings,
        LiteLLMElearningAuthoringClient,
    )
    from learning_pipeline.tools.elearning_bundle.executor_bundle import RealElearningBundleAssemblerExecutor
    from learning_pipeline.tools.elearning_bundle.executor_real_author import RealElearningCourseAuthorExecutor
    from learning_pipeline.tools.manim_video._contracts import ManimRenderPolicy
    from learning_pipeline.tools.manim_video.executor_real import RealManimVideoExecutor

    store = _coerce_artifact_store(artifact_store_root)
    client_settings = LiteLLMAuthoringSettings(
        base_url=authoring_settings.litellm_base_url,
        api_key=authoring_settings.litellm_api_key,
        model_name=authoring_settings.model_name,
        input_cost_per_token=authoring_settings.input_cost_per_token,
        output_cost_per_token=authoring_settings.output_cost_per_token,
    )
    authoring_client = LiteLLMElearningAuthoringClient(client_settings)

    manim_settings = load_manim_settings()
    real_manim = RealManimVideoExecutor(
        artifact_store=store,
        manim_image=manim_settings.docker_image,
        lite_llm_base_url=manim_settings.litellm_base_url,
        lite_llm_api_key=manim_settings.litellm_api_key,
        llm_model=manim_settings.model_name,
        tts_model=manim_settings.tts_model,
        tts_voice=manim_settings.tts_voice,
        policy=AgenticExecutionPolicy(),
        render_policy=ManimRenderPolicy(
            render_timeout_seconds=manim_settings.render_timeout_seconds
        ),
        cpu_limit=manim_settings.cpu_limit,
        memory_limit=manim_settings.memory_limit,
        docker_network=manim_settings.docker_network,
        brand_outro=manim_settings.brand_outro,
    )

    registry = ExecutorRegistry()
    registry.register(_CAP_VIDEO, _build_real_avatar_video_executor(store))
    registry.register(
        _CAP_ELEARNING_AUTHOR,
        RealElearningCourseAuthorExecutor(
            artifact_store=store,
            authoring_client=authoring_client,
        ),
    )
    registry.register(_CAP_MANIM, real_manim)
    registry.register(_CAP_ELEARNING_ASSEMBLE, RealElearningBundleAssemblerExecutor(artifact_store=store))
    return registry


# ── Manim settings ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManimSettings:
    """Typed configuration for real Manim video generation."""

    litellm_base_url: str
    litellm_api_key: str
    model_name: str
    tts_model: str
    tts_voice: str
    docker_image: str
    cpu_limit: str
    memory_limit: str
    docker_network: str | None
    artifact_store_root: Path
    brand_outro: bool
    render_timeout_seconds: int


def load_manim_settings() -> ManimSettings:
    """Read and validate Manim configuration from the environment.

    Raises ``MissingRealModeConfigError`` if required variables are absent.
    Only call when mode=real and the plan contains video.manim.render tasks.
    """
    try:
        connection = load_lite_llm_settings()
    except ValueError as exc:
        raise MissingRealModeConfigError(
            f"{exc} when mode=real and the plan contains Manim tasks"
        ) from exc
    return ManimSettings(
        litellm_base_url=connection.base_url,
        litellm_api_key=connection.api_key,
        model_name=ModelAlias.MANIM_SCENE_GENERATION,
        tts_model=ModelAlias.MANIM_SPEECH_SYNTHESIS,
        tts_voice=os.getenv("MANIM_TTS_VOICE", "Kore"),
        docker_image=os.getenv("MANIM_DOCKER_IMAGE", "manim-renderer:latest"),
        cpu_limit=os.getenv("MANIM_CPU_LIMIT", "2"),
        memory_limit=os.getenv("MANIM_MEMORY_LIMIT", "4g"),
        docker_network=os.getenv("MANIM_DOCKER_NETWORK") or None,
        artifact_store_root=Path(os.getenv("ARTIFACT_STORE_ROOT", _DEFAULT_ARTIFACT_ROOT)),
        brand_outro=os.getenv("MANIM_BRAND_OUTRO", "on").strip().lower() != "off",
        render_timeout_seconds=int(os.getenv("MANIM_RENDER_TIMEOUT_SECONDS", "900")),
    )


def build_elearning_real_manim_registry(
    artifact_store_root: Path | ArtifactStore,
    authoring_settings: ElearningAuthoringSettings,
    manim_settings: ManimSettings,
) -> ExecutorRegistry:
    """Registry with real author, real Manim, and real assembler.

    Requires both ElearningAuthoringSettings (LiteLLM credentials) and
    ManimSettings (Manim LLM + optional TTS credentials, Docker image).
    No HeyGen or podcast TTS calls.
    """
    from learning_pipeline.tools.elearning_bundle._authoring_client import (
        LiteLLMAuthoringSettings,
        LiteLLMElearningAuthoringClient,
    )
    from learning_pipeline.tools.elearning_bundle.executor_bundle import RealElearningBundleAssemblerExecutor
    from learning_pipeline.tools.elearning_bundle.executor_real_author import RealElearningCourseAuthorExecutor
    from learning_pipeline.tools.manim_video.executor_real import RealManimVideoExecutor
    from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
    from learning_pipeline.tools.manim_video._contracts import ManimRenderPolicy

    store = _coerce_artifact_store(artifact_store_root)
    client_settings = LiteLLMAuthoringSettings(
        base_url=authoring_settings.litellm_base_url,
        api_key=authoring_settings.litellm_api_key,
        model_name=authoring_settings.model_name,
        input_cost_per_token=authoring_settings.input_cost_per_token,
        output_cost_per_token=authoring_settings.output_cost_per_token,
    )
    authoring_client = LiteLLMElearningAuthoringClient(client_settings)

    real_manim = RealManimVideoExecutor(
        artifact_store=store,
        manim_image=manim_settings.docker_image,
        lite_llm_base_url=manim_settings.litellm_base_url,
        lite_llm_api_key=manim_settings.litellm_api_key,
        llm_model=manim_settings.model_name,
        tts_model=manim_settings.tts_model,
        tts_voice=manim_settings.tts_voice,
        policy=AgenticExecutionPolicy(),
        render_policy=ManimRenderPolicy(
            render_timeout_seconds=manim_settings.render_timeout_seconds
        ),
        cpu_limit=manim_settings.cpu_limit,
        memory_limit=manim_settings.memory_limit,
        docker_network=manim_settings.docker_network,
        brand_outro=manim_settings.brand_outro,
    )

    registry = ExecutorRegistry()
    registry.register(
        _CAP_ELEARNING_AUTHOR,
        RealElearningCourseAuthorExecutor(
            artifact_store=store,
            authoring_client=authoring_client,
        ),
    )
    registry.register(_CAP_MANIM, real_manim)
    registry.register(_CAP_ELEARNING_ASSEMBLE, RealElearningBundleAssemblerExecutor(artifact_store=store))
    return registry


# ── Assembly service factory ──────────────────────────────────────────────────


def build_assembly_service(
    *,
    rlo_root: Path | None = None,
    trace_root: Path | None = None,
    context_budget_chars: int = 500_000,
    mode: str,
):
    """Construct a CourseAssemblyService.

    Parameters
    ----------
    mode:
        'reference' or 'real'. Always supplied by the caller (no env fallback).
    rlo_root:
        Root directory for FileRLORepository. Required in both modes — the
        service loads RLO content before calling the planning agent regardless
        of mode. Falls back to ASSEMBLY_RLO_ROOT env var, then /rlos.
    trace_root:
        Directory for persisting assembly outputs. Reads ASSEMBLY_TRACE_ROOT
        from environment when not supplied.
    context_budget_chars:
        Maximum serialized context size.
    """
    from learning_pipeline.planners.curriculum.agent import (
        FakeCurriculumAssemblyAgent,
        LiteLLMCurriculumAssemblyAgent,
    )
    from learning_pipeline.planners.curriculum.service import CourseAssemblyService
    from learning_pipeline.repository import FileRLORepository

    if trace_root is None:
        root_str = os.getenv("ASSEMBLY_TRACE_ROOT", "").strip()
        trace_root = Path(root_str) if root_str else None

    rlo_directory = rlo_root or Path(os.getenv("ASSEMBLY_RLO_ROOT", "/rlos"))
    repo = FileRLORepository(rlo_directory)

    if mode.strip().lower() == PipelineMode.REAL:
        settings = load_planner_settings(model=ModelAlias.CURRICULUM_ASSEMBLY)
        from learning_pipeline.planners.client import LiteLLMPlanningClient
        client = LiteLLMPlanningClient(
            base_url=settings.base_url,
            api_key=settings.api_key,
        )
        agent = LiteLLMCurriculumAssemblyAgent(client=client, model=settings.model)
    else:
        agent = FakeCurriculumAssemblyAgent()

    return CourseAssemblyService(
        agent=agent,
        repository=repo,
        trace_root=trace_root,
        context_budget_chars=context_budget_chars,
    )
