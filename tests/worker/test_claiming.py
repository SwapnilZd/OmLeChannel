"""Worker claims pending work from the repository."""

from __future__ import annotations

import pytest

from learning_pipeline.db.repository import PersistentWorkflowStatus
from learning_pipeline.worker.main import WorkerLoop
from learning_pipeline.validation import canonical_plan_hash
from tests.api.conftest import InMemoryWorkflowRepository
from tests.worker.conftest import InMemoryRunStateStore
from learning_pipeline.runtime.execution import ExecutorRegistry
from learning_pipeline.worker.main import _worker_profile


def test_worker_profile_prefers_explicit_profile(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_PROFILE", "elearning-real-manim")
    monkeypatch.setenv("PIPELINE_MODE", "reference")
    assert _worker_profile() == "elearning-real-manim"


def test_worker_profile_preserves_real_pipeline_mode_compatibility(monkeypatch) -> None:
    monkeypatch.delenv("WORKER_PROFILE", raising=False)
    monkeypatch.setenv("PIPELINE_MODE", "real")
    assert _worker_profile() == "podcast-real"


def test_worker_profile_defaults_to_reference(monkeypatch) -> None:
    monkeypatch.delenv("WORKER_PROFILE", raising=False)
    monkeypatch.delenv("PIPELINE_MODE", raising=False)
    assert _worker_profile() == "reference"


async def test_worker_claims_pending_workflow(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    ph = canonical_plan_hash(reference_plan)
    await fake_repo.create_pending(reference_plan, ph)

    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-1")
    claimed = await loop.run_once()

    assert claimed is True


async def test_empty_queue_returns_false(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
) -> None:
    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-1")
    claimed = await loop.run_once()
    assert claimed is False


async def test_worker_does_not_claim_same_workflow_twice(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    ph = canonical_plan_hash(reference_plan)
    await fake_repo.create_pending(reference_plan, ph)

    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "w-1")
    await loop.run_once()  # consumes the one job

    # queue is now empty (succeeded or failed)
    claimed_again = await loop.run_once()
    assert claimed_again is False


async def test_worker_id_recorded_on_claim(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    ph = canonical_plan_hash(reference_plan)
    await fake_repo.create_pending(reference_plan, ph)

    loop = WorkerLoop(fake_repo, fake_state_store, fake_registry, "distinctive-worker-42")
    await loop.run_once()

    # After execution the status moved to succeeded/failed, claimed_by should be set
    record = await fake_repo.get(reference_plan.workflow_id)
    assert record.claimed_by == "distinctive-worker-42"


async def test_worker_does_not_claim_plan_with_unsupported_task_types(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    reference_plan,
) -> None:
    await fake_repo.create_pending(reference_plan, canonical_plan_hash(reference_plan))
    incompatible_registry = ExecutorRegistry()
    loop = WorkerLoop(
        fake_repo,
        fake_state_store,
        incompatible_registry,
        "incompatible-worker",
    )

    assert await loop.run_once() is False
    record = await fake_repo.get(reference_plan.workflow_id)
    assert record.status == PersistentWorkflowStatus.PENDING


async def test_worker_does_not_claim_plan_from_another_modality(
    fake_repo: InMemoryWorkflowRepository,
    fake_state_store: InMemoryRunStateStore,
    fake_registry,
    reference_plan,
) -> None:
    await fake_repo.create_pending(reference_plan, canonical_plan_hash(reference_plan))
    loop = WorkerLoop(
        fake_repo,
        fake_state_store,
        fake_registry,
        "video-only-worker",
        supported_modalities=frozenset({"video"}),
    )

    assert await loop.run_once() is False
