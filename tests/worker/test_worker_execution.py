"""Worker invokes DAGRunner with fake executors and marks workflows succeeded."""

from __future__ import annotations

import asyncio

import pytest

from learning_pipeline.contracts import BuildPlan, LiteralInput, Modality, TaskSpec, WorkflowResult
from learning_pipeline.db.repository import PersistentWorkflowStatus
from learning_pipeline.runtime.execution import ExecutionContext, ExecutorRegistry
from learning_pipeline.worker.main import WorkerLoop
from learning_pipeline.validation import canonical_plan_hash
from tests.api.conftest import InMemoryWorkflowRepository
from tests.worker.conftest import InMemoryRunStateStore


async def test_worker_marks_workflow_succeeded(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    ph = canonical_plan_hash(reference_plan)
    await fake_repo.create_pending(reference_plan, ph)

    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-exec")
    await loop.run_once()

    record = await fake_repo.get(reference_plan.workflow_id)
    assert record.status == PersistentWorkflowStatus.SUCCEEDED


async def test_worker_persists_result_json(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    ph = canonical_plan_hash(reference_plan)
    await fake_repo.create_pending(reference_plan, ph)

    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-exec")
    await loop.run_once()

    record = await fake_repo.get(reference_plan.workflow_id)
    assert record.result_json is not None
    result = WorkflowResult.model_validate_json(record.result_json)
    assert result.workflow_id == reference_plan.workflow_id
    assert len(result.deliverables) == 1
    assert "audio_uri" in result.deliverables[0].outputs


async def test_worker_uses_fake_executors_no_network(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    """Fake URIs confirm no real TTS was invoked."""
    ph = canonical_plan_hash(reference_plan)
    await fake_repo.create_pending(reference_plan, ph)

    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-exec")
    await loop.run_once()

    record = await fake_repo.get(reference_plan.workflow_id)
    result = WorkflowResult.model_validate_json(record.result_json)

    # Verify the primary artifact URI keys use fake:// — other fields (usage,
    # duration_seconds, media_type) are non-URI metadata and are excluded.
    for task_result in result.task_results.values():
        # speech tasks → audio_uri; assembly task → audio_uri (and costs_uri)
        uri_value = task_result.outputs.get("audio_uri")
        if uri_value is not None:
            assert str(uri_value).startswith("fake://"), f"Expected fake URI, got {uri_value!r}"


async def test_run_state_persisted_by_worker(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    ph = canonical_plan_hash(reference_plan)
    await fake_repo.create_pending(reference_plan, ph)

    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-exec")
    await loop.run_once()

    snapshot = await fake_state_store.load(reference_plan.workflow_id)
    from learning_pipeline.runtime.persistence import WorkflowStatus
    assert snapshot.workflow_status == WorkflowStatus.SUCCEEDED


async def test_worker_cooperatively_cancels_running_workflow(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
) -> None:
    started = asyncio.Event()
    canceled = asyncio.Event()

    class SlowExecutor:
        async def execute(self, context: ExecutionContext) -> dict:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                canceled.set()
                raise

    plan = BuildPlan(
        workflow_id="wf-cancel-running",
        source_plan_id="sp-cancel",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="slow",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="scene")},
                output_keys=("audio_file",),
                max_attempts=1,
            ),
        ),
        deliverable_task_ids=("slow",),
    )
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", SlowExecutor())
    await fake_repo.create_pending(plan, canonical_plan_hash(plan))
    loop = WorkerLoop(
        fake_repo,
        fake_state_store,
        registry,
        "w-cancel",
        poll_interval=0.01,
    )

    running = asyncio.create_task(loop.run_once())
    await started.wait()
    await fake_repo.request_cancel(plan.workflow_id)
    await asyncio.wait_for(running, timeout=1)

    record = await fake_repo.get(plan.workflow_id)
    assert record is not None
    assert record.status == PersistentWorkflowStatus.CANCELED
    assert canceled.is_set()


async def test_worker_heartbeats_while_executor_is_running(
    fake_state_store: InMemoryRunStateStore,
) -> None:
    class TrackingRepository(InMemoryWorkflowRepository):
        def __init__(self) -> None:
            super().__init__()
            self.heartbeat_count = 0

        async def heartbeat(self, workflow_id: str) -> None:
            self.heartbeat_count += 1
            await super().heartbeat(workflow_id)

    class SlowExecutor:
        async def execute(self, context: ExecutionContext) -> dict:
            await asyncio.sleep(0.05)
            return {"audio_file": "fake://audio.mp3"}

    repo = TrackingRepository()
    plan = BuildPlan(
        workflow_id="wf-heartbeat",
        source_plan_id="sp-heartbeat",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="slow",
                task_type="speech.synthesize",
                inputs={"scene_id": LiteralInput(value="scene")},
                output_keys=("audio_file",),
                max_attempts=1,
            ),
        ),
        deliverable_task_ids=("slow",),
    )
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", SlowExecutor())
    await repo.create_pending(plan, canonical_plan_hash(plan))

    loop = WorkerLoop(
        repo,
        fake_state_store,
        registry,
        "w-heartbeat",
        poll_interval=0.005,
        heartbeat_interval_seconds=0.01,
    )
    await loop.run_once()

    assert repo.heartbeat_count >= 1
    record = await repo.get(plan.workflow_id)
    assert record is not None
    assert record.status == PersistentWorkflowStatus.SUCCEEDED
