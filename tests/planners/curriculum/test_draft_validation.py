"""Assembly draft validation tests — Phase 12."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts.assembly import RLOContentSelection
from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyRLOCandidate,
    CourseAssemblyConstraints,
    CourseAssemblyDraft,
    CourseAssemblyRequest,
    OmittedRLODecision,
    TailoredRLODraft,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.context import build_assembly_context
from learning_pipeline.planners.curriculum.draft_validation import (
    DraftValidationError,
    validate_draft,
)

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)

_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Learn",),
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _simple_draft_entry(rlo_id="rlo-adkar-01-name-and-sequence", version="1.1.0", order=1):
    return TailoredRLODraft(
        rlo_id=rlo_id,
        rlo_version=version,
        order=order,
        selected_content=RLOContentSelection(component_ids=("comp-hook-01",)),
        target_proficiency=TopicProficiency.INTERMEDIATE,
        content_depth=ContentDepth.WORKING,
        role_relevance="Relevant.",
        personalization_rationale="For goals.",
        sequencing_rationale="First.",
    )


def _make_request(required_ids=()) -> CourseAssemblyRequest:
    rlo = _load_rlo()
    return CourseAssemblyRequest(
        request_id="req-01",
        learner=_LEARNER,
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Learn ADKAR.",
        constraints=CourseAssemblyConstraints(required_rlo_ids=tuple(required_ids)),
    )


def _valid_draft(rlo: RLODocument) -> CourseAssemblyDraft:
    return CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("Learners will state elements.",),
        ordered_rlo_drafts=(_simple_draft_entry(rlo.id, rlo.version, 1),),
        sequencing_rationale="single rlo",
        assessment_strategy="formative checks",
    )


def test_valid_draft_passes():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    validate_draft(_valid_draft(rlo), _make_request(), (ctx,))


def test_every_candidate_must_be_accounted_for():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    # Empty draft — doesn't account for the eligible candidate
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome",),
        ordered_rlo_drafts=(),
        omitted_rlos=(),
        sequencing_rationale="none",
        assessment_strategy="formative checks",
    )
    with pytest.raises(DraftValidationError, match="not accounted"):
        validate_draft(draft, _make_request(), (ctx,))


def test_required_rlo_cannot_be_omitted():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome",),
        ordered_rlo_drafts=(),
        omitted_rlos=(OmittedRLODecision(rlo_id=rlo.id, rlo_version=rlo.version, rationale="x"),),
        sequencing_rationale="none",
        assessment_strategy="formative checks",
    )
    with pytest.raises(DraftValidationError, match="Required"):
        validate_draft(draft, _make_request(required_ids=[rlo.id]), (ctx,))


def test_unknown_rlo_id_fails():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome",),
        ordered_rlo_drafts=(
            _simple_draft_entry(rlo.id, rlo.version, 1),
            _simple_draft_entry("rlo-unknown", "1.0.0", 2),
        ),
        sequencing_rationale="includes unknown",
        assessment_strategy="formative checks",
    )
    with pytest.raises(DraftValidationError, match="not among eligible"):
        validate_draft(draft, _make_request(), (ctx,))


def test_noncontiguous_orders_fail():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome",),
        ordered_rlo_drafts=(_simple_draft_entry(rlo.id, rlo.version, 3),),  # order 3, not 1
        sequencing_rationale="bad order",
        assessment_strategy="formative checks",
    )
    with pytest.raises(DraftValidationError, match="contiguous"):
        validate_draft(draft, _make_request(), (ctx,))


def test_version_mismatch_fails():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome",),
        ordered_rlo_drafts=(_simple_draft_entry(rlo.id, "9.9.9", 1),),  # wrong version
        sequencing_rationale="version mismatch",
        assessment_strategy="formative checks",
    )
    with pytest.raises(DraftValidationError, match="not among eligible"):
        validate_draft(draft, _make_request(), (ctx,))


def test_modality_specific_assessment_strategy_fails():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome",),
        ordered_rlo_drafts=(_simple_draft_entry(rlo.id, rlo.version, 1),),
        sequencing_rationale="single",
        assessment_strategy="Have the podcast host ask the expert about ADKAR.",
    )
    with pytest.raises(DraftValidationError, match="modality-specific"):
        validate_draft(draft, _make_request(), (ctx,))
