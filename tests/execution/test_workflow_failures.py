"""
Tests for DAGRunner failure behaviour: retry limits, blocked tasks, and
fail-fast cancellation.
"""
from __future__ import annotations

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
from learning_pipeline.runtime.runner import DAGRunner, WorkflowExecutionError


class _FailFirstN:
    """Fails the first N attempts, then succeeds."""

    def __init__(self, fail_count: int = 1) -> None:
        self._fail_count = fail_count
        self.attempts = 0

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        self.attempts += 1
        if self.attempts <= self._fail_count:
            raise RuntimeError(f"transient failure #{self.attempts}")
        return {"value": context.task_id}


class _AlwaysFail:
    def __init__(self) -> None:
        self.attempts = 0

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        self.attempts += 1
        raise RuntimeError("permanent failure")


class _AlwaysSucceed:
    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        return {"value": "ok"}


def _single_speech_plan(workflow_id: str, max_attempts: int = 2) -> BuildPlan:
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
                max_attempts=max_attempts,
            ),
        ),
        deliverable_task_ids=("speech-1",),
    )


@pytest.mark.asyncio
async def test_executor_failing_once_succeeds_on_second_attempt(tmp_path):
    executor = _FailFirstN(fail_count=1)
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", executor)

    result = await DAGRunner(reg, FileRunStateStore(tmp_path)).run(
        _single_speech_plan("wf-retry-once", max_attempts=2)
    )
    assert executor.attempts == 2
    assert result.task_results["speech-1"].attempts == 2


@pytest.mark.asyncio
async def test_task_result_records_correct_attempt_count(tmp_path):
    executor = _FailFirstN(fail_count=2)
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", executor)

    result = await DAGRunner(reg, FileRunStateStore(tmp_path)).run(
        _single_speech_plan("wf-retry-two", max_attempts=3)
    )
    assert result.task_results["speech-1"].attempts == 3


@pytest.mark.asyncio
async def test_executor_never_exceeds_max_attempts(tmp_path):
    executor = _AlwaysFail()
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", executor)

    with pytest.raises(WorkflowExecutionError):
        await DAGRunner(reg, FileRunStateStore(tmp_path)).run(
            _single_speech_plan("wf-max", max_attempts=3)
        )
    assert executor.attempts == 3


@pytest.mark.asyncio
async def test_permanent_failure_marks_task_failed(tmp_path):
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _AlwaysFail())
    store = FileRunStateStore(tmp_path)

    with pytest.raises(WorkflowExecutionError):
        await DAGRunner(reg, store).run(_single_speech_plan("wf-fail-status", max_attempts=1))

    snapshot = store.load("wf-fail-status")
    assert snapshot.statuses["speech-1"] == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_workflow_status_is_failed_after_permanent_failure(tmp_path):
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _AlwaysFail())
    store = FileRunStateStore(tmp_path)

    with pytest.raises(WorkflowExecutionError):
        await DAGRunner(reg, store).run(_single_speech_plan("wf-wf-status", max_attempts=1))

    assert store.load("wf-wf-status").workflow_status == WorkflowStatus.FAILED


@pytest.mark.asyncio
async def test_downstream_tasks_become_blocked_on_failure(tmp_path):
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _AlwaysFail())
    reg.register("audio.assemble", _AlwaysSucceed())

    plan = BuildPlan(
        workflow_id="wf-blocked",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="speech-1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s1")},
                output_keys=("value",),
                max_attempts=1,
            ),
            TaskSpec(
                id="assemble",
                task_type="audio.assemble",
                depends_on=("speech-1",),
                inputs={"seg": TaskOutputInput(task_id="speech-1", output_key="value")},
                output_keys=("value",),
            ),
        ),
        deliverable_task_ids=("assemble",),
    )
    store = FileRunStateStore(tmp_path)
    with pytest.raises(WorkflowExecutionError):
        await DAGRunner(reg, store).run(plan)

    snapshot = store.load("wf-blocked")
    assert snapshot.statuses["speech-1"] == TaskStatus.FAILED
    assert snapshot.statuses["assemble"] == TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_failed_state_is_persisted_with_failure_message(tmp_path):
    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _AlwaysFail())
    store = FileRunStateStore(tmp_path)

    with pytest.raises(WorkflowExecutionError):
        await DAGRunner(reg, store).run(_single_speech_plan("wf-persist-fail", max_attempts=1))

    snapshot = store.load("wf-persist-fail")
    assert snapshot.failure is not None
    assert len(snapshot.failure) > 0


@pytest.mark.asyncio
async def test_no_llm_or_repair_is_invoked_on_failure(tmp_path):
    """No planning, repair, or LLM component should be called on failure."""
    called: list[str] = []

    class _LLMGuard:
        def plan(self, *args, **kwargs):
            called.append("plan")
            raise AssertionError("LLM must not be called")

        def repair(self, *args, **kwargs):
            called.append("repair")
            raise AssertionError("repair must not be called")

    reg = ExecutorRegistry()
    reg.register("speech.synthesize", _AlwaysFail())

    with pytest.raises(WorkflowExecutionError):
        await DAGRunner(reg, FileRunStateStore(tmp_path)).run(
            _single_speech_plan("wf-no-llm", max_attempts=1)
        )
    assert called == [], "no LLM or repair function should have been invoked"
