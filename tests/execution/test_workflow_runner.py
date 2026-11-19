"""
Tests for DAGRunner / WorkflowRunner correctness and concurrency behaviour.

Concurrency is verified using an active-execution counter rather than elapsed
time to keep tests deterministic.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from learning_pipeline.contracts import (
    BuildPlan,
    LiteralInput,
    Modality,
    TaskOutputInput,
    TaskSpec,
)
from learning_pipeline.runtime.execution import ExecutionContext, ExecutorRegistry
from learning_pipeline.runtime.persistence import FileRunStateStore, TaskStatus, WorkflowStatus
from learning_pipeline.runtime.runner import DAGRunner, WorkflowRunner
from learning_pipeline.validation import canonical_plan_hash


class _RecordingExecutor:
    def __init__(self, delay: float = 0.05) -> None:
        self._delay = delay
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        self.calls.append(context.task_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(self._delay)
        self.active -= 1
        return {"value": context.task_id}


def _podcast_plan(workflow_id: str = "wf-concurrent") -> BuildPlan:
    return BuildPlan(
        workflow_id=workflow_id,
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="speech-1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s1")},
                output_keys=("value",),
            ),
            TaskSpec(
                id="speech-2",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s2")},
                output_keys=("value",),
            ),
            TaskSpec(
                id="assemble",
                task_type="audio.assemble",
                depends_on=("speech-1", "speech-2"),
                inputs={
                    "seg1": TaskOutputInput(task_id="speech-1", output_key="value"),
                    "seg2": TaskOutputInput(task_id="speech-2", output_key="value"),
                },
                output_keys=("value",),
            ),
        ),
        deliverable_task_ids=("assemble",),
    )


def _registry(*types: str) -> tuple[ExecutorRegistry, _RecordingExecutor]:
    executor = _RecordingExecutor()
    reg = ExecutorRegistry()
    for t in types:
        reg.register(t, executor)
    return reg, executor


@pytest.mark.asyncio
async def test_invalid_plan_invokes_zero_executors(tmp_path):
    executor = _RecordingExecutor()
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", executor)
    # plan uses "unregistered.type" which is NOT in the registry
    plan = BuildPlan(
        workflow_id="wf-bad",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(id="t1", task_type="unregistered.type", output_keys=("v",)),
        ),
        deliverable_task_ids=("t1",),
    )
    runner = DAGRunner(reg, FileRunStateStore(tmp_path))
    with pytest.raises(Exception):
        await runner.run(plan)
    assert len(executor.calls) == 0


@pytest.mark.asyncio
async def test_two_speech_tasks_overlap_in_execution(tmp_path):
    reg, executor = _registry("speech.synthesize", "audio.assemble")
    runner = DAGRunner(reg, FileRunStateStore(tmp_path), max_concurrency=4)
    await runner.run(_podcast_plan())
    assert executor.max_active == 2, "both speech tasks must be concurrently active"


@pytest.mark.asyncio
async def test_assembly_starts_only_after_both_speech_tasks(tmp_path):
    reg, executor = _registry("speech.synthesize", "audio.assemble")
    runner = DAGRunner(reg, FileRunStateStore(tmp_path))
    await runner.run(_podcast_plan())

    assemble_idx = executor.calls.index("assemble")
    assert executor.calls.index("speech-1") < assemble_idx
    assert executor.calls.index("speech-2") < assemble_idx


@pytest.mark.asyncio
async def test_runner_respects_max_concurrency(tmp_path):
    executor = _RecordingExecutor(delay=0.05)
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", executor)
    plan = BuildPlan(
        workflow_id="wf-concurrency",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(id="s1", task_type="speech.synthesize", inputs={"scene_id": LiteralInput(value="a")}, output_keys=("value",)),
            TaskSpec(id="s2", task_type="speech.synthesize", inputs={"scene_id": LiteralInput(value="b")}, output_keys=("value",)),
            TaskSpec(id="s3", task_type="speech.synthesize", inputs={"scene_id": LiteralInput(value="c")}, output_keys=("value",)),
        ),
        deliverable_task_ids=("s1",),
    )
    await DAGRunner(reg, FileRunStateStore(tmp_path), max_concurrency=2).run(plan)
    assert executor.max_active <= 2


@pytest.mark.asyncio
async def test_successful_results_are_persisted(tmp_path):
    reg, _ = _registry("speech.synthesize", "audio.assemble")
    store = FileRunStateStore(tmp_path)
    await DAGRunner(reg, store).run(_podcast_plan())

    snapshot = store.load("wf-concurrent")
    for task_id in ("speech-1", "speech-2", "assemble"):
        assert snapshot.statuses[task_id] == TaskStatus.SUCCEEDED
        assert task_id in snapshot.results


@pytest.mark.asyncio
async def test_workflow_status_is_succeeded_after_successful_run(tmp_path):
    reg, _ = _registry("speech.synthesize", "audio.assemble")
    store = FileRunStateStore(tmp_path)
    await DAGRunner(reg, store).run(_podcast_plan())
    assert store.load("wf-concurrent").workflow_status == WorkflowStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_deliverables_match_deliverable_task_ids(tmp_path):
    reg, _ = _registry("speech.synthesize", "audio.assemble")
    result = await DAGRunner(reg, FileRunStateStore(tmp_path)).run(_podcast_plan())
    assert len(result.deliverables) == 1
    assert result.deliverables[0].task_id == "assemble"


@pytest.mark.asyncio
async def test_workflow_result_contains_correct_plan_hash(tmp_path):
    plan = _podcast_plan("wf-hash")
    reg, _ = _registry("speech.synthesize", "audio.assemble")
    result = await DAGRunner(reg, FileRunStateStore(tmp_path)).run(plan)
    assert result.plan_hash == canonical_plan_hash(plan)


@pytest.mark.asyncio
async def test_build_plan_is_not_mutated_during_run(tmp_path):
    plan = _podcast_plan()
    original_tasks = plan.tasks
    reg, _ = _registry("speech.synthesize", "audio.assemble")
    await DAGRunner(reg, FileRunStateStore(tmp_path)).run(plan)
    assert plan.tasks == original_tasks


def test_workflow_runner_is_the_dag_runner_alias():
    assert WorkflowRunner is DAGRunner


@pytest.mark.asyncio
async def test_attempt_number_is_passed_to_executor(tmp_path):
    received_attempts: list[int] = []

    class _AttemptRecorder:
        async def execute(self, context: ExecutionContext) -> dict[str, Any]:
            received_attempts.append(context.attempt)
            return {"value": "ok"}

    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _AttemptRecorder())
    plan = BuildPlan(
        workflow_id="wf-attempt",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="s1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s")},
                output_keys=("value",),
            ),
        ),
        deliverable_task_ids=("s1",),
    )
    await DAGRunner(reg, FileRunStateStore(tmp_path)).run(plan)
    assert received_attempts == [1]


@pytest.mark.asyncio
async def test_executor_extra_outputs_are_preserved(tmp_path):
    """Executors may return keys beyond output_keys (e.g. usage metadata).

    output_keys declares the REQUIRED outputs; additional keys are allowed and
    preserved in TaskResult.outputs so downstream tasks or callers can read them.
    """
    class _RichOutputExecutor:
        async def execute(self, context: ExecutionContext) -> dict[str, Any]:
            return {"value": "ok", "usage": {"tokens": 12}, "duration_seconds": 1.5}

    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _RichOutputExecutor())
    plan = BuildPlan(
        workflow_id="wf-extra-output",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="s1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s")},
                output_keys=("value",),
                max_attempts=1,
            ),
        ),
        deliverable_task_ids=("s1",),
    )
    result = await DAGRunner(reg, FileRunStateStore(tmp_path)).run(plan)
    assert result.task_results["s1"].outputs["value"] == "ok"
    assert result.task_results["s1"].outputs["duration_seconds"] == 1.5
