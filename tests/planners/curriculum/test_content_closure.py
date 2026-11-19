"""Content closure validation and expansion tests — Phase 12."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts.assembly import RLOContentSelection
from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import TailoredRLODraft
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.content_closure import (
    ContentClosureError,
    validate_and_close_selection,
)
from learning_pipeline.planners.curriculum.context import build_assembly_context

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _draft(sel: RLOContentSelection, rlo_id="rlo-adkar-01-name-and-sequence") -> TailoredRLODraft:
    return TailoredRLODraft(
        rlo_id=rlo_id,
        rlo_version="1.1.0",
        order=1,
        selected_content=sel,
        target_proficiency=TopicProficiency.INTERMEDIATE,
        content_depth=ContentDepth.WORKING,
        role_relevance="Test role relevance",
        personalization_rationale="Test rationale.",
        sequencing_rationale="First and only.",
    )


def test_full_selection_passes():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection(
        objective_ids=("lo-01",),
        concept_ids=("c-01",),
        component_ids=("comp-hook-01",),
        assessment_item_ids=("q-01",),
    )
    closed, added = validate_and_close_selection(_draft(sel), ctx)
    assert closed.concept_ids == ("c-01",)
    assert added == ()


def test_component_dependency_auto_expanded():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    # comp-hook-01 references c-01 — select component but omit concept
    sel = RLOContentSelection(
        component_ids=("comp-hook-01",),
        concept_ids=(),  # deliberately omit c-01
    )
    closed, added = validate_and_close_selection(_draft(sel), ctx)
    assert "c-01" in closed.concept_ids
    assert "c-01" in added


def test_assessment_concept_dependency_expanded():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection(
        assessment_item_ids=("q-01",),
        concept_ids=(),
    )
    closed, added = validate_and_close_selection(_draft(sel), ctx)
    assert "c-01" in closed.concept_ids
    assert "c-01" in added


def test_no_expansion_when_concept_already_selected():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection(
        component_ids=("comp-hook-01",),
        concept_ids=("c-01",),
    )
    closed, added = validate_and_close_selection(_draft(sel), ctx)
    assert added == ()


def test_unknown_component_id_fails():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection(component_ids=("unknown-comp",))
    with pytest.raises(ContentClosureError) as exc_info:
        validate_and_close_selection(_draft(sel), ctx)
    assert "unknown-comp" in str(exc_info.value.unknown_ids)


def test_unknown_concept_id_fails():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection(concept_ids=("c-unknown",))
    with pytest.raises(ContentClosureError):
        validate_and_close_selection(_draft(sel), ctx)


def test_unknown_assessment_id_fails():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection(assessment_item_ids=("q-unknown",))
    with pytest.raises(ContentClosureError):
        validate_and_close_selection(_draft(sel), ctx)


def test_empty_selection_returns_as_is():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection()  # full selection intent
    closed, added = validate_and_close_selection(_draft(sel), ctx)
    assert added == ()


def test_canonical_rlo_is_unchanged_after_closure():
    rlo = _load_rlo()
    original_concept_count = len(rlo.concepts)
    ctx = build_assembly_context(rlo)
    sel = RLOContentSelection(component_ids=("comp-hook-01",))
    validate_and_close_selection(_draft(sel), ctx)
    assert len(rlo.concepts) == original_concept_count
