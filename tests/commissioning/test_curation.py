import json
from pathlib import Path
from types import SimpleNamespace

from learning_commissioning.contracts import (
    CandidateCurationReview,
    LearningCommissionRequest,
    LearningSearchIntent,
    RLOCandidateMatch,
)
from learning_commissioning.services.curation import CandidateCurationService

_ROOT = Path(__file__).parents[2]


def _request():
    return LearningCommissionRequest.model_validate_json(
        (_ROOT / "examples/reference/commissioning/cohort-request.json").read_text()
    )


def _intent():
    return LearningSearchIntent(
        primary_subject="stakeholder resistance in organizational change",
        subject_facets=("recognizing resistance", "selecting interventions"),
        desired_outcomes=("Recognize resistance", "Choose an intervention"),
        search_queries=("recognize resistance", "select resistance intervention"),
    )


def _candidate(raw, score=0.6):
    return RLOCandidateMatch(
        rlo_id=raw["id"], rlo_version=raw["version"], title=raw["title"],
        topic=raw["topic"], domain=raw["domain"], level=raw["level"],
        estimated_duration_minutes=raw["estimated_duration_minutes"],
        governance_status="approved", vector_scores={"facet-1": score},
        reciprocal_rank_fusion_score=0.016, final_score=score + 0.016,
        relevance_band="acceptable" if score >= 0.52 else "weak",
        match_reasons=("Semantic match",), source_query_ids=("facet-1",),
        storage_uri=f"memory://{raw['id']}/{raw['version']}", index_revision="rlo-index-v2",
    )


class FakeCatalog:
    def __init__(self, documents):
        self.documents = {(item["id"], item["version"]): item for item in documents}

    async def get_exact(self, rlo_id, rlo_version):
        return self.documents[(rlo_id, rlo_version)]


class FakeCompletions:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="curation-response-1",
            output_parsed=CandidateCurationReview.model_validate(self.output),
            usage=SimpleNamespace(input_tokens=500, output_tokens=150),
        )


def _client(responses):
    return SimpleNamespace(responses=SimpleNamespace(parse=responses.parse))


async def test_smart_curation_can_separate_related_frameworks():
    adkar = json.loads((_ROOT / "course-definitions/rlos/rlo-adkar-10-differentiated-interventions.json").read_text())
    kotter = json.loads((_ROOT / "course-definitions/rlos/rlo-kotter-10-institute-change.json").read_text())
    candidates = (_candidate(adkar), _candidate(kotter))
    completions = FakeCompletions({
        "strategy_summary": "Use ADKAR for individual barrier diagnosis and response.",
        "framework_approach": "Do not mix Kotter's organizational process with the requested individual ADKAR intervention task.",
        "decisions": [
            {
                "rlo_id": adkar["id"], "rlo_version": adkar["version"],
                "recommendation": "include", "conceptual_framework": "Prosci ADKAR",
                "coverage_contribution": ["selecting interventions"],
                "rationale": "Directly supports differentiated intervention selection.",
                "relationship_to_other_candidates": "Preferred over the organizational-level Kotter candidate."
            },
            {
                "rlo_id": kotter["id"], "rlo_version": kotter["version"],
                "recommendation": "exclude", "conceptual_framework": "Kotter 8 Steps",
                "coverage_contribution": [],
                "rationale": "Addresses institutionalizing change rather than diagnosing individual barriers.",
                "relationship_to_other_candidates": "Related domain, different framework and level of analysis."
            }
        ],
        "warnings": []
    })
    service = CandidateCurationService(
        FakeCatalog([adkar, kotter]), client=_client(completions), model="course-generator"
    )
    review, trace = await service.curate(_request(), _intent(), candidates)

    decisions = {decision.rlo_id: decision.recommendation for decision in review.decisions}
    assert decisions == {adkar["id"]: "include", kotter["id"]: "exclude"}
    assert trace.model == "course-generator"
    assert completions.calls[0]["model"] == "course-generator"
    sent = json.loads(completions.calls[0]["input"][1]["content"])
    assert sent["candidate_profiles"][0]["concepts"]


async def test_identity_drift_uses_safe_deterministic_fallback():
    adkar = json.loads((_ROOT / "course-definitions/rlos/rlo-adkar-10-differentiated-interventions.json").read_text())
    completions = FakeCompletions({
        "strategy_summary": "Invalid identity",
        "framework_approach": "Invalid identity",
        "decisions": [{
            "rlo_id": "invented-rlo", "rlo_version": "1.0.0",
            "recommendation": "include", "conceptual_framework": None,
            "coverage_contribution": [], "rationale": "Invalid", "relationship_to_other_candidates": None
        }],
        "warnings": []
    })
    service = CandidateCurationService(
        FakeCatalog([adkar]), client=_client(completions), model="course-generator"
    )
    review, trace = await service.curate(_request(), _intent(), (_candidate(adkar),))
    assert review.decisions[0].rlo_id == adkar["id"]
    assert trace.model is None
    assert "exactly match" in trace.fallback_reason


async def test_prerequisite_beyond_semantic_limit_is_still_reviewed():
    dependent = json.loads(
        (_ROOT / "course-definitions/rlos/rlo-kotter-06-volunteer-army.json").read_text()
    )
    prerequisite = json.loads(
        (_ROOT / "course-definitions/rlos/rlo-kotter-05-vision.json").read_text()
    )
    prerequisite_candidate = _candidate(prerequisite).model_copy(update={
        "vector_scores": {},
        "source_query_ids": ("dependency-closure",),
        "required_as_prerequisite_for": (dependent["id"],),
    })
    candidates = (_candidate(dependent), prerequisite_candidate)
    completions = FakeCompletions({
        "strategy_summary": "Include the dependent content and its prerequisite.",
        "framework_approach": "Preserve the authoritative prerequisite sequence.",
        "decisions": [
            {
                "rlo_id": dependent["id"],
                "rlo_version": dependent["version"],
                "recommendation": "include",
                "rationale": "Directly supports the request.",
            },
            {
                "rlo_id": prerequisite["id"],
                "rlo_version": prerequisite["version"],
                "recommendation": "exclude",
                "rationale": "It has no semantic-search score.",
            },
        ],
        "warnings": [],
    })
    service = CandidateCurationService(
        FakeCatalog([dependent, prerequisite]),
        client=_client(completions),
        model="course-generator",
        review_limit=1,
    )

    review, trace = await service.curate(_request(), _intent(), candidates)

    assert len(review.decisions) == 2
    assert {decision.recommendation for decision in review.decisions} == {"include"}
    assert "Included by dependency policy" in review.decisions[1].rationale
    assert trace.reviewed_candidate_count == 2
    sent = json.loads(completions.calls[0]["input"][1]["content"])
    assert len(sent["candidate_profiles"]) == 2
    assert sent["candidate_profiles"][1]["required_as_prerequisite_for"] == [
        dependent["id"]
    ]
    assert sent["candidate_profiles"][0]["prerequisites"]
