import argparse
import asyncio
import os
import sys
from pathlib import Path

from llm_gateway import ModelAlias
from learning_pipeline.contracts import BuildPlan
from learning_pipeline.runtime.execution import ExecutorRegistry
from learning_pipeline.runtime.local_executors import ConcatExecutor, EmitExecutor
from learning_pipeline.runtime.persistence import FileRunStateStore
from learning_pipeline.runtime.runner import DAGRunner, WorkflowExecutionError

_SUBCOMMANDS = frozenset({
    "run-workflow",
    "run-reference-elearning",
    "plan-podcast-workflow",
    "plan-podcast-modality",
    "plan-video-workflow",
    "plan-video-modality",
    "plan-elearning-modality",
    "plan-elearning-workflow",
    "select-format",
    "assemble-course",
})

_MODE_CHOICES = ["reference", "real"]
_DEFAULT_RLO_ROOT = "/rlos"
_RLO_REQUIRED = "--rlo-directory is required in reference mode"
_PLANNING_TRACE = "planning-trace.json"


def _pipeline_mode(arg: str | None) -> str:
    """Resolve pipeline mode from CLI arg or PIPELINE_MODE env var."""
    if arg:
        return arg.strip().lower()
    return os.getenv("PIPELINE_MODE", "reference").strip().lower()


# ── run-workflow ──────────────────────────────────────────────────────────────


def _select_registry(task_types: set[str], mode: str, run_dir: Path):
    from learning_pipeline.config import ELEARNING_TASK_TYPES

    needs_elearning = bool(task_types & ELEARNING_TASK_TYPES)
    needs_tts = bool(task_types & {"speech.synthesize", "audio.assemble"})

    if mode != "real":
        from learning_pipeline.config import build_elearning_reference_registry, build_fake_registry
        if not needs_elearning:
            return build_fake_registry()
        artifact_root = run_dir / "artifacts"
        artifact_root.mkdir(parents=True, exist_ok=True)
        return build_elearning_reference_registry(artifact_root)

    if needs_elearning:
        from learning_pipeline.config import build_elearning_real_author_registry, load_elearning_author_settings
        artifact_root = run_dir / "artifacts"
        artifact_root.mkdir(parents=True, exist_ok=True)
        try:
            settings = load_elearning_author_settings()
        except Exception as exc:
            raise SystemExit(f"real-mode e-learning authoring configuration error: {exc}") from exc
        return build_elearning_real_author_registry(artifact_root, settings)

    if needs_tts:
        from learning_pipeline.config import build_real_registry, load_tts_settings
        try:
            settings = load_tts_settings()
        except Exception as exc:
            raise SystemExit(f"real-mode TTS configuration error: {exc}") from exc
        return build_real_registry(settings=settings)

    from learning_pipeline.config import build_video_real_registry
    return build_video_real_registry()


async def _run(plan_path: Path, run_dir: Path, mode: str) -> str:
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read plan file: {exc}") from exc

    try:
        plan = BuildPlan.model_validate_json(text)
    except Exception as exc:
        raise SystemExit(f"invalid build plan: {exc}") from exc

    task_types = {t.task_type for t in plan.tasks}
    registry = _select_registry(task_types, mode, run_dir)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(plan)
    return result.model_dump_json(indent=2)


async def _run_reference_elearning(
    plan_path: Path,
    run_dir: Path,
    artifact_root: Path | None,
) -> str:
    """Execute an e-learning BuildPlan with the deterministic reference registry."""
    try:
        text = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read plan file: {exc}") from exc

    try:
        plan = BuildPlan.model_validate_json(text)
    except Exception as exc:
        raise SystemExit(f"invalid build plan: {exc}") from exc

    from learning_pipeline.config import build_elearning_reference_registry

    store_root = artifact_root or (run_dir / "artifacts")
    store_root.mkdir(parents=True, exist_ok=True)
    registry = build_elearning_reference_registry(store_root)

    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(plan)
    return result.model_dump_json(indent=2)


# ── plan-podcast-workflow ─────────────────────────────────────────────────────


async def _plan_podcast_workflow(
    blueprint_path: Path,
    modality_plan_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    mode: str,
) -> str:
    import json as _json

    from learning_pipeline.contracts import CourseBlueprint, ModalityPlan
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.planners.context import PlanningContextResolver
    from learning_pipeline.planners.workflow.podcast.planner import PodcastWorkflowPlanner
    from learning_pipeline.services.workflow_planning import WorkflowPlanningService
    from learning_pipeline.production import ProductionCompiler

    try:
        blueprint = CourseBlueprint.model_validate_json(
            blueprint_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc

    try:
        modality_plan = ModalityPlan.model_validate_json(
            modality_plan_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid modality plan: {exc}") from exc

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)

    import hashlib
    catalog_hash = hashlib.sha256(
        _json.dumps(
            sorted(m.capability for m in catalog.planner_view(Modality.PODCAST)),
            sort_keys=True,
        ).encode()
    ).hexdigest()

    if mode == "real":
        from learning_pipeline.config import load_planner_settings
        from learning_pipeline.planners.client import LiteLLMPlanningClient
        from learning_pipeline.repository import FileRLORepository

        ps = load_planner_settings(model=ModelAlias.PODCAST_WORKFLOW_PLANNING)
        client = LiteLLMPlanningClient(base_url=ps.base_url, api_key=ps.api_key)
        model = ps.model
        resolver = PlanningContextResolver(FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)))
    else:
        from learning_pipeline.contracts.planning import (
            PodcastProductionDraft,
            PodcastSpeechSegmentDraft,
        )
        from learning_pipeline.planners.client import FakePlanningClient
        from learning_pipeline.repository import FileRLORepository

        if rlo_root is None:
            raise SystemExit(_RLO_REQUIRED)

        scene_ids = [s.id for s in modality_plan.scenes]
        fake_draft = PodcastProductionDraft(
            draft_id="reference-draft",
            title=f"{blueprint.title} — Reference Draft",
            narrative_summary=(
                "Reference draft generated by plan-podcast-workflow in reference mode. "
                "Use --mode real for a model-generated plan."
            ),
            segments=tuple(
                PodcastSpeechSegmentDraft(
                    segment_id=f"seg-{i + 1}",
                    source_scene_ids=(sid,),
                    speaker="Host" if i % 2 == 0 else "Expert",
                    text=f"Placeholder content for scene {sid}.",
                    learning_purpose="Reference placeholder",
                )
                for i, sid in enumerate(scene_ids)
            ),
        )
        client = FakePlanningClient(draft=fake_draft)
        model = "reference"
        resolver = PlanningContextResolver(FileRLORepository(rlo_root))

    planner = PodcastWorkflowPlanner(client=client, catalog=catalog, model=model)
    service = WorkflowPlanningService(
        resolver=resolver,
        planner=planner,
        compiler=compiler,
        catalog_hash=catalog_hash,
        trace_root=output_dir / "traces",
    )

    result = await service.plan(
        blueprint,
        modality_plan,
        planning_request_id=request_id,
        workflow_id=request_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "production_plan.json").write_text(
        result.production_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "build_plan.json").write_text(
        result.build_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / _PLANNING_TRACE).write_text(
        result.trace.model_dump_json(indent=2), encoding="utf-8"
    )

    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "production_plan": str(output_dir / "production_plan.json"),
            "build_plan": str(output_dir / "build_plan.json"),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
        },
        indent=2,
    )


# ── plan-video-workflow ───────────────────────────────────────────────────────


async def _plan_video_workflow(
    blueprint_path: Path,
    modality_plan_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    mode: str,
) -> str:
    import json as _json

    from learning_pipeline.contracts import CourseBlueprint, ModalityPlan
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.planners.context import PlanningContextResolver
    from learning_pipeline.planners.workflow.video.planner import VideoWorkflowPlanner
    from learning_pipeline.services.workflow_planning import WorkflowPlanningService
    from learning_pipeline.production import ProductionCompiler

    try:
        blueprint = CourseBlueprint.model_validate_json(
            blueprint_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc

    try:
        modality_plan = ModalityPlan.model_validate_json(
            modality_plan_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid modality plan: {exc}") from exc

    if modality_plan.modality != Modality.VIDEO:
        raise SystemExit(
            f"plan-video-workflow requires a video modality plan; "
            f"got '{modality_plan.modality}'"
        )

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)

    import hashlib
    catalog_hash = hashlib.sha256(
        _json.dumps(
            sorted(m.capability for m in catalog.planner_view(Modality.VIDEO)),
            sort_keys=True,
        ).encode()
    ).hexdigest()

    if mode == "real":
        from learning_pipeline.config import load_planner_settings
        from learning_pipeline.planners.client import LiteLLMPlanningClient
        from learning_pipeline.repository import FileRLORepository

        ps = load_planner_settings(model=ModelAlias.VIDEO_WORKFLOW_PLANNING)
        client = LiteLLMPlanningClient(base_url=ps.base_url, api_key=ps.api_key)
        model = ps.model
        resolver = PlanningContextResolver(FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)))
    else:
        from learning_pipeline.contracts.planning import (
            AvatarVideoSceneDraft,
            VideoBackgroundDraft,
            VideoProductionDraft,
        )
        from learning_pipeline.planners.client import FakePlanningClient
        from learning_pipeline.repository import FileRLORepository

        if rlo_root is None:
            raise SystemExit(_RLO_REQUIRED)

        scene_ids = [s.id for s in modality_plan.scenes]
        fake_draft = VideoProductionDraft(
            draft_id=f"video-reference-{blueprint.blueprint_id}",
            title=f"{blueprint.title} — Reference Video Draft",
            narrative_summary=(
                "Reference draft generated by plan-video-workflow in reference mode. "
                "Use --mode real for a model-generated plan."
            ),
            render_capability="video.avatar.render",
            avatar_profile="default_instructor",
            voice_profile="default_instructor",
            width=1280,
            height=720,
            captions=False,
            scenes=tuple(
                AvatarVideoSceneDraft(
                    scene_id=sid,
                    source_scene_ids=(sid,),
                    script=f"Placeholder narration for scene {sid}.",
                    background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
                    estimated_duration_seconds=float(
                        modality_plan.scenes[i].target_duration_seconds or 60
                    ),
                )
                for i, sid in enumerate(scene_ids)
            ),
            production_rationale="Reference placeholder; use --mode real for a real plan.",
        )
        client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
        model = "reference"
        resolver = PlanningContextResolver(FileRLORepository(rlo_root))

    planner = VideoWorkflowPlanner(client=client, catalog=catalog, model=model)
    service = WorkflowPlanningService(
        resolver=resolver,
        planner=planner,
        compiler=compiler,
        catalog_hash=catalog_hash,
        trace_root=output_dir / "traces",
    )

    result = await service.plan(
        blueprint,
        modality_plan,
        planning_request_id=request_id,
        workflow_id=request_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "video-production-plan.json").write_text(
        result.production_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "video-build-plan.json").write_text(
        result.build_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / _PLANNING_TRACE).write_text(
        result.trace.model_dump_json(indent=2), encoding="utf-8"
    )

    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "video_production_plan": str(output_dir / "video-production-plan.json"),
            "video_build_plan": str(output_dir / "video-build-plan.json"),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
        },
        indent=2,
    )


# ── plan-podcast-modality ─────────────────────────────────────────────────────


async def _plan_podcast_modality(
    blueprint_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    mode: str,
) -> str:
    import json as _json

    from learning_pipeline.contracts import CourseBlueprint
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.planners.modality.context import ModalityContextResolver
    from learning_pipeline.planners.modality.podcast.planner import PodcastModalityPlanner
    from learning_pipeline.services.modality_planning import ModalityPlanningService
    from learning_pipeline.affordances.podcast import PODCAST_SUPPORT_RULES

    try:
        blueprint = CourseBlueprint.model_validate_json(
            blueprint_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc

    catalog = build_tool_catalog()

    if mode == "real":
        from learning_pipeline.config import load_planner_settings
        from learning_pipeline.planners.client import LiteLLMPlanningClient
        from learning_pipeline.repository import FileRLORepository

        ps = load_planner_settings(model=ModelAlias.PODCAST_MODALITY_PLANNING)
        client = LiteLLMPlanningClient(base_url=ps.base_url, api_key=ps.api_key)
        resolver = ModalityContextResolver(FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)))
        planner = PodcastModalityPlanner(client=client, model=ps.model)
    else:
        from learning_pipeline.contracts.modality import RLOContentRef
        from learning_pipeline.contracts.planning import (
            PodcastModalityDraft,
            PodcastSceneDraft,
            NarrativeRole,
        )
        from learning_pipeline.planners.client import FakePlanningClient
        from learning_pipeline.repository import FileRLORepository

        if rlo_root is None:
            raise SystemExit(_RLO_REQUIRED)

        sorted_refs = sorted(blueprint.ordered_rlo_refs, key=lambda r: r.order)
        scenes = []
        for i, ref in enumerate(sorted_refs):
            sel = ref.selected_content
            scenes.append(PodcastSceneDraft(
                scene_id=f"scene-{ref.rlo_id}-{i + 1}",
                source_content=(RLOContentRef(
                    rlo_id=ref.rlo_id,
                    rlo_version=ref.rlo_version,
                    objective_ids=sel.objective_ids,
                    concept_ids=sel.concept_ids,
                    component_ids=sel.component_ids,
                    assessment_item_ids=sel.assessment_item_ids,
                ),),
                learning_objective=f"Learn content from {ref.rlo_id}",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct_instruction",
                content_direction=f"Reference placeholder for {ref.rlo_id}.",
                target_duration_seconds=180,
            ))

        fake_draft = PodcastModalityDraft(
            draft_id=f"reference-{blueprint.blueprint_id}",
            title=f"{blueprint.title} — Reference Podcast Modality Plan",
            narrative="Reference draft; use --mode real for a model-generated modality plan.",
            scenes=tuple(scenes),
        )
        client = FakePlanningClient(draft=fake_draft, prompt_version="podcast_modality_v1")
        resolver = ModalityContextResolver(FileRLORepository(rlo_root))
        planner = PodcastModalityPlanner(client=client, model="reference")

    service = ModalityPlanningService(
        resolver=resolver,
        planner=planner,
        tool_catalog=catalog,
        support_rules=PODCAST_SUPPORT_RULES,
        trace_root=output_dir / "traces",
    )

    result = await service.create_modality_plan(
        blueprint,
        Modality.PODCAST,
        planning_request_id=request_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "modality_plan.json").write_text(
        result.modality_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "coverage_report.json").write_text(
        result.coverage.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "planning_trace.json").write_text(
        result.trace.model_dump_json(indent=2), encoding="utf-8"
    )

    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "modality_plan": str(output_dir / "modality_plan.json"),
            "coverage_report": str(output_dir / "coverage_report.json"),
            "planning_trace": str(output_dir / "planning_trace.json"),
            "context_hash": result.trace.context_hash,
        },
        indent=2,
    )


# ── plan-video-modality ───────────────────────────────────────────────────────


async def _plan_video_modality(
    blueprint_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    format_selection_path: Path | None,
    mode: str,
) -> str:
    import json as _json

    from learning_pipeline.contracts import CourseBlueprint
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.planners.modality.context import ModalityContextResolver
    from learning_pipeline.planners.modality.video.planner import VideoModalityPlanner
    from learning_pipeline.services.modality_planning import ModalityPlanningService
    from learning_pipeline.affordances.video import VIDEO_SUPPORT_RULES, build_video_affordance_catalog

    try:
        blueprint = CourseBlueprint.model_validate_json(
            blueprint_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc

    if format_selection_path is not None:
        from learning_pipeline.contracts.format_selection import FormatSelectionDecision
        try:
            decision = FormatSelectionDecision.model_validate_json(
                format_selection_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise SystemExit(f"invalid format selection: {exc}") from exc
        if decision.selected_modality != Modality.VIDEO:
            raise SystemExit(
                f"format selection specifies '{decision.selected_modality}', not video"
            )
        if decision.blueprint_id != blueprint.blueprint_id:
            raise SystemExit(
                f"format selection references blueprint '{decision.blueprint_id}' "
                f"but blueprint is '{blueprint.blueprint_id}'"
            )

    catalog = build_tool_catalog()

    if mode == "real":
        from learning_pipeline.config import load_planner_settings
        from learning_pipeline.planners.client import LiteLLMPlanningClient
        from learning_pipeline.repository import FileRLORepository

        ps = load_planner_settings(model=ModelAlias.VIDEO_MODALITY_PLANNING)
        client = LiteLLMPlanningClient(base_url=ps.base_url, api_key=ps.api_key)
        resolver = ModalityContextResolver(FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)))
        planner = VideoModalityPlanner(client=client, model=ps.model)
    else:
        from learning_pipeline.contracts.modality import RLOContentRef
        from learning_pipeline.contracts.planning import (
            NarrativeRole,
            VideoModalityDraft,
            VideoSceneDraft,
        )
        from learning_pipeline.planners.client import FakePlanningClient
        from learning_pipeline.repository import FileRLORepository

        if rlo_root is None:
            raise SystemExit(_RLO_REQUIRED)

        sorted_refs = sorted(blueprint.ordered_rlo_refs, key=lambda r: r.order)
        scenes = []
        for i, ref in enumerate(sorted_refs):
            sel = ref.selected_content
            scenes.append(VideoSceneDraft(
                scene_id=f"scene-{ref.rlo_id}-{i + 1}",
                source_content=(RLOContentRef(
                    rlo_id=ref.rlo_id,
                    rlo_version=ref.rlo_version,
                    objective_ids=sel.objective_ids,
                    concept_ids=sel.concept_ids,
                    component_ids=sel.component_ids,
                    assessment_item_ids=sel.assessment_item_ids,
                ),),
                learning_objective=f"Learn content from {ref.rlo_id}",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="avatar_led_explanation",
                teaching_pattern="direct_instruction",
                content_direction=f"Reference placeholder for {ref.rlo_id}.",
                presentation_direction="Avatar presents directly to camera on an approved solid-color background.",
                target_duration_seconds=120,
            ))

        fake_draft = VideoModalityDraft(
            draft_id=f"video-reference-{blueprint.blueprint_id}",
            title=f"{blueprint.title} — Reference Video Modality Plan",
            narrative="Reference draft; use --mode real for a model-generated plan.",
            scenes=tuple(scenes),
        )
        client = FakePlanningClient(draft=fake_draft, prompt_version="video_modality_v1")
        resolver = ModalityContextResolver(FileRLORepository(rlo_root))
        planner = VideoModalityPlanner(client=client, model="reference")

    service = ModalityPlanningService(
        resolver=resolver,
        planner=planner,
        tool_catalog=catalog,
        support_rules=VIDEO_SUPPORT_RULES,
        affordance_catalog=build_video_affordance_catalog(),
        trace_root=output_dir / "traces",
    )

    result = await service.create_modality_plan(
        blueprint,
        Modality.VIDEO,
        planning_request_id=request_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "video-modality-plan.json").write_text(
        result.modality_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "coverage-report.json").write_text(
        result.coverage.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / _PLANNING_TRACE).write_text(
        result.trace.model_dump_json(indent=2), encoding="utf-8"
    )

    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "video_modality_plan": str(output_dir / "video-modality-plan.json"),
            "coverage_report": str(output_dir / "coverage-report.json"),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
            "context_hash": result.trace.context_hash,
        },
        indent=2,
    )


# ── plan-elearning-modality ───────────────────────────────────────────────────


async def _plan_elearning_modality(
    blueprint_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    mode: str,
) -> str:
    import json as _json

    from learning_pipeline.contracts import CourseBlueprint
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.planners.modality.context import ModalityContextResolver
    from learning_pipeline.planners.modality.elearning.planner import ElearningModalityPlanner
    from learning_pipeline.services.modality_planning import ModalityPlanningService
    from learning_pipeline.affordances.elearning import (
        ELEARNING_SUPPORT_RULES,
        build_elearning_affordance_catalog,
    )

    try:
        blueprint = CourseBlueprint.model_validate_json(
            blueprint_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc

    catalog = build_tool_catalog()

    if mode == "real":
        from learning_pipeline.config import load_planner_settings
        from learning_pipeline.planners.client import LiteLLMPlanningClient
        from learning_pipeline.repository import FileRLORepository

        ps = load_planner_settings(model=ModelAlias.ELEARNING_MODALITY_PLANNING)
        client = LiteLLMPlanningClient(base_url=ps.base_url, api_key=ps.api_key)
        resolver = ModalityContextResolver(FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)))
        planner = ElearningModalityPlanner(client=client, model=ps.model)
    else:
        from learning_pipeline.contracts.modality import RLOContentRef
        from learning_pipeline.contracts.planning import (
            ElearningModalityDraft,
            ElearningSceneDraft,
            NarrativeRole,
        )
        from learning_pipeline.planners.client import FakePlanningClient
        from learning_pipeline.repository import FileRLORepository

        if rlo_root is None:
            raise SystemExit(_RLO_REQUIRED)

        sorted_refs = sorted(blueprint.ordered_rlo_refs, key=lambda r: r.order)
        scenes = []
        for i, ref in enumerate(sorted_refs):
            sel = ref.selected_content
            scenes.append(ElearningSceneDraft(
                scene_id=f"scene-{ref.rlo_id}-{i + 1}",
                source_content=(RLOContentRef(
                    rlo_id=ref.rlo_id,
                    rlo_version=ref.rlo_version,
                    objective_ids=sel.objective_ids,
                    concept_ids=sel.concept_ids,
                    component_ids=sel.component_ids,
                    assessment_item_ids=sel.assessment_item_ids,
                ),),
                learning_objective=f"Learn content from {ref.rlo_id}",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction",
                content_direction=f"Reference placeholder for {ref.rlo_id}.",
                target_duration_seconds=180,
            ))

        fake_draft = ElearningModalityDraft(
            draft_id=f"elearning-reference-{blueprint.blueprint_id}",
            title=f"{blueprint.title} — Reference E-learning Modality Plan",
            narrative="Reference draft; use --mode real for a model-generated modality plan.",
            scenes=tuple(scenes),
        )
        from learning_pipeline.planners.modality.elearning.planner import PROMPT_VERSION
        client = FakePlanningClient(draft=fake_draft, prompt_version=PROMPT_VERSION)
        resolver = ModalityContextResolver(FileRLORepository(rlo_root))
        planner = ElearningModalityPlanner(client=client, model="reference")

    service = ModalityPlanningService(
        resolver=resolver,
        planner=planner,
        tool_catalog=catalog,
        support_rules=ELEARNING_SUPPORT_RULES,
        affordance_catalog=build_elearning_affordance_catalog(),
        trace_root=output_dir / "traces",
    )

    result = await service.create_modality_plan(
        blueprint,
        Modality.ELEARNING,
        planning_request_id=request_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "elearning-modality-plan.json").write_text(
        result.modality_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "coverage-report.json").write_text(
        result.coverage.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / _PLANNING_TRACE).write_text(
        result.trace.model_dump_json(indent=2), encoding="utf-8"
    )

    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "elearning_modality_plan": str(output_dir / "elearning-modality-plan.json"),
            "coverage_report": str(output_dir / "coverage-report.json"),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
            "context_hash": result.trace.context_hash,
        },
        indent=2,
    )


# ── plan-elearning-workflow ────────────────────────────────────────────────────


async def _plan_elearning_workflow(
    blueprint_path: Path,
    modality_plan_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    mode: str,
) -> str:
    import json as _json

    from learning_pipeline.contracts import CourseBlueprint, ModalityPlan
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.planners.context import PlanningContextResolver
    from learning_pipeline.planners.workflow.elearning.planner import ElearningWorkflowPlanner
    from learning_pipeline.services.workflow_planning import WorkflowPlanningService
    from learning_pipeline.production import ProductionCompiler

    try:
        blueprint = CourseBlueprint.model_validate_json(
            blueprint_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc

    try:
        modality_plan = ModalityPlan.model_validate_json(
            modality_plan_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid modality plan: {exc}") from exc

    if modality_plan.modality != Modality.ELEARNING:
        raise SystemExit(
            f"plan-elearning-workflow requires an elearning modality plan; "
            f"got '{modality_plan.modality}'"
        )

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)

    import hashlib
    catalog_hash = hashlib.sha256(
        _json.dumps(
            sorted(m.capability for m in catalog.planner_view(Modality.ELEARNING)),
            sort_keys=True,
        ).encode()
    ).hexdigest()

    if mode == "real":
        from learning_pipeline.config import load_planner_settings
        from learning_pipeline.planners.client import LiteLLMPlanningClient
        from learning_pipeline.repository import FileRLORepository

        ps = load_planner_settings(model=ModelAlias.ELEARNING_WORKFLOW_PLANNING)
        client = LiteLLMPlanningClient(base_url=ps.base_url, api_key=ps.api_key)
        model = ps.model
        resolver = PlanningContextResolver(FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)))
    else:
        from learning_pipeline.contracts.planning import (
            ElearningProductionDraft,
        )
        from learning_pipeline.tools.elearning_bundle.contracts import (
            AuthoredScreenRequirement,
            LearnerAction,
        )
        from learning_pipeline.planners.client import FakePlanningClient
        from learning_pipeline.repository import FileRLORepository

        if rlo_root is None:
            raise SystemExit(_RLO_REQUIRED)

        scene_ids = [s.id for s in modality_plan.scenes]
        _authored_screens = tuple(
            AuthoredScreenRequirement(
                screen_id=f"screen-{i + 1}",
                screen_type="title" if i == 0 else "key_takeaways",
                source_scene_ids=(sid,),
                content_direction=f"Placeholder content for scene {sid}.",
                learner_action=LearnerAction.CONSUME,
            )
            for i, sid in enumerate(scene_ids)
        )
        fake_draft = ElearningProductionDraft(
            draft_id=f"elearning-reference-{blueprint.blueprint_id}",
            source_modality_plan_id=modality_plan.plan_id,
            narrative="Reference draft generated by plan-elearning-workflow in reference mode.",
            authored_screens=_authored_screens,
            video_slots=(),
            screen_order=tuple(s.screen_id for s in _authored_screens),
            avatar_directives=(),
            manim_directives=(),
            course_authoring_direction=(
                "Reference placeholder; use --mode real for a model-generated plan."
            ),
        )
        from learning_pipeline.planners.workflow.elearning.planner import PROMPT_VERSION
        client = FakePlanningClient(draft=fake_draft, prompt_version=PROMPT_VERSION)
        model = "reference"
        resolver = PlanningContextResolver(FileRLORepository(rlo_root))

    from learning_pipeline.runtime.artifact_store import FileArtifactStore
    artifact_root = output_dir.parent / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_store = FileArtifactStore(artifact_root)

    planner = ElearningWorkflowPlanner(
        client=client, catalog=catalog, model=model, artifact_store=artifact_store
    )
    service = WorkflowPlanningService(
        resolver=resolver,
        planner=planner,
        compiler=compiler,
        catalog_hash=catalog_hash,
        trace_root=output_dir / "traces",
    )

    result = await service.plan(
        blueprint,
        modality_plan,
        planning_request_id=request_id,
        workflow_id=request_id,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "elearning-production-plan.json").write_text(
        result.production_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "elearning-build-plan.json").write_text(
        result.build_plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / _PLANNING_TRACE).write_text(
        result.trace.model_dump_json(indent=2), encoding="utf-8"
    )

    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "elearning_production_plan": str(output_dir / "elearning-production-plan.json"),
            "elearning_build_plan": str(output_dir / "elearning-build-plan.json"),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
        },
        indent=2,
    )


# ── select-format ─────────────────────────────────────────────────────────────


async def _select_format(
    blueprint_path: Path,
    selection_mode: str,
    modality: str | None,
    output_path: Path,
    allow_fallback: bool,
    request_id: str | None,
) -> str:
    import json as _json

    from learning_pipeline.contracts import CourseBlueprint
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.contracts.format_selection import (
        DeliveryConstraints,
        FormatSelectionMode,
        FormatSelectionRequest,
    )
    from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
    from learning_pipeline.format_selector.registry import build_default_registry
    from learning_pipeline.format_selector.service import FormatSelectionService
    from learning_pipeline.config import build_tool_catalog

    try:
        blueprint = CourseBlueprint.model_validate_json(
            blueprint_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc

    try:
        sel_mode = FormatSelectionMode(selection_mode.lower())
    except ValueError:
        raise SystemExit(f"unsupported selection mode: {selection_mode!r}; use 'explicit' or 'auto'")

    requested = None
    if modality is not None:
        try:
            requested = Modality(modality.lower())
        except ValueError:
            raise SystemExit(f"unsupported modality: {modality!r}")

    req_id = request_id or __import__("uuid").uuid4().__str__()
    request = FormatSelectionRequest(
        request_id=req_id,
        blueprint_id=blueprint.blueprint_id,
        mode=sel_mode,
        requested_modality=requested,
        allow_fallback=allow_fallback,
    )

    catalog = build_tool_catalog()
    available_caps = frozenset(catalog.capabilities)
    registry = build_default_registry(available_capabilities=available_caps)
    service = FormatSelectionService(registry=registry, profiles=MODALITY_PROFILES)
    result = await service.select_format(blueprint, request)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.decision.model_dump_json(indent=2), encoding="utf-8")

    trace_path = output_path.parent / "selection_trace.json"
    trace_path.write_text(result.trace.model_dump_json(indent=2), encoding="utf-8")

    return _json.dumps(
        {
            "selected_modality": result.decision.selected_modality,
            "basis": result.decision.basis,
            "from_cache": result.from_cache,
            "decision": str(output_path),
            "trace": str(trace_path),
        },
        indent=2,
    )


# ── assemble-course ───────────────────────────────────────────────────────────


async def _assemble_course(
    request_path: Path,
    rlo_directory: Path | None,
    output_dir: Path,
    request_id: str | None,
    mode: str,
) -> str:
    import json as _json

    from learning_pipeline.contracts.curriculum_assembly import CourseAssemblyRequest
    from learning_pipeline.config import build_assembly_service

    try:
        request = CourseAssemblyRequest.model_validate_json(
            request_path.read_text(encoding="utf-8")
        )
        if request_id:
            data = _json.loads(request.model_dump_json())
            data["request_id"] = request_id
            request = CourseAssemblyRequest.model_validate(data)
    except Exception as exc:
        raise SystemExit(f"invalid assembly request: {exc}") from exc

    if mode == "reference" and rlo_directory is None:
        raise SystemExit(_RLO_REQUIRED)

    service = build_assembly_service(
        rlo_root=rlo_directory,
        trace_root=output_dir / "traces",
        mode=mode,
    )

    try:
        result = await service.assemble_course(request)
    except Exception as exc:
        raise SystemExit(f"assembly failed: {exc}") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "assembly-draft.json").write_text(
        result.report.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "course-blueprint.json").write_text(
        result.blueprint.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "assembly-report.json").write_text(
        result.report.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / _PLANNING_TRACE).write_text(
        result.trace.model_dump_json(indent=2), encoding="utf-8"
    )

    included = len(result.blueprint.ordered_rlo_refs)
    total = len(request.candidates)

    return _json.dumps(
        {
            "blueprint_id": result.blueprint.blueprint_id,
            "included_rlo_count": included,
            "omitted_rlo_count": total - included,
            "estimated_duration_minutes": result.blueprint.estimated_duration_minutes,
            "from_cache": result.from_cache,
            "course_blueprint": str(output_dir / "course-blueprint.json"),
            "assembly_report": str(output_dir / "assembly-report.json"),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
        },
        indent=2,
    )


# ── Entry point ────────────────────────────────────────────────────────────────


async def _shared_plan_modality(
    modality_name: str,
    blueprint_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    mode: str,
    format_selection_path: Path | None = None,
) -> str:
    """CLI adapter over the same planning composition used by commissioning."""
    import json as _json
    from learning_pipeline.contracts import CourseBlueprint
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.repository import FileRLORepository
    from learning_pipeline.services.generation_planning import GenerationPlanningService

    if mode == "reference" and rlo_root is None:
        raise SystemExit(_RLO_REQUIRED)
    try:
        blueprint = CourseBlueprint.model_validate_json(blueprint_path.read_text())
    except Exception as exc:
        raise SystemExit(f"invalid blueprint: {exc}") from exc
    modality = Modality(modality_name)
    if format_selection_path is not None:
        from learning_pipeline.contracts.format_selection import FormatSelectionDecision
        try:
            decision = FormatSelectionDecision.model_validate_json(
                format_selection_path.read_text()
            )
        except Exception as exc:
            raise SystemExit(f"invalid format selection: {exc}") from exc
        if decision.blueprint_id != blueprint.blueprint_id or decision.selected_modality != modality:
            raise SystemExit("format selection does not match the supplied blueprint and modality")
    service = GenerationPlanningService(
        FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)),
        trace_root=output_dir / "traces",
        artifact_root=output_dir / "artifacts",
        mode=mode,
    )
    result = await service.plan_modality(
        blueprint,
        modality,
        request_id=request_id or f"planning-{blueprint.blueprint_id}",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_name = {
        Modality.PODCAST: "modality_plan.json",
        Modality.VIDEO: "video-modality-plan.json",
        Modality.ELEARNING: "elearning-modality-plan.json",
    }[modality]
    coverage_name = "coverage_report.json" if modality == Modality.PODCAST else "coverage-report.json"
    (output_dir / plan_name).write_text(result.modality_plan.model_dump_json(indent=2))
    (output_dir / coverage_name).write_text(result.coverage.model_dump_json(indent=2))
    (output_dir / _PLANNING_TRACE).write_text(result.trace.model_dump_json(indent=2))
    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "modality_plan": str(output_dir / plan_name),
            "coverage_report": str(output_dir / coverage_name),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
        },
        indent=2,
    )


async def _shared_plan_workflow(
    modality_name: str,
    blueprint_path: Path,
    modality_plan_path: Path,
    output_dir: Path,
    rlo_root: Path | None,
    request_id: str | None,
    mode: str,
) -> str:
    import json as _json
    from learning_pipeline.contracts import CourseBlueprint, ModalityPlan
    from learning_pipeline.contracts.common import Modality
    from learning_pipeline.repository import FileRLORepository
    from learning_pipeline.services.generation_planning import GenerationPlanningService

    if mode == "reference" and rlo_root is None:
        raise SystemExit(_RLO_REQUIRED)
    try:
        blueprint = CourseBlueprint.model_validate_json(blueprint_path.read_text())
        modality_plan = ModalityPlan.model_validate_json(modality_plan_path.read_text())
    except Exception as exc:
        raise SystemExit(f"invalid planning input: {exc}") from exc
    modality = Modality(modality_name)
    if modality_plan.modality != modality:
        raise SystemExit(
            f"workflow planner requires a {modality.value} modality plan; "
            f"got '{modality_plan.modality}'"
        )
    rid = request_id or f"planning-{blueprint.blueprint_id}"
    service = GenerationPlanningService(
        FileRLORepository(rlo_root or Path(_DEFAULT_RLO_ROOT)),
        trace_root=output_dir / "traces",
        artifact_root=output_dir / "artifacts",
        mode=mode,
    )
    result = await service.plan_workflow(
        blueprint, modality_plan, request_id=rid, workflow_id=rid
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "" if modality == Modality.PODCAST else f"{modality.value}-"
    production_name = f"{prefix}production-plan.json"
    build_name = f"{prefix}build-plan.json"
    (output_dir / production_name).write_text(result.production_plan.model_dump_json(indent=2))
    (output_dir / build_name).write_text(result.build_plan.model_dump_json(indent=2))
    (output_dir / _PLANNING_TRACE).write_text(result.trace.model_dump_json(indent=2))
    return _json.dumps(
        {
            "from_cache": result.from_cache,
            "production_plan": str(output_dir / production_name),
            "build_plan": str(output_dir / build_name),
            "planning_trace": str(output_dir / _PLANNING_TRACE),
        },
        indent=2,
    )


def _mode_arg(parser: argparse.ArgumentParser) -> None:
    """Add --mode to parser. Overrides PIPELINE_MODE env var."""
    parser.add_argument(
        "--mode",
        type=str,
        default=None,
        choices=_MODE_CHOICES,
        help="Pipeline mode: 'reference' (default, no credentials) or 'real' "
             "(calls live LLM/APIs). Overrides PIPELINE_MODE env var.",
    )


def _dispatch(coro, *, workflow_error: bool = False) -> None:
    """Run an async subcommand coroutine, printing the result or exiting on error."""
    try:
        print(asyncio.run(coro))
    except SystemExit:
        raise
    except WorkflowExecutionError as exc:
        if workflow_error:
            print(f"workflow failed: {exc}", file=sys.stderr)
            sys.exit(1)
        raise
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def _dispatch_assemble_course() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli assemble-course",
        description="Assemble a modality-agnostic CourseBlueprint from candidate RLOs.",
    )
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--rlo-directory", type=Path, default=None)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--request-id", type=str, default=None)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_assemble_course(
        args.request, args.rlo_directory, args.output_directory,
        args.request_id, _pipeline_mode(args.mode),
    ))


def _dispatch_select_format() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli select-format",
        description="Select a deliverable modality for a CourseBlueprint.",
    )
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--selection-mode", type=str, required=True,
                        choices=["explicit", "auto"],
                        help="Selection strategy: 'explicit' or 'auto'.")
    parser.add_argument("--modality", type=str, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-fallback", action="store_true")
    parser.add_argument("--request-id", type=str, default=None)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_select_format(
        args.blueprint, args.selection_mode, args.modality,
        args.output, args.allow_fallback, args.request_id,
    ))


def _dispatch_plan_podcast_modality() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli plan-podcast-modality",
        description="Generate a podcast ModalityPlan from a CourseBlueprint.",
    )
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--rlo-directory", type=Path, default=None)
    parser.add_argument("--request-id", type=str, default=None)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_shared_plan_modality(
        "podcast", args.blueprint, args.output_directory, args.rlo_directory,
        args.request_id, _pipeline_mode(args.mode),
    ))


def _dispatch_plan_video_modality() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli plan-video-modality",
        description="Generate a video ModalityPlan from a CourseBlueprint.",
    )
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--format-selection", type=Path, default=None)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--rlo-directory", type=Path, default=None)
    parser.add_argument("--request-id", type=str, default=None)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_shared_plan_modality(
        "video", args.blueprint, args.output_directory, args.rlo_directory,
        args.request_id, _pipeline_mode(args.mode), args.format_selection,
    ))


def _dispatch_plan_podcast_workflow() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli plan-podcast-workflow",
        description="Generate a podcast BuildPlan from a blueprint and modality plan.",
    )
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--modality-plan", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--rlo-directory", type=Path, default=None)
    parser.add_argument("--request-id", type=str, default=None)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_shared_plan_workflow(
        "podcast", args.blueprint, args.modality_plan, args.output_directory,
        args.rlo_directory, args.request_id, _pipeline_mode(args.mode),
    ))


def _dispatch_plan_video_workflow() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli plan-video-workflow",
        description="Generate a video BuildPlan from a blueprint and video modality plan.",
    )
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--modality-plan", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--rlo-directory", type=Path, default=None)
    parser.add_argument("--request-id", type=str, default=None)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_shared_plan_workflow(
        "video", args.blueprint, args.modality_plan, args.output_directory,
        args.rlo_directory, args.request_id, _pipeline_mode(args.mode),
    ))


def _dispatch_plan_elearning_modality() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli plan-elearning-modality",
        description="Generate an e-learning ModalityPlan from a CourseBlueprint.",
    )
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--rlo-directory", type=Path, default=None)
    parser.add_argument("--request-id", type=str, default=None)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_shared_plan_modality(
        "elearning", args.blueprint, args.output_directory, args.rlo_directory,
        args.request_id, _pipeline_mode(args.mode),
    ))


def _dispatch_plan_elearning_workflow() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli plan-elearning-workflow",
        description="Generate an e-learning BuildPlan from a blueprint and e-learning modality plan.",
    )
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--modality-plan", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--rlo-directory", type=Path, default=None)
    parser.add_argument("--request-id", type=str, default=None)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_shared_plan_workflow(
        "elearning", args.blueprint, args.modality_plan, args.output_directory,
        args.rlo_directory, args.request_id, _pipeline_mode(args.mode),
    ))


def _dispatch_run_workflow() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli run-workflow",
        description="Execute a BuildPlan workflow deterministically.",
    )
    parser.add_argument("plan", type=Path, help="Path to build_plan.json")
    parser.add_argument("--run-dir", type=Path, required=True)
    _mode_arg(parser)
    args = parser.parse_args(sys.argv[2:])
    _dispatch(_run(args.plan, args.run_dir, _pipeline_mode(args.mode)), workflow_error=True)


def _dispatch_run_reference_elearning() -> None:
    parser = argparse.ArgumentParser(
        prog="learning_pipeline.cli run-reference-elearning",
        description=(
            "Execute an e-learning BuildPlan with the deterministic reference registry. "
            "No LLM, Manim, or HeyGen calls. Produces a portable ZIP bundle."
        ),
    )
    parser.add_argument("plan", type=Path, help="Path to elearning build_plan.json")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--artifact-root", type=Path, default=None,
        help="Root directory for artifact storage (default: <run-dir>/artifacts).",
    )
    args = parser.parse_args(sys.argv[2:])
    _dispatch(
        _run_reference_elearning(args.plan, args.run_dir, args.artifact_root),
        workflow_error=True,
    )


_DISPATCH = {
    "assemble-course": _dispatch_assemble_course,
    "select-format": _dispatch_select_format,
    "plan-podcast-modality": _dispatch_plan_podcast_modality,
    "plan-video-modality": _dispatch_plan_video_modality,
    "plan-podcast-workflow": _dispatch_plan_podcast_workflow,
    "plan-video-workflow": _dispatch_plan_video_workflow,
    "plan-elearning-modality": _dispatch_plan_elearning_modality,
    "plan-elearning-workflow": _dispatch_plan_elearning_workflow,
    "run-workflow": _dispatch_run_workflow,
    "run-reference-elearning": _dispatch_run_reference_elearning,
}


def main() -> None:
    first = sys.argv[1] if len(sys.argv) > 1 else None
    handler = _DISPATCH.get(first)  # type: ignore[arg-type]
    if handler:
        handler()
    else:
        print(
            f"Unknown subcommand: {first!r}\n\n"
            "Available subcommands:\n"
            + "\n".join(f"  {s}" for s in sorted(_SUBCOMMANDS)),
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
