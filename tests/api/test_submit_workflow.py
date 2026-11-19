"""POST /workflow-runs — submit workflow tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from learning_pipeline.contracts import BuildPlan, LiteralInput, Modality, TaskSpec
from learning_pipeline.validation import canonical_plan_hash


async def test_valid_plan_returns_202(client: AsyncClient, reference_plan_json: dict) -> None:
    response = await client.post("/workflow-runs", json={"plan": reference_plan_json})
    assert response.status_code == 202
    body = response.json()
    assert body["workflow_id"] == "workflow-adkar-01-podcast-manager-l55"
    assert body["status"] == "pending"
    assert len(body["plan_hash"]) == 64  # SHA-256 hex


async def test_plan_hash_is_canonical(client: AsyncClient, reference_plan_json: dict, reference_plan: BuildPlan) -> None:
    response = await client.post("/workflow-runs", json={"plan": reference_plan_json})
    assert response.status_code == 202
    expected_hash = canonical_plan_hash(reference_plan)
    assert response.json()["plan_hash"] == expected_hash


async def test_invalid_contract_returns_422(client: AsyncClient) -> None:
    # Missing required fields — Pydantic returns 422
    response = await client.post("/workflow-runs", json={"plan": {"workflow_id": "bad"}})
    assert response.status_code == 422


async def test_not_json_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/workflow-runs",
        content=b"not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


async def test_unsupported_task_type_returns_400(client: AsyncClient) -> None:
    plan = BuildPlan(
        workflow_id="wf-bad-type",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="t1",
                task_type="unknown.task.type",
                output_keys=("out",),
            ),
        ),
        deliverable_task_ids=("t1",),
    )
    import json
    response = await client.post(
        "/workflow-runs", json={"plan": json.loads(plan.model_dump_json())}
    )
    assert response.status_code == 400
    assert "unsupported task type" in response.json()["detail"].lower()


async def test_dag_cycle_returns_400(client: AsyncClient) -> None:
    # Self-dependency — passes Pydantic, fails validate_build_plan
    plan = BuildPlan(
        workflow_id="wf-cycle",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=(
            TaskSpec(
                id="t1",
                task_type="speech.synthesize",
                depends_on=("t1",),
                output_keys=("audio_file",),
            ),
        ),
        deliverable_task_ids=("t1",),
    )
    import json
    response = await client.post(
        "/workflow-runs", json={"plan": json.loads(plan.model_dump_json())}
    )
    assert response.status_code == 400


async def test_duplicate_workflow_id_returns_409(client: AsyncClient, reference_plan_json: dict) -> None:
    r1 = await client.post("/workflow-runs", json={"plan": reference_plan_json})
    assert r1.status_code == 202
    r2 = await client.post("/workflow-runs", json={"plan": reference_plan_json})
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"]
