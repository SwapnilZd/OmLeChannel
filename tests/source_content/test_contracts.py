from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.source_ingestion.contracts import (
    ArtifactEntry,
    ArtifactManifest,
    DocumentNode,
    EvidenceCitation,
    ExtractionMethod,
    SourceLocator,
    SourceVersion,
)
from src.source_ingestion.hierarchy import stable_node_id


def test_contracts_are_strict_and_versioned():
    with pytest.raises(ValidationError):
        SourceVersion(
            source_version_id="version-1",
            source_id="source-1",
            checksum="a" * 64,
            filename="source.pdf",
            format="pdf",
            original_object_key="source/original.pdf",
            created_at=datetime.now(timezone.utc),
            unexpected=True,
        )


def test_locator_requires_exactly_one_valid_extent():
    with pytest.raises(ValidationError):
        SourceLocator(page=1, slide=1)
    with pytest.raises(ValidationError):
        SourceLocator(page=1, bbox=(10, 10, 5, 20))


def test_unknown_material_is_a_first_class_ordered_node():
    node = DocumentNode(
        node_id="unknown-1",
        ordinal=0,
        ordinal_path=(0,),
        kind="unknown",
        role="unclassified",
        text="Preserve this extractor block",
        locators=[SourceLocator(page=1)],
        method=ExtractionMethod.UNKNOWN,
    )

    assert node.kind == "unknown"
    assert node.text == "Preserve this extractor block"


def test_duplicate_citation_nodes_are_normalized_in_source_order():
    citation = EvidenceCitation(
        source_version_id="version-1",
        node_ids=["node-1", "node-2", "node-1"],
    )

    assert citation.node_ids == ["node-1", "node-2"]


def test_stable_node_ids_and_asset_manifest_round_trip():
    first = stable_node_id("version-1", kind="figure", ordinal_path=(0, 2))
    second = stable_node_id("version-1", kind="figure", ordinal_path=(0, 2))
    manifest = ArtifactManifest(
        source_version_id="version-1",
        extraction_run_id="run-1",
        artifacts=[
            ArtifactEntry(
                artifact_id="asset-1",
                kind="figure",
                object_key="source-content/asset-1.webp",
                sha256="b" * 64,
                content_type="image/webp",
                size_bytes=100,
            )
        ],
    )

    assert first == second
    assert ArtifactManifest.model_validate_json(manifest.model_dump_json()) == manifest
