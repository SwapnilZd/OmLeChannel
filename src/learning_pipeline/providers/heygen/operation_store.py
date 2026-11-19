"""Durable external-operation checkpoint store.

HeyGen video generation is a long-running external operation.  If the worker
restarts after submitting a video but before downloading it, this store lets
the executor resume polling the same video_id instead of submitting a new job.

Each checkpoint is stored as a JSON file at:
    {store_root}/{workflow_id}/{task_id}.json

Atomic writes follow the same pattern as FileArtifactStore.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.runtime.artifact_store import (
    ArtifactNotFoundError,
    ArtifactReadError,
    ArtifactStore,
)

logger = logging.getLogger(__name__)


class ExternalOperationCheckpoint(FrozenModel):
    """Persistent record for one submitted provider operation."""

    workflow_id: str
    task_id: str
    provider: str
    operation_id: str       # HeyGen video_id
    input_hash: str         # stable hash of AvatarVideoRenderInput
    status: str             # mirrors ProviderVideoStatus values
    submitted_at: str       # ISO-8601 UTC
    last_checked_at: str | None = None
    provider_metadata: dict[str, Any] = {}


@runtime_checkable
class ExternalOperationStore(Protocol):
    """Protocol for persisting external-operation checkpoints."""

    async def get(
        self,
        workflow_id: str,
        task_id: str,
    ) -> ExternalOperationCheckpoint | None: ...

    async def save(
        self,
        checkpoint: ExternalOperationCheckpoint,
    ) -> None: ...


class FileExternalOperationStore:
    """File-backed ExternalOperationStore.

    Parameters
    ----------
    store_root:
        Root directory.  Checkpoints are stored at
        ``{store_root}/{workflow_id}/{task_id}.json``.
    """

    def __init__(self, store_root: Path) -> None:
        self._root = Path(store_root)

    async def get(
        self,
        workflow_id: str,
        task_id: str,
    ) -> ExternalOperationCheckpoint | None:
        path = self._checkpoint_path(workflow_id, task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ExternalOperationCheckpoint.model_validate(data)
        except Exception as exc:
            logger.warning(
                "ExternalOperationStore: malformed checkpoint at %s — ignoring: %s",
                path, exc,
            )
            return None

    async def save(self, checkpoint: ExternalOperationCheckpoint) -> None:
        path = self._checkpoint_path(checkpoint.workflow_id, checkpoint.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
        logger.debug(
            "ExternalOperationStore: saved %s/%s status=%s",
            checkpoint.workflow_id,
            checkpoint.task_id,
            checkpoint.status,
        )

    def _checkpoint_path(self, workflow_id: str, task_id: str) -> Path:
        return self._root / workflow_id / f"{task_id}.json"


class ArtifactExternalOperationStore:
    """Persist provider checkpoints in the configured artifact store."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._store = artifact_store

    async def get(
        self,
        workflow_id: str,
        task_id: str,
    ) -> ExternalOperationCheckpoint | None:
        uri = f"artifact://heygen-operations/{workflow_id}/{task_id}.json"
        try:
            data = await self._store.get_bytes(uri)
            return ExternalOperationCheckpoint.model_validate_json(data)
        except (ArtifactNotFoundError, KeyError):
            return None
        except (ArtifactReadError, ValueError) as exc:
            logger.warning(
                "ExternalOperationStore: malformed checkpoint %s/%s — ignoring: %s",
                workflow_id,
                task_id,
                exc,
            )
            return None

    async def save(self, checkpoint: ExternalOperationCheckpoint) -> None:
        await self._store.put_bytes(
            f"heygen-operations/{checkpoint.workflow_id}",
            f"{checkpoint.task_id}.json",
            checkpoint.model_dump_json(indent=2).encode("utf-8"),
            "application/json",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_checkpoint(
    *,
    workflow_id: str,
    task_id: str,
    operation_id: str,
    input_hash: str,
    status: str,
) -> ExternalOperationCheckpoint:
    return ExternalOperationCheckpoint(
        workflow_id=workflow_id,
        task_id=task_id,
        provider="heygen",
        operation_id=operation_id,
        input_hash=input_hash,
        status=status,
        submitted_at=utc_now_iso(),
    )
