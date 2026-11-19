"""One-call planning rule tests — Phase 12."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyRLOCandidate,
    CourseAssemblyConstraints,
    CourseAssemblyDraft,
    CourseAssemblyRequest,
)
from learning_pipeline.contracts.planning import StructuredPlanningResponse
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.agent import FakeCurriculumAssemblyAgent
from learning_pipeline.planners.curriculum.context import build_assembly_context
from learning_pipeline.planners.curriculum.service import CourseAssemblyService
from learning_pipeline.planners.client import PlanningOutputValidationError
from learning_pipeline.repository import InMemoryRLORepository

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)

_LEARNER = LearnerContext(
    role="Analyst",
    deloitte_level=45,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Understand ADKAR.",),
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _make_request(rlo: RLODocument) -> CourseAssemblyRequest:
    return CourseAssemblyRequest(
        request_id="req-oc-01",
        learner=_LEARNER,
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Understand ADKAR.",
    )


def test_exactly_one_agent_call_per_request():
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    svc = CourseAssemblyService(agent, InMemoryRLORepository([rlo]))
    asyncio.run(svc.assemble_course(_make_request(rlo)))
    assert agent.call_count == 1


def test_learner_and_context_are_supplied_to_agent():
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    svc = CourseAssemblyService(agent, InMemoryRLORepository([rlo]))
    request = _make_request(rlo)
    asyncio.run(svc.assemble_course(request))
    assert agent.last_request is not None
    assert agent.last_request.learner.role == "Analyst"
    assert agent.last_contexts is not None
    assert len(agent.last_contexts) == 1
    assert agent.last_contexts[0].rlo_id == rlo.id


def test_candidates_supplied_unordered_without_pretended_sequence():
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    svc = CourseAssemblyService(agent, InMemoryRLORepository([rlo]))
    asyncio.run(svc.assemble_course(_make_request(rlo)))
    # Fake agent receives contexts; no ordering guarantee should be imposed by service
    assert agent.last_contexts is not None
    # Exactly one context for our one candidate
    assert len(agent.last_contexts) == 1


def test_invalid_output_fails_without_repair_call():
    """An agent that raises validation error results in error — not retried."""
    rlo = _load_rlo()
    fail_agent = FakeCurriculumAssemblyAgent(fail=True)
    svc = CourseAssemblyService(fail_agent, InMemoryRLORepository([rlo]))
    from learning_pipeline.planners.curriculum.service import CourseAssemblyError
    with pytest.raises(CourseAssemblyError, match="schema validation"):
        asyncio.run(svc.assemble_course(_make_request(rlo)))
    # Only one attempt, no repair
    assert fail_agent.call_count == 1


def test_duration_failure_gets_one_bounded_repair():
    rlo = _load_rlo()

    class DurationRepairAgent(FakeCurriculumAssemblyAgent):
        async def repair_duration_draft(
            self, request, contexts, previous_draft, validation_error
        ):
            self.call_count += 1
            repaired_rlo = previous_draft.ordered_rlo_drafts[0].model_copy(
                update={"content_depth": ContentDepth.SUMMARY}
            )
            repaired = previous_draft.model_copy(
                update={"ordered_rlo_drafts": (repaired_rlo,)}
            )
            return StructuredPlanningResponse(
                result=repaired,
                model="repair-test",
                prompt_version="course_assembly_v1",
            )

    request = CourseAssemblyRequest(
        request_id="req-duration-repair",
        learner=_LEARNER,
        candidates=(
            AssemblyRLOCandidate(
                rlo_id=rlo.id, rlo_version=rlo.version, required=True
            ),
        ),
        course_goal="Understand ADKAR.",
        constraints=CourseAssemblyConstraints(
            required_rlo_ids=(rlo.id,), maximum_duration_minutes=7
        ),
    )
    agent = DurationRepairAgent()
    service = CourseAssemblyService(agent, InMemoryRLORepository([rlo]))
    result = asyncio.run(service.assemble_course(request))
    assert result.blueprint.estimated_duration_minutes <= 7
    assert result.blueprint.ordered_rlo_refs[0].content_depth == ContentDepth.SUMMARY
    assert agent.call_count == 2


def test_duration_error_names_selected_content_when_no_rlo_is_required():
    rlo = _load_rlo()
    request = CourseAssemblyRequest(
        request_id="req-duration-error",
        learner=_LEARNER,
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Understand ADKAR.",
        constraints=CourseAssemblyConstraints(maximum_duration_minutes=7),
    )
    agent = FakeCurriculumAssemblyAgent()
    service = CourseAssemblyService(agent, InMemoryRLORepository([rlo]))
    from learning_pipeline.planners.curriculum.service import CourseAssemblyError

    with pytest.raises(CourseAssemblyError) as error:
        asyncio.run(service.assemble_course(request))
    message = str(error.value)
    assert "Selected RLO duration breakdown" in message
    assert "Explicitly required RLOs: none explicitly required" in message
    assert "Required content driving the conflict: []" not in message
