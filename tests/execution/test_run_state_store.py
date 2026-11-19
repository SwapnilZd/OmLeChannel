import pytest

from learning_pipeline.contracts import TaskResult
from learning_pipeline.runtime.persistence import FileRunStateStore, RunSnapshot, TaskStatus, WorkflowStatus


def _snapshot(**overrides) -> RunSnapshot:
    defaults: dict = {
        "workflow_id": "wf-test",
        "plan_hash": "abc123def456",
        "workflow_status": WorkflowStatus.SUCCEEDED,
        "statuses": {"task-a": TaskStatus.SUCCEEDED},
        "results": {
            "task-a": TaskResult(
                task_id="task-a",
                outputs={"audio_file": "fake://audio/task-a.wav"},
                attempts=1,
            )
        },
    }
    defaults.update(overrides)
    return RunSnapshot(**defaults)


def test_save_and_load_roundtrip(tmp_path):
    store = FileRunStateStore(tmp_path)
    snapshot = _snapshot()
    store.save(snapshot)
    assert store.load("wf-test") == snapshot


def test_save_creates_missing_parent_directories(tmp_path):
    store = FileRunStateStore(tmp_path / "deep" / "nested" / "dir")
    store.save(_snapshot())
    loaded = store.load("wf-test")
    assert loaded.workflow_id == "wf-test"


def test_overwrite_stores_latest_snapshot(tmp_path):
    store = FileRunStateStore(tmp_path)
    store.save(_snapshot(statuses={"task-a": TaskStatus.RUNNING}))
    store.save(_snapshot(statuses={"task-a": TaskStatus.SUCCEEDED}))
    loaded = store.load("wf-test")
    assert loaded.statuses["task-a"] == TaskStatus.SUCCEEDED


def test_load_nonexistent_workflow_raises(tmp_path):
    store = FileRunStateStore(tmp_path)
    with pytest.raises(Exception):
        store.load("does-not-exist")


def test_failure_message_roundtrips(tmp_path):
    store = FileRunStateStore(tmp_path)
    snapshot = _snapshot(
        workflow_status=WorkflowStatus.FAILED,
        statuses={"task-a": TaskStatus.FAILED},
        results={},
        failure="executor crashed",
    )
    store.save(snapshot)
    loaded = store.load("wf-test")
    assert loaded.failure == "executor crashed"
    assert loaded.workflow_status == WorkflowStatus.FAILED


def test_workflow_status_pending_roundtrips(tmp_path):
    store = FileRunStateStore(tmp_path)
    snapshot = _snapshot(
        workflow_status=WorkflowStatus.PENDING,
        statuses={"task-a": TaskStatus.PENDING},
        results={},
    )
    store.save(snapshot)
    loaded = store.load("wf-test")
    assert loaded.workflow_status == WorkflowStatus.PENDING


def test_multiple_workflows_are_stored_independently(tmp_path):
    store = FileRunStateStore(tmp_path)
    store.save(_snapshot(workflow_id="wf-a", plan_hash="hash-a"))
    store.save(_snapshot(workflow_id="wf-b", plan_hash="hash-b"))
    assert store.load("wf-a").plan_hash == "hash-a"
    assert store.load("wf-b").plan_hash == "hash-b"
