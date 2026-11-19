"""
End-to-end video planning + fake execution tests — Phase 13B.

Exercises the full pipeline:
  1. Load reference CourseBlueprint + Video ModalityPlan.
  2. Resolve planning context (via InMemoryRLORepository with loaded RLO).
  3. Plan with fake planning client (VideoProductionDraft).
  4. Build ModalityProductionPlan deterministically.
  5. Compile to BuildPlan.
  6. Execute with FakeAvatarVideoExecutor.
  7. Verify artifact result.

No live LLM or HeyGen API is called.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learning_pipeline.contracts import BuildPlan, CourseBlueprint, Modality, ModalityPlan
from learning_pipeline.contracts.modality import ModalityScene, RLOContentRef
from learning_pipeline.contracts.planning import (
    AvatarVideoSceneDraft,
    VideoBackgroundDraft,
    VideoProductionDraft,
)
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.planners.workflow.video.planner import VideoWorkflowPlanner
from learning_pipeline.services.workflow_planning import WorkflowPlanningService
from learning_pipeline.production import ProductionCompiler

_REPO_ROOT = Path(__file__).parents[4]
_EXAMPLES = _REPO_ROOT / "examples" / "reference"
_RLOS = _EXAMPLES / "rlos"


def _load_blueprint() -> CourseBlueprint:
    bp_path = _EXAMPLES / "podcast" / "course_blueprint.json"
    return CourseBlueprint.model_validate_json(bp_path.read_text(encoding="utf-8"))


def _load_video_modality_plan() -> ModalityPlan:
    """Build a video ModalityPlan that references the real RLO fixture.

    The reference video modality_plan.json uses placeholder RLO IDs that do
    not match the available fixture.  We build a synthetic plan using the real
    RLO ID so the PlanningContextResolver can load it from FileRLORepository.
    """
    _rlo_ref = RLOContentRef(
        rlo_id="rlo-adkar-01-name-and-sequence",
        rlo_version="1.1.0",
        objective_ids=["obj-awareness"],
    )
    return ModalityPlan(
        plan_id="mp-e2e-video",
        modality=Modality.VIDEO,
        narrative="E2E video plan using the real RLO fixture.",
        scenes=(
            ModalityScene(
                id="video-hook",
                source_content=(_rlo_ref,),
                learning_objective="Understand why structured change management matters.",
                teaching_pattern="hook_then_rule",
                preferred_capability="avatar_video",
                content_direction="Open with a relatable change-failure scenario.",
                target_duration_seconds=60,
            ),
            ModalityScene(
                id="video-explanation",
                source_content=(_rlo_ref,),
                learning_objective="Name the five ADKAR elements and their management relevance.",
                teaching_pattern="direct_instruction",
                preferred_capability="avatar_video",
                content_direction="Explain each ADKAR element with a management example.",
                target_duration_seconds=120,
            ),
        ),
    )


def _build_fake_draft(modality_plan: ModalityPlan) -> VideoProductionDraft:
    return VideoProductionDraft(
        draft_id="e2e-video-draft",
        title="E2E Test Video",
        narrative_summary="End-to-end test video.",
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
                script=f"Test narration for {scene.id}.",
                background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
                estimated_duration_seconds=float(scene.target_duration_seconds or 60),
            )
            for scene in modality_plan.scenes
        ),
        production_rationale="E2E test",
    )


@pytest.fixture
def blueprint() -> CourseBlueprint:
    return _load_blueprint()


@pytest.fixture
def video_plan() -> ModalityPlan:
    return _load_video_modality_plan()


@pytest.fixture
def fake_draft(video_plan: ModalityPlan) -> VideoProductionDraft:
    return _build_fake_draft(video_plan)


@pytest.fixture
def prompt_file(tmp_path: Path) -> Path:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# E2E test prompt", encoding="utf-8")
    return pp


# ── Contract validation ───────────────────────────────────────────────────────


def test_video_modality_plan_is_valid(video_plan: ModalityPlan) -> None:
    assert video_plan.modality == Modality.VIDEO
    assert len(video_plan.scenes) >= 1


def test_fake_draft_is_valid(fake_draft: VideoProductionDraft, video_plan: ModalityPlan) -> None:
    from learning_pipeline.planners.workflow.video.validation import validate_video_draft
    validate_video_draft(fake_draft, video_plan)


# ── Planning pipeline ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_planning_produces_build_plan(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
) -> None:
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.repository import FileRLORepository

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(resolver=resolver, planner=planner, compiler=compiler)

    result = await service.plan(blueprint, video_plan)

    assert isinstance(result.build_plan, BuildPlan)
    assert result.build_plan.modality == Modality.VIDEO


@pytest.mark.asyncio
async def test_planning_calls_client_exactly_once(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
) -> None:
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.repository import FileRLORepository

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(resolver=resolver, planner=planner, compiler=compiler)

    assert client.call_count == 0
    await service.plan(blueprint, video_plan)
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_planning_trace_records_video_planner(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
) -> None:
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.repository import FileRLORepository

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(resolver=resolver, planner=planner, compiler=compiler)

    result = await service.plan(blueprint, video_plan)

    assert result.trace.planner_type == "VideoWorkflowPlanner"
    assert result.trace.modality == Modality.VIDEO
    assert result.trace.prompt_version == "video_v1"


@pytest.mark.asyncio
async def test_build_plan_has_render_task(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
) -> None:
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.repository import FileRLORepository

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(resolver=resolver, planner=planner, compiler=compiler)

    result = await service.plan(blueprint, video_plan)
    task_types = {t.task_type for t in result.build_plan.tasks}
    assert "video.avatar.render" in task_types


# ── DAG compilation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compiled_build_plan_validates(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
) -> None:
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.repository import FileRLORepository

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(resolver=resolver, planner=planner, compiler=compiler)

    result = await service.plan(blueprint, video_plan)
    # BuildPlan is a FrozenModel; if it parsed it validated
    rebuilt = BuildPlan.model_validate_json(result.build_plan.model_dump_json())
    assert rebuilt == result.build_plan


# ── Idempotency ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_context_uses_cache(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
    tmp_path: Path,
) -> None:
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.repository import FileRLORepository

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(
        resolver=resolver,
        planner=planner,
        compiler=compiler,
        trace_root=tmp_path / "traces",
    )

    result1 = await service.plan(blueprint, video_plan)
    assert not result1.from_cache
    assert client.call_count == 1

    result2 = await service.plan(blueprint, video_plan)
    assert result2.from_cache
    assert client.call_count == 1  # LLM not called again


# ── Full execution with FakeAvatarVideoExecutor ────────────────────────────────


@pytest.mark.asyncio
async def test_built_plan_executes_with_fake_executor(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
    tmp_path: Path,
) -> None:
    from learning_pipeline.runtime.artifact_store import FileArtifactStore
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.runtime.execution import ExecutorRegistry
    from learning_pipeline.runtime.persistence import FileRunStateStore
    from learning_pipeline.repository import FileRLORepository
    from learning_pipeline.runtime.runner import DAGRunner
    from learning_pipeline.tools.avatar_video.executor_fake import FakeAvatarVideoExecutor

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(resolver=resolver, planner=planner, compiler=compiler)

    plan_result = await service.plan(blueprint, video_plan)
    build_plan = plan_result.build_plan

    registry = ExecutorRegistry()
    registry.register("video.avatar.render", FakeAvatarVideoExecutor())

    run_result = await DAGRunner(registry, FileRunStateStore(tmp_path / "run")).run(build_plan)

    assert len(run_result.deliverables) == 1
    deliverable_id = build_plan.deliverable_task_ids[0]
    task_result = run_result.task_results[deliverable_id]
    video_uri = task_result.outputs["video_uri"]
    assert video_uri.startswith("artifact://") or video_uri.startswith("fake://")
    assert task_result.outputs["media_type"] == "video/mp4"


# ── HEYGEN_API_KEY not required ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_planning_requires_no_heygen_key(
    blueprint: CourseBlueprint,
    video_plan: ModalityPlan,
    fake_draft: VideoProductionDraft,
    prompt_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.repository import FileRLORepository

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    client = FakePlanningClient(draft=fake_draft, prompt_version="video_v1")
    resolver = PlanningContextResolver(FileRLORepository(_RLOS))
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=prompt_file)
    service = WorkflowPlanningService(resolver=resolver, planner=planner, compiler=compiler)

    # Must not raise even without HEYGEN_API_KEY
    result = await service.plan(blueprint, video_plan)
    assert result.build_plan is not None
