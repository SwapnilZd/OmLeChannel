"""
Shared fixtures for API tests.

InMemoryWorkflowRepository is the test double for PostgresWorkflowRepository.
It implements the same interface and is injected via FastAPI's dependency_overrides
so tests never need a running PostgreSQL instance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from learning_pipeline.api.app import create_app, get_repo
from learning_pipeline.contracts import BuildPlan, WorkflowResult
from learning_pipeline.db.repository import DuplicateWorkflowError, PersistentWorkflowStatus, WorkflowRecord
from learning_pipeline.validation import canonical_plan_hash

UTC = timezone.utc
_REFERENCE_PLAN_PATH = (
    Path(__file__).parent.parent.parent / "examples" / "reference" / "podcast" / "build_plan.json"
)


class InMemoryWorkflowRepository:
    """In-memory WorkflowRepository for API tests."""

    def __init__(self) -> None:
        self._store: dict[str, WorkflowRecord] = {}

    async def create_pending(self, plan: BuildPlan, plan_hash: str) -> None:
        wid = plan.workflow_id
        if wid in self._store:
            raise DuplicateWorkflowError(wid)
        now = datetime.now(UTC)
        self._store[wid] = WorkflowRecord(
            workflow_id=wid,
            plan_json=plan.model_dump_json(),
            plan_hash=plan_hash,
            status=PersistentWorkflowStatus.PENDING,
            result_json=None,
            error_message=None,
            created_at=now,
            updated_at=now,
            claimed_at=None,
            claimed_by=None,
            completed_at=None,
            required_task_types=tuple(sorted({task.task_type for task in plan.tasks})),
            modality=plan.modality.value,
        )

    async def get(self, workflow_id: str) -> WorkflowRecord | None:
        return self._store.get(workflow_id)

    async def claim_next_pending(
        self,
        worker_id: str,
        supported_task_types: frozenset[str] | None = None,
        supported_modalities: frozenset[str] | None = None,
    ) -> WorkflowRecord | None:
        for wid, record in self._store.items():
            compatible = supported_task_types is None or set(record.required_task_types).issubset(
                supported_task_types
            )
            modality_compatible = (
                supported_modalities is None or record.modality in supported_modalities
            )
            if record.status == PersistentWorkflowStatus.PENDING and compatible and modality_compatible:
                now = datetime.now(UTC)
                self._store[wid] = record.model_copy(update={
                    "status": PersistentWorkflowStatus.RUNNING,
                    "claimed_at": now,
                    "claimed_by": worker_id,
                    "updated_at": now,
                })
                return self._store[wid]
        return None

    async def mark_succeeded(self, workflow_id: str, result: WorkflowResult) -> None:
        record = self._store[workflow_id]
        now = datetime.now(UTC)
        self._store[workflow_id] = record.model_copy(update={
            "status": PersistentWorkflowStatus.SUCCEEDED,
            "result_json": result.model_dump_json(),
            "completed_at": now,
            "updated_at": now,
        })

    async def mark_failed(self, workflow_id: str, error_message: str) -> None:
        record = self._store[workflow_id]
        now = datetime.now(UTC)
        self._store[workflow_id] = record.model_copy(update={
            "status": PersistentWorkflowStatus.FAILED,
            "error_message": error_message,
            "completed_at": now,
            "updated_at": now,
        })

    async def heartbeat(self, workflow_id: str) -> None:
        record = self._store[workflow_id]
        if record.status == PersistentWorkflowStatus.RUNNING:
            self._store[workflow_id] = record.model_copy(update={
                "updated_at": datetime.now(UTC),
            })

    async def request_cancel(self, workflow_id: str) -> None:
        record = self._store[workflow_id]
        if record.status not in {
            PersistentWorkflowStatus.PENDING,
            PersistentWorkflowStatus.RUNNING,
        }:
            raise ValueError(f"workflow {workflow_id!r} is not cancelable")
        now = datetime.now(UTC)
        pending = record.status == PersistentWorkflowStatus.PENDING
        self._store[workflow_id] = record.model_copy(update={
            "status": (
                PersistentWorkflowStatus.CANCELED
                if pending else PersistentWorkflowStatus.CANCEL_REQUESTED
            ),
            "error_message": "Canceled by user.",
            "completed_at": now if pending else None,
            "updated_at": now,
        })

    async def mark_canceled(self, workflow_id: str) -> None:
        record = self._store[workflow_id]
        now = datetime.now(UTC)
        self._store[workflow_id] = record.model_copy(update={
            "status": PersistentWorkflowStatus.CANCELED,
            "error_message": "Canceled by user.",
            "completed_at": now,
            "updated_at": now,
        })


@pytest.fixture
def fake_repo() -> InMemoryWorkflowRepository:
    return InMemoryWorkflowRepository()


@pytest.fixture
async def client(fake_repo: InMemoryWorkflowRepository) -> AsyncClient:
    """
    Async HTTP client with an in-memory repository injected.

    DATABASE_URL is not required; the lifespan skips pool creation when it is
    absent, and get_repo is overridden before the first request.
    """
    test_app = create_app()
    test_app.dependency_overrides[get_repo] = lambda: fake_repo
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as c:
        yield c
    test_app.dependency_overrides.clear()


@pytest.fixture
def reference_plan() -> BuildPlan:
    return BuildPlan.model_validate_json(_REFERENCE_PLAN_PATH.read_text())


@pytest.fixture
def reference_plan_json(reference_plan: BuildPlan) -> dict:
    import json
    return json.loads(reference_plan.model_dump_json())
