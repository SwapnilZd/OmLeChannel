"""
End-to-end test: submit the reference podcast BuildPlan via the API, run one
worker cycle, verify the result in both the API and PostgreSQL.

Requires a live PostgreSQL instance.  Skipped when DATABASE_URL is not set.

To run locally (set DATABASE_URL to your workflow-postgres connection string):
    python -m pytest tests/end_to_end -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from learning_pipeline.api.app import create_app, get_repo
from learning_pipeline.config import build_fake_registry
from learning_pipeline.contracts import BuildPlan, WorkflowResult
from learning_pipeline.db.migrate import run_migrations
from learning_pipeline.db.repository import PostgresWorkflowRepository
from learning_pipeline.db.run_state import PostgresRunStateStore
from learning_pipeline.worker.main import WorkerLoop

_DATABASE_URL = os.getenv("DATABASE_URL", "")
_REFERENCE_PLAN_PATH = (
    Path(__file__).parent.parent.parent / "examples" / "reference" / "podcast" / "build_plan.json"
)
_REFERENCE_WID = "workflow-adkar-01-podcast-manager-l55"

pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="DATABASE_URL not set — end-to-end tests require PostgreSQL",
)


@pytest.fixture
async def db_pool() -> asyncpg.Pool:
    """Function-scoped pool to avoid event-loop mismatch with pytest-asyncio."""
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    pool = await asyncpg.create_pool(dsn=_DATABASE_URL, min_size=1, max_size=5)
    await run_migrations(pool)
    # Clean the reference workflow row before each test
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM workflow_run_state WHERE workflow_id = $1", _REFERENCE_WID
        )
        await conn.execute(
            "DELETE FROM workflow_runs WHERE workflow_id = $1", _REFERENCE_WID
        )
    yield pool
    await pool.close()


async def test_end_to_end_fake_podcast(db_pool: asyncpg.Pool) -> None:
    # ── 1. Build test app with the real pool ──────────────────────────────────
    test_app = create_app(pool=db_pool)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:

        # ── 2. Submit the reference podcast plan ──────────────────────────────
        plan_json = json.loads(_REFERENCE_PLAN_PATH.read_text())
        submit_response = await client.post("/workflow-runs", json={"plan": plan_json})
        assert submit_response.status_code == 202, submit_response.text
        submit_body = submit_response.json()
        wid = submit_body["workflow_id"]
        assert wid == _REFERENCE_WID
        assert submit_body["status"] == "pending"
        assert len(submit_body["plan_hash"]) == 64

        # ── 3. Verify API did NOT execute the plan ────────────────────────────
        status_response = await client.get(f"/workflow-runs/{wid}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "pending"

        # result endpoint must return 409 (not yet completed)
        result_before = await client.get(f"/workflow-runs/{wid}/result")
        assert result_before.status_code == 409

        # ── 4. Run one worker cycle ───────────────────────────────────────────
        repo = PostgresWorkflowRepository(db_pool)
        state_store = PostgresRunStateStore(db_pool)
        registry = build_fake_registry()
        worker = WorkerLoop(repo, state_store, registry, "worker-e2e-test")
        claimed = await worker.run_once()
        assert claimed is True

        # ── 5. Verify status changed to succeeded ─────────────────────────────
        status_response = await client.get(f"/workflow-runs/{wid}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "succeeded"

        # ── 6. Retrieve result via API ────────────────────────────────────────
        result_response = await client.get(f"/workflow-runs/{wid}/result")
        assert result_response.status_code == 200
        result_body = result_response.json()
        assert result_body["workflow_id"] == wid

        result = WorkflowResult.model_validate(result_body["result"])
        assert "speech-segment-1" in result.task_results
        assert "speech-segment-2" in result.task_results
        assert "assemble-podcast" in result.task_results

        # Deliverable must contain the assembly audio URI and costs URI
        assert len(result.deliverables) == 1
        assert "audio_uri" in result.deliverables[0].outputs
        assert "costs_uri" in result.deliverables[0].outputs

        # Primary artifact URIs must be fake (no real TTS calls made).
        # Other fields (usage, duration_seconds, media_type) are metadata, not URIs.
        for task_result in result.task_results.values():
            uri_value = task_result.outputs.get("audio_uri")
            if uri_value is not None:
                assert str(uri_value).startswith("fake://"), f"Expected fake URI, got {uri_value!r}"

        # ── 7. Verify PostgreSQL contains run snapshot ────────────────────────
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_run_state WHERE workflow_id = $1", wid
            )
        assert row is not None, "run snapshot must be persisted in PostgreSQL"

        from learning_pipeline.runtime.persistence import RunSnapshot, WorkflowStatus
        snapshot = RunSnapshot.model_validate_json(row["snapshot_json"])
        assert snapshot.workflow_status == WorkflowStatus.SUCCEEDED

        # ── 8. Verify plan and hash stored in PostgreSQL ──────────────────────
        async with db_pool.acquire() as conn:
            db_record = await conn.fetchrow(
                "SELECT plan_json, plan_hash, status FROM workflow_runs WHERE workflow_id = $1",
                wid,
            )
        assert db_record is not None
        assert db_record["status"] == "succeeded"
        assert len(db_record["plan_hash"]) == 64

        restored_plan = BuildPlan.model_validate_json(db_record["plan_json"])
        assert restored_plan.workflow_id == _REFERENCE_WID
