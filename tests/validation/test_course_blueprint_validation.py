"""Tests for validate_course_blueprint — cross-contract blueprint validation."""

from __future__ import annotations

import json
import pathlib

import pytest

from learning_pipeline.contracts import (
    CourseBlueprint,
    LearnerContext,
    RLOContentSelection,
    RLODocument,
    TailoredRLORef,
    TopicProficiency,
)
from learning_pipeline.validation.course_blueprint import validate_course_blueprint
from learning_pipeline.validation.errors import CrossContractValidationError

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_RLO_PATH = _REPO_ROOT / "course-definitions" / "rlos" / "rlo-adkar-01-name-and-sequence.json"
_FIXTURE_DIR = _REPO_ROOT / "examples" / "reference" / "podcast"


@pytest.fixture(scope="module")
def rlo() -> RLODocument:
    return RLODocument.model_validate(json.loads(_RLO_PATH.read_text()))


@pytest.fixture(scope="module")
def blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate(
        json.loads((_FIXTURE_DIR / "course_blueprint.json").read_text())
    )


_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Learn ADKAR",),
)


def _make_blueprint(
    rlo_id: str = "rlo-adkar-01-name-and-sequence",
    rlo_version: str = "1.1.0",
    selected_content: RLOContentSelection | None = None,
    learning_outcomes: tuple[str, ...] = ("outcome 1",),
) -> CourseBlueprint:
    if selected_content is None:
        selected_content = RLOContentSelection(
            objective_ids=("lo-01",),
            concept_ids=("c-01",),
            component_ids=("comp-hook-01",),
            assessment_item_ids=("q-01",),
        )
    tailored_ref = TailoredRLORef(
        rlo_id=rlo_id,
        rlo_version=rlo_version,
        order=1,
        selected_content=selected_content,
        starting_proficiency=TopicProficiency.BEGINNER,
        target_proficiency=TopicProficiency.INTERMEDIATE,
        role_relevance="relevant",
        personalization_rationale="rationale",
        sequencing_rationale="sequence",
    )
    return CourseBlueprint(
        blueprint_id="bp-test",
        learner=_LEARNER,
        title="Test Blueprint",
        learning_outcomes=learning_outcomes,
        ordered_rlo_refs=(tailored_ref,),
        sequencing_rationale="sequence",
        assessment_strategy="assessment",
        estimated_duration_minutes=10,
        source_rlo_versions={rlo_id: rlo_version},
    )


# ── Happy path ────────────────────────────────────────────────────────────────


def test_reference_blueprint_passes(rlo: RLODocument, blueprint: CourseBlueprint) -> None:
    validate_course_blueprint(blueprint, (rlo,))


def test_minimal_valid_blueprint_passes(rlo: RLODocument) -> None:
    bp = _make_blueprint()
    validate_course_blueprint(bp, (rlo,))


# ── Negative: unknown / mismatched RLO (tests 1 and 2) ───────────────────────


def test_unknown_rlo_id_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint(rlo_id="completely-unknown-rlo")
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_course_blueprint(bp, (rlo,))
    assert exc_info.value.code == "rlo_not_found"


def test_incorrect_rlo_version_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint(rlo_version="9.9.9")
    # Create a second RLO object with the same ID but version "9.9.9" isn't available;
    # supply the real RLO (version 1.1.0) so the version mismatch is caught.
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_course_blueprint(bp, (rlo,))
    assert exc_info.value.code == "rlo_version_mismatch"
    assert "9.9.9" in str(exc_info.value)


# ── Negative: content reference errors (tests 3–6) ───────────────────────────


def test_unknown_objective_in_selection_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint(
        selected_content=RLOContentSelection(objective_ids=("nonexistent-lo",))
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_course_blueprint(bp, (rlo,))
    assert exc_info.value.code == "content_reference_not_found"


def test_unknown_concept_in_selection_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            concept_ids=("nonexistent-concept",),
        )
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_course_blueprint(bp, (rlo,))
    assert exc_info.value.code == "content_reference_not_found"


def test_unknown_component_in_selection_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            component_ids=("nonexistent-comp",),
        )
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_course_blueprint(bp, (rlo,))
    assert exc_info.value.code == "content_reference_not_found"


def test_unknown_assessment_in_selection_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            assessment_item_ids=("nonexistent-q",),
        )
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_course_blueprint(bp, (rlo,))
    assert exc_info.value.code == "content_reference_not_found"
