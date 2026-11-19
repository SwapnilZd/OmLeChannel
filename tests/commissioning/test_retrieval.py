import json
from pathlib import Path

from learning_commissioning.contracts import LearningCommissionRequest, LearningSearchIntent
from learning_commissioning.services.retrieval import (
    CatalogBatchResponse,
    RLODiscoveryService,
)

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


def _intent():
    return LearningSearchIntent(
        primary_subject="organizational change frameworks",
        subject_facets=("sequencing the ADKAR elements",),
        desired_outcomes=("Sequence the five elements",),
        search_queries=("ADKAR elements correct sequence",),
    )


class FakeCatalog:
    def __init__(self, raw, score=0.70, context_tags=True, documents=None):
        self.raw = raw
        self.score = score
        self.context_tags = context_tags
        values = documents or [raw]
        self.documents = {(item["id"], item["version"]): item for item in values}
        self.payload = None

    async def search_batch(self, payload):
        self.payload = payload
        return CatalogBatchResponse.model_validate({
            "index_revision": "rlo-index-v2",
            "embedding_model": "component-embedder",
            "results": [{
                "query_id": "facet-1",
                "hits": [{
                    "rlo_id": self.raw["id"],
                    "rlo_version": self.raw["version"],
                    "score": self.score,
                    "title": self.raw["title"],
                    "topic": self.raw["topic"],
                    "domain": self.raw["domain"],
                    "level": self.raw["level"],
                    "language": self.raw["language"],
                    "locale": self.raw["locale"],
                    "estimated_duration_minutes": self.raw["estimated_duration_minutes"],
                    "governance_status": "approved",
                    "audience": self.raw["audience"],
                    "industry_tags": ["Financial Services"] if self.context_tags else [],
                    "role_tags": ["Manager"] if self.context_tags else [],
                    "service_line_tags": ["Human Capital"] if self.context_tags else [],
                    "competency_tags": self.raw["competency_map"],
                    "regulatory_tags": self.raw["regulatory_tags"],
                    "storage_uri": f"minio://rlos/{self.raw['id']}/{self.raw['version']}.json",
                }],
            }],
        })

    async def get_exact(self, rlo_id, rlo_version):
        return self.documents[(rlo_id, rlo_version)]

    async def get_versions(self, rlo_id):
        matches = [
            item for (item_id, _), item in self.documents.items()
            if item_id == rlo_id
        ]
        if not matches:
            raise ValueError(f"missing RLO {rlo_id}")
        current = matches[0]
        return [{
            "rlo_id": rlo_id,
            "rlo_version": current["version"],
            "is_current": True,
            "storage_uri": f"minio://rlos/{rlo_id}/{current['version']}.json",
        }]


async def test_discovery_fuses_hydrates_boosts_and_reports_sufficient_content():
    catalog = FakeCatalog(_approved_rlo())
    outcome = await RLODiscoveryService(catalog).discover(_request(), _intent())

    assert outcome.gap_report.sufficient is True
    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].relevance_band == "strong"
    assert outcome.candidates[0].facet_boost_score > 0
    filters = catalog.payload["queries"][0]["filters"]
    assert filters["statuses"] == ["approved"]
    assert filters["active_only"] is True
    assert filters["industry_tags"] == []  # boost mode is not a hard filter


async def test_incompatible_rlo_is_excluded_and_creates_blocking_gap():
    raw = _approved_rlo()
    raw["components"][0]["canonical_content"] = [{"unsupported": "downstream"}]
    outcome = await RLODiscoveryService(FakeCatalog(raw)).discover(_request(), _intent())

    assert outcome.candidates == ()
    assert outcome.gap_report.sufficient is False
    assert outcome.gap_report.gaps[0].severity == "blocking"
    assert outcome.gap_report.gaps[0].filters_responsible == ("assembly_compatibility",)
    assert outcome.compatibility_errors


async def test_context_boost_cannot_promote_weak_semantic_content():
    outcome = await RLODiscoveryService(FakeCatalog(_approved_rlo(), score=0.48)).discover(
        _request(), _intent()
    )
    assert outcome.candidates[0].final_score > 0.52
    assert outcome.candidates[0].relevance_band == "weak"
    assert outcome.gap_report.sufficient is False


async def test_missing_context_tags_do_not_create_a_content_gap():
    outcome = await RLODiscoveryService(
        FakeCatalog(_approved_rlo(), context_tags=False)
    ).discover(_request(), _intent())

    assert outcome.gap_report.sufficient is True
    assert outcome.gap_report.gaps == ()


async def test_discovery_expands_transitive_prerequisites_for_candidate_review():
    documents = [
        json.loads(path.read_text())
        for path in sorted(
            (_ROOT / "course-definitions/rlos").glob("rlo-kotter-0[1-6]-*.json")
        )
    ]
    volunteer_army = next(
        item for item in documents if item["id"] == "rlo-kotter-06-volunteer-army"
    )
    outcome = await RLODiscoveryService(
        FakeCatalog(volunteer_army, documents=documents)
    ).discover(_request(), _intent())

    assert {candidate.rlo_id for candidate in outcome.candidates} == {
        f"rlo-kotter-0{index}-{suffix}"
        for index, suffix in (
            (1, "name-and-sequence"),
            (2, "sequenced-process"),
            (3, "urgency"),
            (4, "coalition"),
            (5, "vision"),
            (6, "volunteer-army"),
        )
    }
    vision = next(
        candidate for candidate in outcome.candidates
        if candidate.rlo_id == "rlo-kotter-05-vision"
    )
    assert vision.required_as_prerequisite_for == ("rlo-kotter-06-volunteer-army",)
    assert vision.relevance_band == "acceptable"
    assert vision.vector_scores == {}
    assert outcome.gap_report.sufficient is True


async def test_explicitly_excluded_prerequisite_creates_early_blocking_gap():
    documents = [
        json.loads(path.read_text())
        for path in sorted(
            (_ROOT / "course-definitions/rlos").glob("rlo-kotter-0[1-6]-*.json")
        )
    ]
    volunteer_army = next(
        item for item in documents if item["id"] == "rlo-kotter-06-volunteer-army"
    )
    request = _request().model_copy(update={
        "excluded_rlo_ids": ("rlo-kotter-05-vision",),
    })
    outcome = await RLODiscoveryService(
        FakeCatalog(volunteer_army, documents=documents)
    ).discover(request, _intent())

    assert outcome.gap_report.sufficient is False
    gap = next(
        gap for gap in outcome.gap_report.gaps
        if gap.subject == "prerequisite rlo-kotter-05-vision"
    )
    assert gap.severity == "blocking"
    assert gap.filters_responsible == ("prerequisite_dependency",)


def test_retrieval_judgments_reference_real_rlos_and_have_disjoint_labels():
    judgments = json.loads(
        (Path(__file__).parent / "fixtures/retrieval_judgments.json").read_text()
    )
    catalog_ids = {path.stem for path in (_ROOT / "course-definitions/rlos").glob("*.json")}
    assert len(judgments) >= 6
    for judgment in judgments:
        labels = [set(judgment[name]) for name in ("expected", "acceptable", "weak", "forbidden")]
        assert set.union(*labels) <= catalog_ids
        assert sum(len(label) for label in labels) == len(set.union(*labels))
