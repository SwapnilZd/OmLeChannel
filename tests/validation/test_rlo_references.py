"""Tests for validate_rlo_selection — cross-contract RLO reference validation."""

from __future__ import annotations

import json
import pathlib

import pytest

from learning_pipeline.contracts import (
    RLOContentSelection,
    RLODocument,
    TailoredRLORef,
    TopicProficiency,
)
from learning_pipeline.validation.errors import CrossContractValidationError
from learning_pipeline.validation.rlo_references import validate_rlo_selection

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_RLO_PATH = _REPO_ROOT / "course-definitions" / "rlos" / "rlo-adkar-01-name-and-sequence.json"


@pytest.fixture(scope="module")
def rlo() -> RLODocument:
    return RLODocument.model_validate(json.loads(_RLO_PATH.read_text()))


def _make_ref(
    rlo_id: str = "rlo-adkar-01-name-and-sequence",
    rlo_version: str = "1.1.0",
    selected_content: RLOContentSelection | None = None,
) -> TailoredRLORef:
    if selected_content is None:
        selected_content = RLOContentSelection(objective_ids=("lo-01",))
    return TailoredRLORef(
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


# ── Happy path ────────────────────────────────────────────────────────────────


def test_valid_full_selection_passes(rlo: RLODocument) -> None:
    ref = _make_ref(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            concept_ids=("c-01",),
            component_ids=("comp-hook-01", "comp-rule-01"),
            assessment_item_ids=("q-01",),
        )
    )
    validate_rlo_selection(ref, rlo)


def test_valid_objective_only_selection_passes(rlo: RLODocument) -> None:
    ref = _make_ref(selected_content=RLOContentSelection(objective_ids=("lo-01",)))
    validate_rlo_selection(ref, rlo)


# ── Negative: identity checks (tests 1 and 2) ─────────────────────────────────


def test_unknown_rlo_id_rejected(rlo: RLODocument) -> None:
    ref = _make_ref(rlo_id="unknown-rlo-id")
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_rlo_selection(ref, rlo)
    assert exc_info.value.code == "rlo_not_found"


def test_incorrect_rlo_version_rejected(rlo: RLODocument) -> None:
    ref = _make_ref(rlo_version="9.9.9")
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_rlo_selection(ref, rlo)
    assert exc_info.value.code == "rlo_version_mismatch"
    assert "9.9.9" in str(exc_info.value)


# ── Negative: empty selection ──────────────────────────────────────────────────


def test_empty_selection_rejected(rlo: RLODocument) -> None:
    ref = _make_ref(selected_content=RLOContentSelection())
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_rlo_selection(ref, rlo)
    assert exc_info.value.code == "content_not_selected"


# ── Negative: unknown content references (tests 3–6) ──────────────────────────


def test_unknown_objective_reference_rejected(rlo: RLODocument) -> None:
    ref = _make_ref(
        selected_content=RLOContentSelection(objective_ids=("nonexistent-lo",))
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_rlo_selection(ref, rlo)
    assert exc_info.value.code == "content_reference_not_found"
    assert "nonexistent-lo" in str(exc_info.value)


def test_unknown_concept_reference_rejected(rlo: RLODocument) -> None:
    ref = _make_ref(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            concept_ids=("nonexistent-concept",),
        )
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_rlo_selection(ref, rlo)
    assert exc_info.value.code == "content_reference_not_found"
    assert "nonexistent-concept" in str(exc_info.value)


def test_unknown_component_reference_rejected(rlo: RLODocument) -> None:
    ref = _make_ref(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            component_ids=("nonexistent-comp",),
        )
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_rlo_selection(ref, rlo)
    assert exc_info.value.code == "content_reference_not_found"
    assert "nonexistent-comp" in str(exc_info.value)


def test_unknown_assessment_reference_rejected(rlo: RLODocument) -> None:
    ref = _make_ref(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            assessment_item_ids=("nonexistent-q",),
        )
    )
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_rlo_selection(ref, rlo)
    assert exc_info.value.code == "content_reference_not_found"
    assert "nonexistent-q" in str(exc_info.value)
