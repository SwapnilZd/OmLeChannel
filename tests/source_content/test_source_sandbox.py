import asyncio
from types import SimpleNamespace

from src import source_upload
from src.source_authoring.contracts import PractitionerInstructions
from src.source_ingestion.contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceFormat,
    SourceLocator,
    SourceSegment,
)


def test_single_source_sandbox_runs_real_pipeline_boundaries(monkeypatch):
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
                text="Incident responders communicate during recovery.",
                locators=[SourceLocator(page=1)],
                method=ExtractionMethod.NATIVE,
            )
        ],
    )
    segments = [
        SourceSegment(
            segment_id="segment-1",
            source_version_id="version-1",
            extraction_run_id="job-1",
            ordinal=0,
            node_ids=["node-1"],
            hierarchy_path=["document"],
            locator_start=SourceLocator(page=1),
            locator_end=SourceLocator(page=1),
            token_count=7,
            text="Incident responders communicate during recovery.",
        )
    ]
    bundle = SimpleNamespace(
        job=SimpleNamespace(
            source_version_id="version-1", original_filename="incident-response.pdf"
        ),
        document=document,
        segments=segments,
    )
    collection = SimpleNamespace(collection_id="sandbox-version-1")
    calls = []

    monkeypatch.setattr(
        "src.source_ingestion.artifacts.load_extraction", lambda _job_id: bundle
    )
    monkeypatch.setattr(
        "src.source_ingestion.repository.get_source_collection",
        lambda _collection_id: collection,
    )

    class Mapping:
        def map_document(self, loaded_document, loaded_segments):
            calls.append(("document", loaded_document, loaded_segments))
            return "document-map"

        def map_collection(self, loaded_collection, maps, documents):
            calls.append(("collection", loaded_collection, maps, documents))
            return "collection-map"

    class Discovery:
        def discover(self, collection_map, documents, **kwargs):
            calls.append(("objectives", collection_map, documents, kwargs))
            return SimpleNamespace(workspace_id=kwargs["workspace_id"])

    monkeypatch.setattr("src.source_authoring.mapping.SourceMappingService", Mapping)
    monkeypatch.setattr(
        "src.source_authoring.objectives.ObjectiveDiscoveryService", Discovery
    )

    result = source_upload._generate_sandbox_objectives(
        "job-1",
        source_upload.SandboxObjectiveRequest(
            roles=["incident responder"],
            tasks=["coordinate recovery"],
        ),
        created_by="admin@deloitte.com",
    )

    assert result.workspace_id == "sandbox-version-1"
    assert [call[0] for call in calls] == ["document", "collection", "objectives"]
    instructions = calls[-1][3]["instructions"]
    assert isinstance(instructions, PractitionerInstructions)
    assert instructions.roles == ["incident responder"]
    assert calls[-1][3]["created_by"] == "admin@deloitte.com"


def test_sandbox_progress_reports_completed_section_maps(monkeypatch):
    bundle = SimpleNamespace(
        job=SimpleNamespace(source_version_id="version-1"),
        segments=[SimpleNamespace() for _ in range(10)],
    )
    monkeypatch.setattr(
        "src.source_ingestion.artifacts.load_extraction", lambda _job_id: bundle
    )
    monkeypatch.setattr(
        "src.source_ingestion.repository.count_source_map_artifacts",
        lambda scope_kind, scope_id: 4,
    )
    monkeypatch.setattr(
        "src.source_ingestion.repository.get_source_map_artifact",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "src.source_authoring.repository.get_objective_workspace",
        lambda _workspace_id: None,
    )

    progress = asyncio.run(source_upload.get_sandbox_objective_progress("job-1"))

    assert progress["stage"] == "section_mapping"
    assert progress["completed_sections"] == 4
    assert progress["total_sections"] == 10
    assert progress["percent"] == 28
