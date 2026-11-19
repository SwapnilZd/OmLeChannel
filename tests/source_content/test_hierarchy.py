from copy import deepcopy

import pytest

from src.source_ingestion.contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    NodeRelationship,
    RelationshipType,
    SourceLocator,
)
from src.source_ingestion.hierarchy import (
    HierarchyError,
    adjacency_from_nested,
    depth_first_nodes,
    nested_view,
    validate_document,
)


def node(node_id, ordinal, path, *, parent=None, children=None, page=1):
    return DocumentNode(
        node_id=node_id,
        parent_id=parent,
        ordinal=ordinal,
        ordinal_path=path,
        kind="text",
        role="body",
        text=node_id,
        locators=[SourceLocator(page=page)],
        method=ExtractionMethod.NATIVE,
        child_ids=children or [],
    )


def pdf_document():
    return ExtractedDocument(
        source_version_id="version-1",
        extraction_run_id="run-1",
        format="pdf",
        page_count=2,
        nodes=[
            node("root-a", 0, (0,), children=["child-a", "child-b"]),
            node("child-b", 1, (0, 1), parent="root-a"),
            node("root-b", 1, (1,), page=2),
            node("child-a", 0, (0, 0), parent="root-a"),
        ],
        relationships=[
            NodeRelationship(
                relationship_id="footnote-1",
                type=RelationshipType.FOOTNOTE_OF,
                source_node_id="child-b",
                target_node_id="child-a",
            )
        ],
    )


def test_depth_first_traversal_is_complete_and_deterministic():
    document = pdf_document()

    assert [item.node_id for item in depth_first_nodes(document)] == [
        "root-a", "child-a", "child-b", "root-b"
    ]
    nested = nested_view(document)
    assert nested[0]["children"][1]["node_id"] == "child-b"
    assert adjacency_from_nested(nested) == depth_first_nodes(document)
    assert ExtractedDocument.model_validate_json(document.model_dump_json()) == document


@pytest.mark.parametrize(
    "mutate,error",
    [
        (lambda doc: doc.nodes.append(deepcopy(doc.nodes[0])), "duplicate node ID"),
        (lambda doc: setattr(doc.nodes[1], "parent_id", "missing"), "orphaned node"),
        (lambda doc: setattr(doc.nodes[1], "ordinal", 0), "duplicate sibling ordinal"),
        (lambda doc: setattr(doc.nodes[0], "child_ids", ["child-b", "child-a"]), "mismatched child list"),
        (lambda doc: setattr(doc.nodes[1], "ordinal_path", (9,)), "invalid ordinal path"),
        (
            lambda doc: (
                setattr(doc.nodes[0], "parent_id", "child-a"),
                setattr(doc.nodes[3], "child_ids", ["root-a"]),
            ),
            "cycle",
        ),
        (lambda doc: setattr(doc.nodes[3].locators[0], "page", 3), "locator outside source"),
        (lambda doc: setattr(doc.relationships[0], "target_node_id", "missing"), "invalid relationship"),
    ],
)
def test_invalid_hierarchy_is_rejected(mutate, error):
    document = pdf_document()
    mutate(document)

    with pytest.raises(HierarchyError, match=error):
        validate_document(document)


def test_pptx_like_hierarchy_uses_slide_locators():
    document = ExtractedDocument(
        source_version_id="version-2",
        extraction_run_id="run-2",
        format="pptx",
        slide_count=1,
        nodes=[
            DocumentNode(
                node_id="slide-1",
                ordinal=0,
                ordinal_path=(0,),
                kind="slide",
                role="container",
                text="Slide one",
                locators=[SourceLocator(slide=1)],
                method=ExtractionMethod.NATIVE,
            )
        ],
    )

    assert depth_first_nodes(document)[0].node_id == "slide-1"
