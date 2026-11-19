"""
Shared fixtures for worker unit tests.

These tests use in-memory fakes for both the repository and the run-state store.
No PostgreSQL instance is required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import BuildPlan, WorkflowResult
from learning_pipeline.config import build_fake_registry
from learning_pipeline.runtime.persistence import RunSnapshot
from tests.api.conftest import InMemoryWorkflowRepository
from learning_pipeline.validation import canonical_plan_hash


class InMemoryRunStateStore:
    """Async run-state store backed by a plain dict."""

    def __init__(self) -> None:
        self._store: dict[str, RunSnapshot] = {}

    async def save(self, snapshot: RunSnapshot) -> None:
        self._store[snapshot.workflow_id] = snapshot

    async def load(self, workflow_id: str) -> RunSnapshot:
        return self._store[workflow_id]


_REFERENCE_PLAN_PATH = (
    Path(__file__).parent.parent.parent / "examples" / "reference" / "podcast" / "build_plan.json"
)


@pytest.fixture
def reference_plan() -> BuildPlan:
    return BuildPlan.model_validate_json(_REFERENCE_PLAN_PATH.read_text())


@pytest.fixture
def fake_repo() -> InMemoryWorkflowRepository:
    return InMemoryWorkflowRepository()


@pytest.fixture
def fake_state_store() -> InMemoryRunStateStore:
    return InMemoryRunStateStore()


@pytest.fixture
def fake_registry():
    return build_fake_registry()
