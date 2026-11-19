"""
Tests for RealAudioAssemblyExecutor.

Uses FileArtifactStore in a temporary directory.
Speech segment WAVs are generated in memory — no TTS provider is called.
"""
from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from typing import Any

import pytest

from learning_pipeline.runtime.artifact_store import ArtifactNotFoundError, FileArtifactStore
from learning_pipeline.tools.audio_utils import wav_duration_seconds
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.audio_assembly.contracts import (
    AudioAssemblyOutput,
)
from learning_pipeline.tools.audio_assembly.executor import (
    AudioAssemblyError,
    IncompatibleSegmentError,
    RealAudioAssemblyExecutor,
)
from learning_pipeline.tools.errors import InvalidToolInputError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_wav(
    *,
    duration_seconds: float = 0.5,
    sample_rate: int = 24_000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    buf = io.BytesIO()
    n_frames = int(sample_rate * duration_seconds)
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * n_frames * channels * sample_width)
    return buf.getvalue()


_ZERO_USAGE = {
    "input_characters": 0,
    "input_tokens_estimate": 0.0,
    "audio_duration_seconds": 0.0,
    "input_cost_usd": 0.0,
    "output_cost_usd": 0.0,
    "total_cost_usd": 0.0,
}


async def _store_segment(store: FileArtifactStore, uri_name: str, wav: bytes) -> str:
    """Store a WAV and return its artifact URI."""
    ref = await store.put_bytes("speech/wf-test", uri_name, wav, "audio/wav")
    return ref.uri


def _make_executor(tmp_path: Path) -> tuple[RealAudioAssemblyExecutor, FileArtifactStore]:
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = RealAudioAssemblyExecutor(artifact_store=store)
    return executor, store


def _ctx(inputs: dict[str, Any]) -> ExecutionContext:
    return ExecutionContext(
        workflow_id="wf-test",
        task_id="assemble-podcast",
        attempt=1,
        inputs=inputs,
    )


# ── Core success path ─────────────────────────────────────────────────────────


async def test_reads_segment_artifacts_from_store(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uri1 = await _store_segment(store, "seg1.wav", _make_wav())
    uri2 = await _store_segment(store, "seg2.wav", _make_wav())

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": "s1", "audio_uri": uri1, "pause_after_seconds": 0.0},
            {"segment_id": "s2", "audio_uri": uri2, "pause_after_seconds": 0.0},
        ],
        "default_gap_seconds": 0.0,
    }))
    assert "audio_uri" in result
    assert result["audio_uri"].startswith("artifact://")


async def test_preserves_declared_segment_order(tmp_path) -> None:
    """Executor uses the tuple order, not internal dict insertion order."""
    executor, store = _make_executor(tmp_path)
    # Segment A with frames all 0x01; Segment B with frames all 0x02
    buf_a, buf_b = io.BytesIO(), io.BytesIO()
    for buf, byte in [(buf_a, 0x01), (buf_b, 0x02)]:
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24_000)
            w.writeframes(bytes([byte, 0x00] * 50))

    uri_a = (await store.put_bytes("speech/wf-test", "a.wav", buf_a.getvalue(), "audio/wav")).uri
    uri_b = (await store.put_bytes("speech/wf-test", "b.wav", buf_b.getvalue(), "audio/wav")).uri

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": "a", "audio_uri": uri_a, "pause_after_seconds": 0.0},
            {"segment_id": "b", "audio_uri": uri_b, "pause_after_seconds": 0.0},
        ],
        "default_gap_seconds": 0.0,
    }))

    final_wav = await store.get_bytes(result["audio_uri"])
    with wave.open(io.BytesIO(final_wav)) as out:
        frames = out.readframes(out.getnframes())
    # First 100 bytes of PCM → Segment A (0x01 0x00 pattern)
    assert frames[:100:2] == bytes([0x01] * 50)


async def test_inserts_default_gap_between_segments(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    wav = _make_wav(duration_seconds=1.0, sample_rate=24_000)
    uri1 = await _store_segment(store, "s1.wav", wav)
    uri2 = await _store_segment(store, "s2.wav", wav)

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": "s1", "audio_uri": uri1, "pause_after_seconds": 0.0},
            {"segment_id": "s2", "audio_uri": uri2, "pause_after_seconds": 0.0},
        ],
        "default_gap_seconds": 0.35,
    }))

    final_wav = await store.get_bytes(result["audio_uri"])
    duration = wav_duration_seconds(final_wav)
    # 1.0 + 0.35 gap + 1.0 = 2.35 (no trailing gap after final segment)
    assert abs(duration - 2.35) < 0.01


async def test_explicit_pause_adds_to_default_gap(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    wav = _make_wav(duration_seconds=1.0, sample_rate=24_000)
    uri1 = await _store_segment(store, "s1.wav", wav)
    uri2 = await _store_segment(store, "s2.wav", wav)

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": "s1", "audio_uri": uri1, "pause_after_seconds": 5.0},
            {"segment_id": "s2", "audio_uri": uri2, "pause_after_seconds": 0.0},
        ],
        "default_gap_seconds": 0.35,
    }))

    final_wav = await store.get_bytes(result["audio_uri"])
    duration = wav_duration_seconds(final_wav)
    # 1.0 + (5.0 + 0.35) + 1.0 = 7.35
    assert abs(duration - 7.35) < 0.01


async def test_final_segment_pause_policy(tmp_path) -> None:
    """Only pause_after_seconds is appended after the final segment (no default gap)."""
    executor, store = _make_executor(tmp_path)
    wav = _make_wav(duration_seconds=1.0, sample_rate=24_000)
    uri = await _store_segment(store, "s1.wav", wav)

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [{"segment_id": "s1", "audio_uri": uri, "pause_after_seconds": 2.0}],
        "default_gap_seconds": 0.35,
    }))

    final_wav = await store.get_bytes(result["audio_uri"])
    duration = wav_duration_seconds(final_wav)
    # 1.0 + 2.0 trailing silence = 3.0 (not 3.35)
    assert abs(duration - 3.0) < 0.01


async def test_zero_explicit_and_zero_default_gap_no_silence(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    wav = _make_wav(duration_seconds=1.0, sample_rate=24_000)
    uri1 = await _store_segment(store, "s1.wav", wav)
    uri2 = await _store_segment(store, "s2.wav", wav)

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": "s1", "audio_uri": uri1, "pause_after_seconds": 0.0},
            {"segment_id": "s2", "audio_uri": uri2, "pause_after_seconds": 0.0},
        ],
        "default_gap_seconds": 0.0,
    }))

    final_wav = await store.get_bytes(result["audio_uri"])
    duration = wav_duration_seconds(final_wav)
    assert abs(duration - 2.0) < 0.01


async def test_output_validates_as_audio_assembly_output(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uri = await _store_segment(store, "s1.wav", _make_wav())

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [{"segment_id": "s1", "audio_uri": uri, "pause_after_seconds": 0.0}],
        "default_gap_seconds": 0.0,
    }))

    parsed = AudioAssemblyOutput.model_validate(result)
    assert parsed.media_type == "audio/wav"
    assert parsed.segment_count == 1


async def test_costs_uri_stores_valid_utf8_json(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uri = await _store_segment(store, "s1.wav", _make_wav())

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [{"segment_id": "s1", "audio_uri": uri, "pause_after_seconds": 0.0}],
        "default_gap_seconds": 0.0,
    }))

    costs_bytes = await store.get_bytes(result["costs_uri"])
    costs = json.loads(costs_bytes.decode("utf-8"))
    assert costs["deliverable_id"] == "pod-01"
    assert "segments" in costs
    assert isinstance(costs["segments"], list)


async def test_final_wav_is_valid(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uri = await _store_segment(store, "s1.wav", _make_wav())

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [{"segment_id": "s1", "audio_uri": uri, "pause_after_seconds": 0.0}],
        "default_gap_seconds": 0.0,
    }))

    final_bytes = await store.get_bytes(result["audio_uri"])
    with wave.open(io.BytesIO(final_bytes)):
        pass  # must not raise


async def test_returns_logical_artifact_uris(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uri = await _store_segment(store, "s1.wav", _make_wav())

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [{"segment_id": "s1", "audio_uri": uri, "pause_after_seconds": 0.0}],
        "default_gap_seconds": 0.0,
    }))

    assert result["audio_uri"].startswith("artifact://")
    assert result["costs_uri"].startswith("artifact://")
    # Must not expose filesystem paths
    assert "/artifacts/" not in result["audio_uri"]


async def test_correct_segment_count_returned(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uris = [await _store_segment(store, f"s{i}.wav", _make_wav()) for i in range(3)]

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": f"s{i}", "audio_uri": uri, "pause_after_seconds": 0.0}
            for i, uri in enumerate(uris)
        ],
        "default_gap_seconds": 0.0,
    }))
    assert result["segment_count"] == 3


async def test_aggregates_speech_usage_records(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uri1 = await _store_segment(store, "s1.wav", _make_wav())
    uri2 = await _store_segment(store, "s2.wav", _make_wav())

    usage1 = {**_ZERO_USAGE, "input_characters": 50, "input_cost_usd": 0.000012}
    usage2 = {**_ZERO_USAGE, "input_characters": 80, "input_cost_usd": 0.000020}

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": "s1", "audio_uri": uri1, "pause_after_seconds": 0.0, "usage": usage1},
            {"segment_id": "s2", "audio_uri": uri2, "pause_after_seconds": 0.0, "usage": usage2},
        ],
        "default_gap_seconds": 0.0,
    }))

    assert result["usage"]["total_input_characters"] == 130
    assert abs(result["usage"]["total_input_cost_usd"] - 0.000032) < 1e-9


async def test_pause_duration_tracked_separately_from_speech(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    wav = _make_wav(duration_seconds=1.0, sample_rate=24_000)
    uri1 = await _store_segment(store, "s1.wav", wav)
    uri2 = await _store_segment(store, "s2.wav", wav)

    result = await executor.execute(_ctx({
        "deliverable_id": "pod-01",
        "segments": [
            {"segment_id": "s1", "audio_uri": uri1, "pause_after_seconds": 0.0},
            {"segment_id": "s2", "audio_uri": uri2, "pause_after_seconds": 0.0},
        ],
        "default_gap_seconds": 0.35,
    }))

    assert abs(result["usage"]["total_pause_duration_seconds"] - 0.35) < 0.01


async def test_idempotent_retry_replaces_artifact(tmp_path) -> None:
    """Running the same task twice overwrites the same deterministic artifact path."""
    executor, store = _make_executor(tmp_path)
    uri = await _store_segment(store, "s1.wav", _make_wav())
    inputs = {
        "deliverable_id": "pod-01",
        "segments": [{"segment_id": "s1", "audio_uri": uri, "pause_after_seconds": 0.0}],
        "default_gap_seconds": 0.0,
    }

    result1 = await executor.execute(_ctx(inputs))
    result2 = await executor.execute(_ctx(inputs))
    # Same deterministic URI — idempotent
    assert result1["audio_uri"] == result2["audio_uri"]
    assert result1["costs_uri"] == result2["costs_uri"]


# ── Error paths ───────────────────────────────────────────────────────────────


async def test_missing_artifact_raises_assembly_error(tmp_path) -> None:
    executor, _ = _make_executor(tmp_path)
    with pytest.raises(AudioAssemblyError, match="not found"):
        await executor.execute(_ctx({
            "deliverable_id": "pod-01",
            "segments": [
                {"segment_id": "s1", "audio_uri": "artifact://speech/wf-test/nonexistent.wav"}
            ],
            "default_gap_seconds": 0.0,
        }))


async def test_incompatible_sample_rates_raise_before_writing(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    uri1 = await _store_segment(store, "s1.wav", _make_wav(sample_rate=24_000))
    uri2 = await _store_segment(store, "s2.wav", _make_wav(sample_rate=16_000))

    with pytest.raises(IncompatibleSegmentError):
        await executor.execute(_ctx({
            "deliverable_id": "pod-01",
            "segments": [
                {"segment_id": "s1", "audio_uri": uri1, "pause_after_seconds": 0.0},
                {"segment_id": "s2", "audio_uri": uri2, "pause_after_seconds": 0.0},
            ],
            "default_gap_seconds": 0.0,
        }))

    # No partial artifact should have been written
    deliverable_ns = "deliverables/wf-test"
    with pytest.raises(ArtifactNotFoundError):
        await store.get_bytes(f"artifact://{deliverable_ns}/pod-01.wav")


async def test_invalid_input_raises_tool_input_error(tmp_path) -> None:
    executor, _ = _make_executor(tmp_path)
    with pytest.raises(InvalidToolInputError):
        await executor.execute(_ctx({
            "deliverable_id": "",  # blank — invalid
            "segments": [{"segment_id": "s1", "audio_uri": "fake://x.wav"}],
        }))


async def test_corrupt_wav_raises_assembly_error(tmp_path) -> None:
    executor, store = _make_executor(tmp_path)
    corrupt_ref = await store.put_bytes("speech/wf-test", "corrupt.wav", b"not a wav", "audio/wav")

    with pytest.raises((AudioAssemblyError, IncompatibleSegmentError)):
        await executor.execute(_ctx({
            "deliverable_id": "pod-01",
            "segments": [{"segment_id": "s1", "audio_uri": corrupt_ref.uri}],
            "default_gap_seconds": 0.0,
        }))
