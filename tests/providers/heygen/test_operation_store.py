"""Tests for FileExternalOperationStore — checkpoint persistence and retry safety."""
from __future__ import annotations

import json

import pytest

from learning_pipeline.providers.heygen.models import ProviderVideoStatus
from learning_pipeline.providers.heygen.operation_store import (
    ArtifactExternalOperationStore,
    ExternalOperationCheckpoint,
    FileExternalOperationStore,
    make_checkpoint,
    utc_now_iso,
)
from learning_pipeline.runtime.artifact_store import FileArtifactStore


def _make(tmp_path) -> FileExternalOperationStore:
    return FileExternalOperationStore(tmp_path / "ops")


def _checkpoint(
    wf_id: str = "wf-1",
    task_id: str = "task-1",
    op_id: str = "vid-abc",
    status: str = "pending",
    input_hash: str = "hash-xyz",
) -> ExternalOperationCheckpoint:
    return make_checkpoint(
        workflow_id=wf_id,
        task_id=task_id,
        operation_id=op_id,
        input_hash=input_hash,
        status=status,
    )


@pytest.mark.asyncio
async def test_get_returns_none_when_absent(tmp_path):
    store = _make(tmp_path)
    result = await store.get("wf-missing", "task-missing")
    assert result is None


@pytest.mark.asyncio
async def test_save_and_get_roundtrip(tmp_path):
    store = _make(tmp_path)
    cp = _checkpoint()
    await store.save(cp)
    loaded = await store.get("wf-1", "task-1")
    assert loaded is not None
    assert loaded.operation_id == "vid-abc"
    assert loaded.status == "pending"
    assert loaded.provider == "heygen"


@pytest.mark.asyncio
async def test_save_updates_status(tmp_path):
    store = _make(tmp_path)
    cp = _checkpoint(status="pending")
    await store.save(cp)

    updated = ExternalOperationCheckpoint.model_validate(
        {**cp.model_dump(), "status": "completed"}
    )
    await store.save(updated)

    loaded = await store.get("wf-1", "task-1")
    assert loaded.status == "completed"


@pytest.mark.asyncio
async def test_save_persists_operation_id_before_polling(tmp_path):
    store = _make(tmp_path)
    cp = _checkpoint(op_id="vid-brand-new")
    await store.save(cp)  # persisted immediately after submission

    loaded = await store.get("wf-1", "task-1")
    assert loaded.operation_id == "vid-brand-new"


@pytest.mark.asyncio
async def test_provider_metadata_preserved(tmp_path):
    store = _make(tmp_path)
    cp = _checkpoint()
    cp_with_meta = ExternalOperationCheckpoint.model_validate(
        {**cp.model_dump(), "provider_metadata": {"upload_count": 3}}
    )
    await store.save(cp_with_meta)
    loaded = await store.get("wf-1", "task-1")
    assert loaded.provider_metadata["upload_count"] == 3


@pytest.mark.asyncio
async def test_different_tasks_stored_independently(tmp_path):
    store = _make(tmp_path)
    await store.save(_checkpoint(task_id="t1", op_id="vid-1"))
    await store.save(_checkpoint(task_id="t2", op_id="vid-2"))
    t1 = await store.get("wf-1", "t1")
    t2 = await store.get("wf-1", "t2")
    assert t1.operation_id == "vid-1"
    assert t2.operation_id == "vid-2"


@pytest.mark.asyncio
async def test_checkpoint_file_is_valid_json(tmp_path):
    store = _make(tmp_path)
    cp = _checkpoint()
    await store.save(cp)
    checkpoint_file = tmp_path / "ops" / "wf-1" / "task-1.json"
    assert checkpoint_file.exists()
    data = json.loads(checkpoint_file.read_text())
    assert data["operation_id"] == "vid-abc"


@pytest.mark.asyncio
async def test_malformed_checkpoint_file_returns_none(tmp_path):
    store = _make(tmp_path)
    checkpoint_dir = tmp_path / "ops" / "wf-1"
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "task-1.json").write_text("not valid json")
    result = await store.get("wf-1", "task-1")
    assert result is None


@pytest.mark.asyncio
async def test_artifact_checkpoint_store_roundtrip(tmp_path):
    store = ArtifactExternalOperationStore(FileArtifactStore(tmp_path / "artifacts"))

    await store.save(_checkpoint(op_id="vid-minio-ready"))

    loaded = await store.get("wf-1", "task-1")
    assert loaded is not None
    assert loaded.operation_id == "vid-minio-ready"
