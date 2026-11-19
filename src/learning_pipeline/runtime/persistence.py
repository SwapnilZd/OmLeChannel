import os
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from learning_pipeline.contracts import BuildPlan, FrozenModel, TaskResult


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunSnapshot(FrozenModel):
    workflow_id: str
    plan_hash: str
    workflow_status: WorkflowStatus = WorkflowStatus.PENDING
    statuses: dict[str, TaskStatus]
    results: dict[str, TaskResult] = Field(default_factory=dict)
    failure: str | None = None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


class FilePlanStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, plan: BuildPlan) -> None:
        _atomic_write(self._root / plan.workflow_id / "plan.json", plan.model_dump_json(indent=2))

    def load(self, workflow_id: str) -> BuildPlan:
        path = self._root / workflow_id / "plan.json"
        return BuildPlan.model_validate_json(path.read_text(encoding="utf-8"))


class FileRunStateStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, snapshot: RunSnapshot) -> None:
        _atomic_write(
            self._root / snapshot.workflow_id / "run-state.json",
            snapshot.model_dump_json(indent=2),
        )

    def load(self, workflow_id: str) -> RunSnapshot:
        path = self._root / workflow_id / "run-state.json"
        return RunSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
