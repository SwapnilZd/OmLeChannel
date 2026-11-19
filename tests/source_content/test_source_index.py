from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from src.source_ingestion.contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceLocator,
    SourceSegment,
)
from src.source_ingestion.source_index import SourceSegmentIndex, index_extracted_document


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def create(self, *, model, input, **kwargs):
        self.calls.append(input)
        data = []
        for index, text in enumerate(input):
            lowered = text.lower()
            vector = [
                float("alpha" in lowered),
                float("beta" in lowered),
                1.0,
            ]
            data.append(SimpleNamespace(index=index, embedding=vector))
        return SimpleNamespace(data=data)


def _segment(segment_id, source_version_id, ordinal, text, node_id):
    return SourceSegment(
        segment_id=segment_id,
        source_version_id=source_version_id,
        extraction_run_id="run-1",
        ordinal=ordinal,
        node_ids=[node_id],
        hierarchy_path=["root"],
        locator_start=SourceLocator(page=1),
        locator_end=SourceLocator(page=1),
        token_count=3,
        text=text,
    )


def index(*, token_budget=None):
    embeddings = FakeEmbeddings()
    return SourceSegmentIndex(
        qdrant=QdrantClient(location=":memory:"),
        embeddings=embeddings,
        vector_size=3,
        token_budget=token_budget,
    )


def test_replace_is_idempotent_and_removes_stale_source_segments():
    source_index = index()
    source_index.replace(
        "version-1",
        [
            _segment("6fd98ba1-cf31-50b0-9c6c-7f3b88596306", "version-1", 0, "alpha", "node-a"),
            _segment("e254c412-7ad1-5588-a62f-3a73a1fda352", "version-1", 1, "beta", "node-b"),
        ],
    )
    source_index.replace(
        "version-1",
        [_segment("6fd98ba1-cf31-50b0-9c6c-7f3b88596306", "version-1", 0, "alpha", "node-a")],
    )

    assert source_index.count("version-1") == 1


def test_failed_reembedding_does_not_delete_the_current_source_index():
    source_index = index()
    source_index.replace(
        "version-1",
        [_segment("6fd98ba1-cf31-50b0-9c6c-7f3b88596306", "version-1", 0, "alpha", "node-a")],
    )

    def fail(**kwargs):
        raise RuntimeError("embedding unavailable")

    source_index._embeddings.create = fail

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        source_index.replace(
            "version-1",
            [_segment("e254c412-7ad1-5588-a62f-3a73a1fda352", "version-1", 0, "beta", "node-b")],
        )

    assert source_index.count("version-1") == 1


def test_embedding_batches_obey_the_configured_source_token_limit(monkeypatch):
    monkeypatch.setenv("SOURCE_CONTENT_TRANCHE_TOKEN_LIMIT", "3")
    source_index = index()
    source_index.replace(
        "version-1",
        [
            _segment("6fd98ba1-cf31-50b0-9c6c-7f3b88596306", "version-1", 0, "alpha words", "node-a"),
            _segment("e254c412-7ad1-5588-a62f-3a73a1fda352", "version-1", 1, "beta words", "node-b"),
        ],
    )

    assert len(source_index._embeddings.calls) == 2


def test_extracted_document_vertical_slice_segments_and_indexes():
    document = ExtractedDocument(
        source_version_id="version-1",
        extraction_run_id="run-1",
        format="pdf",
        page_count=1,
        nodes=[
            DocumentNode(
                node_id="root",
                ordinal=0,
                ordinal_path=(0,),
                kind="document",
                role="root",
                text="A complete source",
                locators=[SourceLocator(page=1)],
                method=ExtractionMethod.NATIVE,
            )
        ],
    )
    source_index = index()

    segments = index_extracted_document(document, index=source_index)

    assert len(segments) == 1
    assert source_index.count("version-1") == 1
