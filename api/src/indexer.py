"""Version-aware RLO embeddings and compact filtered search in Qdrant."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone

from openai import OpenAI
from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    load_lite_llm_settings,
)
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from rlo_schema import RLO

from .rlo_schema import RloSearchFilters

COLLECTION = "rlos"
INDEX_REVISION = "rlo-index-v4"
VECTOR_SIZE = 1536
# This is an OpenAI-compatible LiteLLM model alias, not a direct provider model.
EMBED_MODEL = ModelAlias.RLO_CATALOG_EMBEDDING

_KEYWORD_INDEX_FIELDS = (
    "rlo_id",
    "rlo_version",
    "language",
    "locale",
    "status",
    "level",
    "role_tags",
    "industry_tags",
    "service_line_tags",
    "competency_tags",
    "regulatory_tags",
)


def _stable_uuid(rlo_id: str, rlo_version: str) -> str:
    digest = hashlib.md5(f"{rlo_id}:{rlo_version}".encode()).hexdigest()
    return str(uuid.UUID(digest))


def _legacy_stable_uuid(rlo_id: str) -> str:
    """Point ID used by the pre-versioned index."""
    return str(uuid.UUID(hashlib.md5(rlo_id.encode()).hexdigest()))


def _build_embed_text(rlo: RLO) -> str:
    """Represent subject matter and teachable outcomes, not cohort metadata."""
    parts = [rlo.title, rlo.topic, rlo.domain]
    if rlo.terminal_objective:
        parts.append(rlo.terminal_objective)
    parts.append(rlo.enabling_objective.statement)
    parts.extend(f"{concept.name}: {concept.definition}" for concept in rlo.concepts)
    return "\n".join(parts)


def _match_any(key: str, values: list[str]) -> FieldCondition | None:
    return FieldCondition(key=key, match=MatchAny(any=values)) if values else None


def _indexed_governance_status(status: str) -> str:
    """Canonicalize legacy catalog documents at the vector-index boundary."""
    return "approved" if status == "signed" else status


def _search_filter(filters: RloSearchFilters) -> Filter:
    must = [
        _match_any("language", filters.languages),
        _match_any("locale", filters.locales),
        _match_any("status", filters.statuses),
        _match_any("level", filters.levels),
        _match_any("industry_tags", filters.industry_tags),
        _match_any("role_tags", filters.role_tags),
        _match_any("service_line_tags", filters.service_line_tags),
        _match_any("competency_tags", filters.competency_tags),
        _match_any("regulatory_tags", filters.regulatory_tags),
    ]
    if filters.active_only:
        must.append(FieldCondition(key="is_active", match=MatchValue(value=True)))
    must_not = []
    if filters.excluded_rlo_ids:
        must_not.append(FieldCondition(key="rlo_id", match=MatchAny(any=filters.excluded_rlo_ids)))
    return Filter(must=[condition for condition in must if condition], must_not=must_not)


class RloIndexer:
    def __init__(self) -> None:
        qdrant_url = os.environ.get("QDRANT_URL", "http://qdrant:6333")
        connection = load_lite_llm_settings()
        self._openai = OpenAI(
            base_url=connection.base_url,
            api_key=connection.api_key,
        )
        self._available = False
        try:
            self._qdrant = QdrantClient(url=qdrant_url, timeout=5)
            self._ensure_collection()
            self._available = True
        except Exception as exc:
            print(f"[indexer] Qdrant unavailable — indexing disabled: {exc}")

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_collection(self) -> None:
        existing = {collection.name for collection in self._qdrant.get_collections().collections}
        if COLLECTION not in existing:
            self._qdrant.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            print(f"[indexer] Created Qdrant collection '{COLLECTION}'")
        for field in _KEYWORD_INDEX_FIELDS:
            self._qdrant.create_payload_index(
                collection_name=COLLECTION,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )
        self._qdrant.create_payload_index(
            collection_name=COLLECTION,
            field_name="is_active",
            field_schema=PayloadSchemaType.BOOL,
            wait=True,
        )

    def _embed_many(self, texts: list[str]) -> list[list[float]]:
        response = self._openai.embeddings.create(
            model=EMBED_MODEL,
            input=texts,
            extra_body={"metadata": build_litellm_metadata(EMBED_MODEL, operation="index")},
            extra_headers=build_langfuse_headers(EMBED_MODEL, operation="index"),
        )
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    def upsert(self, rlo: RLO, storage_uri: str, *, is_active: bool) -> bool:
        if not self._available:
            return False
        try:
            vector = self._embed_many([_build_embed_text(rlo)])[0]
            point = PointStruct(
                id=_stable_uuid(rlo.id, rlo.version),
                vector=vector,
                payload={
                    "rlo_id": rlo.id,
                    "rlo_version": rlo.version,
                    "title": rlo.title,
                    "topic": rlo.topic,
                    "domain": rlo.domain,
                    "level": rlo.level.value,
                    "language": rlo.language,
                    "locale": rlo.locale,
                    "audience": rlo.audience,
                    "estimated_duration_minutes": rlo.estimated_duration_minutes,
                    "content_type": rlo.content_type.value,
                    "status": _indexed_governance_status(rlo.governance.status.value),
                    "schema_version": rlo.schema_version,
                    "storage_uri": storage_uri,
                    "stored_at": datetime.now(timezone.utc).isoformat(),
                    "is_active": is_active,
                    "concept_count": len(rlo.concepts),
                    "component_count": len(rlo.components),
                    "role_tags": rlo.role_tags,
                    "industry_tags": rlo.industry_tags,
                    "service_line_tags": rlo.service_line_tags,
                    "competency_tags": rlo.competency_map,
                    "regulatory_tags": rlo.regulatory_tags,
                    "index_revision": INDEX_REVISION,
                    "embedding_model": str(EMBED_MODEL),
                },
            )
            self._qdrant.upsert(collection_name=COLLECTION, points=[point], wait=True)
            return True
        except Exception as exc:
            print(f"[indexer] Failed to index {rlo.id}@{rlo.version}: {exc}")
            return False

    def is_index_current(self, rlo_id: str, rlo_version: str) -> bool:
        """Return whether the exact RLO has a vector from the current index contract."""
        if not self._available:
            return False
        try:
            records = self._qdrant.retrieve(
                collection_name=COLLECTION,
                ids=[_stable_uuid(rlo_id, rlo_version)],
                with_payload=True,
                with_vectors=False,
            )
            if len(records) != 1:
                return False
            payload = records[0].payload or {}
            return (
                payload.get("index_revision") == INDEX_REVISION
                and payload.get("embedding_model") == str(EMBED_MODEL)
            )
        except Exception as exc:
            print(f"[indexer] Failed to inspect {rlo_id}@{rlo_version}: {exc}")
            return False

    def set_active_version(self, rlo_id: str, rlo_version: str) -> None:
        if not self._available:
            return
        id_filter = Filter(must=[FieldCondition(key="rlo_id", match=MatchValue(value=rlo_id))])
        exact_filter = Filter(must=[
            FieldCondition(key="rlo_id", match=MatchValue(value=rlo_id)),
            FieldCondition(key="rlo_version", match=MatchValue(value=rlo_version)),
        ])
        try:
            self._qdrant.set_payload(
                collection_name=COLLECTION, payload={"is_active": False}, points=id_filter, wait=True
            )
            self._qdrant.set_payload(
                collection_name=COLLECTION, payload={"is_active": True}, points=exact_filter, wait=True
            )
        except Exception as exc:
            print(f"[indexer] Failed to activate {rlo_id}@{rlo_version}: {exc}")

    def search_batch(self, queries: list[tuple[str, RloSearchFilters, int]]) -> list[list[dict]]:
        if not self._available:
            raise RuntimeError("RLO search index is unavailable.")
        vectors = self._embed_many([text for text, _, _ in queries])
        results: list[list[dict]] = []
        for vector, (_, filters, limit) in zip(vectors, queries, strict=True):
            response = self._qdrant.query_points(
                collection_name=COLLECTION,
                query=vector,
                query_filter=_search_filter(filters),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            results.append([
                {"score": point.score, **(point.payload or {})}
                for point in response.points
            ])
        return results

    def delete(self, rlo_id: str, rlo_version: str | None = None) -> None:
        if not self._available:
            return
        must = [FieldCondition(key="rlo_id", match=MatchValue(value=rlo_id))]
        if rlo_version is not None:
            must.append(FieldCondition(key="rlo_version", match=MatchValue(value=rlo_version)))
        try:
            self._qdrant.delete(
                collection_name=COLLECTION,
                points_selector=FilterSelector(filter=Filter(must=must)),
                wait=True,
            )
        except Exception as exc:
            print(f"[indexer] Failed to deindex {rlo_id}: {exc}")

    def delete_legacy_point(self, rlo_id: str) -> None:
        if not self._available:
            return
        try:
            self._qdrant.delete(
                collection_name=COLLECTION,
                points_selector=[_legacy_stable_uuid(rlo_id)],
                wait=True,
            )
        except Exception as exc:
            print(f"[indexer] Failed to remove legacy point for {rlo_id}: {exc}")
