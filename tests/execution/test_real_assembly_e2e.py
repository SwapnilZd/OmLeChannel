"""
End-to-end deterministic test for the full podcast assembly pipeline.

Uses in-memory speech executors that produce valid WAV bytes (no TTS provider),
the real RealAudioAssemblyExecutor, and a FileArtifactStore in a temporary
directory.  No network calls are made.

Flow: reference BuildPlan → DAGRunner → speech tasks produce WAV artifacts →
assembly task reads those artifacts → WorkflowResult contains valid final WAV.
"""
from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from typing import Any

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.tools.audio_utils import wav_duration_seconds
from learning_pipeline.contracts import BuildPlan, WorkflowResult
from learning_pipeline.runtime.execution import ExecutionContext, ExecutorRegistry
from learning_pipeline.runtime.persistence import FileRunStateStore
from learning_pipeline.runtime.runner import DAGRunner
from learning_pipeline.tools.audio_assembly.executor import RealAudioAssemblyExecutor
from learning_pipeline.tools.speech.contracts import SpeechSynthesisInput


_REFERENCE_PLAN = (
    Path(__file__).parent.parent.parent
    / "examples"
    / "reference"
    / "podcast"
    / "build_plan.json"
)


# ── WAV helpers ───────────────────────────────────────────────────────────────


def _make_wav(
    *,
    duration_seconds: float = 1.0,
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
    "audio_duration_seconds": 1.0,
    "input_cost_usd": 0.0,
    "output_cost_usd": 0.0,
    "total_cost_usd": 0.0,
}


# ── In-memory speech executor ─────────────────────────────────────────────────


class _InMemorySpeechExecutor:
    """Stores a valid WAV artifact in the provided store and returns audio_uri."""

    def __init__(self, artifact_store: FileArtifactStore) -> None:
        self._store = artifact_store
        self._duration = 1.0

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        inp = SpeechSynthesisInput.model_validate(context.inputs)
        wav = _make_wav(duration_seconds=self._duration)
        namespace = f"speech/{context.workflow_id}"
        name = f"{inp.line_id}.wav"
        ref = await self._store.put_bytes(namespace, name, wav, "audio/wav")
        return {
            "audio_uri": ref.uri,
            "usage": _ZERO_USAGE,
        }


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path) -> FileArtifactStore:
    return FileArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def reference_plan() -> BuildPlan:
    plan_json = json.loads(_REFERENCE_PLAN.read_text())
    return BuildPlan.model_validate(plan_json)


@pytest.fixture
def registry(store) -> ExecutorRegistry:
    speech_executor = _InMemorySpeechExecutor(store)
    assembly_executor = RealAudioAssemblyExecutor(artifact_store=store)
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", speech_executor)
    reg.register("audio.assemble", assembly_executor)
    return reg


def _runner(registry: ExecutorRegistry, tmp_path: Path) -> DAGRunner:
    return DAGRunner(registry, FileRunStateStore(tmp_path / "state"))


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_reference_plan_runs_to_completion(
    reference_plan, registry, tmp_path
) -> None:
    result = await _runner(registry, tmp_path).run(reference_plan)
    assert isinstance(result, WorkflowResult)
    assert result.workflow_id == reference_plan.workflow_id


async def test_all_speech_and_assembly_tasks_ran(
    reference_plan, registry, tmp_path
) -> None:
    result = await _runner(registry, tmp_path).run(reference_plan)
    assert "speech-segment-1" in result.task_results
    assert "speech-segment-2" in result.task_results
    assert "assemble-podcast" in result.task_results


async def test_assembly_deliverable_has_audio_and_costs_uris(
    reference_plan, registry, tmp_path
) -> None:
    result = await _runner(registry, tmp_path).run(reference_plan)
    assert len(result.deliverables) == 1
    deliverable = result.deliverables[0]
    assert "audio_uri" in deliverable.outputs
    assert "costs_uri" in deliverable.outputs
    assert deliverable.outputs["audio_uri"].startswith("artifact://")
    assert deliverable.outputs["costs_uri"].startswith("artifact://")


async def test_final_wav_artifact_is_readable(
    reference_plan, registry, store, tmp_path
) -> None:
    result = await _runner(registry, tmp_path).run(reference_plan)
    audio_uri = result.deliverables[0].outputs["audio_uri"]
    final_wav = await store.get_bytes(audio_uri)
    with wave.open(io.BytesIO(final_wav)):
        pass  # must not raise


async def test_costs_artifact_is_valid_json(
    reference_plan, registry, store, tmp_path
) -> None:
    result = await _runner(registry, tmp_path).run(reference_plan)
    costs_uri = result.deliverables[0].outputs["costs_uri"]
    costs_bytes = await store.get_bytes(costs_uri)
    costs = json.loads(costs_bytes.decode("utf-8"))
    assert "deliverable_id" in costs
    assert "segments" in costs
    assert isinstance(costs["segments"], list)
    assert len(costs["segments"]) == 2


async def test_final_wav_is_longer_than_individual_segments(
    reference_plan, registry, store, tmp_path
) -> None:
    """Assembly must be longer than a single 1.0 s speech segment due to gaps."""
    result = await _runner(registry, tmp_path).run(reference_plan)
    audio_uri = result.deliverables[0].outputs["audio_uri"]
    final_wav = await store.get_bytes(audio_uri)
    duration = wav_duration_seconds(final_wav)
    # 2 × 1.0 s speech + at least the default gap (0.35 s) between them
    assert duration > 2.0


async def test_speech_artifacts_are_stored_before_assembly(
    reference_plan, registry, store, tmp_path
) -> None:
    """Speech WAV artifacts must be physically present so assembly can read them."""
    result = await _runner(registry, tmp_path).run(reference_plan)

    seg1_uri = result.task_results["speech-segment-1"].outputs["audio_uri"]
    seg2_uri = result.task_results["speech-segment-2"].outputs["audio_uri"]
    wav1 = await store.get_bytes(seg1_uri)
    wav2 = await store.get_bytes(seg2_uri)
    assert len(wav1) > 0
    assert len(wav2) > 0


async def test_assembly_result_segment_count_matches_plan(
    reference_plan, registry, tmp_path
) -> None:
    result = await _runner(registry, tmp_path).run(reference_plan)
    assembly_result = result.task_results["assemble-podcast"]
    assert assembly_result.outputs["segment_count"] == 2
