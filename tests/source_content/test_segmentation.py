import pytest

from src.source_ingestion.contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceLocator,
)
from src.source_ingestion.segmentation import (
    SourceTokenBudget,
    TokenBudgetExceeded,
    segment_document,
)


def _node(node_id, ordinal, text, *, kind="paragraph", parent="root", children=None):
    return DocumentNode(
        node_id=node_id,
        parent_id=parent,
        ordinal=ordinal,
        ordinal_path=(0, ordinal),
        kind=kind,
        role=kind,
        text=text,
        locators=[SourceLocator(page=1)],
        method=ExtractionMethod.NATIVE,
        child_ids=children or [],
    )


def _document(*nodes):
    root = DocumentNode(
        node_id="root",
        ordinal=0,
        ordinal_path=(0,),
        kind="document",
        role="root",
        text="Source title",
        locators=[SourceLocator(page=1)],
        method=ExtractionMethod.NATIVE,
        child_ids=[node.node_id for node in nodes],
    )
    return ExtractedDocument(
        source_version_id="version-1",
        extraction_run_id="run-1",
        format="pdf",
        page_count=1,
        nodes=[root, *nodes],
    )


def test_segments_preserve_order_lineage_and_atomic_structures():
    document = _document(
        _node("heading", 0, "Controls", kind="section_header"),
        _node("body", 1, "A control has an owner and a purpose."),
        _node("table", 2, "| Owner | Purpose |\n|---|---|\n| Team | Review |", kind="table"),
        _node("caption", 3, "Table 1. Control responsibilities", kind="caption"),
    )

    segments = segment_document(document, max_tokens=20, overlap_tokens=0)

    assert [node_id for segment in segments for node_id in segment.node_ids] == [
        "root",
        "heading",
        "body",
        "table",
        "caption",
    ]
    assert [segment.ordinal for segment in segments] == list(range(len(segments)))
    table_segment = next(segment for segment in segments if "table" in segment.node_ids)
    assert table_segment.text.count("| Owner | Purpose |") == 1
    assert table_segment.locator_start.page == 1
    assert table_segment.token_count <= 20


def test_oversized_node_is_split_only_at_hard_limit_with_overlap():
    text = " ".join(f"term-{index}" for index in range(100))
    segments = segment_document(
        _document(_node("large", 0, text)),
        max_tokens=25,
        overlap_tokens=5,
    )

    large_segments = [segment for segment in segments if segment.node_ids == ["large"]]
    assert len(large_segments) > 1
    assert all(segment.token_count <= 25 for segment in large_segments)
    assert all(segment.split_from_node for segment in large_segments)


def test_oversized_table_repeats_headers_and_preserves_complete_rows():
    header = "| Control | Description |"
    separator = "|---|---|"
    rows = [f"| C-{index:02d} | Description for control {index:02d} |" for index in range(20)]
    text = "\n".join([header, separator, *rows])

    segments = segment_document(
        _document(_node("large-table", 0, text, kind="table")),
        max_tokens=40,
        overlap_tokens=0,
    )

    table_segments = [
        segment for segment in segments if segment.node_ids == ["large-table"]
    ]
    assert len(table_segments) > 1
    assert all(
        segment.text.startswith(f"{header}\n{separator}\n")
        for segment in table_segments
    )
    assert all(segment.token_count <= 40 for segment in table_segments)
    combined = "\n".join(segment.text for segment in table_segments)
    assert all(combined.count(row) == 1 for row in rows)


def test_table_below_token_limit_is_not_cut_at_character_boundary():
    header = f"| Name{' ' * 2200}| Purpose |"
    text = "\n".join(
        [header, "|---|---|", "| Preparation | Establish readiness |"]
    )

    segment = next(
        item
        for item in segment_document(
            _document(_node("wide-table", 0, text, kind="table")),
            max_tokens=1_200,
            overlap_tokens=0,
        )
        if "wide-table" in item.node_ids
    )

    assert len(segment.text) > 2_000
    assert "| Preparation | Establish readiness |" in segment.text
    assert segment.token_count < 1_200


def test_source_token_budget_enforces_an_explicit_limit():
    budget = SourceTokenBudget(
        source_token_limit=15_000,
        request_token_limit=50_000,
    )

    assert budget.count("small input") > 0
    with pytest.raises(TokenBudgetExceeded):
        budget.require_within_limit(" token" * 60_000)


def test_source_token_budget_uses_configured_limits(monkeypatch):
    monkeypatch.setenv("SOURCE_CONTENT_TRANCHE_TOKEN_LIMIT", "17")
    monkeypatch.setenv("SOURCE_CONTENT_REQUEST_TOKEN_LIMIT", "101")

    assert SourceTokenBudget().source_token_limit == 17
    assert SourceTokenBudget().request_token_limit == 101


@pytest.mark.parametrize("value", ["0", "not-a-number"])
def test_source_token_budget_rejects_invalid_tranche_config(monkeypatch, value):
    monkeypatch.setenv("SOURCE_CONTENT_TRANCHE_TOKEN_LIMIT", value)

    with pytest.raises(ValueError, match="SOURCE_CONTENT_TRANCHE_TOKEN_LIMIT"):
        SourceTokenBudget()


def test_source_token_budget_rejects_request_smaller_than_tranche():
    with pytest.raises(ValueError, match="at least the tranche"):
        SourceTokenBudget(source_token_limit=15_000, request_token_limit=14_999)
