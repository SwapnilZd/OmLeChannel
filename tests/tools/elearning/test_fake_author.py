"""Tests for FakeElearningCourseAuthorExecutor."""
from __future__ import annotations

import json

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.elearning_bundle.executor_fake_author import FakeElearningCourseAuthorExecutor
from learning_pipeline.tools.errors import InvalidToolInputError


def _context(inputs: dict, wf_id: str = "wf-001", task_id: str = "author-1") -> ExecutionContext:
    return ExecutionContext(workflow_id=wf_id, task_id=task_id, attempt=1, inputs=inputs)


def _valid_inputs(slot_ids: list[str] | None = None) -> dict:
    slots = slot_ids or ["intro-video"]
    authored_reqs = [
        {
            "kind": "authored_screen",
            "screen_id": "screen-title",
            "screen_type": "title",
            "source_scene_ids": ("scene-01",),
            "content_direction": "Write a title.",
        },
        {
            "kind": "authored_screen",
            "screen_id": "screen-completion",
            "screen_type": "completion",
            "source_scene_ids": ("scene-01",),
            "content_direction": "Write a completion message.",
        },
    ]
    slot_reqs = [
        {
            "kind": "video_slot",
            "screen_id": f"screen-{sid}",
            "slot_id": sid,
            "source_scene_ids": (f"scene-{sid}",),
            "title": f"Video: {sid}",
        }
        for sid in slots
    ]
    return {
        "deliverable_id": "course-001",
        "source_plan_id": "plan-001",
        "resolved_context_uri": "fake://ctx/001.json",
        "resolved_context_sha256": "a" * 64,
        "screen_requirements": authored_reqs + slot_reqs,
        "theme": "deloitte-green",
        "brand_contract": {},
        "accessibility_requirements": [],
        "authoring_direction": "Reference placeholder.",
    }


# ── Input validation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validates_input_contract():
    executor = FakeElearningCourseAuthorExecutor()
    ctx = _context({"deliverable_id": ""})
    with pytest.raises(InvalidToolInputError):
        await executor.execute(ctx)


# ── Without store (fake:// URIs) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_store_returns_fake_uri():
    executor = FakeElearningCourseAuthorExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["course_json_uri"].startswith("fake://")


@pytest.mark.asyncio
async def test_no_store_output_keys_present():
    executor = FakeElearningCourseAuthorExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert "course_json_uri" in result
    assert "assets" in result
    assert "slot_report" in result


# ── With store ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_with_store_writes_artifact(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeElearningCourseAuthorExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)

    uri = result["course_json_uri"]
    assert uri.startswith("artifact://")
    course_bytes = await store.get_bytes(uri)
    course_dict = json.loads(course_bytes)
    assert "screens" in course_dict


@pytest.mark.asyncio
async def test_with_store_includes_image_asset(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeElearningCourseAuthorExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assets = result["assets"]
    assert len(assets) >= 1
    logical_paths = [a["logical_path"] for a in assets]
    assert any("generated-course-image.png" in p for p in logical_paths)


# ── Slot preservation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generates_video_slot_screen_per_slot():
    executor = FakeElearningCourseAuthorExecutor()
    ctx = _context(_valid_inputs(["slot-a", "slot-b"]))
    result = await executor.execute(ctx)
    # Decode course from fake:// URI by reading stored JSON directly
    # We can verify via slot_report
    report = result["slot_report"]
    assert set(report["discovered_slot_ids"]) == {"slot-a", "slot-b"}
    assert report["valid"] is True


@pytest.mark.asyncio
async def test_slot_report_valid_for_all_required_slots():
    executor = FakeElearningCourseAuthorExecutor()
    ctx = _context(_valid_inputs(["main-video", "recap-video"]))
    result = await executor.execute(ctx)
    report = result["slot_report"]
    assert report["valid"] is True
    assert not report["missing_slot_ids"]


# ── Preview HTML ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_html_written_when_enabled(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeElearningCourseAuthorExecutor(artifact_store=store, write_preview_html=True)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["preview_html"] is not None
    preview_uri = result["preview_html"]["uri"]
    html_bytes = await store.get_bytes(preview_uri)
    assert b"<!DOCTYPE html" in html_bytes or b"<html" in html_bytes or b"reveal" in html_bytes.lower()


@pytest.mark.asyncio
async def test_preview_html_not_written_by_default(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeElearningCourseAuthorExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["preview_html"] is None
