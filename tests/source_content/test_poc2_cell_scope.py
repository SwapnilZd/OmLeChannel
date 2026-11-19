from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.source_authoring.cell_scope import POC2_CELL_SET, is_poc2_cell
from src.source_authoring.contracts import (
    ObjectiveBloomDecision,
    ObjectiveCandidate,
    ObjectiveClassification,
    ObjectiveKindDecision,
)
from src.source_authoring.generation_contracts import (
    AuthoringReviewDraft,
    TargetPlanDraft,
)
from src.source_authoring.objectives import (
    ObjectiveClassificationDraft,
    ObjectiveDiscoveryService,
)
from src.source_authoring.authoring_contracts import ClassificationDecision
from src.source_authoring.methodology import get_methodology_profile
from tests.source_content.test_rlo_drafting import _workspace


EXPECTED = {
    ("fact", "remember"),
    ("concept", "understand"),
    ("concept", "apply"),
    ("process", "understand"),
    ("procedure", "apply"),
}


def _decision(kind, bloom):
    return ClassificationDecision(
        content_type=kind,
        bloom_level=bloom,
        confidence="high",
        rationale="Test classification.",
    )


def _objective_classification(kind, bloom):
    return ObjectiveClassification(
        content_kind=ObjectiveKindDecision(
            value=kind,
            confidence="high",
            rationale="Test content kind.",
        ),
        bloom=ObjectiveBloomDecision(
            value=bloom,
            confidence="high",
            rationale="Test Bloom level.",
            expected_practice="Perform the objective.",
        ),
        combined_confidence="high",
        rule_ids=["C-1", "C-2"],
    )


def test_poc2_policy_contains_exactly_the_five_approved_cells():
    assert POC2_CELL_SET == EXPECTED
    for kind, bloom in EXPECTED:
        assert is_poc2_cell(kind, bloom)
        assert get_methodology_profile(kind, bloom).profile_id == f"{kind}-{bloom}"
        assert TargetPlanDraft(classification=_decision(kind, bloom))
        assert ObjectiveClassificationDraft(
            candidate_id="candidate-1",
            classification=_objective_classification(kind, bloom),
        )
        assert AuthoringReviewDraft(observed_classification=_decision(kind, bloom))


@pytest.mark.parametrize(
    ("kind", "bloom"),
    [
        ("fact", "understand"),
        ("concept", "analyze"),
        ("process", "apply"),
        ("process", "analyze"),
        ("procedure", "analyze"),
        ("principle", "apply"),
        ("principle", "analyze"),
        ("principle", "evaluate"),
    ],
)
def test_former_cells_are_not_executable(kind, bloom):
    assert not is_poc2_cell(kind, bloom)
    with pytest.raises(ValueError, match="unsupported RLO classification cell"):
        get_methodology_profile(kind, bloom)
    with pytest.raises(ValidationError, match="outside the five POC2 cells"):
        TargetPlanDraft(classification=_decision(kind, bloom))
    with pytest.raises(ValidationError, match="outside the five POC2 cells"):
        ObjectiveClassificationDraft(
            candidate_id="candidate-1",
            classification=_objective_classification(kind, bloom),
        )
    review = AuthoringReviewDraft(observed_classification=_decision(kind, bloom))
    assert review.observed_classification is None
    assert review.findings[0].code == "target_observed_mismatch"


def test_historical_outside_scope_candidate_still_deserializes_for_audit():
    raw = _workspace().candidates[0].model_dump(mode="json")
    raw.pop("poc2_scope_status", None)
    raw.pop("poc2_scope_reason", None)
    raw["classification"]["content_kind"]["value"] = "principle"
    raw["classification"]["bloom"]["value"] = "analyze"

    candidate = ObjectiveCandidate.model_validate(raw)

    assert candidate.classification.content_kind.value == "principle"
    assert candidate.poc2_scope_status == "outside_poc2_scope"
    assert candidate.poc2_scope_reason


def test_revised_objective_can_be_reclassified_before_approval():
    candidate = _workspace().candidates[0].model_copy(
        update={
            "classification": None,
            "poc2_scope_status": "needs_review",
            "poc2_scope_reason": "Objective changed.",
        }
    )
    expected = ObjectiveClassificationDraft(
        candidate_id=candidate.candidate_id,
        classification=_objective_classification("procedure", "apply"),
    )

    class Responses:
        def __init__(self):
            self.input = None

        def parse(self, **kwargs):
            self.input = kwargs["input"]
            return SimpleNamespace(output_parsed=expected, usage=None)

    responses = Responses()
    service = ObjectiveDiscoveryService(
        client=SimpleNamespace(responses=responses)
    )
    workspace = _workspace()

    result = service.classify_revised_candidate(
        candidate,
        brief=workspace.learning_brief,
        sibling_statements=[],
        workspace_id=workspace.workspace_id,
    )

    assert result.scope_status == "supported"
    assert result.classification.bloom.value == "apply"
    assert "poc2_scope_status" not in responses.input[1]["content"]
