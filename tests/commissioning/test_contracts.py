from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from learning_commissioning.contracts import (
    AudienceProfile,
    ContentGapReport,
    LearningCommissionRequest,
    LearningRequestPreview,
    LearningSearchIntent,
    RLOCandidateMatch,
    SearchInterpretationTrace,
)

_ROOT = Path(__file__).parents[2]
_REQUEST = _ROOT / "examples/reference/commissioning/cohort-request.json"
_SCENARIOS = Path(__file__).parent / "fixtures/retrieval_scenarios.json"


def _request() -> LearningCommissionRequest:
    return LearningCommissionRequest.model_validate_json(_REQUEST.read_text(encoding="utf-8"))


def _intent() -> LearningSearchIntent:
    return LearningSearchIntent(
        primary_subject="stakeholder resistance during organizational change",
        subject_facets=("recognizing resistance", "selecting interventions"),
        skills=("diagnose resistance", "select an intervention"),
        desired_outcomes=("Choose a proportionate response",),
        required_concepts=("resistance signals",),
        search_queries=(
            "recognizing stakeholder resistance signals",
            "selecting interventions for change resistance",
        ),
    )


def test_legacy_multi_role_request_fixture_is_strict_and_valid():
    request = _request()
    assert request.audience.roles == ("Manager", "Senior Manager")
    assert request.audience.deloitte_levels == (45, 55)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        LearningCommissionRequest.model_validate(
            {**request.model_dump(), "model_selected_rlo_ids": ["not-allowed"]}
        )


def test_individual_request_does_not_require_a_role():
    audience = AudienceProfile(
        current_proficiency="beginner",
        target_proficiency="intermediate",
    )

    assert audience.roles == ()


def test_audience_target_proficiency_cannot_regress():
    with pytest.raises(ValidationError, match="target_proficiency"):
        AudienceProfile(
            roles=("Manager",),
            current_proficiency="advanced",
            target_proficiency="beginner",
        )


def test_search_intent_requires_one_query_per_subject_facet():
    with pytest.raises(ValidationError, match="same length"):
        LearningSearchIntent(
            primary_subject="change resistance",
            subject_facets=("recognition", "response"),
            search_queries=("recognizing resistance",),
        )


def test_search_intent_cannot_set_retrieval_internals():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        LearningSearchIntent.model_validate(
            {
                **_intent().model_dump(),
                "qdrant_filter": {"governance_status": "approved"},
                "selected_rlo_ids": ["rlo-injected"],
            }
        )


def test_retrieval_scenarios_exercise_confirmation_policy():
    scenarios = json.loads(_SCENARIOS.read_text(encoding="utf-8"))
    allowed = {}
    for name, scenario in scenarios.items():
        candidates = tuple(
            RLOCandidateMatch.model_validate(candidate)
            for candidate in scenario["candidates"]
        )
        report = ContentGapReport.model_validate(scenario["gap_report"])
        preview = LearningRequestPreview(
            preview_id=f"preview-{name}",
            preview_hash=f"hash-{name}",
            request=_request(),
            intent=_intent(),
            candidates=candidates,
            gap_report=report,
            interpretation_trace=SearchInterpretationTrace(
                request_hash="request-hash",
                intent_hash="intent-hash",
                prompt_version="commissioning-search-v2",
                model=None,
                fallback_reason="fixture",
            ),
            retrieval_policy_version="retrieval-v1",
            index_revision="rlo-index-v2",
            created_at=datetime.now(UTC),
        )
        allowed[name] = preview.confirmation_allowed
    assert allowed == {"sufficient": True, "partial": False, "insufficient": False}


def test_insufficient_report_requires_a_blocking_gap():
    with pytest.raises(ValidationError, match="blocking gap"):
        ContentGapReport(
            sufficient=False,
            gaps=(),
            retrieval_policy_version="retrieval-v1",
            explanation="No content.",
        )
