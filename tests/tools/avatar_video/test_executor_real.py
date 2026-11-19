"""Tests for RealAvatarVideoExecutor — mocked HeyGen client, no real API calls."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from learning_pipeline.runtime.artifact_store import ArtifactWriteError, FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.providers.heygen.asset_cache import ProviderAssetCache
from learning_pipeline.providers.heygen.client import AsyncHeyGenClient
from learning_pipeline.providers.heygen.errors import (
    HeyGenOperationFailedError,
    HeyGenOperationTimeoutError,
    HeyGenTransientError,
)
from learning_pipeline.providers.heygen.mapper import HeyGenSceneMapper
from learning_pipeline.providers.heygen.models import (
    HeyGenCreateVideoResponse,
    HeyGenUploadedAsset,
    HeyGenVideoStatus,
    ProviderVideoStatus,
)
from learning_pipeline.providers.heygen.operation_store import FileExternalOperationStore
from learning_pipeline.tools.avatar_video.executor_real import RealAvatarVideoExecutor
from learning_pipeline.tools.avatar_video.pricing import DEFAULT_PRICING
from learning_pipeline.tools.avatar_video.profiles import build_fake_profile_registry
from learning_pipeline.tools.errors import InvalidToolInputError
from learning_pipeline.tools._fake_media import fake_mp4_bytes

_FAKE_MP4 = fake_mp4_bytes()
_FAKE_SRT = b"1\n00:00:00,000 --> 00:00:05,000\n[test subtitle]\n"


def _context(inputs: dict, wf_id: str = "wf-001", task_id: str = "render-1") -> ExecutionContext:
    return ExecutionContext(workflow_id=wf_id, task_id=task_id, attempt=1, inputs=inputs)


def _valid_inputs(captions: bool = False) -> dict:
    return {
        "deliverable_id": "video-001",
        "scenes": [
            {
                "scene_id": "s1",
                "source_scene_ids": ["src-1"],
                "script": "Hello world.",
                "background": {"kind": "color", "color": "#1A1A2E"},
                "estimated_duration_seconds": 30.0,
            }
        ],
        "avatar": {"profile": "default_instructor"},
        "voice": {"profile": "default_instructor", "speed": 1.0},
        "dimensions": {"width": 1280, "height": 720},
        "captions": captions,
    }


def _mock_client(
    video_id: str = "vid-abc",
    status_sequence: list | None = None,
    video_url: str = "https://cdn.heygen.com/test.mp4",
    duration: float = 42.0,
    subtitle_url: str | None = None,
) -> MagicMock:
    """Build a mock HeyGenClientProtocol with pre-programmed responses."""
    client = MagicMock()
    client.create_video = AsyncMock(
        return_value=HeyGenCreateVideoResponse(video_id=video_id)
    )
    client.upload_asset = AsyncMock(
        return_value=HeyGenUploadedAsset(asset_id="asset-uploaded")
    )
    client.download_bytes = AsyncMock(return_value=_FAKE_MP4)

    if status_sequence is None:
        status_sequence = [
            HeyGenVideoStatus(
                video_id=video_id,
                status=ProviderVideoStatus.COMPLETED,
                video_url=video_url,
                duration=duration,
                subtitle_url=subtitle_url,
            )
        ]
    import itertools
    status_iter = itertools.cycle(status_sequence)
    client.get_video_status = AsyncMock(side_effect=lambda _: next(status_iter))
    return client


def _build_executor(
    tmp_path,
    client,
    sleep_fn=None,
    artifact_store=None,
) -> RealAvatarVideoExecutor:
    store = artifact_store or FileArtifactStore(tmp_path / "artifacts")
    op_store = FileExternalOperationStore(tmp_path / "ops")
    asset_cache = ProviderAssetCache(tmp_path / "cache")
    return RealAvatarVideoExecutor(
        client=client,
        artifact_store=store,
        profile_registry=build_fake_profile_registry(),
        operation_store=op_store,
        asset_cache=asset_cache,
        scene_mapper=HeyGenSceneMapper(),
        pricing=DEFAULT_PRICING,
        poll_interval=0.0,
        max_poll_wait=60.0,
        sleep_fn=sleep_fn or (lambda _: asyncio.sleep(0)),
    )


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_executor_complete_flow(tmp_path):
    client = _mock_client()
    executor = _build_executor(tmp_path, client)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)

    assert result["deliverable_id"] == "video-001"
    assert result["provider_operation_id"] == "vid-abc"
    assert result["video_uri"].startswith("artifact://")
    assert result["media_type"] == "video/mp4"
    assert result["duration_seconds"] == 42.0


@pytest.mark.asyncio
async def test_real_executor_mp4_persisted_to_store(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    client = _mock_client()
    op_store = FileExternalOperationStore(tmp_path / "ops")
    asset_cache = ProviderAssetCache(tmp_path / "cache")
    executor = RealAvatarVideoExecutor(
        client=client,
        artifact_store=store,
        profile_registry=build_fake_profile_registry(),
        operation_store=op_store,
        asset_cache=asset_cache,
        scene_mapper=HeyGenSceneMapper(),
        pricing=DEFAULT_PRICING,
        poll_interval=0.0,
        max_poll_wait=60.0,
        sleep_fn=lambda _: asyncio.sleep(0),
    )
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)

    mp4_bytes = await store.get_bytes(result["video_uri"])
    assert mp4_bytes == _FAKE_MP4


@pytest.mark.asyncio
async def test_real_executor_cost_report_persisted(tmp_path):
    import json as _json
    store = FileArtifactStore(tmp_path / "artifacts")
    client = _mock_client()
    executor = _build_executor(tmp_path, client)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)

    cost_bytes = await store.get_bytes(result["cost_report_uri"])
    cost_data = _json.loads(cost_bytes)
    assert cost_data["video_id"] == "vid-abc"
    assert "estimated_cost_usd" in cost_data


@pytest.mark.asyncio
async def test_real_executor_subtitle_when_captions_enabled(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    client = _mock_client(subtitle_url="https://cdn.heygen.com/test.srt")
    client.download_bytes = AsyncMock(side_effect=[_FAKE_MP4, _FAKE_SRT])
    executor = _build_executor(tmp_path, client, artifact_store=store)
    ctx = _context(_valid_inputs(captions=True))
    result = await executor.execute(ctx)
    assert result["subtitle_uri"] is not None
    assert result["subtitle_media_type"] == "text/srt"
    assert await store.get_bytes(result["subtitle_uri"]) == _FAKE_SRT


@pytest.mark.asyncio
async def test_real_executor_required_subtitle_missing_fails(tmp_path):
    client = _mock_client(subtitle_url=None)
    executor = _build_executor(tmp_path, client)
    with pytest.raises(HeyGenTransientError, match="no caption_url"):
        await executor.execute(_context(_valid_inputs(captions=True)))


@pytest.mark.asyncio
async def test_real_executor_invalid_subtitle_fails(tmp_path):
    client = _mock_client(subtitle_url="https://cdn.heygen.com/test.srt")
    client.download_bytes = AsyncMock(side_effect=[_FAKE_MP4, b"not timed captions"])
    executor = _build_executor(tmp_path, client)
    with pytest.raises(HeyGenTransientError, match="valid SRT"):
        await executor.execute(_context(_valid_inputs(captions=True)))


@pytest.mark.asyncio
async def test_real_executor_subtitle_artifact_write_failure_fails(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    original_put = store.put_bytes

    async def fail_subtitle_write(*, namespace, name, data, media_type):
        if name.endswith(".srt"):
            raise ArtifactWriteError("simulated subtitle write failure")
        return await original_put(
            namespace=namespace,
            name=name,
            data=data,
            media_type=media_type,
        )

    store.put_bytes = fail_subtitle_write
    client = _mock_client(subtitle_url="https://cdn.heygen.com/test.srt")
    client.download_bytes = AsyncMock(side_effect=[_FAKE_MP4, _FAKE_SRT])
    executor = _build_executor(tmp_path, client, artifact_store=store)
    with pytest.raises(ArtifactWriteError, match="Failed to persist subtitle"):
        await executor.execute(_context(_valid_inputs(captions=True)))


@pytest.mark.asyncio
async def test_real_executor_no_subtitle_when_captions_false(tmp_path):
    client = _mock_client()
    executor = _build_executor(tmp_path, client)
    ctx = _context(_valid_inputs(captions=False))
    result = await executor.execute(ctx)
    assert result["subtitle_uri"] is None


@pytest.mark.asyncio
async def test_real_executor_rejects_unexpected_video_dimensions(tmp_path):
    client = _mock_client()
    client.download_bytes = AsyncMock(return_value=fake_mp4_bytes(1920, 1080))
    executor = _build_executor(tmp_path, client)
    with pytest.raises(HeyGenTransientError, match="1920x1080.*1280x720"):
        await executor.execute(_context(_valid_inputs()))


# ── Polling ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_executor_polls_multiple_times(tmp_path):
    video_id = "vid-poll"
    statuses = [
        HeyGenVideoStatus(video_id=video_id, status=ProviderVideoStatus.PENDING),
        HeyGenVideoStatus(video_id=video_id, status=ProviderVideoStatus.PROCESSING),
        HeyGenVideoStatus(
            video_id=video_id,
            status=ProviderVideoStatus.COMPLETED,
            video_url="https://cdn.heygen.com/test.mp4",
            duration=10.0,
        ),
    ]
    client = _mock_client(video_id=video_id, status_sequence=statuses)
    sleep_calls = []

    async def tracking_sleep(s):
        sleep_calls.append(s)

    executor = _build_executor(tmp_path, client, sleep_fn=tracking_sleep)
    ctx = _context(_valid_inputs())
    result = await executor.execute(ctx)
    assert result["provider_operation_id"] == video_id
    # Two sleeps: after pending and after processing
    assert len(sleep_calls) == 2


@pytest.mark.asyncio
async def test_real_executor_polling_does_not_block_event_loop(tmp_path):
    """Verify sleep_fn is called, not time.sleep."""
    blocked = []
    original_sleep = asyncio.sleep

    async def mock_sleep(interval):
        blocked.append(interval)
        await original_sleep(0)

    video_id = "vid-sleep-test"
    client = _mock_client(
        video_id=video_id,
        status_sequence=[
            HeyGenVideoStatus(video_id=video_id, status=ProviderVideoStatus.PROCESSING),
            HeyGenVideoStatus(
                video_id=video_id,
                status=ProviderVideoStatus.COMPLETED,
                video_url="https://cdn.heygen.com/test.mp4",
                duration=5.0,
            ),
        ],
    )
    executor = _build_executor(tmp_path, client, sleep_fn=mock_sleep)
    await executor.execute(_context(_valid_inputs()))
    assert len(blocked) >= 1


@pytest.mark.asyncio
async def test_real_executor_timeout_raises_with_provider_id(tmp_path):
    video_id = "vid-timeout"
    client = _mock_client(
        video_id=video_id,
        status_sequence=[
            HeyGenVideoStatus(video_id=video_id, status=ProviderVideoStatus.PROCESSING),
        ] * 100,  # always processing
    )
    executor = RealAvatarVideoExecutor(
        client=client,
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        profile_registry=build_fake_profile_registry(),
        operation_store=FileExternalOperationStore(tmp_path / "ops"),
        asset_cache=ProviderAssetCache(tmp_path / "cache"),
        scene_mapper=HeyGenSceneMapper(),
        pricing=DEFAULT_PRICING,
        poll_interval=1.0,
        max_poll_wait=2.0,  # expire quickly
        sleep_fn=lambda _: asyncio.sleep(0),
    )
    with pytest.raises(HeyGenOperationTimeoutError) as exc_info:
        await executor.execute(_context(_valid_inputs()))
    assert exc_info.value.provider_video_id == video_id


@pytest.mark.asyncio
async def test_real_executor_provider_failure_raises(tmp_path):
    video_id = "vid-fail"
    client = _mock_client(
        video_id=video_id,
        status_sequence=[
            HeyGenVideoStatus(
                video_id=video_id,
                status=ProviderVideoStatus.FAILED,
                error="render_error",
            )
        ],
    )
    executor = _build_executor(tmp_path, client)
    with pytest.raises(HeyGenOperationFailedError, match="render_error"):
        await executor.execute(_context(_valid_inputs()))


# ── Idempotency / retry safety ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_executor_does_not_resubmit_on_retry(tmp_path):
    client = _mock_client()
    executor = _build_executor(tmp_path, client)
    ctx = _context(_valid_inputs())

    # First execution
    await executor.execute(ctx)
    first_call_count = client.create_video.call_count

    # Second execution (same context = retry) — create_video must NOT be called again
    await executor.execute(ctx)
    assert client.create_video.call_count == first_call_count


@pytest.mark.asyncio
async def test_real_executor_input_hash_mismatch_raises(tmp_path):
    from learning_pipeline.providers.heygen.operation_store import make_checkpoint
    store = FileExternalOperationStore(tmp_path / "ops")
    # Manually save a checkpoint with a different input hash
    cp = make_checkpoint(
        workflow_id="wf-001",
        task_id="render-1",
        operation_id="vid-old",
        input_hash="wrong-hash",
        status="pending",
    )
    await store.save(cp)

    client = _mock_client()
    executor = RealAvatarVideoExecutor(
        client=client,
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        profile_registry=build_fake_profile_registry(),
        operation_store=store,
        asset_cache=ProviderAssetCache(tmp_path / "cache"),
        scene_mapper=HeyGenSceneMapper(),
        pricing=DEFAULT_PRICING,
        poll_interval=0.0,
        max_poll_wait=60.0,
        sleep_fn=lambda _: asyncio.sleep(0),
    )
    with pytest.raises(InvalidToolInputError, match="Input hash mismatch"):
        await executor.execute(_context(_valid_inputs()))


# ── Duration handling ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_executor_uses_provider_duration_not_generation_latency(tmp_path):
    client = _mock_client(duration=55.5)
    executor = _build_executor(tmp_path, client)
    result = await executor.execute(_context(_valid_inputs()))
    assert result["duration_seconds"] == 55.5


@pytest.mark.asyncio
async def test_real_executor_none_duration_when_provider_reports_none(tmp_path):
    video_id = "vid-no-dur"
    client = _mock_client(
        video_id=video_id,
        status_sequence=[
            HeyGenVideoStatus(
                video_id=video_id,
                status=ProviderVideoStatus.COMPLETED,
                video_url="https://cdn.heygen.com/test.mp4",
                duration=None,
            )
        ],
    )
    executor = _build_executor(tmp_path, client)
    result = await executor.execute(_context(_valid_inputs()))
    assert result["duration_seconds"] is None


# ── Input validation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_executor_invalid_input_raises(tmp_path):
    client = _mock_client()
    executor = _build_executor(tmp_path, client)
    with pytest.raises(InvalidToolInputError):
        await executor.execute(_context({"deliverable_id": ""}))
