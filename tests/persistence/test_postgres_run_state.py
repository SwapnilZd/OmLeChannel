"""
PostgresRunStateStore integration tests.

All tests require PostgreSQL (skipped when DATABASE_URL is absent).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — PostgreSQL required",
)

from pathlib import Path

import asyncpg
import pytest

from learning_pipeline.contracts import BuildPlan, TaskResult
from learning_pipeline.db.repository import PostgresWorkflowRepository
from learning_pipeline.db.run_state import PostgresRunStateStore
from learning_pipeline.runtime.persistence import RunSnapshot, TaskStatus, WorkflowStatus
from learning_pipeline.validation import canonical_plan_hash

_REFERENCE_PLAN_PATH = (
    Path(__file__).parent.parent.parent / "examples" / "reference" / "podcast" / "build_plan.json"
)


@pytest.fixture
def reference_plan() -> BuildPlan:
    return BuildPlan.model_validate_json(_REFERENCE_PLAN_PATH.read_text())


@pytest.fixture
def state_store(db_pool: asyncpg.Pool) -> PostgresRunStateStore:
    return PostgresRunStateStore(db_pool)


@pytest.fixture
async def persisted_workflow(db_pool, reference_plan):
    """Persist the reference plan in workflow_runs before inserting run state."""
    repo = PostgresWorkflowRepository(db_pool)
    ph = canonical_plan_hash(reference_plan)
    await repo.create_pending(reference_plan, ph)
    return reference_plan


async def test_snapshot_round_trips(state_store, persisted_workflow):
    plan = persisted_workflow
    ph = canonical_plan_hash(plan)
    snapshot = RunSnapshot(
        workflow_id=plan.workflow_id,
        plan_hash=ph,
        workflow_status=WorkflowStatus.RUNNING,
        statuses={"speech-segment-1": TaskStatus.RUNNING},
        results={},
    )
    await state_store.save(snapshot)
    loaded = await state_store.load(plan.workflow_id)
    assert loaded == snapshot


async def test_save_replaces_previous_snapshot(state_store, persisted_workflow):
    plan = persisted_workflow
    ph = canonical_plan_hash(plan)

    s1 = RunSnapshot(
        workflow_id=plan.workflow_id,
        plan_hash=ph,
        workflow_status=WorkflowStatus.RUNNING,
        statuses={"speech-segment-1": TaskStatus.RUNNING},
        results={},
    )
    await state_store.save(s1)

    s2 = RunSnapshot(
        workflow_id=plan.workflow_id,
        plan_hash=ph,
        workflow_status=WorkflowStatus.SUCCEEDED,
        statuses={"speech-segment-1": TaskStatus.SUCCEEDED},
        results={
            "speech-segment-1": TaskResult(
                task_id="speech-segment-1",
                outputs={"audio_file": "fake://audio/speech-segment-1.wav"},
                attempts=1,
            )
        },
    )
    await state_store.save(s2)

    loaded = await state_store.load(plan.workflow_id)
    assert loaded.workflow_status == WorkflowStatus.SUCCEEDED
    assert "speech-segment-1" in loaded.results


async def test_load_missing_raises_key_error(state_store):
    with pytest.raises(KeyError):
        await state_store.load("nonexistent-workflow")
