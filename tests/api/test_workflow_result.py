"""GET /workflow-runs/{id}/result — result endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from learning_pipeline.contracts import TaskResult, WorkflowResult
from tests.api.conftest import InMemoryWorkflowRepository


async def test_result_not_found_returns_404(client: AsyncClient) -> None:
    response = await client.get("/workflow-runs/ghost/result")
    assert response.status_code == 404


async def test_result_while_pending_returns_409(
    client: AsyncClient,
    reference_plan_json: dict,
    reference_plan,
) -> None:
    await client.post("/workflow-runs", json={"plan": reference_plan_json})
    wid = reference_plan.workflow_id
    response = await client.get(f"/workflow-runs/{wid}/result")
    assert response.status_code == 409
    assert "pending" in response.json()["detail"]


async def test_result_while_failed_returns_409(
    client: AsyncClient,
    fake_repo: InMemoryWorkflowRepository,
    reference_plan_json: dict,
    reference_plan,
) -> None:
    await client.post("/workflow-runs", json={"plan": reference_plan_json})
    wid = reference_plan.workflow_id
    await fake_repo.mark_failed(wid, "boom")
    response = await client.get(f"/workflow-runs/{wid}/result")
    assert response.status_code == 409
    assert "failed" in response.json()["detail"]


async def test_succeeded_result_returns_200(
    client: AsyncClient,
    fake_repo: InMemoryWorkflowRepository,
    reference_plan_json: dict,
    reference_plan,
) -> None:
    await client.post("/workflow-runs", json={"plan": reference_plan_json})
    wid = reference_plan.workflow_id

    fake_result = WorkflowResult(
        workflow_id=wid,
        plan_hash="deadbeef" * 8,
        task_results={
            "speech-segment-1": TaskResult(
                task_id="speech-segment-1",
                outputs={"audio_file": "fake://audio/speech-segment-1.wav"},
                attempts=1,
            ),
        },
        deliverables=(
            TaskResult(
                task_id="speech-segment-1",
                outputs={"audio_file": "fake://audio/speech-segment-1.wav"},
                attempts=1,
            ),
        ),
    )
    await fake_repo.mark_succeeded(wid, fake_result)

    response = await client.get(f"/workflow-runs/{wid}/result")
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == wid
    assert "task_results" in body["result"]
    assert "speech-segment-1" in body["result"]["task_results"]
