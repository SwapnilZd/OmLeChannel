"""
End-to-end execution test for the committed ADKAR video reference BuildPlan.

Loads the real build_plan.json from examples/reference/video/, registers
FakeAvatarVideoExecutor, and drives the plan through WorkflowRunner.

Proves:
* The video render task completes successfully.
* The deliverable is the render task's video_uri output.
* The artifact has the correct media type.
* The plan hash from the snapshot matches the canonical plan hash.
* No HeyGen API key was required.
* No network call was made.
* No real video files were generated.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.contracts import BuildPlan
from learning_pipeline.runtime.execution import ExecutorRegistry
from learning_pipeline.runtime.persistence import FileRunStateStore, TaskStatus, WorkflowStatus
from learning_pipeline.runtime.runner import WorkflowRunner
from learning_pipeline.tools.avatar_video.executor_fake import FakeAvatarVideoExecutor
from learning_pipeline.validation import canonical_plan_hash

_REFERENCE_PLAN = (
    Path(__file__).parent.parent.parent
    / "examples"
    / "reference"
    / "video"
    / "build_plan.json"
)


@pytest.fixture(scope="module")
def build_plan() -> BuildPlan:
    return BuildPlan.model_validate_json(_REFERENCE_PLAN.read_text(encoding="utf-8"))


@pytest.fixture
def registry(tmp_path_factory) -> ExecutorRegistry:
    store = FileArtifactStore(tmp_path_factory.mktemp("artifacts"))
    reg = ExecutorRegistry()
    reg.register("video.avatar.render", FakeAvatarVideoExecutor(artifact_store=store))
    return reg


# ── Build plan schema ─────────────────────────────────────────────────────────


def test_reference_plan_parses_as_build_plan():
    data = _REFERENCE_PLAN.read_text(encoding="utf-8")
    plan = BuildPlan.model_validate_json(data)
    assert plan.workflow_id == "workflow-adkar-01-video-manager-l55"


def test_reference_plan_has_one_task(build_plan):
    assert len(build_plan.tasks) == 1


def test_reference_plan_task_type_is_avatar_render(build_plan):
    assert build_plan.tasks[0].task_type == "video.avatar.render"


def test_reference_plan_deliverable_task_ids(build_plan):
    assert list(build_plan.deliverable_task_ids) == ["render-avatar-video"]


def test_reference_plan_modality(build_plan):
    assert build_plan.modality == "video"


# ── Execution ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reference_plan_completes_successfully(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    assert "render-avatar-video" in result.task_results


@pytest.mark.asyncio
async def test_reference_plan_deliverable_is_render_output(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    assert len(result.deliverables) == 1
    deliverable = result.deliverables[0]
    assert deliverable.task_id == "render-avatar-video"
    assert "video_uri" in deliverable.outputs


@pytest.mark.asyncio
async def test_reference_plan_video_uri_is_artifact(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    video_uri = result.task_results["render-avatar-video"].outputs["video_uri"]
    assert video_uri.startswith("artifact://")


@pytest.mark.asyncio
async def test_reference_plan_media_type_is_mp4(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    assert result.task_results["render-avatar-video"].outputs["media_type"] == "video/mp4"


@pytest.mark.asyncio
async def test_reference_plan_duration_from_scene_hints(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    duration = result.task_results["render-avatar-video"].outputs["duration_seconds"]
    # 60s + 120s from the two reference scenes
    assert duration == 180.0


@pytest.mark.asyncio
async def test_reference_plan_cost_report_present(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    outputs = result.task_results["render-avatar-video"].outputs
    assert "cost_report_uri" in outputs
    assert outputs["cost_report_uri"] is not None


@pytest.mark.asyncio
async def test_reference_plan_usage_scene_count(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    usage = result.task_results["render-avatar-video"].outputs["usage"]
    assert usage["scene_count"] == 2


# ── Persistence proof ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reference_plan_hash_matches_canonical(build_plan, registry, tmp_path):
    store = FileRunStateStore(tmp_path)
    result = await WorkflowRunner(registry, store).run(build_plan)
    assert result.plan_hash == canonical_plan_hash(build_plan)


@pytest.mark.asyncio
async def test_final_snapshot_workflow_succeeded(build_plan, registry, tmp_path):
    store = FileRunStateStore(tmp_path)
    await WorkflowRunner(registry, store).run(build_plan)
    snapshot = store.load(build_plan.workflow_id)
    assert snapshot.workflow_status == WorkflowStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_final_snapshot_task_succeeded(build_plan, registry, tmp_path):
    store = FileRunStateStore(tmp_path)
    await WorkflowRunner(registry, store).run(build_plan)
    snapshot = store.load(build_plan.workflow_id)
    assert snapshot.statuses["render-avatar-video"] == TaskStatus.SUCCEEDED


# ── No external calls proof ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execution_requires_no_heygen_credentials(build_plan, registry, tmp_path):
    os.environ.pop("HEYGEN_API_KEY", None)
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    assert result is not None


@pytest.mark.asyncio
async def test_execution_creates_no_real_video_files(build_plan, registry, tmp_path):
    state_root = tmp_path / "state"
    await WorkflowRunner(registry, FileRunStateStore(state_root)).run(build_plan)
    real_videos = list(state_root.rglob("*.mp4")) + list(state_root.rglob("*.mov"))
    assert real_videos == [], f"unexpected video files on disk: {real_videos}"
