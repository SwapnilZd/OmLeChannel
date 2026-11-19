"""Qdrant-backed semantic, lexical, and node retrieval for source segments."""

from __future__ import annotations

import os
import re
from typing import Literal

from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    load_lite_llm_settings,
)
from openai import OpenAI
from pydantic import Field
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from .contracts import ExtractedDocument, RetrievalHit, SourceSegment, StrictModel
from .segmentation import (
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_SEGMENT_TOKENS,
    SourceTokenBudget,
    TokenBudgetExceeded,
    segment_document,
)


COLLECTION = "source_segments"
INDEX_REVISION = "source-segment-index-v1"
VECTOR_SIZE = 1536
EMBED_MODEL = ModelAlias.SOURCE_SEGMENT_EMBEDDING
_LEXICAL_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)


class RetrievalQuery(StrictModel):
    query: str = Field(min_length=1)
    source_version_ids: list[str] = Field(min_length=1)
    collection_id: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


def _source_filter(source_version_ids: list[str]) -> Filter:
    return Filter(
        must=[
            FieldCondition(
                key="source_version_id",
                match=MatchAny(any=source_version_ids),
            )
        ]
    )


def _terms(text: str) -> set[str]:
    return {token.casefold() for token in _LEXICAL_TOKEN.findall(text)}


class SourceSegmentIndex:
    def __init__(
        self,
        *,
        qdrant=None,
        embeddings=None,
        vector_size: int = VECTOR_SIZE,
        token_budget: SourceTokenBudget | None = None,
    ) -> None:
        self._qdrant = qdrant or QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant:6333"), timeout=10
        )
        if embeddings is None:
            settings = load_lite_llm_settings()
            embeddings = OpenAI(base_url=settings.base_url, api_key=settings.api_key).embeddings
        self._embeddings = embeddings
        self._vector_size = vector_size
        self._token_budget = token_budget or SourceTokenBudget()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        existing = {item.name for item in self._qdrant.get_collections().collections}
        if COLLECTION not in existing:
            self._qdrant.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(
                    size=self._vector_size,
                    distance=Distance.COSINE,
                ),
            )
        for field in ("source_version_id", "node_ids", "index_revision"):
            self._qdrant.create_payload_index(
                collection_name=COLLECTION,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )

    def _embed(self, texts: list[str], *, operation: str) -> list[list[float]]:
        batches: list[list[str]] = []
        pending: list[str] = []
        pending_tokens = 0
        for text in texts:
            token_count = self._token_budget.count(text)
            if token_count > self._token_budget.source_token_limit:
                raise TokenBudgetExceeded("one embedding input exceeds the source-token limit")
            if pending and pending_tokens + token_count > self._token_budget.source_token_limit:
                batches.append(pending)
                pending = []
                pending_tokens = 0
            pending.append(text)
            pending_tokens += token_count
        if pending:
            batches.append(pending)

        vectors = []
        for batch in batches:
            response = self._embeddings.create(
                model=EMBED_MODEL,
                input=batch,
                extra_body={
                    "metadata": build_litellm_metadata(EMBED_MODEL, operation=operation)
                },
                extra_headers=build_langfuse_headers(EMBED_MODEL, operation=operation),
            )
            vectors.extend(
                item.embedding for item in sorted(response.data, key=lambda item: item.index)
            )
        return vectors

    def replace(self, source_version_id: str, segments: list[SourceSegment]) -> None:
        if any(segment.source_version_id != source_version_id for segment in segments):
            raise ValueError("all segments must belong to the replaced source version")
        existing_ids = {
            str(point.id) for point in self._segments([source_version_id])
        }
        replacement_ids = {segment.segment_id for segment in segments}
        if segments:
            vectors = self._embed([segment.text for segment in segments], operation="index")
            points = []
            for segment, vector in zip(segments, vectors, strict=True):
                payload = segment.model_dump(mode="json")
                payload.update(
                    {
                        "index_revision": INDEX_REVISION,
                        "embedding_model": str(EMBED_MODEL),
                    }
                )
                points.append(PointStruct(id=segment.segment_id, vector=vector, payload=payload))
            self._qdrant.upsert(collection_name=COLLECTION, points=points, wait=True)
        stale_ids = sorted(existing_ids - replacement_ids)
        if stale_ids:
            self._qdrant.delete(
                collection_name=COLLECTION,
                points_selector=PointIdsList(points=stale_ids),
                wait=True,
            )

    def count(self, source_version_id: str) -> int:
        return self._qdrant.count(
            collection_name=COLLECTION,
            count_filter=Filter(
                must=[
                    FieldCondition(
                        key="source_version_id",
                        match=MatchValue(value=source_version_id),
                    )
                ]
            ),
            exact=True,
        ).count

    def _segments(self, source_version_ids: list[str]):
        offset = None
        while True:
            records, offset = self._qdrant.scroll(
                collection_name=COLLECTION,
                scroll_filter=_source_filter(source_version_ids),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            yield from records
            if offset is None:
                return

    @staticmethod
    def _hit(
        payload: dict,
        score: float,
        match_type: Literal["semantic", "lexical", "hybrid", "node"],
        *,
        collection_id: str | None = None,
    ):
        segment = SourceSegment.model_validate(
            {key: value for key, value in payload.items() if key in SourceSegment.model_fields}
        )
        return RetrievalHit(
            segment_id=segment.segment_id,
            source_version_id=segment.source_version_id,
            collection_id=collection_id,
            ordinal=segment.ordinal,
            node_ids=segment.node_ids,
            hierarchy_path=segment.hierarchy_path,
            locator_start=segment.locator_start,
            locator_end=segment.locator_end,
            text=segment.text,
            score=max(0.0, score),
            match_type=match_type,
        )

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]:
        vector = self._embed([request.query], operation="search")[0]
        semantic = self._qdrant.query_points(
            collection_name=COLLECTION,
            query=vector,
            query_filter=_source_filter(request.source_version_ids),
            limit=min(request.limit * 3, 100),
            with_payload=True,
            with_vectors=False,
        ).points
        combined: dict[str, dict] = {}
        for point in semantic:
            combined[str(point.id)] = {
                "payload": point.payload or {},
                "semantic": max(0.0, float(point.score)),
                "lexical": 0.0,
            }
        query_terms = _terms(request.query)
        for point in self._segments(request.source_version_ids):
            payload = point.payload or {}
            overlap = len(query_terms & _terms(str(payload.get("text", ""))))
            if overlap:
                entry = combined.setdefault(
                    str(point.id),
                    {"payload": payload, "semantic": 0.0, "lexical": 0.0},
                )
                entry["lexical"] = overlap / len(query_terms)
        ranked = []
        for entry in combined.values():
            semantic_score = entry["semantic"]
            lexical_score = entry["lexical"]
            match_type = "hybrid" if semantic_score and lexical_score else (
                "lexical" if lexical_score else "semantic"
            )
            score = semantic_score * 0.65 + lexical_score * 0.35
            ranked.append(
                self._hit(
                    entry["payload"], score, match_type, collection_id=request.collection_id
                )
            )
        source_order = {
            source_version_id: ordinal
            for ordinal, source_version_id in enumerate(request.source_version_ids)
        }
        return sorted(
            ranked,
            key=lambda hit: (-hit.score, source_order[hit.source_version_id], hit.ordinal),
        )[: request.limit]

    def search_collection(self, query: str, collection, *, limit: int = 10) -> list[RetrievalHit]:
        members = list(collection.members)
        hits = self.search(
            RetrievalQuery(
                query=query,
                source_version_ids=[member.source_version_id for member in members],
                collection_id=collection.collection_id,
                limit=limit,
            )
        )
        metadata = {
            member.source_version_id: (member.ordinal, member.authority_note)
            for member in members
        }
        return [
            hit.model_copy(
                update={
                    "source_ordinal": metadata[hit.source_version_id][0],
                    "authority_note": metadata[hit.source_version_id][1],
                }
            )
            for hit in hits
        ]

    def by_node_ids(
        self,
        node_ids: list[str],
        *,
        source_version_ids: list[str],
    ) -> list[RetrievalHit]:
        wanted = set(node_ids)
        hits = []
        for point in self._segments(source_version_ids):
            payload = point.payload or {}
            if wanted.intersection(payload.get("node_ids", [])):
                hits.append(self._hit(payload, 1.0, "node"))
        return sorted(hits, key=lambda hit: (source_version_ids.index(hit.source_version_id), hit.ordinal))


def index_extracted_document(
    document: ExtractedDocument,
    *,
    index: SourceSegmentIndex | None = None,
    max_tokens: int = DEFAULT_SEGMENT_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[SourceSegment]:
    segments = segment_document(
        document,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )
    (index or SourceSegmentIndex()).replace(document.source_version_id, segments)
    return segments
