"""
PostgresWorkflowRepository integration tests.

All tests require PostgreSQL (skipped when DATABASE_URL is absent).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — PostgreSQL required",
)

import asyncio
from pathlib import Path

import asyncpg
import pytest

from learning_pipeline.contracts import BuildPlan, WorkflowResult
from learning_pipeline.db.repository import (
    DuplicateWorkflowError,
    PersistentWorkflowStatus,
    PostgresWorkflowRepository,
)
from learning_pipeline.validation import canonical_plan_hash

_REFERENCE_PLAN_PATH = (
    Path(__file__).parent.parent.parent / "examples" / "reference" / "podcast" / "build_plan.json"
)


@pytest.fixture
def reference_plan() -> BuildPlan:
    return BuildPlan.model_validate_json(_REFERENCE_PLAN_PATH.read_text())


@pytest.fixture
def repo(db_pool: asyncpg.Pool) -> PostgresWorkflowRepository:
    return PostgresWorkflowRepository(db_pool)


async def test_create_pending_persists_record(repo, reference_plan):
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)

    record = await repo.get(reference_plan.workflow_id)
    assert record is not None
    assert record.workflow_id == reference_plan.workflow_id
    assert record.plan_hash == ph
    assert record.status == PersistentWorkflowStatus.PENDING
    assert record.result_json is None
    assert record.error_message is None


async def test_plan_json_round_trips(repo, reference_plan):
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)

    record = await repo.get(reference_plan.workflow_id)
    restored = BuildPlan.model_validate_json(record.plan_json)
    assert restored == reference_plan


async def test_get_unknown_returns_none(repo):
    result = await repo.get("does-not-exist")
    assert result is None


async def test_duplicate_workflow_raises(repo, reference_plan):
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)
    with pytest.raises(DuplicateWorkflowError):
        await repo.create_pending(reference_plan, ph)


async def test_claim_changes_status_atomically(repo, reference_plan):
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)

    claimed = await repo.claim_next_pending("worker-1")
    assert claimed is not None
    assert claimed.status == PersistentWorkflowStatus.RUNNING
    assert claimed.claimed_by == "worker-1"
    assert claimed.claimed_at is not None

    record = await repo.get(reference_plan.workflow_id)
    assert record.status == PersistentWorkflowStatus.RUNNING


async def test_empty_queue_returns_none(repo):
    result = await repo.claim_next_pending("worker-1")
    assert result is None


async def test_two_concurrent_workers_claim_once(repo, reference_plan, db_pool):
    """Both workers race to claim the same pending row; exactly one succeeds."""
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)

    repo2 = PostgresWorkflowRepository(db_pool)
    results = await asyncio.gather(
        repo.claim_next_pending("worker-A"),
        repo2.claim_next_pending("worker-B"),
    )
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1, "exactly one worker must claim the pending row"


async def test_mark_succeeded_persists_result(repo, reference_plan):
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)
    await repo.claim_next_pending("w1")

    fake_result = WorkflowResult(
        workflow_id=reference_plan.workflow_id,
        plan_hash=ph,
        task_results={},
        deliverables=(),
    )
    await repo.mark_succeeded(reference_plan.workflow_id, fake_result)

    record = await repo.get(reference_plan.workflow_id)
    assert record.status == PersistentWorkflowStatus.SUCCEEDED
    assert record.result_json is not None
    restored = WorkflowResult.model_validate_json(record.result_json)
    assert restored.workflow_id == reference_plan.workflow_id
    assert record.completed_at is not None


async def test_mark_failed_persists_error(repo, reference_plan):
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)
    await repo.claim_next_pending("w1")

    await repo.mark_failed(reference_plan.workflow_id, "executor exploded")

    record = await repo.get(reference_plan.workflow_id)
    assert record.status == PersistentWorkflowStatus.FAILED
    assert record.error_message == "executor exploded"
    assert record.completed_at is not None
