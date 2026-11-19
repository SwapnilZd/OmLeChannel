"""Catalog API implementation of the existing assembly RLORepository protocol."""

from __future__ import annotations

from learning_pipeline.contracts import RLODocument
from learning_pipeline.repository import RLONotFoundError, RLOVersionNotFoundError

from .rlo import adapt_stored_rlo
from ..services.retrieval import CatalogClient, CatalogUnavailableError


class CatalogRLORepository:
    def __init__(self, catalog: CatalogClient) -> None:
        self.catalog = catalog
        self._cache: dict[tuple[str, str], RLODocument] = {}

    async def get(self, rlo_id: str, version: str) -> RLODocument:
        key = (rlo_id, version)
        if key in self._cache:
            return self._cache[key]
        try:
            versions = await self.catalog.get_versions(rlo_id)
        except CatalogUnavailableError as exc:
            # Catalog availability is an operational failure, not evidence
            # that the requested RLO is absent.
            raise CatalogUnavailableError(
                f"Catalog unavailable while loading RLO '{rlo_id}': {exc}"
            ) from exc
        if version not in {item.get("rlo_version") for item in versions}:
            raise RLOVersionNotFoundError(
                f"RLO '{rlo_id}' exists but not at exact version '{version}'"
            )
        raw = await self.catalog.get_exact(rlo_id, version)
        document = adapt_stored_rlo(raw)
        self._cache[key] = document
        return document
