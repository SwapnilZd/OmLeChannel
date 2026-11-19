"""Validates the reference e-learning build_plan.json fixture.

Runs the full end-to-end workflow with the deterministic reference registry
and verifies the output without any provider calls.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from learning_pipeline.contracts import BuildPlan
from learning_pipeline.config import build_elearning_reference_registry
from learning_pipeline.runtime.persistence import FileRunStateStore
from learning_pipeline.runtime.runner import DAGRunner

_FIXTURE = Path(__file__).parent.parent.parent.parent / "examples/reference/elearning/build_plan.json"


@pytest.fixture()
def build_plan() -> BuildPlan:
    text = _FIXTURE.read_text(encoding="utf-8")
    return BuildPlan.model_validate_json(text)


def test_reference_fixture_is_valid_build_plan(build_plan):
    assert build_plan.workflow_id == "workflow-elearning-ref-01"
    assert build_plan.modality == "elearning"
    assert len(build_plan.tasks) == 3


def test_reference_fixture_task_types(build_plan):
    task_types = {t.task_type for t in build_plan.tasks}
    assert "elearning.course.author" in task_types
    assert "video.manim.render" in task_types
    assert "elearning.bundle.assemble" in task_types


def test_reference_fixture_dag_dependencies(build_plan):
    by_id = {t.id: t for t in build_plan.tasks}
    assemble = by_id["assemble-bundle"]
    assert "author-course" in assemble.depends_on
    assert "render-intro-animation" in assemble.depends_on


@pytest.mark.asyncio
async def test_reference_fixture_runs_end_to_end(tmp_path):
    plan = BuildPlan.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    registry = build_elearning_reference_registry(artifact_root)
    store = FileRunStateStore(run_dir)
    result = await DAGRunner(registry, store).run(plan)

    assert result.workflow_id == plan.workflow_id
    # All three tasks must have produced outputs
    assert set(result.task_results.keys()) == {
        "author-course", "render-intro-animation", "assemble-bundle"
    }
    for task_result in result.task_results.values():
        assert task_result.outputs, f"Task {task_result.task_id!r} produced no outputs"


@pytest.mark.asyncio
async def test_reference_fixture_produces_zip_bundle(tmp_path):
    plan = BuildPlan.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    registry = build_elearning_reference_registry(artifact_root)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(plan)

    assemble_result = result.task_results["assemble-bundle"]
    outputs = assemble_result.outputs

    assert "bundle_zip" in outputs
    assert outputs["video_count"] == 1
    assert outputs["unresolved_slot_count"] == 0
    assert outputs["screen_count"] >= 3
