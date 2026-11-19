"""GET /workflow-runs/{id} — status endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from learning_pipeline.contracts import WorkflowResult
from learning_pipeline.db.repository import PersistentWorkflowStatus
from tests.api.conftest import InMemoryWorkflowRepository


async def test_pending_status_after_submit(
    client: AsyncClient,
    reference_plan_json: dict,
) -> None:
    await client.post("/workflow-runs", json={"plan": reference_plan_json})
    wid = "workflow-adkar-01-podcast-manager-l55"
    response = await client.get(f"/workflow-runs/{wid}")
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == wid
    assert body["status"] == "pending"
    assert body["error_message"] is None


async def test_unknown_workflow_returns_404(client: AsyncClient) -> None:
    response = await client.get("/workflow-runs/does-not-exist")
    assert response.status_code == 404


async def test_succeeded_status(
    client: AsyncClient,
    fake_repo: InMemoryWorkflowRepository,
    reference_plan_json: dict,
    reference_plan,
) -> None:
    await client.post("/workflow-runs", json={"plan": reference_plan_json})
    wid = reference_plan.workflow_id
    fake_result = WorkflowResult(
        workflow_id=wid,
        plan_hash="abc",
        task_results={},
        deliverables=(),
    )
    await fake_repo.mark_succeeded(wid, fake_result)

    response = await client.get(f"/workflow-runs/{wid}")
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


async def test_failed_status(
    client: AsyncClient,
    fake_repo: InMemoryWorkflowRepository,
    reference_plan_json: dict,
    reference_plan,
) -> None:
    await client.post("/workflow-runs", json={"plan": reference_plan_json})
    wid = reference_plan.workflow_id
    await fake_repo.mark_failed(wid, "executor crashed")

    response = await client.get(f"/workflow-runs/{wid}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "executor crashed"
