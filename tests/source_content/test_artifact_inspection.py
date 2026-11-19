from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from src.source_ingestion import artifacts
from src.source_ingestion.contracts import (
    ArtifactEntry,
    ArtifactManifest,
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceFormat,
    SourceLocator,
    SourceSegment,
)


class MemoryStorage:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values[key]


def _fixture():
    document = ExtractedDocument(
        source_version_id="version-1",
        extraction_run_id="job-1",
        format=SourceFormat.PDF,
        page_count=1,
        nodes=[
            DocumentNode(
                node_id="node-1",
                ordinal=0,
                ordinal_path=(0,),
                kind="paragraph",
                role="body",
                text="A grounded extracted paragraph.",
                locators=[SourceLocator(page=1)],
                method=ExtractionMethod.NATIVE,
            )
        ],
    )
    segment = SourceSegment(
        segment_id="segment-1",
        source_version_id="version-1",
        extraction_run_id="job-1",
        ordinal=0,
        node_ids=["node-1"],
        hierarchy_path=["document"],
        locator_start=SourceLocator(page=1),
        locator_end=SourceLocator(page=1),
        token_count=5,
        text="A grounded extracted paragraph.",
    )
    bodies = {
        "document": document.model_dump_json().encode(),
        "report": json.dumps({"text_coverage": 1, "warnings": []}).encode(),
        "segments": json.dumps([segment.model_dump(mode="json")]).encode(),
    }
    entries = [
        ArtifactEntry(
            artifact_id=name,
            kind=name,
            object_key=f"artifact/{name}.json",
            sha256=hashlib.sha256(body).hexdigest(),
            content_type="application/json",
            size_bytes=len(body),
        )
        for name, body in bodies.items()
    ]
    manifest = ArtifactManifest(
        source_version_id="version-1",
        extraction_run_id="job-1",
        artifacts=entries,
    )
    values = {
        "artifact/manifest.json": manifest.model_dump_json().encode(),
        **{f"artifact/{name}.json": body for name, body in bodies.items()},
    }
    return values


def _patch(monkeypatch, values):
    monkeypatch.setattr(
        artifacts,
        "get_job",
        lambda _job_id: SimpleNamespace(
            status="ready", source_version_id="version-1"
        ),
    )
    monkeypatch.setattr(
        artifacts,
        "get_artifact_manifest_object_key",
        lambda _job_id: "artifact/manifest.json",
    )
    return MemoryStorage(values)


def test_ready_extraction_artifacts_are_loaded_with_order_and_lineage(monkeypatch):
    values = _fixture()
    storage = _patch(monkeypatch, values)

    bundle = artifacts.load_extraction("job-1", storage=storage)

    assert bundle.document.nodes[0].node_id == "node-1"
    assert bundle.segments[0].node_ids == ["node-1"]
    assert bundle.report["text_coverage"] == 1


def test_tampered_extraction_artifact_is_rejected(monkeypatch):
    values = _fixture()
    values["artifact/document.json"] = b"{}"
    storage = _patch(monkeypatch, values)

    with pytest.raises(ValueError, match="checksum mismatch"):
        artifacts.load_extraction("job-1", storage=storage)
