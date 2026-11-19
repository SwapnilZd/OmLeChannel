from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Iterable, Protocol

from learning_pipeline.contracts import RLODocument


class RLONotFoundError(KeyError):
    pass


class RLOVersionNotFoundError(KeyError):
    pass


class InvalidContentReferenceError(ValueError):
    pass


class RLORepository(Protocol):
    async def get(self, rlo_id: str, version: str) -> RLODocument: ...


class InMemoryRLORepository:
    def __init__(self, documents: Iterable[RLODocument]) -> None:
        self._docs: dict[tuple[str, str], RLODocument] = {}
        self._ids: set[str] = set()
        for doc in documents:
            self._docs[(doc.id, doc.version)] = doc
            self._ids.add(doc.id)

    async def get(self, rlo_id: str, version: str) -> RLODocument:
        await asyncio.sleep(0)
        key = (rlo_id, version)
        if key in self._docs:
            return self._docs[key]
        if rlo_id in self._ids:
            raise RLOVersionNotFoundError(
                f"RLO '{rlo_id}' exists but not at version '{version}'"
            )
        raise RLONotFoundError(f"RLO '{rlo_id}' not found")


class FileRLORepository:
    """Load RLO documents from JSON files on the local filesystem.

    File naming convention: ``{rlo_id}_v{version}.json``

    For example, RLO ``rlo-adkar-01`` at version ``1.1.0`` must be stored as:
        ``{root}/rlo-adkar-01_v1.1.0.json``

    Raises:
        RLONotFoundError:        No file found for *rlo_id* at any version.
        RLOVersionNotFoundError: A file exists for *rlo_id* but not at *version*.
        ValueError:              The file content cannot be parsed as RLODocument.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    async def get(self, rlo_id: str, version: str) -> RLODocument:
        await asyncio.sleep(0)
        target = self._root / f"{rlo_id}_v{version}.json"
        if not target.exists():
            # Check if any version exists for this RLO to improve the error message.
            any_exist = any(self._root.glob(f"{rlo_id}_v*.json"))
            if any_exist:
                raise RLOVersionNotFoundError(
                    f"RLO '{rlo_id}' exists in {self._root} but not at version '{version}'"
                )
            raise RLONotFoundError(
                f"RLO '{rlo_id}' not found in {self._root} "
                f"(expected '{rlo_id}_v{version}.json')"
            )
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return RLODocument.model_validate(data)
        except Exception as exc:
            raise ValueError(
                f"Cannot parse RLO document at {target}: {exc}"
            ) from exc
