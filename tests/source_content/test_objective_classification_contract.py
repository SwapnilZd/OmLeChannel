import pytest
from pydantic import ValidationError

from src.source_authoring.contracts import (
    ObjectiveBloomDecision,
    ObjectiveClassification,
    ObjectiveKindDecision,
)


def _classification(**updates):
    values = {
        "content_kind": ObjectiveKindDecision(
            value="procedure",
            confidence="high",
            rationale="The learner executes single-actor steps.",
        ),
        "bloom": ObjectiveBloomDecision(
            value="apply",
            confidence="medium",
            rationale="The learner performs the steps in an unambiguous case.",
            expected_practice="Execute the procedure in a new routine case.",
        ),
        "combined_confidence": "medium",
        "rule_ids": ["C-2", "C-7", "C-13", "C-20"],
    }
    values.update(updates)
    return ObjectiveClassification(**values)


def test_classification_accepts_a_valid_cell_and_lower_axis_confidence():
    classification = _classification()

    assert classification.content_kind.value == "procedure"
    assert classification.bloom.value == "apply"
    assert classification.combined_confidence == "medium"


def test_objective_stage_classification_is_always_provisional():
    classification = _classification(provisional=False)

    assert classification.provisional is True


def test_classification_rejects_an_unsupported_cell():
    with pytest.raises(ValidationError, match="unsupported classification cell"):
        _classification(
            bloom=ObjectiveBloomDecision(
                value="understand",
                confidence="medium",
                rationale="The learner explains the steps.",
                expected_practice="Explain the steps.",
            )
        )


def test_classification_rejects_averaged_or_inflated_confidence():
    with pytest.raises(ValidationError, match="lower axis confidence"):
        _classification(combined_confidence="high")


def test_escalation_requires_an_alternative_and_discriminator_question():
    with pytest.raises(ValidationError, match="requires alternatives"):
        _classification(escalation_required=True)

    classification = _classification(
        escalation_required=True,
        plausible_alternative_cells=["concept-apply"],
        discriminator_question="Does the learner classify a case or execute steps?",
    )
    assert classification.escalation_required is True


def test_plausible_alternative_implies_escalation():
    classification = _classification(
        plausible_alternative_cells=["concept-apply"],
        discriminator_question="Does the learner classify a case or execute steps?",
    )

    assert classification.escalation_required is True


def test_classification_normalizes_explanatory_model_cell_values():
    classification = _classification(
        rejected_cells=[
            "Procedure × Apply: rejected because the learner analyzes the procedure.",
            "concept-understand",
        ]
    )

    assert classification.rejected_cells == ["procedure-apply", "concept-understand"]


def test_low_confidence_classification_must_escalate():
    with pytest.raises(ValidationError, match="must be escalated"):
        _classification(
            bloom=ObjectiveBloomDecision(
                value="apply",
                confidence="low",
                rationale="Expected practice is not present in the source.",
                expected_practice="Classify or execute in a new case.",
            ),
            combined_confidence="low",
        )
