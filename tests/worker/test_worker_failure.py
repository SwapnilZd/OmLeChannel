"""Worker handles failing workflows gracefully and continues processing."""

from __future__ import annotations

import pytest

from learning_pipeline.contracts import BuildPlan, LiteralInput, Modality, TaskSpec
from learning_pipeline.db.repository import PersistentWorkflowStatus
from learning_pipeline.runtime.execution import ExecutionContext, ExecutorRegistry
from learning_pipeline.worker.main import WorkerLoop
from learning_pipeline.validation import canonical_plan_hash
from tests.api.conftest import InMemoryWorkflowRepository
from tests.worker.conftest import InMemoryRunStateStore


class AlwaysFailExecutor:
    async def execute(self, context: ExecutionContext) -> dict:
        raise RuntimeError("executor always fails")


def _broken_registry() -> ExecutorRegistry:
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", AlwaysFailExecutor())
    registry.register("audio.assemble", AlwaysFailExecutor())
    return registry


def _make_minimal_plan(wid: str) -> BuildPlan:
    return BuildPlan(
        workflow_id=wid,
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="t1",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="s1")},
                output_keys=("audio_file",),
                max_attempts=1,
            ),
        ),
        deliverable_task_ids=("t1",),
    )


async def test_worker_marks_failed_on_executor_error(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
) -> None:
    plan = _make_minimal_plan("wf-fail-1")
    await fake_repo.create_pending(plan, canonical_plan_hash(plan))

    loop = WorkerLoop(fake_repo, fake_state_store, _broken_registry(), "w-fail")
    claimed = await loop.run_once()

    assert claimed is True
    record = await fake_repo.get("wf-fail-1")
    assert record.status == PersistentWorkflowStatus.FAILED
    assert record.error_message is not None


async def test_worker_continues_after_failed_workflow(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    """A failing workflow must not stop the worker from processing subsequent jobs."""
    broken_plan = _make_minimal_plan("wf-fail-first")
    await fake_repo.create_pending(broken_plan, canonical_plan_hash(broken_plan))
    await fake_repo.create_pending(reference_plan, canonical_plan_hash(reference_plan))

    # First run with broken registry — fails the first job
    broken_loop = WorkerLoop(fake_repo, fake_state_store, _broken_registry(), "w-cont")
    await broken_loop.run_once()

    failed_record = await fake_repo.get("wf-fail-first")
    assert failed_record.status == PersistentWorkflowStatus.FAILED

    # Second run with real fake registry — succeeds the second job
    good_loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-cont")
    await good_loop.run_once()

    good_record = await fake_repo.get(reference_plan.workflow_id)
    assert good_record.status == PersistentWorkflowStatus.SUCCEEDED


async def test_error_message_is_concise(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
) -> None:
    plan = _make_minimal_plan("wf-fail-msg")
    await fake_repo.create_pending(plan, canonical_plan_hash(plan))

    loop = WorkerLoop(fake_repo, fake_state_store, _broken_registry(), "w-msg")
    await loop.run_once()

    record = await fake_repo.get("wf-fail-msg")
    assert record.error_message is not None
    # Must be a short string, not a full stack trace
    assert len(record.error_message) <= 500
    assert "\n" not in record.error_message


async def test_error_message_preserves_multiline_validation_detail(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
) -> None:
    class MultilineFailExecutor:
        async def execute(self, context: ExecutionContext) -> dict:
            raise RuntimeError(
                "1 validation error for Draft\n"
                "authored_screens.7.content.heading Field required"
            )

    registry = ExecutorRegistry()
    registry.register("speech.synthesize", MultilineFailExecutor())
    registry.register("audio.assemble", MultilineFailExecutor())
    plan = _make_minimal_plan("wf-fail-multiline")
    await fake_repo.create_pending(plan, canonical_plan_hash(plan))

    loop = WorkerLoop(fake_repo, fake_state_store, registry, "w-multiline")
    await loop.run_once()

    record = await fake_repo.get("wf-fail-multiline")
    assert record.error_message is not None
    assert "authored_screens.7.content.heading Field required" in record.error_message
    assert "\n" not in record.error_message
