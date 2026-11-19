"""
End-to-end execution test for the committed ADKAR podcast reference BuildPlan.

Loads the real build_plan.json from examples/reference/podcast/, registers
fake executors, and drives the plan through WorkflowRunner.

Proves:
* Both speech tasks succeed and ran concurrently.
* Assembly started only after both speech tasks completed.
* Assembly received resolved audio_uri values from both speech tasks.
* The deliverable is the assembly task's podcast_file output.
* The final run snapshot matches the workflow result.
* No OpenAI client was created.
* No network call was made.
* No environment credentials were required.
* No real audio files were generated.
* No LLM or planning component was invoked.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from learning_pipeline.contracts import BuildPlan
from learning_pipeline.runtime.execution import ExecutionContext, ExecutorRegistry
from learning_pipeline.executors.fake import FakeAudioAssemblyExecutor, FakeSpeechExecutor
from learning_pipeline.runtime.persistence import FileRunStateStore, TaskStatus, WorkflowStatus
from learning_pipeline.runtime.runner import WorkflowRunner
from learning_pipeline.validation import canonical_plan_hash

_REFERENCE_PLAN = (
    Path(__file__).parent.parent.parent
    / "examples"
    / "reference"
    / "podcast"
    / "build_plan.json"
)


@pytest.fixture(scope="module")
def build_plan() -> BuildPlan:
    return BuildPlan.model_validate_json(_REFERENCE_PLAN.read_text(encoding="utf-8"))


@pytest.fixture
def registry() -> ExecutorRegistry:
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", FakeSpeechExecutor(delay=0.05))
    reg.register("audio.assemble", FakeAudioAssemblyExecutor())
    return reg


# ── Core success path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reference_plan_completes_successfully(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)

    assert "speech-segment-1" in result.task_results
    assert "speech-segment-2" in result.task_results
    assert "assemble-podcast" in result.task_results

    assert result.task_results["speech-segment-1"].outputs["audio_uri"].startswith("fake://audio/")
    assert result.task_results["speech-segment-2"].outputs["audio_uri"].startswith("fake://audio/")
    assert "audio_uri" in result.task_results["assemble-podcast"].outputs
    assert "costs_uri" in result.task_results["assemble-podcast"].outputs

    assert len(result.deliverables) == 1
    assert result.deliverables[0].task_id == "assemble-podcast"


@pytest.mark.asyncio
async def test_reference_plan_deliverable_is_assembly_output(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    deliverable = result.deliverables[0]
    assert "audio_uri" in deliverable.outputs
    assert deliverable.outputs["audio_uri"].startswith("fake://deliverables/")
    assert "costs_uri" in deliverable.outputs


@pytest.mark.asyncio
async def test_reference_plan_hash_matches_canonical(build_plan, registry, tmp_path):
    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    assert result.plan_hash == canonical_plan_hash(build_plan)


# ── Concurrency proof ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_speech_tasks_ran_concurrently(build_plan, tmp_path):
    active = 0
    peak_active: list[int] = []

    class _TrackingSpeech:
        async def execute(self, context: ExecutionContext) -> dict[str, Any]:
            nonlocal active
            active += 1
            peak_active.append(active)
            await asyncio.sleep(0.05)
            active -= 1
            return {
                "audio_uri": f"fake://audio/{context.task_id}.wav",
                "usage": {"input_characters": 0, "input_tokens_estimate": 0.0,
                          "audio_duration_seconds": 0.0, "input_cost_usd": 0.0,
                          "output_cost_usd": 0.0, "total_cost_usd": 0.0},
            }

    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _TrackingSpeech())
    reg.register("audio.assemble", FakeAudioAssemblyExecutor())

    await WorkflowRunner(reg, FileRunStateStore(tmp_path), max_concurrency=4).run(build_plan)
    assert max(peak_active) == 2, "both speech tasks must have been concurrently active"


@pytest.mark.asyncio
async def test_assembly_started_after_both_speech_tasks(build_plan, tmp_path):
    call_order: list[str] = []

    _ZERO_USAGE = {"input_characters": 0, "input_tokens_estimate": 0.0,
                   "audio_duration_seconds": 0.0, "input_cost_usd": 0.0,
                   "output_cost_usd": 0.0, "total_cost_usd": 0.0}

    class _OrderedSpeech:
        async def execute(self, context: ExecutionContext) -> dict[str, Any]:
            call_order.append(context.task_id)
            await asyncio.sleep(0.02)
            return {"audio_uri": f"fake://audio/{context.task_id}.wav", "usage": _ZERO_USAGE}

    class _OrderedAssembly:
        async def execute(self, context: ExecutionContext) -> dict[str, Any]:
            call_order.append(context.task_id)
            return {
                "audio_uri": "fake://deliverables/podcast.wav",
                "costs_uri": "fake://deliverables/podcast.costs.json",
            }

    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _OrderedSpeech())
    reg.register("audio.assemble", _OrderedAssembly())

    await WorkflowRunner(reg, FileRunStateStore(tmp_path)).run(build_plan)

    assemble_idx = call_order.index("assemble-podcast")
    assert call_order.index("speech-segment-1") < assemble_idx
    assert call_order.index("speech-segment-2") < assemble_idx


# ── Input resolution proof ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assembly_received_resolved_segments_from_both_speech_tasks(build_plan, tmp_path):
    assembly_inputs: dict[str, Any] = {}

    class _CapturingAssembly:
        async def execute(self, context: ExecutionContext) -> dict[str, Any]:
            assembly_inputs.update(context.inputs)
            return {
                "audio_uri": "fake://deliverables/podcast.wav",
                "costs_uri": "fake://deliverables/podcast.costs.json",
            }

    reg = ExecutorRegistry()
    reg.register("speech.synthesize", FakeSpeechExecutor(delay=0.01))
    reg.register("audio.assemble", _CapturingAssembly())

    await WorkflowRunner(reg, FileRunStateStore(tmp_path)).run(build_plan)

    # Inputs now use the structured list binding: deliverable_id + segments list
    assert "deliverable_id" in assembly_inputs
    assert assembly_inputs["deliverable_id"] == "podcast-adkar-01"
    segments = assembly_inputs["segments"]
    assert isinstance(segments, list)
    assert len(segments) == 2
    # Narrative order is preserved regardless of task completion order
    assert segments[0]["segment_id"] == "adkar-intro-host-01"
    assert segments[0]["audio_uri"] == "fake://audio/speech-segment-1.wav"
    assert segments[1]["segment_id"] == "adkar-awareness-expert-01"
    assert segments[1]["audio_uri"] == "fake://audio/speech-segment-2.wav"


# ── Persistence proof ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_final_snapshot_contains_all_task_results(build_plan, registry, tmp_path):
    store = FileRunStateStore(tmp_path)
    await WorkflowRunner(registry, store).run(build_plan)

    snapshot = store.load(build_plan.workflow_id)
    assert snapshot.workflow_status == WorkflowStatus.SUCCEEDED
    for task_id in ("speech-segment-1", "speech-segment-2", "assemble-podcast"):
        assert snapshot.statuses[task_id] == TaskStatus.SUCCEEDED
        assert task_id in snapshot.results


@pytest.mark.asyncio
async def test_snapshot_outputs_match_workflow_result(build_plan, registry, tmp_path):
    store = FileRunStateStore(tmp_path)
    result = await WorkflowRunner(registry, store).run(build_plan)
    snapshot = store.load(build_plan.workflow_id)

    for task_id, task_result in result.task_results.items():
        assert task_id in snapshot.results
        assert snapshot.results[task_id].outputs == task_result.outputs


# ── No external calls proof ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execution_requires_no_credentials(build_plan, registry, tmp_path):
    """Fake executors complete without any environment credentials."""
    for key in ("OPENAI_API_KEY", "LITE_LLM_API_KEY", "LITE_LLM_BASE_URL"):
        os.environ.pop(key, None)

    result = await WorkflowRunner(registry, FileRunStateStore(tmp_path)).run(build_plan)
    assert result is not None


@pytest.mark.asyncio
async def test_execution_creates_no_real_audio_files(build_plan, registry, tmp_path):
    """No WAV or MP3 files should appear on disk after fake execution."""
    state_root = tmp_path / "state"
    await WorkflowRunner(registry, FileRunStateStore(state_root)).run(build_plan)

    real_audio = list(state_root.rglob("*.wav")) + list(state_root.rglob("*.mp3"))
    assert real_audio == [], f"unexpected audio files on disk: {real_audio}"
