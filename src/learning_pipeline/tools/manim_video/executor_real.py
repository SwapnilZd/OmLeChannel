"""Real Manim video executor — delegates to ManimGenerationController.

This is the canonical implementation of the video.manim.render tool step.
It wraps ManimGenerationController with:
  - ArtifactStore from workflow context
  - LLM client built from ManimSettings
  - ContainerManimRenderRunner with Docker isolation + LiteLLM-routed TTS

Fake mode (PIPELINE_MODE != "real") continues to use FakeManimVideoExecutor
defined in the elearning_bundle package.  This file is only imported in real
mode so that Docker, provider credentials, and container dependencies are not
required for tests.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from llm_gateway import ModelAlias
from learning_pipeline.runtime.artifact_store import ArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.elearning_bundle.contracts import (
    AnimationBrief,
    ManimVideoOutput,
)
from learning_pipeline.tools.errors import InvalidToolInputError
from learning_pipeline.tools.manim_video._contracts import ManimRenderPolicy
from learning_pipeline.tools.manim_video._controller import ManimGenerationController
from learning_pipeline.tools.manim_video._render_runner import ContainerManimRenderRunner
from learning_pipeline.tools.manim_video._template_catalog import ManimTemplateCatalog
from learning_pipeline.tools.manim_video._source_policy import SourcePolicyValidator


class RealManimVideoExecutor:
    """Executes video.manim.render using the canonical controller.

    The executor is responsible for:
    - Constructing an ArtifactStore scoped to the workflow.
    - Building the LLM and TTS clients from settings.
    - Running the controller and returning ManimVideoOutput.

    It does NOT interpret the brief — that is the controller's responsibility.
    It does NOT retry at this level — retries are owned by the controller state
    machine and render runner.

    Parameters
    ----------
    artifact_store:
        Pre-constructed ArtifactStore for artifact persistence.
    manim_image:
        Docker image name/tag for the isolated Manim renderer.
    lite_llm_base_url / lite_llm_api_key:
        Shared LiteLLM connection used for scene drafting and narration.
    llm_model:
        Purpose-specific LiteLLM alias for scene drafting.
    tts_model:
        Purpose-specific LiteLLM alias for Manim narration.
    tts_voice:
        Voice name passed to the TTS model (default: Kore).
    policy:
        Agentic execution policy bounds.
    render_policy:
        Render-specific bounds (attempts, timeout).
    cpu_limit / memory_limit:
        Docker resource limits for the render container.
    """

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        manim_image: str = "manim-renderer:latest",
        lite_llm_base_url: str,
        lite_llm_api_key: str,
        llm_model: str = ModelAlias.MANIM_SCENE_GENERATION,
        tts_model: str = ModelAlias.MANIM_SPEECH_SYNTHESIS,
        tts_voice: str = "Kore",
        policy: AgenticExecutionPolicy = AgenticExecutionPolicy(),
        render_policy: ManimRenderPolicy = ManimRenderPolicy(),
        cpu_limit: str = "2",
        memory_limit: str = "4g",
        docker_network: str | None = None,
        brand_outro: bool = True,
    ) -> None:
        from learning_pipeline.tools.manim_video._manim_client import (
            LiteLLMManimClient,
            LiteLLMManimSettings,
        )

        llm_client = LiteLLMManimClient(
            LiteLLMManimSettings(
                base_url=lite_llm_base_url,
                api_key=lite_llm_api_key,
                model_name=llm_model,
            )
        )

        tts_import = "from tts_service import LiteLLMTTSService"
        tts_service_call = (
            f'LiteLLMTTSService(voice="{tts_voice}", model="{tts_model}", transcription_model=None)'
        )

        render_runner = ContainerManimRenderRunner(
            image=manim_image,
            timeout_seconds=render_policy.render_timeout_seconds,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            lite_llm_base_url=lite_llm_base_url,
            lite_llm_api_key=lite_llm_api_key,
            docker_network=docker_network,
            brand_outro=brand_outro,
        )

        self._controller = ManimGenerationController(
            artifact_store=artifact_store,
            llm_client=llm_client,
            render_runner=render_runner,
            template_catalog=ManimTemplateCatalog(),
            source_validator=SourcePolicyValidator(),
            tts_import=tts_import,
            tts_service_call=tts_service_call,
            policy=policy,
            render_policy=render_policy,
        )

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        """Run the controller for the AnimationBrief encoded in context.inputs."""
        try:
            brief = AnimationBrief.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid video.manim.render input: {exc}"
            ) from exc

        context_bytes = json.dumps(context.inputs, ensure_ascii=False, default=str).encode()
        context_hash = hashlib.sha256(context_bytes).hexdigest()
        output: ManimVideoOutput = await self._controller.run(
            brief,
            workflow_id=context.workflow_id,
            task_id=context.task_id,
            context_bytes=context_bytes,
            context_hash=context_hash,
        )
        return output.model_dump()
