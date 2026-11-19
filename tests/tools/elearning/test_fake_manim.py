"""Tests for FakeManimVideoExecutor."""
from __future__ import annotations

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.elearning_bundle.executor_fake_manim import (
    FakeManimVideoExecutor,
    _FAKE_MP4_BYTES,
    _FAKE_VTT_BYTES,
)
from learning_pipeline.tools.errors import InvalidToolInputError


def _context(inputs: dict, wf_id: str = "wf-001", task_id: str = "manim-1") -> ExecutionContext:
    return ExecutionContext(workflow_id=wf_id, task_id=task_id, attempt=1, inputs=inputs)


def _valid_inputs() -> dict:
    return {
        "animation_id": "intro-animation",
        "source_scene_ids": ("scene-1",),
        "learning_objective": "Understand the ADKAR framework.",
        "teaching_purpose": "Animated introduction.",
        "visual_direction": "Animated diagram on dark background.",
        "narration_script": "ADKAR stands for five elements.",
        "resolved_context_uri": "fake://ctx/001.json",
        "resolved_context_sha256": "a" * 64,
    }


# ── Input validation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validates_input_contract():
    executor = FakeManimVideoExecutor()
    ctx = _context({"animation_id": ""})
    with pytest.raises(InvalidToolInputError):
        await executor.execute(ctx)


@pytest.mark.asyncio
async def test_validates_empty_source_scene_ids():
    executor = FakeManimVideoExecutor()
    ctx = _context({**_valid_inputs(), "source_scene_ids": ()})
    with pytest.raises(InvalidToolInputError):
        await executor.execute(ctx)


# ── Without store (fake:// URIs) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_store_returns_fake_uri():
    executor = FakeManimVideoExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["video_uri"].startswith("fake://")


@pytest.mark.asyncio
async def test_no_store_video_and_captions_present():
    executor = FakeManimVideoExecutor()
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["video_uri"] is not None
    assert result["captions_uri"] is not None


@pytest.mark.asyncio
async def test_no_store_no_captions_when_disabled():
    executor = FakeManimVideoExecutor(write_captions=False)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["captions_uri"] is None


# ── With store ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_with_store_writes_mp4(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeManimVideoExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)

    uri = result["video_uri"]
    assert uri.startswith("artifact://")
    mp4_bytes = await store.get_bytes(uri)
    assert mp4_bytes == _FAKE_MP4_BYTES


@pytest.mark.asyncio
async def test_with_store_writes_vtt_captions(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeManimVideoExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)

    uri = result["captions_uri"]
    assert uri.startswith("artifact://")
    vtt_bytes = await store.get_bytes(uri)
    assert vtt_bytes.startswith(b"WEBVTT")


@pytest.mark.asyncio
async def test_with_store_no_captions_when_disabled(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeManimVideoExecutor(artifact_store=store, write_captions=False)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["captions_uri"] is None
    assert result["captions"] is None


# ── URI consistency ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_uri_matches_video_artifact_uri(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeManimVideoExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["video_uri"] == result["video"]["uri"]


@pytest.mark.asyncio
async def test_captions_uri_matches_captions_artifact_uri(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = FakeManimVideoExecutor(artifact_store=store)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["captions_uri"] == result["captions"]["uri"]


# ── Fake MP4 header ───────────────────────────────────────────────────────────


def test_fake_mp4_has_ftyp_box():
    assert _FAKE_MP4_BYTES[4:8] == b"ftyp"


def test_fake_vtt_is_valid_webvtt():
    assert _FAKE_VTT_BYTES.startswith(b"WEBVTT")
