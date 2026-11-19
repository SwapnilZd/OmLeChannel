"""Blueprint builder tests — Phase 12."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from learning_pipeline.contracts.assembly import CourseBlueprint
from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyRLOCandidate,
    CourseAssemblyConstraints,
    CourseAssemblyRequest,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.agent import FakeCurriculumAssemblyAgent
from learning_pipeline.planners.curriculum.builder import build_blueprint
from learning_pipeline.planners.curriculum.context import build_assembly_context
from learning_pipeline.contracts.planning import StructuredPlanningResponse
from learning_pipeline.contracts.curriculum_assembly import CourseAssemblyDraft
from learning_pipeline.repository import InMemoryRLORepository

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)

_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Learn ADKAR.",),
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _make_request(rlo: RLODocument) -> CourseAssemblyRequest:
    return CourseAssemblyRequest(
        request_id="req-01",
        learner=_LEARNER,
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Learn ADKAR.",
    )


def _fake_response(draft: CourseAssemblyDraft) -> StructuredPlanningResponse:
    return StructuredPlanningResponse(
        result=draft,
        model="fake-model",
        prompt_version="course_assembly_v1",
        provider_request_id=None,
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=None,
    )


async def _assemble(rlo: RLODocument) -> "CourseAssemblyResult":  # noqa: F821
    from learning_pipeline.planners.curriculum.service import CourseAssemblyService
    repo = InMemoryRLORepository([rlo])
    agent = FakeCurriculumAssemblyAgent()
    svc = CourseAssemblyService(agent, repo)
    return await svc.assemble_course(_make_request(rlo))


def test_blueprint_is_returned():
    rlo = _load_rlo()
    result = asyncio.run(_assemble(rlo))
    assert isinstance(result.blueprint, CourseBlueprint)


def test_starting_proficiency_derived_from_learner():
    rlo = _load_rlo()
    result = asyncio.run(_assemble(rlo))
    ref = result.blueprint.ordered_rlo_refs[0]
    assert ref.starting_proficiency == TopicProficiency.BEGINNER


def test_authoritative_version_in_blueprint():
    rlo = _load_rlo()
    result = asyncio.run(_assemble(rlo))
    ref = result.blueprint.ordered_rlo_refs[0]
    assert ref.rlo_version == rlo.version


def test_source_version_manifest_populated():
    rlo = _load_rlo()
    result = asyncio.run(_assemble(rlo))
    assert rlo.id in result.blueprint.source_rlo_versions
    assert result.blueprint.source_rlo_versions[rlo.id] == rlo.version


def test_orders_are_contiguous_starting_at_one():
    rlo = _load_rlo()
    result = asyncio.run(_assemble(rlo))
    orders = [ref.order for ref in result.blueprint.ordered_rlo_refs]
    assert orders == list(range(1, len(orders) + 1))


def test_repeated_build_is_identical():
    """Builder is deterministic — same inputs produce same blueprint_id structure."""
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    request = _make_request(rlo)
    agent = FakeCurriculumAssemblyAgent()
    response1 = asyncio.run(agent.create_assembly_draft(request, (ctx,)))
    response2 = asyncio.run(agent.create_assembly_draft(request, (ctx,)))
    draft1 = response1.result
    draft2 = response2.result
    assert isinstance(draft1, CourseAssemblyDraft)
    assert isinstance(draft2, CourseAssemblyDraft)
    # Same orderings and selection
    assert [d.rlo_id for d in draft1.ordered_rlo_drafts] == [d.rlo_id for d in draft2.ordered_rlo_drafts]
    assert [d.selected_content for d in draft1.ordered_rlo_drafts] == [
        d.selected_content for d in draft2.ordered_rlo_drafts
    ]


def test_canonical_rlo_is_unchanged_after_build():
    rlo = _load_rlo()
    original_concept_count = len(rlo.concepts)
    asyncio.run(_assemble(rlo))
    assert len(rlo.concepts) == original_concept_count
