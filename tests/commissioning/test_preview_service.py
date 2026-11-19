import json
from pathlib import Path

import pytest

from learning_commissioning.contracts import (
    ConfirmedRLOCandidate,
    ContentGap,
    ContentGapReport,
    GapSeverity,
    LearningCommissionRequest,
    LearningRequestConfirmation,
    LearningSearchIntent,
    RelevanceBand,
    RLOCandidateDisposition,
    RLOCandidateMatch,
    SearchInterpretationTrace,
)
from learning_commissioning.repository import InMemoryPreviewRepository
from learning_commissioning.services.preview import (
    ConfirmationRejectedError,
    LearningRequestPreviewService,
    StalePreviewError,
)
from learning_commissioning.services.retrieval import RetrievalOutcome

_ROOT = Path(__file__).parents[2]


def _request():
    return LearningCommissionRequest.model_validate_json(
        (_ROOT / "examples/reference/commissioning/cohort-request.json").read_text()
    )


def _approved_rlo():
    raw = json.loads(
        (_ROOT / "course-definitions/rlos/rlo-adkar-01-name-and-sequence.json").read_text()
    )
    raw["governance"].update({
        "status": "approved",
        "signoff_date": "2026-07-22",
        "signoff_authority": "Test SME",
    })
    return raw


class StubInterpreter:
    async def interpret(self, request):
        intent = LearningSearchIntent(
            primary_subject="ADKAR sequencing",
            subject_facets=("ADKAR sequencing",),
            search_queries=("ADKAR elements sequence",),
        )
        return intent, SearchInterpretationTrace(
            request_hash="request-hash",
            intent_hash="intent-hash",
            prompt_version="commissioning-search-v2",
            model="course-generator-mini",
        )


class StubDiscovery:
    def __init__(self, sufficient=True, compatibility_errors=()):
        self.sufficient = sufficient
        self.compatibility_errors = compatibility_errors

    async def discover(self, request, intent):
        raw = _approved_rlo()
        candidate = RLOCandidateMatch(
            rlo_id=raw["id"],
            rlo_version=raw["version"],
            title=raw["title"],
            topic=raw["topic"],
            domain=raw["domain"],
            level=raw["level"],
            estimated_duration_minutes=raw["estimated_duration_minutes"],
            governance_status="approved",
            vector_scores={"facet-1": 0.7},
            reciprocal_rank_fusion_score=0.016,
            final_score=0.716,
            relevance_band=RelevanceBand.STRONG,
            match_reasons=("Direct semantic match",),
            source_query_ids=("facet-1",),
            storage_uri=f"memory://{raw['id']}/{raw['version']}",
            index_revision="rlo-index-v2",
        )
        gaps = () if self.sufficient else (ContentGap(
            subject="ADKAR sequencing",
            severity=GapSeverity.BLOCKING,
            explanation="No approved content.",
            recommendation="Add an approved RLO.",
        ),)
        return RetrievalOutcome(
            candidates=(candidate,) if self.sufficient else (),
            gap_report=ContentGapReport(
                sufficient=self.sufficient,
                covered_subject_facets=("ADKAR sequencing",) if self.sufficient else (),
                gaps=gaps,
                retrieval_policy_version="retrieval-v1",
                explanation="Covered." if self.sufficient else "Insufficient approved content.",
            ),
            index_revision="rlo-index-v2",
            embedding_model="component-embedder",
            compatibility_errors=self.compatibility_errors,
        )


class StubCatalog:
    def __init__(self, current=True):
        self.raw = _approved_rlo()
        self.current = current

    async def get_versions(self, rlo_id):
        return [{
            "rlo_id": rlo_id,
            "rlo_version": self.raw["version"] if self.current else "9.0.0",
            "is_current": True,
        }]

    async def get_exact(self, rlo_id, rlo_version):
        return self.raw


def _service(*, sufficient=True, current=True, compatibility_errors=()):
    return LearningRequestPreviewService(
        StubInterpreter(),
        StubDiscovery(sufficient, compatibility_errors),
        StubCatalog(current),
        InMemoryPreviewRepository(),
    )


def _confirmation(preview):
    candidate = preview.candidates[0]
    return LearningRequestConfirmation(
        preview_hash=preview.preview_hash,
        confirmed_course_goal="Apply the ADKAR framework correctly.",
        candidates=(ConfirmedRLOCandidate(
            rlo_id=candidate.rlo_id,
            rlo_version=candidate.rlo_version,
            disposition=RLOCandidateDisposition.INCLUDE,
        ),),
        confirmation_actor="manager@example.test",
    )


async def test_identical_snapshot_returns_same_immutable_preview():
    service = _service()
    first = await service.create_preview(_request())
    second = await service.create_preview(_request())
    assert first == second
    assert first.confirmation_allowed is True


async def test_preview_surfaces_catalog_compatibility_exclusions():
    service = _service(compatibility_errors=("rlo-broken@1.0.0: unsupported shape",))
    preview = await service.create_preview(_request())

    assert preview.compatibility_errors == ("rlo-broken@1.0.0: unsupported shape",)


async def test_blocking_gap_rejects_confirmation():
    service = _service(sufficient=False)
    preview = await service.create_preview(_request())
    command = LearningRequestConfirmation(
        preview_hash=preview.preview_hash,
        confirmed_course_goal="A goal",
        candidates=(ConfirmedRLOCandidate(
            rlo_id="not-eligible",
            rlo_version="1.0.0",
            disposition=RLOCandidateDisposition.INCLUDE,
        ),),
        confirmation_actor="manager@example.test",
    )
    with pytest.raises(ConfirmationRejectedError):
        await service.confirm(preview.preview_id, command)


async def test_confirmation_revalidates_current_exact_version():
    service = _service()
    preview = await service.create_preview(_request())
    confirmed = await service.confirm(preview.preview_id, _confirmation(preview))
    assert confirmed.preview_hash == preview.preview_hash
    assert await service.confirm(preview.preview_id, _confirmation(preview)) == confirmed

    stale_service = _service(current=False)
    stale_preview = await stale_service.create_preview(_request())
    with pytest.raises(StalePreviewError, match="no longer current"):
        await stale_service.confirm(stale_preview.preview_id, _confirmation(stale_preview))
