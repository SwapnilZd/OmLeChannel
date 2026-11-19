import json
from types import SimpleNamespace

import pytest

from src.source_authoring.mapping import (
    CollectionSynthesisDraft,
    SectionMapDraft,
    SourceMappingService,
    SynthesisDraft,
)
from src.source_ingestion.contracts import (
    CoverageEntry,
    CoverageStatus,
    DocumentNode,
    EvidenceCitation,
    ExtractedDocument,
    ExtractionMethod,
    MapClaim,
    MapConflict,
    MapRelationship,
    SourceLocator,
    SourceSegment,
)
from src.source_ingestion.segmentation import TokenBudgetExceeded


class MemoryStore:
    def __init__(self):
        self.values = {}
        self.saved = []

    def load(self, scope_kind, scope_id, hierarchy_key):
        return self.values.get((scope_kind, scope_id, hierarchy_key))

    def save(self, **kwargs):
        key = (kwargs["scope_kind"], kwargs["scope_id"], kwargs["hierarchy_key"])
        self.values[key] = kwargs["payload"]
        self.saved.append(kwargs)


class FakeResponses:
    def __init__(self):
        self.calls = []
        self.fail_next_synthesis = False
        self.use_unknown_citation = False
        self.use_unknown_synthesis_citation = False

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        content = json.loads(kwargs["input"][1]["content"])
        text_format = kwargs["text_format"]
        if text_format is SectionMapDraft:
            node_id = "unknown-node" if self.use_unknown_citation else content["nodes"][0]["node_id"]
            claim = MapClaim(
                claim_id=f"claim-{content['segment_id']}",
                statement=f"Mapped {content['segment_id']}",
                citations=[
                    EvidenceCitation(
                        source_version_id=content["source_version_id"],
                        node_ids=[node_id],
                    )
                ],
            )
            parsed = SectionMapDraft(
                claims=[claim],
                coverage=[
                    CoverageEntry(
                        source_version_id=content["source_version_id"],
                        node_id=item["node_id"],
                        status=CoverageStatus.REPRESENTED,
                        claim_ids=[claim.claim_id],
                    )
                    for item in content["nodes"]
                ],
            )
        elif text_format is SynthesisDraft:
            if self.fail_next_synthesis:
                self.fail_next_synthesis = False
                raise RuntimeError("synthesis unavailable")
            claims = [
                MapClaim.model_validate(claim)
                for child in content["child_maps"]
                for claim in child["claims"]
            ]
            if self.use_unknown_synthesis_citation and claims:
                claims[0] = claims[0].model_copy(
                    update={
                        "citations": [
                            claims[0].citations[0].model_copy(
                                update={"node_ids": ["unknown-promoted-node"]}
                            )
                        ]
                    }
                )
            parsed = SynthesisDraft(claims=claims)
        elif text_format is CollectionSynthesisDraft:
            claims = [
                MapClaim.model_validate(claim)
                for document_map in content["document_maps"]
                for claim in document_map["claims"]
            ]
            parsed = CollectionSynthesisDraft(
                claims=claims,
                agreements=["The sources contain related coffee information."],
                overlaps=["Both sources discuss factors affecting a cup of coffee."],
                conflicts=[
                    MapConflict(
                        conflict_id="conflict-1",
                        description="The sources emphasize different coffee outcomes.",
                        citations=[claims[0].citations[0], claims[-1].citations[0]],
                    )
                ],
                version_differences=["The sources describe different scopes and editions."],
                gaps=["No source connects every concept to a single learner task."],
            )
        else:
            raise AssertionError(f"unexpected response format: {text_format}")
        return SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


class CollectionReductionBudget:
    def require_within_limit(self, text):
        if text.count('"schema_version":"source-document-map-v1"') > 1:
            raise TokenBudgetExceeded("collection input exceeds configured limit")
        return 1


class OneTimeHierarchyLimitBudget:
    def __init__(self):
        self.rejected = False

    def require_within_limit(self, text):
        if '"child_maps"' in text and not self.rejected:
            self.rejected = True
            raise TokenBudgetExceeded("hierarchy input exceeds configured limit")
        return 1


class SingleMapReductionBudget:
    def __init__(self):
        self.oversized_child_attempts = 0

    def require_within_limit(self, text):
        try:
            content = json.loads(text)
        except json.JSONDecodeError:
            return 1
        if any(
            item.get("schema_version") == "source-document-map-v1"
            for item in content.get("document_maps", [])
        ):
            raise TokenBudgetExceeded("full document map exceeds configured limit")
        child_claims = sum(
            len(item.get("claims", [])) for item in content.get("child_maps", [])
        )
        if child_claims > 1 and self.oversized_child_attempts < 2:
            self.oversized_child_attempts += 1
            raise TokenBudgetExceeded("single map exceeds configured limit")
        return 1


def _document(source_version_id="source-v1", run_id="run-1"):
    root = DocumentNode(
        node_id=f"{source_version_id}-root",
        parent_id=None,
        ordinal=0,
        ordinal_path=(0,),
        kind="document",
        role="root",
        text="Coffee source",
        locators=[SourceLocator(page=1)],
        method=ExtractionMethod.NATIVE,
        child_ids=[f"{source_version_id}-a", f"{source_version_id}-b"],
    )
    first = DocumentNode(
        node_id=f"{source_version_id}-a",
        parent_id=root.node_id,
        ordinal=0,
        ordinal_path=(0, 0),
        kind="section",
        role="body",
        text="Insert the capsule and press the button.",
        locators=[SourceLocator(page=1)],
        method=ExtractionMethod.NATIVE,
    )
    second = DocumentNode(
        node_id=f"{source_version_id}-b",
        parent_id=root.node_id,
        ordinal=1,
        ordinal_path=(0, 1),
        kind="section",
        role="body",
        text="Soil conditions can influence coffee flavor.",
        locators=[SourceLocator(page=1)],
        method=ExtractionMethod.NATIVE,
    )
    return ExtractedDocument(
        source_version_id=source_version_id,
        extraction_run_id=run_id,
        format="pdf",
        page_count=1,
        nodes=[root, first, second],
    )


def _segments(document):
    return [
        SourceSegment(
            segment_id=f"segment-{index}-{document.source_version_id}",
            source_version_id=document.source_version_id,
            extraction_run_id=document.extraction_run_id,
            ordinal=index,
            node_ids=[node.node_id],
            hierarchy_path=[document.nodes[0].node_id, node.node_id],
            locator_start=node.locators[0],
            locator_end=node.locators[-1],
            token_count=8,
            text=node.text,
        )
        for index, node in enumerate(document.nodes[1:])
    ]


def _service(responses=None, store=None):
    responses = responses or FakeResponses()
    return SourceMappingService(
        client=SimpleNamespace(responses=responses),
        store=store or MemoryStore(),
    )


def test_document_mapping_is_bottom_up_cited_and_preserves_secondary_concepts():
    document = _document()
    responses = FakeResponses()
    service = _service(responses)

    result = service.map_document(document, _segments(document))

    assert [claim.statement for claim in result.claims] == [
        "Mapped segment-0-source-v1",
        "Mapped segment-1-source-v1",
    ]
    assert all(claim.citations for claim in result.claims)
    assert {entry.node_id for entry in result.coverage.entries} == {
        node.node_id for node in document.nodes
    }
    assert next(
        entry for entry in result.coverage.entries if entry.node_id.endswith("-root")
    ).status == CoverageStatus.UNRESOLVED
    assert sum(call["text_format"] is SynthesisDraft for call in responses.calls) == 1
    assert all("untrusted data" in call["input"][0]["content"] for call in responses.calls)


def test_completed_section_maps_are_reused_after_synthesis_failure():
    document = _document()
    store = MemoryStore()
    responses = FakeResponses()
    responses.fail_next_synthesis = True
    service = _service(responses, store)

    with pytest.raises(RuntimeError, match="synthesis unavailable"):
        service.map_document(document, _segments(document))
    service.map_document(document, _segments(document))

    assert sum(call["text_format"] is SectionMapDraft for call in responses.calls) == 2
    assert len([item for item in store.saved if item["scope_kind"] == "section"]) == 2


def test_model_local_claim_ids_are_namespaced_with_references_preserved():
    document = _document()
    segment = _segments(document)[0]
    store = MemoryStore()
    store.values[("section", document.source_version_id, segment.segment_id)] = {
        "schema_version": "source-section-map-v1",
        "map_id": "cached-map",
        "source_version_id": document.source_version_id,
        "hierarchy_path": segment.hierarchy_path,
        "segment_ids": [segment.segment_id],
        "claims": [
            MapClaim(
                claim_id="c1",
                statement="First claim",
                citations=[
                    EvidenceCitation(
                        source_version_id=document.source_version_id,
                        node_ids=[segment.node_ids[0]],
                    )
                ],
            ).model_dump(mode="json"),
            MapClaim(
                claim_id="c2",
                statement="Second claim",
                citations=[
                    EvidenceCitation(
                        source_version_id=document.source_version_id,
                        node_ids=[segment.node_ids[0]],
                    )
                ],
            ).model_dump(mode="json"),
        ],
        "relationships": [
            MapRelationship(
                relationship_id="r1",
                source_claim_id="c1",
                target_claim_id="c2",
                relationship="supports",
            ).model_dump(mode="json")
        ],
        "uncertainties": [],
        "coverage": {
            "entries": [
                CoverageEntry(
                    source_version_id=document.source_version_id,
                    node_id=segment.node_ids[0],
                    status=CoverageStatus.REPRESENTED,
                    claim_ids=["c1", "c2"],
                ).model_dump(mode="json")
            ]
        },
        "map_revision": "source-map-v1",
    }

    result = _service(store=store).map_section(document, segment)

    assert [claim.claim_id for claim in result.claims] == [
        f"{segment.segment_id}:c1",
        f"{segment.segment_id}:c2",
    ]
    assert result.relationships[0].source_claim_id == f"{segment.segment_id}:c1"
    assert result.relationships[0].target_claim_id == f"{segment.segment_id}:c2"
    assert result.coverage.entries[0].claim_ids == [
        f"{segment.segment_id}:c1",
        f"{segment.segment_id}:c2",
    ]


def test_unknown_citations_are_not_promoted_and_remain_visible_as_uncertainty():
    document = _document()
    responses = FakeResponses()
    responses.use_unknown_citation = True
    service = _service(responses)

    section_map = service.map_section(document, _segments(document)[0])

    assert section_map.claims == []
    assert section_map.coverage.entries[0].status == CoverageStatus.UNRESOLVED
    assert "unknown nodes" in section_map.uncertainties[0].description


def test_higher_level_claims_are_revalidated_against_original_nodes():
    document = _document()
    responses = FakeResponses()
    responses.use_unknown_synthesis_citation = True
    service = _service(responses)

    result = service.map_document(document, _segments(document))

    assert len(result.claims) == 1
    assert any("unknown nodes" in item.description for item in result.uncertainties)


def test_collection_mapping_preserves_authority_lineage_conflicts_and_gaps():
    first = _document("source-v1", "run-1")
    second = _document("source-v2", "run-2")
    responses = FakeResponses()
    service = _service(responses)
    document_maps = [
        service.map_document(first, _segments(first)),
        service.map_document(second, _segments(second)),
    ]
    collection = SimpleNamespace(
        collection_id="coffee-collection",
        members=(
            SimpleNamespace(
                source_version_id="source-v2", ordinal=0, authority_note="Primary manual"
            ),
            SimpleNamespace(source_version_id="source-v1", ordinal=1, authority_note=None),
        ),
    )

    result = service.map_collection(
        collection,
        document_maps,
        {first.source_version_id: first, second.source_version_id: second},
    )

    assert [source.source_version_id for source in result.sources] == [
        "source-v2",
        "source-v1",
    ]
    assert result.sources[0].authority_note == "Primary manual"
    assert result.agreements and result.overlaps and result.conflicts
    assert result.version_differences and result.gaps
    assert {
        citation.source_version_id
        for citation in result.conflicts[0].citations
    } == {"source-v1", "source-v2"}


def test_over_budget_collection_is_reduced_in_bounded_requests():
    first = _document("source-v1", "run-1")
    second = _document("source-v2", "run-2")
    responses = FakeResponses()
    service = SourceMappingService(
        client=SimpleNamespace(responses=responses),
        store=MemoryStore(),
        token_budget=CollectionReductionBudget(),
    )
    document_maps = [
        service.map_document(first, _segments(first)),
        service.map_document(second, _segments(second)),
    ]
    collection = SimpleNamespace(
        collection_id="bounded-collection",
        members=(
            SimpleNamespace(source_version_id="source-v1", ordinal=0, authority_note=None),
            SimpleNamespace(source_version_id="source-v2", ordinal=1, authority_note=None),
        ),
    )

    result = service.map_collection(
        collection,
        document_maps,
        {first.source_version_id: first, second.source_version_id: second},
    )

    operations = [call["metadata"]["operation"] for call in responses.calls]
    assert "reduce-collection-input" in operations
    assert operations[-1] == "synthesize-collection"
    assert result.collection_id == "bounded-collection"


def test_single_document_collection_reuses_grounded_document_map_without_synthesis():
    document = _document()
    document_map = _service().map_document(document, _segments(document))
    responses = FakeResponses()
    budget = SingleMapReductionBudget()
    service = SourceMappingService(
        client=SimpleNamespace(responses=responses),
        store=MemoryStore(),
        token_budget=budget,
    )
    collection = SimpleNamespace(
        collection_id="single-large-document",
        members=(
            SimpleNamespace(
                source_version_id=document.source_version_id,
                ordinal=0,
                authority_note=None,
            ),
        ),
    )

    result = service.map_collection(
        collection,
        [document_map],
        {document.source_version_id: document},
    )

    operations = [call["metadata"]["operation"] for call in responses.calls]
    assert budget.oversized_child_attempts == 0
    assert operations == []
    assert result.claims == document_map.claims
    assert result.relationships == document_map.relationships


def test_over_budget_document_uses_grounded_children_then_revalidates_citations():
    document = _document()
    responses = FakeResponses()
    service = SourceMappingService(
        client=SimpleNamespace(responses=responses),
        store=MemoryStore(),
        token_budget=OneTimeHierarchyLimitBudget(),
    )

    result = service.map_document(document, _segments(document))

    synthesis_calls = [
        call for call in responses.calls if call["text_format"] is SynthesisDraft
    ]
    assert len(synthesis_calls) == 1
    request = json.loads(synthesis_calls[0]["input"][1]["content"])
    assert request["original_nodes"] == []
    assert "reassembled and validated" in request["evidence_mode"]
    assert len(result.claims) == 2
