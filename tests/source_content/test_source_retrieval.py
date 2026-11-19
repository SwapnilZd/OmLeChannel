from types import SimpleNamespace

from qdrant_client import QdrantClient

from src.source_ingestion.contracts import SourceLocator, SourceSegment
from src.source_ingestion.source_index import RetrievalQuery, SourceSegmentIndex


class FakeEmbeddings:
    def create(self, *, model, input, **kwargs):
        data = []
        for item_index, text in enumerate(input):
            lowered = text.lower()
            data.append(
                SimpleNamespace(
                    index=item_index,
                    embedding=[
                        float("alpha" in lowered),
                        float("beta" in lowered),
                        1.0,
                    ],
                )
            )
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


def index():
    return SourceSegmentIndex(
        qdrant=QdrantClient(location=":memory:"),
        embeddings=FakeEmbeddings(),
        vector_size=3,
    )


def test_hybrid_retrieval_finds_lexical_evidence_and_preserves_lineage():
    source_index = index()
    source_index.replace(
        "version-1",
        [
            _segment("6fd98ba1-cf31-50b0-9c6c-7f3b88596306", "version-1", 0, "alpha overview", "node-a"),
            _segment("e254c412-7ad1-5588-a62f-3a73a1fda352", "version-1", 1, "rare-needle requirement", "node-b"),
        ],
    )

    hits = source_index.search(
        RetrievalQuery(query="rare-needle", source_version_ids=["version-1"], limit=2)
    )

    assert hits[0].segment_id == "e254c412-7ad1-5588-a62f-3a73a1fda352"
    assert hits[0].node_ids == ["node-b"]
    assert hits[0].match_type in {"lexical", "hybrid"}


def test_exact_node_retrieval_is_collection_scoped():
    source_index = index()
    source_index.replace(
        "version-1",
        [_segment("6fd98ba1-cf31-50b0-9c6c-7f3b88596306", "version-1", 0, "first", "shared-node")],
    )
    source_index.replace(
        "version-2",
        [_segment("e254c412-7ad1-5588-a62f-3a73a1fda352", "version-2", 0, "second", "other-node")],
    )

    hits = source_index.by_node_ids(["shared-node"], source_version_ids=["version-1"])

    assert [(hit.source_version_id, hit.node_ids) for hit in hits] == [
        ("version-1", ["shared-node"])
    ]


def test_collection_search_retains_member_order_and_authority_metadata():
    source_index = index()
    source_index.replace(
        "version-1",
        [_segment("6fd98ba1-cf31-50b0-9c6c-7f3b88596306", "version-1", 0, "first", "node-a")],
    )
    source_index.replace(
        "version-2",
        [_segment("e254c412-7ad1-5588-a62f-3a73a1fda352", "version-2", 0, "second", "node-b")],
    )
    collection = SimpleNamespace(
        collection_id="collection-1",
        members=(
            SimpleNamespace(source_version_id="version-2", ordinal=0, authority_note="Primary"),
            SimpleNamespace(source_version_id="version-1", ordinal=1, authority_note=None),
        ),
    )

    hits = source_index.search_collection("second", collection, limit=2)

    assert hits[0].collection_id == "collection-1"
    assert hits[0].source_version_id == "version-2"
    assert hits[0].source_ordinal == 0
    assert hits[0].authority_note == "Primary"
