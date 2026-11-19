"""Shared commissioning-to-generation planning composition.

This module owns the reusable composition that was previously available only
through CLI subcommands. It plans from an already-persisted CourseBlueprint and
does not select or sequence RLOs.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from llm_gateway import ModelAlias, llm_telemetry_context

from learning_pipeline.affordances.elearning import (
    ELEARNING_SUPPORT_RULES,
    build_elearning_affordance_catalog,
)
from learning_pipeline.affordances.podcast import PODCAST_SUPPORT_RULES
from learning_pipeline.affordances.video import VIDEO_SUPPORT_RULES, build_video_affordance_catalog
from learning_pipeline.config import build_tool_catalog, load_planner_settings
from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    FormatSelectionMode,
    FormatSelectionRequest,
    FormatSelectionResult,
)
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    AvatarVideoSceneDraft,
    ElearningModalityDraft,
    ElearningProductionDraft,
    ElearningSceneDraft,
    ModalityPlanningResult,
    NarrativeRole,
    PodcastModalityDraft,
    PodcastProductionDraft,
    PodcastSceneDraft,
    PodcastSpeechSegmentDraft,
    VideoBackgroundDraft,
    VideoModalityDraft,
    VideoProductionDraft,
    VideoSceneDraft,
    WorkflowPlanningResult,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
from learning_pipeline.format_selector.registry import build_default_registry
from learning_pipeline.format_selector.service import FormatSelectionService
from learning_pipeline.planners.client import FakePlanningClient, LiteLLMPlanningClient
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.planners.modality.context import ModalityContextResolver
from learning_pipeline.planners.modality.elearning.planner import ElearningModalityPlanner
from learning_pipeline.planners.modality.podcast.planner import PodcastModalityPlanner
from learning_pipeline.planners.modality.video.planner import VideoModalityPlanner
from learning_pipeline.planners.workflow.elearning.planner import ElearningWorkflowPlanner
from learning_pipeline.planners.workflow.podcast.planner import PodcastWorkflowPlanner
from learning_pipeline.planners.workflow.video.planner import VideoWorkflowPlanner
from learning_pipeline.production import ProductionCompiler
from learning_pipeline.runtime.artifact_store import ArtifactStore, FileArtifactStore
from learning_pipeline.services.modality_planning import ModalityPlanningService
from learning_pipeline.services.workflow_planning import WorkflowPlanningService
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    LearnerAction,
)


@dataclass(frozen=True)
class GenerationPlanningResult:
    format_selection: FormatSelectionResult
    modality_planning: ModalityPlanningResult
    workflow_planning: WorkflowPlanningResult


_MODALITY_ALIASES = {
    Modality.PODCAST: ModelAlias.PODCAST_MODALITY_PLANNING,
    Modality.VIDEO: ModelAlias.VIDEO_MODALITY_PLANNING,
    Modality.ELEARNING: ModelAlias.ELEARNING_MODALITY_PLANNING,
}
_WORKFLOW_ALIASES = {
    Modality.PODCAST: ModelAlias.PODCAST_WORKFLOW_PLANNING,
    Modality.VIDEO: ModelAlias.VIDEO_WORKFLOW_PLANNING,
    Modality.ELEARNING: ModelAlias.ELEARNING_WORKFLOW_PLANNING,
}


def _configured_heygen_profiles() -> frozenset[str]:
    """Logical HeyGen profile names this deployment can fully resolve.

    A profile is usable only when BOTH its avatar ID and voice ID are set in
    the environment (HEYGEN_AVATAR_PROFILE_*_ID / HEYGEN_VOICE_PROFILE_*_ID).
    """
    from learning_pipeline.tools.avatar_video.profiles import load_profile_settings

    registry = load_profile_settings()
    return registry.avatar_profile_names & registry.voice_profile_names


class GenerationPlanningService:
    """Plan format, modality, and executable workflow from one blueprint."""

    def __init__(
        self,
        rlo_repository,
        *,
        trace_root: Path | None = None,
        artifact_root: Path | None = None,
        artifact_store: ArtifactStore | None = None,
        mode: str = "reference",
    ) -> None:
        self._rlo_repository = rlo_repository
        self._trace_root = Path(trace_root) if trace_root else None
        if artifact_store is not None:
            self._artifact_store = artifact_store
        elif artifact_root is not None:
            self._artifact_store = FileArtifactStore(Path(artifact_root))
        else:
            raise ValueError("artifact_store or artifact_root is required")
        self._mode = mode.casefold()
        self._catalog = build_tool_catalog()
        if self._mode == "real":
            capabilities = {
                "speech.synthesize",
                "audio.assemble",
                "elearning.course.author",
                "video.manim.render",
                "elearning.bundle.assemble",
            }
            # Avatar rendering is producible only when the deployment can
            # actually resolve it: a HeyGen key AND at least one profile with
            # both avatar and voice IDs configured. Offering the capability
            # without a resolvable profile would let planners emit slots that
            # can only fail at execution time.
            if os.getenv("HEYGEN_API_KEY", "").strip() and _configured_heygen_profiles():
                capabilities.add("video.avatar.render")
            self._available_capabilities = frozenset(capabilities)
        else:
            self._available_capabilities = frozenset(self._catalog.capabilities)
        self._format_service = FormatSelectionService(
            registry=build_default_registry(
                available_capabilities=self._available_capabilities
            ),
            profiles=MODALITY_PROFILES,
            trace_root=(self._trace_root / "format-selection" if self._trace_root else None),
        )

    async def select_format(
        self,
        blueprint: CourseBlueprint,
        *,
        request_id: str,
        requested_modality: Modality | None = None,
    ) -> FormatSelectionResult:
        request = FormatSelectionRequest(
            request_id=request_id,
            blueprint_id=blueprint.blueprint_id,
            mode=(
                FormatSelectionMode.EXPLICIT
                if requested_modality is not None
                else FormatSelectionMode.AUTO
            ),
            requested_modality=requested_modality,
            allow_fallback=requested_modality is not None,
        )
        with llm_telemetry_context(job_id=request_id):
            return await self._format_service.select_format(
                blueprint, request, selection_id=f"format-{request_id}"
            )

    async def plan_modality(
        self,
        blueprint: CourseBlueprint,
        modality: Modality,
        *,
        request_id: str,
    ) -> ModalityPlanningResult:
        planner = self._build_modality_planner(blueprint, modality)
        support_rules, affordance_catalog = self._affordance_config(modality)
        service = ModalityPlanningService(
            resolver=ModalityContextResolver(self._rlo_repository),
            planner=planner,
            tool_catalog=self._catalog,
            support_rules=support_rules,
            affordance_catalog=affordance_catalog,
            available_capabilities=self._available_capabilities,
            trace_root=(self._trace_root / "modality" if self._trace_root else None),
        )
        with llm_telemetry_context(job_id=request_id):
            return await service.create_modality_plan(
                blueprint, modality, planning_request_id=request_id
            )

    async def plan_workflow(
        self,
        blueprint: CourseBlueprint,
        modality_plan: ModalityPlan,
        *,
        request_id: str,
        workflow_id: str,
    ) -> WorkflowPlanningResult:
        planner = self._build_workflow_planner(blueprint, modality_plan)
        modality = modality_plan.modality
        catalog_hash = hashlib.sha256(
            json.dumps(
                sorted(m.capability for m in self._catalog.planner_view(modality))
            ).encode()
        ).hexdigest()
        service = WorkflowPlanningService(
            resolver=PlanningContextResolver(self._rlo_repository),
            planner=planner,
            compiler=ProductionCompiler(self._catalog),
            catalog_hash=catalog_hash,
            trace_root=(self._trace_root / "workflow" if self._trace_root else None),
        )
        with llm_telemetry_context(job_id=workflow_id):
            return await service.plan(
                blueprint,
                modality_plan,
                planning_request_id=request_id,
                workflow_id=workflow_id,
            )

    async def plan_generation(
        self,
        blueprint: CourseBlueprint,
        *,
        request_id: str,
        workflow_id: str,
        requested_modality: Modality | None = None,
    ) -> GenerationPlanningResult:
        selected = await self.select_format(
            blueprint,
            request_id=request_id,
            requested_modality=requested_modality,
        )
        modality = selected.decision.selected_modality
        modality_result = await self.plan_modality(
            blueprint, modality, request_id=request_id
        )
        workflow_result = await self.plan_workflow(
            blueprint,
            modality_result.modality_plan,
            request_id=request_id,
            workflow_id=workflow_id,
        )
        return GenerationPlanningResult(selected, modality_result, workflow_result)

    def _real_client(self, alias: ModelAlias) -> tuple[LiteLLMPlanningClient, str]:
        settings = load_planner_settings(model=alias)
        return (
            LiteLLMPlanningClient(
                base_url=settings.base_url,
                api_key=settings.api_key,
            ),
            settings.model,
        )

    @staticmethod
    def _content_ref(ref) -> RLOContentRef:
        selected = ref.selected_content
        return RLOContentRef(
            rlo_id=ref.rlo_id,
            rlo_version=ref.rlo_version,
            objective_ids=selected.objective_ids,
            concept_ids=selected.concept_ids,
            component_ids=selected.component_ids,
            assessment_item_ids=selected.assessment_item_ids,
        )

    def _build_modality_planner(self, blueprint: CourseBlueprint, modality: Modality):
        if self._mode == "real":
            client, model = self._real_client(_MODALITY_ALIASES[modality])
        else:
            draft = self._reference_modality_draft(blueprint, modality)
            client = FakePlanningClient(draft=draft, prompt_version=f"{modality.value}_modality_v1")
            model = "reference"
        if modality == Modality.PODCAST:
            return PodcastModalityPlanner(client=client, model=model)
        if modality == Modality.VIDEO:
            return VideoModalityPlanner(client=client, model=model)
        return ElearningModalityPlanner(client=client, model=model)

    def _reference_modality_draft(self, blueprint: CourseBlueprint, modality: Modality):
        refs = sorted(blueprint.ordered_rlo_refs, key=lambda value: value.order)
        if modality == Modality.PODCAST:
            return PodcastModalityDraft(
                draft_id=f"reference-{blueprint.blueprint_id}",
                title=f"{blueprint.title} — Reference Podcast",
                narrative="Deterministic reference modality plan.",
                scenes=tuple(
                    PodcastSceneDraft(
                        scene_id=f"scene-{ref.rlo_id}-{index + 1}",
                        source_content=(self._content_ref(ref),),
                        learning_objective=f"Learn content from {ref.rlo_id}",
                        narrative_role=NarrativeRole.EXPLANATION,
                        affordance_id="host_expert_dialogue",
                        teaching_pattern="direct_instruction",
                        content_direction=f"Present the approved content from {ref.rlo_id}.",
                        target_duration_seconds=180,
                    )
                    for index, ref in enumerate(refs)
                ),
            )
        if modality == Modality.VIDEO:
            return VideoModalityDraft(
                draft_id=f"reference-{blueprint.blueprint_id}",
                title=f"{blueprint.title} — Reference Video",
                narrative="Deterministic reference modality plan.",
                scenes=tuple(
                    VideoSceneDraft(
                        scene_id=f"scene-{ref.rlo_id}-{index + 1}",
                        source_content=(self._content_ref(ref),),
                        learning_objective=f"Learn content from {ref.rlo_id}",
                        narrative_role=NarrativeRole.EXPLANATION,
                        affordance_id="avatar_led_explanation",
                        teaching_pattern="direct_instruction",
                        content_direction=f"Present the approved content from {ref.rlo_id}.",
                        presentation_direction="Instructor presents directly to camera.",
                        target_duration_seconds=120,
                    )
                    for index, ref in enumerate(refs)
                ),
            )
        return ElearningModalityDraft(
            draft_id=f"reference-{blueprint.blueprint_id}",
            title=f"{blueprint.title} — Reference E-learning",
            narrative="Deterministic reference modality plan.",
            scenes=tuple(
                ElearningSceneDraft(
                    scene_id=f"scene-{ref.rlo_id}-{index + 1}",
                    source_content=(self._content_ref(ref),),
                    learning_objective=f"Learn content from {ref.rlo_id}",
                    narrative_role=NarrativeRole.EXPLANATION,
                    affordance_id="elearning.static_explanation",
                    teaching_pattern="direct_instruction",
                    content_direction=f"Present the approved content from {ref.rlo_id}.",
                    target_duration_seconds=180,
                )
                for index, ref in enumerate(refs)
            ),
        )

    @staticmethod
    def _affordance_config(modality: Modality):
        if modality == Modality.VIDEO:
            return VIDEO_SUPPORT_RULES, build_video_affordance_catalog()
        if modality == Modality.ELEARNING:
            return ELEARNING_SUPPORT_RULES, build_elearning_affordance_catalog()
        return PODCAST_SUPPORT_RULES, None

    def _build_workflow_planner(self, blueprint: CourseBlueprint, plan: ModalityPlan):
        modality = plan.modality
        if self._mode == "real":
            client, model = self._real_client(_WORKFLOW_ALIASES[modality])
        else:
            draft = self._reference_workflow_draft(blueprint, plan)
            client = FakePlanningClient(draft=draft, prompt_version=f"{modality.value}_workflow_v1")
            model = "reference"
        if modality == Modality.PODCAST:
            return PodcastWorkflowPlanner(client=client, catalog=self._catalog, model=model)
        if modality == Modality.VIDEO:
            return VideoWorkflowPlanner(client=client, catalog=self._catalog, model=model)
        if self._mode == "real":
            # Offer the LLM only the avatar/voice profiles this deployment has
            # configured — planning must never promise a profile that HeyGen
            # execution cannot resolve. Reference mode keeps the planner's
            # deterministic defaults.
            configured = _configured_heygen_profiles()
            return ElearningWorkflowPlanner(
                client=client,
                catalog=self._catalog,
                model=model,
                approved_avatar_profiles=configured,
                approved_voice_profiles=configured,
                available_capabilities=self._available_capabilities,
                artifact_store=self._artifact_store,
            )
        return ElearningWorkflowPlanner(
            client=client,
            catalog=self._catalog,
            model=model,
            available_capabilities=self._available_capabilities,
            artifact_store=self._artifact_store,
        )

    @staticmethod
    def _reference_workflow_draft(blueprint: CourseBlueprint, plan: ModalityPlan):
        scene_ids = [scene.id for scene in plan.scenes]
        if plan.modality == Modality.PODCAST:
            return PodcastProductionDraft(
                draft_id=f"reference-{blueprint.blueprint_id}",
                title=f"{blueprint.title} — Reference Podcast",
                narrative_summary="Deterministic reference workflow plan.",
                segments=tuple(
                    PodcastSpeechSegmentDraft(
                        segment_id=f"segment-{index + 1}",
                        source_scene_ids=(scene_id,),
                        speaker="Host" if index % 2 == 0 else "Expert",
                        text=f"Approved training content for scene {scene_id}.",
                        learning_purpose="Deliver the planned learning content.",
                    )
                    for index, scene_id in enumerate(scene_ids)
                ),
            )
        if plan.modality == Modality.VIDEO:
            return VideoProductionDraft(
                draft_id=f"reference-{blueprint.blueprint_id}",
                title=f"{blueprint.title} — Reference Video",
                narrative_summary="Deterministic reference workflow plan.",
                render_capability="video.avatar.render",
                avatar_profile="default_instructor",
                voice_profile="default_instructor",
                width=1280,
                height=720,
                captions=False,
                scenes=tuple(
                    AvatarVideoSceneDraft(
                        scene_id=scene_id,
                        source_scene_ids=(scene_id,),
                        script=f"Approved training content for scene {scene_id}.",
                        background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
                        estimated_duration_seconds=float(
                            plan.scenes[index].target_duration_seconds or 60
                        ),
                    )
                    for index, scene_id in enumerate(scene_ids)
                ),
                production_rationale="Deterministic reference workflow plan.",
            )
        screens = tuple(
            requirement
            for index, scene_id in enumerate(scene_ids)
            for requirement in (
                AuthoredScreenRequirement(
                    screen_id=f"screen-{index + 1}",
                    screen_type="title" if index == 0 else "key_takeaways",
                    source_scene_ids=(scene_id,),
                    content_direction=f"Approved training content for scene {scene_id}.",
                    learner_action=LearnerAction.CONSUME,
                ),
                AuthoredScreenRequirement(
                    screen_id=f"screen-{index + 1}-assessment",
                    screen_type="knowledge_check",
                    source_scene_ids=(scene_id,),
                    content_direction=(
                        "Render the approved assessment items assigned to this scene."
                    ),
                    learner_action=LearnerAction.CHOOSE,
                ),
            )
        )
        return ElearningProductionDraft(
            draft_id=f"reference-{blueprint.blueprint_id}",
            source_modality_plan_id=plan.plan_id,
            narrative="Deterministic reference workflow plan.",
            authored_screens=screens,
            video_slots=(),
            screen_order=tuple(screen.screen_id for screen in screens),
            avatar_directives=(),
            manim_directives=(),
            course_authoring_direction="Build a concise corporate training module.",
        )
