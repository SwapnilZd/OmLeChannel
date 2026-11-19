from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from learning_commissioning.adapters import (
    ASSEMBLY_ADAPTER_POLICY_VERSION,
    AssemblyAdapterError,
    build_course_assembly_request,
)
from learning_commissioning.contracts import (
    ConfirmedLearningRequest,
    ConfirmedRLOCandidate,
    LearningCommissionRequest,
)
from learning_pipeline.contracts import CourseAssemblyRequest

_ROOT = Path(__file__).parents[2]
_REQUEST = _ROOT / "examples/reference/commissioning/cohort-request.json"


def _commission(**updates) -> LearningCommissionRequest:
    data = json.loads(_REQUEST.read_text(encoding="utf-8"))
    data.update(updates)
    return LearningCommissionRequest.model_validate(data)


def _confirmed(*candidates, request_id="commission-change-managers-01"):
    return ConfirmedLearningRequest(
        request_id=request_id,
        preview_id="preview-01",
        preview_hash="preview-hash",
        confirmed_course_goal=(
            "Enable managers to recognize stakeholder resistance and select a proportionate response."
        ),
        candidates=tuple(ConfirmedRLOCandidate(**candidate) for candidate in candidates),
        confirmation_actor="gd-manager@example.test",
        confirmed_at=datetime.now(UTC),
    )


def test_confirmed_request_builds_existing_assembly_contract():
    commission = _commission()
    confirmed = _confirmed(
        {
            "rlo_id": "rlo-adkar-04-awareness",
            "rlo_version": "1.1.0",
            "disposition": "include",
        },
        {
            "rlo_id": "rlo-adkar-05-desire",
            "rlo_version": "1.1.0",
            "disposition": "exclude",
        },
    )
    result = build_course_assembly_request(commission, confirmed)
    assert isinstance(result.request, CourseAssemblyRequest)
    assert result.request.learner.role == "Manager / Senior Manager"
    assert result.request.learner.deloitte_level is None
    assert result.request.learner.default_proficiency == "beginner"
    assert result.request.learner.business_context["audience_kind"] == "individual"
    assert result.request.constraints.excluded_rlo_ids == ("rlo-adkar-05-desire",)
    assert result.request.constraints.minimum_target_proficiency == "intermediate"
    assert result.trace.policy_version == ASSEMBLY_ADAPTER_POLICY_VERSION
    assert len(result.trace.request_hash) == 64


def test_single_level_is_preserved_in_learner_projection():
    data = json.loads(_REQUEST.read_text(encoding="utf-8"))
    data["audience"]["deloitte_levels"] = [55]
    commission = LearningCommissionRequest.model_validate(data)
    confirmed = _confirmed(
        {
            "rlo_id": "rlo-adkar-04-awareness",
            "rlo_version": "1.1.0",
            "disposition": "include",
        }
    )
    result = build_course_assembly_request(commission, confirmed)
    assert result.request.learner.deloitte_level == 55


def test_request_without_roles_projects_to_an_individual_learner():
    data = json.loads(_REQUEST.read_text(encoding="utf-8"))
    data["audience"]["roles"] = []
    data["audience"]["deloitte_levels"] = [45]
    commission = LearningCommissionRequest.model_validate(data)
    confirmed = _confirmed(
        {
            "rlo_id": "rlo-adkar-04-awareness",
            "rlo_version": "1.1.0",
            "disposition": "include",
        }
    )

    result = build_course_assembly_request(commission, confirmed)

    assert result.request.learner.role == "Individual learner"
    assert result.request.learner.deloitte_level == 45
    assert result.request.learner.business_context["audience_kind"] == "individual"


def test_user_required_rlo_cannot_be_downgraded_at_confirmation():
    commission = _commission(required_rlo_ids=["rlo-adkar-04-awareness"])
    confirmed = _confirmed(
        {
            "rlo_id": "rlo-adkar-04-awareness",
            "rlo_version": "1.1.0",
            "disposition": "include",
        }
    )
    with pytest.raises(AssemblyAdapterError, match="remain required"):
        build_course_assembly_request(commission, confirmed)


def test_commission_and_confirmation_must_match():
    confirmed = _confirmed(
        {
            "rlo_id": "rlo-adkar-04-awareness",
            "rlo_version": "1.1.0",
            "disposition": "include",
        },
        request_id="different-request",
    )
    with pytest.raises(AssemblyAdapterError, match="request IDs"):
        build_course_assembly_request(_commission(), confirmed)
