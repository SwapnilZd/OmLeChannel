import asyncio

import pytest

from learning_pipeline.contracts import BuildPlan, LiteralInput, Modality, TaskOutputInput, TaskResult, TaskSpec
from learning_pipeline.runtime.execution import ExecutionContext, ExecutorRegistry
from learning_pipeline.runtime.persistence import FileRunStateStore, RunSnapshot, TaskStatus, WorkflowStatus
from learning_pipeline.runtime.runner import DAGRunner, WorkflowExecutionError
from learning_pipeline.validation import canonical_plan_hash


class RecordingExecutor:
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0
        self.calls: list[str] = []

    async def execute(self, context: ExecutionContext) -> dict[str, str]:
        self.calls.append(context.task_id)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"value": str(context.inputs.get("value", context.task_id))}


class FailOnceExecutor:
    def __init__(self) -> None:
        self.attempts = 0

    async def execute(self, context: ExecutionContext) -> dict[str, str]:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("transient")
        return {"value": context.task_id}


@pytest.mark.asyncio
async def test_runner_fans_out_then_joins(tmp_path) -> None:
    executor = RecordingExecutor()
    registry = ExecutorRegistry()
    registry.register("record", executor)
    plan = BuildPlan(
        workflow_id="wf-parallel",
        source_plan_id="source",
        modality=Modality.VIDEO,
        tasks=(
            TaskSpec(id="a", task_type="record", inputs={"value": LiteralInput(value="A")}, output_keys=("value",)),
            TaskSpec(id="b", task_type="record", inputs={"value": LiteralInput(value="B")}, output_keys=("value",)),
            TaskSpec(
                id="join",
                task_type="record",
                depends_on=("a", "b"),
                inputs={"value": TaskOutputInput(task_id="a", output_key="value")},
                output_keys=("value",),
            ),
        ),
        deliverable_task_ids=("join",),
    )
    runner = DAGRunner(registry, FileRunStateStore(tmp_path), max_concurrency=2)

    result = await runner.run(plan)

    assert executor.maximum_active == 2
    assert executor.calls.index("join") > executor.calls.index("a")
    assert executor.calls.index("join") > executor.calls.index("b")
    assert result.deliverables[0].outputs["value"] == "A"


@pytest.mark.asyncio
async def test_runner_retries_only_to_max_attempts(tmp_path) -> None:
    executor = FailOnceExecutor()
    registry = ExecutorRegistry()
    registry.register("flaky", executor)
    plan = BuildPlan(
        workflow_id="wf-retry",
        source_plan_id="source",
        modality=Modality.PODCAST,
        tasks=(TaskSpec(id="audio", task_type="flaky", output_keys=("value",), max_attempts=2),),
        deliverable_task_ids=("audio",),
    )
    result = await DAGRunner(registry, FileRunStateStore(tmp_path)).run(plan)
    assert executor.attempts == 2
    assert result.task_results["audio"].attempts == 2


@pytest.mark.asyncio
async def test_permanent_failure_is_persisted(tmp_path) -> None:
    class BrokenExecutor:
        async def execute(self, context: ExecutionContext) -> dict[str, str]:
            raise RuntimeError("broken")

    registry = ExecutorRegistry()
    registry.register("broken", BrokenExecutor())
    plan = BuildPlan(
        workflow_id="wf-failed",
        source_plan_id="source",
        modality=Modality.ELEARNING,
        tasks=(TaskSpec(id="render", task_type="broken", output_keys=("file",), max_attempts=1),),
        deliverable_task_ids=("render",),
    )
    store = FileRunStateStore(tmp_path)
    with pytest.raises(WorkflowExecutionError, match="render"):
        await DAGRunner(registry, store).run(plan)
    snapshot = store.load("wf-failed")
    assert snapshot.statuses["render"] == TaskStatus.FAILED
    assert snapshot.failure == "broken"


@pytest.mark.asyncio
async def test_blank_exception_is_persisted_with_its_type(tmp_path) -> None:
    class TimedOutExecutor:
        async def execute(self, context: ExecutionContext) -> dict[str, str]:
            raise TimeoutError()

    registry = ExecutorRegistry()
    registry.register("timed-out", TimedOutExecutor())
    plan = BuildPlan(
        workflow_id="wf-blank-failure",
        source_plan_id="source",
        modality=Modality.ELEARNING,
        tasks=(TaskSpec(
            id="render",
            task_type="timed-out",
            output_keys=("file",),
            max_attempts=1,
        ),),
        deliverable_task_ids=("render",),
    )
    store = FileRunStateStore(tmp_path)

    with pytest.raises(WorkflowExecutionError, match="render failed: TimeoutError"):
        await DAGRunner(registry, store).run(plan)

    assert store.load("wf-blank-failure").failure == "TimeoutError"


@pytest.mark.asyncio
async def test_restart_reuses_succeeded_task_results_from_checkpoint(tmp_path) -> None:
    executor = RecordingExecutor()
    registry = ExecutorRegistry()
    registry.register("record", executor)
    plan = BuildPlan(
        workflow_id="wf-resume",
        source_plan_id="source",
        modality=Modality.ELEARNING,
        tasks=(
            TaskSpec(id="done", task_type="record", output_keys=("value",)),
            TaskSpec(
                id="remaining",
                task_type="record",
                depends_on=("done",),
                inputs={"value": TaskOutputInput(task_id="done", output_key="value")},
                output_keys=("value",),
            ),
        ),
        deliverable_task_ids=("remaining",),
    )
    store = FileRunStateStore(tmp_path)
    store.save(
        RunSnapshot(
            workflow_id=plan.workflow_id,
            plan_hash=canonical_plan_hash(plan),
            workflow_status=WorkflowStatus.FAILED,
            statuses={"done": TaskStatus.SUCCEEDED, "remaining": TaskStatus.FAILED},
            results={
                "done": TaskResult(
                    task_id="done", outputs={"value": "checkpoint-value"}, attempts=1
                )
            },
            failure="remaining failed",
        )
    )

    result = await DAGRunner(registry, store).run(plan)

    assert executor.calls == ["remaining"]
    assert result.deliverables[0].outputs["value"] == "checkpoint-value"
