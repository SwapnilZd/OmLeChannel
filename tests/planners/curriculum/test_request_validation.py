"""Assembly request validation tests — Phase 12."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts.common import TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyRLOCandidate,
    CourseAssemblyConstraints,
    CourseAssemblyRequest,
)
from learning_pipeline.contracts.learner import LearnerContext

_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Understand ADKAR",),
)

_CANDIDATE = AssemblyRLOCandidate(rlo_id="rlo-01", rlo_version="1.0.0")


def _request(**overrides) -> CourseAssemblyRequest:
    defaults = dict(
        request_id="req-01",
        learner=_LEARNER,
        candidates=(_CANDIDATE,),
        course_goal="Learn ADKAR fundamentals.",
    )
    defaults.update(overrides)
    return CourseAssemblyRequest(**defaults)


def test_valid_request_constructs():
    req = _request()
    assert req.request_id == "req-01"
    assert len(req.candidates) == 1


def test_missing_candidates_fails():
    with pytest.raises(Exception, match="candidates"):
        _request(candidates=())


def test_duplicate_candidates_fail():
    dup = (
        AssemblyRLOCandidate(rlo_id="rlo-01", rlo_version="1.0.0"),
        AssemblyRLOCandidate(rlo_id="rlo-01", rlo_version="1.0.0"),
    )
    with pytest.raises(Exception, match="Duplicate"):
        _request(candidates=dup)


def test_required_excluded_overlap_fails():
    with pytest.raises(Exception, match="overlap"):
        CourseAssemblyConstraints(
            required_rlo_ids=("rlo-01",),
            excluded_rlo_ids=("rlo-01",),
        )


def test_unknown_required_rlo_fails():
    constraints = CourseAssemblyConstraints(required_rlo_ids=("rlo-unknown",))
    with pytest.raises(Exception, match="not among the candidates"):
        _request(constraints=constraints)


def test_unknown_excluded_rlo_fails():
    constraints = CourseAssemblyConstraints(excluded_rlo_ids=("rlo-unknown",))
    with pytest.raises(Exception, match="not among the candidates"):
        _request(constraints=constraints)


def test_invalid_duration_fails():
    with pytest.raises(Exception, match="positive"):
        CourseAssemblyConstraints(maximum_duration_minutes=0)


def test_empty_request_id_fails():
    with pytest.raises(Exception):
        _request(request_id="")


def test_empty_course_goal_fails():
    with pytest.raises(Exception):
        _request(course_goal="")


def test_duplicate_required_ids_fails():
    with pytest.raises(Exception, match="unique"):
        CourseAssemblyConstraints(
            required_rlo_ids=("rlo-01", "rlo-01"),
        )


def test_duplicate_excluded_ids_fails():
    with pytest.raises(Exception, match="unique"):
        CourseAssemblyConstraints(
            excluded_rlo_ids=("rlo-02", "rlo-02"),
        )


def test_empty_required_content_id_fails():
    with pytest.raises(Exception):
        CourseAssemblyConstraints(required_content_ids=("",))


def test_duplicate_required_content_ids_fails():
    with pytest.raises(Exception, match="unique"):
        CourseAssemblyConstraints(required_content_ids=("c-01", "c-01"))
