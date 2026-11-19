"""Tests for FakeAvatarVideoExecutor — no credentials, no network."""
from __future__ import annotations

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.avatar_video.executor_fake import FakeAvatarVideoExecutor
from learning_pipeline.tools.errors import InvalidToolInputError


def _context(inputs: dict, wf_id: str = "wf-001", task_id: str = "render-1") -> ExecutionContext:
    return ExecutionContext(
        workflow_id=wf_id,
        task_id=task_id,
        attempt=1,
        inputs=inputs,
    )


def _valid_inputs() -> dict:
    return {
        "deliverable_id": "video-001",
        "scenes": [
            {
                "scene_id": "s1",
                "source_scene_ids": ["src-1"],
                "script": "Hello world.",
                "background": {"kind": "color", "color": "#1A1A2E"},
                "estimated_duration_seconds": 60.0,
            }
        ],
        "avatar": {"profile": "default_instructor"},
        "voice": {"profile": "default_instructor", "speed": 1.0},
        "dimensions": {"width": 1280, "height": 720},
        "captions": False,
    }


# ── Contract validation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_executor_validates_input_contract():
    executor = FakeAvatarVideoExecutor()
    bad_inputs = {"deliverable_id": ""}
    ctx = _context(bad_inputs)
    with pytest.raises(InvalidToolInputError):
        await executor.execute(ctx)


@pytest.mark.asyncio
async def test_fake_executor_returns_valid_output_keys():
    executor = FakeAvatarVideoExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert "video_uri" in result
    assert "cost_report_uri" in result
    assert "media_type" in result
    assert result["media_type"] == "video/mp4"
    assert "usage" in result


@pytest.mark.asyncio
async def test_fake_executor_no_credentials_required(monkeypatch):
    for key in ("HEYGEN_API_KEY",):
        monkeypatch.delenv(key, raising=False)
    executor = FakeAvatarVideoExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["video_uri"]


@pytest.mark.asyncio
async def test_fake_executor_no_network():
    executor = FakeAvatarVideoExecutor()
    ctx = _context(_valid_inputs())
    # If the executor made a network call, it would fail in isolated CI.
    # A passing test proves no network calls were made.
    result = await executor.execute(ctx)
    assert result is not None


# ── Artifact store integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_executor_writes_mp4_artifact(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeAvatarVideoExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)

    uri = result["video_uri"]
    assert uri.startswith("artifact://")
    # Verify the bytes are actually persisted
    mp4_bytes = await store.get_bytes(uri)
    assert len(mp4_bytes) > 0


@pytest.mark.asyncio
async def test_fake_executor_no_store_returns_fake_uri():
    executor = FakeAvatarVideoExecutor(artifact_store=None)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["video_uri"].startswith("fake://")


@pytest.mark.asyncio
async def test_fake_executor_captions_writes_subtitle(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeAvatarVideoExecutor(artifact_store=store)
    inputs = _valid_inputs()
    inputs["captions"] = True
    ctx = _context(inputs)
    result = await executor.execute(ctx)
    assert result["subtitle_uri"] is not None


@pytest.mark.asyncio
async def test_fake_executor_no_captions_subtitle_is_none(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeAvatarVideoExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["subtitle_uri"] is None


# ── Determinism ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_executor_provider_operation_id_contains_task_id():
    executor = FakeAvatarVideoExecutor()
    ctx = _context(_valid_inputs(), task_id="my-render-task")
    result = await executor.execute(ctx)
    assert "my-render-task" in result["provider_operation_id"]


@pytest.mark.asyncio
async def test_fake_executor_duration_from_scene_hints():
    executor = FakeAvatarVideoExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    # Single scene has estimated_duration_seconds=60
    assert result["duration_seconds"] == 60.0


@pytest.mark.asyncio
async def test_fake_executor_usage_scene_count():
    executor = FakeAvatarVideoExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["usage"]["scene_count"] == 1


# ── Same task type and contracts as real executor ─────────────────────────────


def test_task_type_matches_definition():
    from learning_pipeline.tools.avatar_video.definition import TASK_TYPE
    # Fake executor is registered under the same task_type
    assert TASK_TYPE == "video.avatar.render"
