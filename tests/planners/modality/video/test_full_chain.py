"""Full video pipeline chain test — Phase 13C.

Exercises the complete path:
  CourseBlueprint
    → ModalityPlanningService (VideoModalityPlanner + FakePlanningClient)
    → ModalityPlan
    → WorkflowPlanningService (VideoWorkflowPlanner + FakePlanningClient)
    → ModalityProductionPlan
    → ProductionCompiler
    → BuildPlan
    → FakeAvatarVideoExecutor
    → Deliverable artifact

No live LLM or HeyGen API is called.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import BuildPlan, CourseBlueprint, Modality, ModalityPlan
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    AvatarVideoSceneDraft,
    VideoBackgroundDraft,
    NarrativeRole,
    VideoModalityDraft,
    VideoProductionDraft,
    VideoSceneDraft,
)
from learning_pipeline.affordances.video import VIDEO_SUPPORT_RULES, build_video_affordance_catalog
from learning_pipeline.config import build_tool_catalog
from learning_pipeline.services.modality_planning import ModalityPlanningService
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.planners.modality.context import ModalityContextResolver
from learning_pipeline.planners.modality.video.planner import VideoModalityPlanner
from learning_pipeline.planners.workflow.video.planner import VideoWorkflowPlanner
from learning_pipeline.services.workflow_planning import WorkflowPlanningService
from learning_pipeline.production import ProductionCompiler
from learning_pipeline.repository import InMemoryRLORepository
from learning_pipeline.contracts.rlo import RLODocument

_REPO_ROOT = Path(__file__).parents[4]
_RLOS = _REPO_ROOT / "examples" / "reference" / "rlos"
_RLO_FILENAME = "rlo-adkar-01-name-and-sequence_v1.1.0.json"
_RLO_ID = "rlo-adkar-01-name-and-sequence"
_RLO_VERSION = "1.1.0"


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(
        (_RLOS / _RLO_FILENAME).read_text(encoding="utf-8")
    )


def _load_blueprint() -> CourseBlueprint:
    bp_path = _REPO_ROOT / "examples" / "reference" / "podcast" / "course_blueprint.json"
    return CourseBlueprint.model_validate_json(bp_path.read_text(encoding="utf-8"))


def _make_modality_draft(rlo: RLODocument) -> VideoModalityDraft:
    # Full ref covering all selected content from the ADKAR podcast blueprint
    full_ref = RLOContentRef(
        rlo_id=rlo.id,
        rlo_version=rlo.version,
        objective_ids=("lo-01",),
        concept_ids=("c-01",),
        component_ids=(
            "comp-hook-01", "comp-rule-01", "comp-example-01",
            "comp-example-02", "comp-nonexample-01", "comp-recall-01",
        ),
        assessment_item_ids=("q-01", "q-02"),
    )
    return VideoModalityDraft(
        draft_id="full-chain-draft",
        title="ADKAR Video",
        narrative="Full-chain test video about ADKAR.",
        scenes=(
            VideoSceneDraft(
                scene_id="hook",
                source_content=(full_ref,),
                learning_objective="Recognise the ADKAR model",
                narrative_role=NarrativeRole.HOOK,
                affordance_id="avatar_led_hook",
                teaching_pattern="problem_statement",
                content_direction="Open with a change scenario.",
                presentation_direction="Avatar on solid background.",
                target_duration_seconds=60,
            ),
            VideoSceneDraft(
                scene_id="explanation",
                source_content=(full_ref,),
                learning_objective="Name the five ADKAR stages",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="avatar_led_explanation",
                teaching_pattern="direct_instruction",
                content_direction="Walk through each ADKAR stage.",
                presentation_direction="Avatar with text overlays.",
                target_duration_seconds=120,
            ),
        ),
    )


def _make_workflow_draft(modality_plan: ModalityPlan) -> VideoProductionDraft:
    return VideoProductionDraft(
        draft_id="full-chain-wf-draft",
        title="ADKAR Video Production",
        narrative_summary="Full chain video production.",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=tuple(
            AvatarVideoSceneDraft(
                scene_id=scene.id,
                source_scene_ids=(scene.id,),
                script=f"Narration for {scene.id}.",
                background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
                estimated_duration_seconds=float(scene.target_duration_seconds or 60),
            )
            for scene in modality_plan.scenes
        ),
        production_rationale="Full chain test",
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def rlo() -> RLODocument:
    return _load_rlo()


@pytest.fixture
def blueprint() -> CourseBlueprint:
    return _load_blueprint()


@pytest.fixture
def modality_prompt(tmp_path: Path) -> Path:
    pp = tmp_path / "video_modality_v1.md"
    pp.write_text("# Modality prompt", encoding="utf-8")
    return pp


@pytest.fixture
def workflow_prompt(tmp_path: Path) -> Path:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# Workflow prompt", encoding="utf-8")
    return pp


# ── Full chain ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_chain_produces_build_plan(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_prompt: Path,
    workflow_prompt: Path,
    tmp_path: Path,
) -> None:
    catalog = build_tool_catalog()
    _AVATAR_CAPS = frozenset({"video.avatar.render"})

    # Step 1 — Modality planning
    modality_draft = _make_modality_draft(rlo)
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="video_modality_v1")
    modality_planner = VideoModalityPlanner(client=modality_client, prompt_path=modality_prompt)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=VIDEO_SUPPORT_RULES,
        affordance_catalog=build_video_affordance_catalog(),
        extra_capabilities=frozenset(),
    )

    modality_result = await modality_service.create_modality_plan(blueprint, Modality.VIDEO)
    modality_plan = modality_result.modality_plan

    assert isinstance(modality_plan, ModalityPlan)
    assert modality_plan.modality == Modality.VIDEO

    # Step 2 — Workflow planning
    wf_draft = _make_workflow_draft(modality_plan)
    wf_client = FakePlanningClient(draft=wf_draft, prompt_version="video_v1")
    wf_planner = VideoWorkflowPlanner(client=wf_client, catalog=catalog, prompt_path=workflow_prompt)
    wf_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    compiler = ProductionCompiler(catalog)
    wf_service = WorkflowPlanningService(resolver=wf_resolver, planner=wf_planner, compiler=compiler)

    wf_result = await wf_service.plan(blueprint, modality_plan)
    build_plan = wf_result.build_plan

    assert isinstance(build_plan, BuildPlan)
    assert build_plan.modality == Modality.VIDEO


@pytest.mark.asyncio
async def test_full_chain_build_plan_has_render_task(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_prompt: Path,
    workflow_prompt: Path,
) -> None:
    catalog = build_tool_catalog()

    modality_draft = _make_modality_draft(rlo)
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="video_modality_v1")
    modality_planner = VideoModalityPlanner(client=modality_client, prompt_path=modality_prompt)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=VIDEO_SUPPORT_RULES,
        affordance_catalog=build_video_affordance_catalog(),
    )
    modality_result = await modality_service.create_modality_plan(blueprint, Modality.VIDEO)
    modality_plan = modality_result.modality_plan

    wf_draft = _make_workflow_draft(modality_plan)
    wf_client = FakePlanningClient(draft=wf_draft, prompt_version="video_v1")
    wf_planner = VideoWorkflowPlanner(client=wf_client, catalog=catalog, prompt_path=workflow_prompt)
    wf_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    compiler = ProductionCompiler(catalog)
    wf_service = WorkflowPlanningService(resolver=wf_resolver, planner=wf_planner, compiler=compiler)

    wf_result = await wf_service.plan(blueprint, modality_plan)
    task_types = {t.task_type for t in wf_result.build_plan.tasks}
    assert "video.avatar.render" in task_types


@pytest.mark.asyncio
async def test_full_chain_executes_with_fake_executor(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_prompt: Path,
    workflow_prompt: Path,
    tmp_path: Path,
) -> None:
    from learning_pipeline.runtime.artifact_store import FileArtifactStore
    from learning_pipeline.runtime.execution import ExecutorRegistry
    from learning_pipeline.runtime.persistence import FileRunStateStore
    from learning_pipeline.runtime.runner import DAGRunner
    from learning_pipeline.tools.avatar_video.executor_fake import FakeAvatarVideoExecutor

    catalog = build_tool_catalog()

    modality_draft = _make_modality_draft(rlo)
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="video_modality_v1")
    modality_planner = VideoModalityPlanner(client=modality_client, prompt_path=modality_prompt)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=VIDEO_SUPPORT_RULES,
        affordance_catalog=build_video_affordance_catalog(),
    )
    modality_result = await modality_service.create_modality_plan(blueprint, Modality.VIDEO)
    modality_plan = modality_result.modality_plan

    wf_draft = _make_workflow_draft(modality_plan)
    wf_client = FakePlanningClient(draft=wf_draft, prompt_version="video_v1")
    wf_planner = VideoWorkflowPlanner(client=wf_client, catalog=catalog, prompt_path=workflow_prompt)
    wf_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    compiler = ProductionCompiler(catalog)
    wf_service = WorkflowPlanningService(resolver=wf_resolver, planner=wf_planner, compiler=compiler)

    wf_result = await wf_service.plan(blueprint, modality_plan)
    build_plan = wf_result.build_plan

    registry = ExecutorRegistry()
    registry.register("video.avatar.render", FakeAvatarVideoExecutor())
    run_result = await DAGRunner(registry, FileRunStateStore(tmp_path / "run")).run(build_plan)

    assert len(run_result.deliverables) == 1
    deliverable_id = build_plan.deliverable_task_ids[0]
    task_result = run_result.task_results[deliverable_id]
    assert task_result.outputs.get("media_type") == "video/mp4"


@pytest.mark.asyncio
async def test_full_chain_one_llm_call_per_planner(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_prompt: Path,
    workflow_prompt: Path,
) -> None:
    catalog = build_tool_catalog()

    modality_draft = _make_modality_draft(rlo)
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="video_modality_v1")
    modality_planner = VideoModalityPlanner(client=modality_client, prompt_path=modality_prompt)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=VIDEO_SUPPORT_RULES,
        affordance_catalog=build_video_affordance_catalog(),
    )

    assert modality_client.call_count == 0
    modality_result = await modality_service.create_modality_plan(blueprint, Modality.VIDEO)
    assert modality_client.call_count == 1

    wf_draft = _make_workflow_draft(modality_result.modality_plan)
    wf_client = FakePlanningClient(draft=wf_draft, prompt_version="video_v1")
    wf_planner = VideoWorkflowPlanner(client=wf_client, catalog=catalog, prompt_path=workflow_prompt)
    wf_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    compiler = ProductionCompiler(catalog)
    wf_service = WorkflowPlanningService(resolver=wf_resolver, planner=wf_planner, compiler=compiler)

    assert wf_client.call_count == 0
    await wf_service.plan(blueprint, modality_result.modality_plan)
    assert wf_client.call_count == 1
    assert modality_client.call_count == 1  # still exactly one modality call


@pytest.mark.asyncio
async def test_full_chain_no_heygen_key_required(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_prompt: Path,
    workflow_prompt: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)

    catalog = build_tool_catalog()
    modality_draft = _make_modality_draft(rlo)
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="video_modality_v1")
    modality_planner = VideoModalityPlanner(client=modality_client, prompt_path=modality_prompt)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=VIDEO_SUPPORT_RULES,
        affordance_catalog=build_video_affordance_catalog(),
    )
    modality_result = await modality_service.create_modality_plan(blueprint, Modality.VIDEO)
    assert modality_result.modality_plan is not None
    assert modality_result.modality_plan.modality == Modality.VIDEO
