"""Assembly service idempotency tests — Phase 12."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from learning_pipeline.contracts.common import TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyRLOCandidate,
    CourseAssemblyRequest,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.agent import FakeCurriculumAssemblyAgent
from learning_pipeline.planners.curriculum.service import CourseAssemblyService
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


def _make_request(rlo: RLODocument, *, request_id: str = "req-01") -> CourseAssemblyRequest:
    return CourseAssemblyRequest(
        request_id=request_id,
        learner=_LEARNER,
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Learn ADKAR.",
    )


def _make_service(rlo: RLODocument, tmp_path: Path) -> CourseAssemblyService:
    agent = FakeCurriculumAssemblyAgent()
    repo = InMemoryRLORepository([rlo])
    return CourseAssemblyService(agent, repo, trace_root=tmp_path)


def test_identical_request_reuses_cached_result(tmp_path):
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    repo = InMemoryRLORepository([rlo])
    svc = CourseAssemblyService(agent, repo, trace_root=tmp_path)
    req = _make_request(rlo)

    result1 = asyncio.run(svc.assemble_course(req))
    result2 = asyncio.run(svc.assemble_course(req))

    assert not result1.from_cache
    assert result2.from_cache


def test_agent_not_called_twice_for_same_request(tmp_path):
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    repo = InMemoryRLORepository([rlo])
    svc = CourseAssemblyService(agent, repo, trace_root=tmp_path)
    req = _make_request(rlo)

    asyncio.run(svc.assemble_course(req))
    asyncio.run(svc.assemble_course(req))

    assert agent.call_count == 1


def test_changed_request_id_still_reuses_cache(tmp_path):
    """request_id is excluded from the idempotency hash."""
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    repo = InMemoryRLORepository([rlo])
    svc = CourseAssemblyService(agent, repo, trace_root=tmp_path)

    asyncio.run(svc.assemble_course(_make_request(rlo, request_id="req-01")))
    result2 = asyncio.run(svc.assemble_course(_make_request(rlo, request_id="req-02")))

    assert result2.from_cache
    assert agent.call_count == 1


def test_changed_learner_context_invalidates_cache(tmp_path):
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    repo = InMemoryRLORepository([rlo])
    svc = CourseAssemblyService(agent, repo, trace_root=tmp_path)

    req1 = CourseAssemblyRequest(
        request_id="req-01",
        learner=LearnerContext(
            role="Manager",
            deloitte_level=55,
            default_proficiency=TopicProficiency.BEGINNER,
            goals=("Learn ADKAR.",),
        ),
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Learn ADKAR.",
    )
    req2 = CourseAssemblyRequest(
        request_id="req-02",
        learner=LearnerContext(
            role="Director",  # different role
            deloitte_level=55,
            default_proficiency=TopicProficiency.BEGINNER,
            goals=("Learn ADKAR.",),
        ),
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Learn ADKAR.",
    )

    result1 = asyncio.run(svc.assemble_course(req1))
    result2 = asyncio.run(svc.assemble_course(req2))

    assert not result1.from_cache
    assert not result2.from_cache
    assert agent.call_count == 2


def test_no_trace_root_means_no_cache():
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    repo = InMemoryRLORepository([rlo])
    svc = CourseAssemblyService(agent, repo, trace_root=None)
    req = _make_request(rlo)

    result1 = asyncio.run(svc.assemble_course(req))
    result2 = asyncio.run(svc.assemble_course(req))

    assert not result1.from_cache
    assert not result2.from_cache
    assert agent.call_count == 2


def test_cache_files_written_to_disk(tmp_path):
    rlo = _load_rlo()
    svc = _make_service(rlo, tmp_path)
    asyncio.run(svc.assemble_course(_make_request(rlo)))

    cache_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(cache_dirs) == 1
    cache_dir = cache_dirs[0]
    assert (cache_dir / "course-blueprint.json").exists()
    assert (cache_dir / "assembly-report.json").exists()
    assert (cache_dir / "planning-trace.json").exists()
    assert (cache_dir / "assembly-draft.json").exists()


def test_cached_blueprint_is_valid(tmp_path):
    from learning_pipeline.contracts.assembly import CourseBlueprint
    rlo = _load_rlo()
    svc = _make_service(rlo, tmp_path)
    asyncio.run(svc.assemble_course(_make_request(rlo)))

    cache_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    bp_path = cache_dirs[0] / "course-blueprint.json"
    blueprint = CourseBlueprint.model_validate_json(bp_path.read_text(encoding="utf-8"))
    assert isinstance(blueprint, CourseBlueprint)
    assert len(blueprint.ordered_rlo_refs) >= 1
