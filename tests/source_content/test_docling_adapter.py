from pathlib import Path

from src.source_ingestion.extractors.docling import extract_document
from src.source_ingestion.hierarchy import depth_first_nodes


FIXTURES = Path("tests/source_content/fixtures/generated")


def test_pdf_adapter_produces_ordered_canonical_nodes_and_table():
    result = extract_document(
        FIXTURES / "ordered-multicolumn.pdf",
        source_version_id="pdf-version",
        extraction_run_id="pdf-run",
    )

    ordered = depth_first_nodes(result.document)
    assert result.document.page_count == 2
    assert ordered[0].kind == "document"
    assert any(node.kind == "table" and "Reviewer" in node.text for node in ordered)
    assert all(node.locators[0].page in {1, 2} for node in ordered)
    assert result.original["schema_name"] == "DoclingDocument"
    assert result.segments
    table_segment = next(
        segment
        for segment in result.segments
        if any(
            node.kind == "table" and node.node_id in segment.node_ids
            for node in result.document.nodes
        )
    )
    assert "Reviewer" in table_segment.text
    assert table_segment.token_count <= 1_200
    assert [artifact.kind for artifact in result.artifacts].count("page_preview") == 2
    assert all(artifact.body.startswith(b"RIFF") for artifact in result.artifacts)
    assert any(artifact.kind == "table_crop" for artifact in result.artifacts)


def test_pptx_adapter_preserves_slide_order_tables_and_speaker_notes():
    result = extract_document(
        FIXTURES / "structured-presentation.pptx",
        source_version_id="pptx-version",
        extraction_run_id="pptx-run",
    )

    ordered = depth_first_nodes(result.document)
    notes = [node for node in ordered if node.kind == "speaker_note"]
    assert result.document.slide_count == 3
    assert len(notes) == 3
    assert [node.locators[0].slide for node in notes] == [1, 2, 3]
    assert any("Low confidence" in (node.text or "") for node in ordered)
    assert len(result.document.relationships) == 3
    assert [artifact.kind for artifact in result.artifacts].count("slide_preview") == 3
    assert {artifact.kind for artifact in result.artifacts} >= {"table_crop", "picture_crop"}


def test_adapter_node_ids_are_stable_across_repeated_runs():
    path = FIXTURES / "ordered-multicolumn.pdf"
    first = extract_document(
        path, source_version_id="same-version", extraction_run_id="run-1"
    )
    second = extract_document(
        path, source_version_id="same-version", extraction_run_id="run-2"
    )

    assert [node.node_id for node in first.document.nodes] == [
        node.node_id for node in second.document.nodes
    ]
    assert [segment.segment_id for segment in first.segments] == [
        segment.segment_id for segment in second.segments
    ]
