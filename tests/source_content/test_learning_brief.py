import json
from types import SimpleNamespace

from src.source_authoring.contracts import PractitionerInstructions, PractitionerLens
from src.source_authoring.objectives import LensDraft, ObjectiveDiscoveryService
from src.source_ingestion.contracts import (
    CollectionMap,
    CollectionSource,
    CoverageEntry,
    CoverageLedger,
    CoverageStatus,
    EvidenceCitation,
    MapClaim,
)


class BriefStore:
    def __init__(self):
        self.briefs = []

    def save_brief(self, brief):
        self.briefs.append(brief)
        return brief


class LensResponses:
    def __init__(self):
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        parsed = LensDraft(
            lenses=[
                PractitionerLens(
                    lens_id="lens-1",
                    title="Coffee preparer",
                    practitioner_role="Person preparing coffee",
                    relevant_tasks=["Prepare a consistent cup"],
                    rationale="The source directly describes coffee preparation.",
                    inferred=False,
                )
            ],
            assumptions=["The learner has access to the machine."],
        )
        return SimpleNamespace(output_parsed=parsed, usage=None)


def _collection_map():
    claim = MapClaim(
        claim_id="claim-brew",
        statement="The machine prepares coffee after the user inserts a capsule.",
        citations=[EvidenceCitation(source_version_id="source-v1", node_ids=["node-1"])],
    )
    return CollectionMap(
        map_id="collection-map-1",
        collection_id="collection-1",
        sources=[CollectionSource(source_version_id="source-v1", ordinal=0)],
        document_map_ids=["document-map-1"],
        claims=[claim],
        coverage=CoverageLedger(
            entries=[
                CoverageEntry(
                    source_version_id="source-v1",
                    node_id="node-1",
                    status=CoverageStatus.REPRESENTED,
                    claim_ids=[claim.claim_id],
                )
            ]
        ),
        map_revision="source-map-v1",
    )


def test_learning_brief_does_not_require_admin_context_and_labels_inference():
    responses = LensResponses()
    store = BriefStore()
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=store,
    )

    brief = service.create_learning_brief(_collection_map())

    assert brief.instructions is None
    assert brief.lenses[0].inferred is True
    assert brief.assumptions == ["The learner has access to the machine."]
    request = json.loads(responses.calls[0]["input"][1]["content"])
    assert request["admin_instructions"] is None


def test_learning_brief_uses_optional_admin_context_without_making_it_source_evidence():
    responses = LensResponses()
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses),
        store=BriefStore(),
    )
    instructions = PractitionerInstructions(
        roles=["Office hospitality lead"],
        tasks=["Prepare coffee for a client meeting"],
        exclusions=["Machine maintenance"],
        duration_minutes=10,
    )

    brief = service.create_learning_brief(_collection_map(), instructions)

    assert brief.instructions == instructions
    assert brief.lenses[0].inferred is False
    assert brief.exclusions == ["Machine maintenance"]
    request = json.loads(responses.calls[0]["input"][1]["content"])
    assert request["admin_instructions"]["roles"] == ["Office hospitality lead"]
