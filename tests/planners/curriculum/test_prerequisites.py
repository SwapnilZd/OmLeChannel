"""Prerequisite validation tests — Phase 12."""
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
    PrerequisiteBridge,
    RLOAssemblyContext,
    TailoredRLODraft,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.context import build_assembly_context
from learning_pipeline.planners.curriculum.prerequisites import (
    DependencyCycleError,
    PrerequisiteViolationError,
    validate_prerequisite_ordering,
)

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)

_BEGINNER_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Learn",),
)

_ADVANCED_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=65,
    default_proficiency=TopicProficiency.ADVANCED,
    goals=("Learn",),
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _simple_draft(rlo_id: str, version: str, order: int) -> TailoredRLODraft:
    return TailoredRLODraft(
        rlo_id=rlo_id,
        rlo_version=version,
        order=order,
        selected_content=RLOContentSelection(),
        target_proficiency=TopicProficiency.INTERMEDIATE,
        content_depth=ContentDepth.WORKING,
        role_relevance="Relevant.",
        personalization_rationale="Included for learner goals.",
        sequencing_rationale="Ordered by dependency.",
    )


def _make_request(learner: LearnerContext = _BEGINNER_LEARNER) -> CourseAssemblyRequest:
    return CourseAssemblyRequest(
        request_id="req-01",
        learner=learner,
        candidates=(AssemblyRLOCandidate(rlo_id="rlo-a", rlo_version="1.0.0"),),
        course_goal="Learn.",
    )


def _fake_ctx(rlo_id: str, topic: str = "Topic A", prerequisites: tuple = ()) -> RLOAssemblyContext:
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    # Override fields using model_copy (immutable FrozenModel)
    return ctx.model_copy(update={
        "rlo_id": rlo_id,
        "topic": topic,
        "prerequisites": prerequisites,
    })


def test_no_prerequisites_passes():
    ctx_a = _fake_ctx("rlo-a", prerequisites=())
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome 1",),
        ordered_rlo_drafts=(_simple_draft("rlo-a", "1.1.0", 1),),
        sequencing_rationale="only one",
        assessment_strategy="formative checks",
    )
    findings = validate_prerequisite_ordering(draft, {"rlo-a": ctx_a}, _make_request())
    assert isinstance(findings, list)


def test_correctly_ordered_prerequisite_passes():
    ctx_a = _fake_ctx("rlo-a", prerequisites=())
    ctx_b = _fake_ctx("rlo-b", prerequisites=("rlo-a",))
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome 1",),
        ordered_rlo_drafts=(
            _simple_draft("rlo-a", "1.1.0", 1),
            _simple_draft("rlo-b", "1.1.0", 2),
        ),
        sequencing_rationale="a before b",
        assessment_strategy="formative checks",
    )
    findings = validate_prerequisite_ordering(
        draft, {"rlo-a": ctx_a, "rlo-b": ctx_b}, _make_request()
    )
    assert any("precedes" in f for f in findings)


def test_reversed_prerequisite_order_fails():
    ctx_a = _fake_ctx("rlo-a", prerequisites=())
    ctx_b = _fake_ctx("rlo-b", prerequisites=("rlo-a",))
    # b before a — wrong order
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome 1",),
        ordered_rlo_drafts=(
            _simple_draft("rlo-b", "1.1.0", 1),
            _simple_draft("rlo-a", "1.1.0", 2),
        ),
        sequencing_rationale="wrong order",
        assessment_strategy="formative checks",
    )
    with pytest.raises(PrerequisiteViolationError):
        validate_prerequisite_ordering(
            draft, {"rlo-a": ctx_a, "rlo-b": ctx_b}, _make_request()
        )


def test_proficient_learner_receives_waiver():
    ctx_a = _fake_ctx("rlo-a", topic="Topic A", prerequisites=())
    ctx_b = _fake_ctx("rlo-b", topic="Topic B", prerequisites=("rlo-a",))
    # rlo-a is omitted; learner is ADVANCED → waiver applies
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome 1",),
        ordered_rlo_drafts=(_simple_draft("rlo-b", "1.1.0", 1),),
        omitted_rlos=(OmittedRLODecision(rlo_id="rlo-a", rlo_version="1.1.0", rationale="Learner knows it"),),
        sequencing_rationale="b only",
        assessment_strategy="formative checks",
    )
    # Advanced learner → waiver for rlo-a
    request = _make_request(learner=_ADVANCED_LEARNER)
    findings = validate_prerequisite_ordering(
        draft, {"rlo-a": ctx_a, "rlo-b": ctx_b}, request
    )
    assert any("waived" in f.lower() for f in findings)


def test_missing_prerequisite_without_bridge_or_waiver_fails():
    ctx_a = _fake_ctx("rlo-a", topic="Topic A", prerequisites=())
    ctx_b = _fake_ctx("rlo-b", topic="Topic B", prerequisites=("rlo-a",))
    # rlo-a omitted, beginner learner, no bridge
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome 1",),
        ordered_rlo_drafts=(_simple_draft("rlo-b", "1.1.0", 1),),
        omitted_rlos=(OmittedRLODecision(rlo_id="rlo-a", rlo_version="1.1.0", rationale="Omitted"),),
        sequencing_rationale="b only",
        assessment_strategy="formative checks",
    )
    with pytest.raises(PrerequisiteViolationError):
        validate_prerequisite_ordering(
            draft, {"rlo-a": ctx_a, "rlo-b": ctx_b}, _make_request()
        )


def test_bridge_satisfies_omitted_prerequisite():
    ctx_a = _fake_ctx("rlo-a", topic="Topic A", prerequisites=())
    ctx_b = _fake_ctx("rlo-b", topic="Topic B", prerequisites=("rlo-a",))
    bridge = PrerequisiteBridge(
        bridge_id="br-01",
        before_rlo_id="rlo-b",
        prerequisite_topic="Topic A",
        learning_direction="Learner assumed to have foundational Topic A knowledge.",
        rationale="Prior training confirmed.",
    )
    draft = CourseAssemblyDraft(
        draft_id="d1",
        title="T",
        learning_outcomes=("outcome 1",),
        ordered_rlo_drafts=(_simple_draft("rlo-b", "1.1.0", 1),),
        omitted_rlos=(OmittedRLODecision(rlo_id="rlo-a", rlo_version="1.1.0", rationale="Bridged"),),
        prerequisite_bridges=(bridge,),
        sequencing_rationale="b only with bridge",
        assessment_strategy="formative checks",
    )
    findings = validate_prerequisite_ordering(
        draft, {"rlo-a": ctx_a, "rlo-b": ctx_b}, _make_request()
    )
    assert any("bridge" in f.lower() for f in findings)
