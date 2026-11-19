"""Repository loading and governance tests — Phase 12."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts.rlo import Governance, RLODocument
from learning_pipeline.planners.curriculum.governance import (
    GovernanceViolationError,
    enforce_governance,
    is_governance_approved,
)
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyRLOCandidate,
    CourseAssemblyConstraints,
    CourseAssemblyRequest,
)
from learning_pipeline.contracts.common import TopicProficiency
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.repository import (
    InMemoryRLORepository,
    RLONotFoundError,
    RLOVersionNotFoundError,
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
    goals=("Understand ADKAR",),
)


def _load_reference_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _make_request(candidates, required_ids=()) -> CourseAssemblyRequest:
    return CourseAssemblyRequest(
        request_id="req-01",
        learner=_LEARNER,
        candidates=candidates,
        course_goal="Learn ADKAR.",
        constraints=CourseAssemblyConstraints(required_rlo_ids=tuple(required_ids)),
    )


# ── Repository loading ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_version_loads():
    rlo = _load_reference_rlo()
    repo = InMemoryRLORepository([rlo])
    loaded = await repo.get(rlo.id, rlo.version)
    assert loaded.id == rlo.id
    assert loaded.version == rlo.version


@pytest.mark.asyncio
async def test_missing_rlo_raises():
    repo = InMemoryRLORepository([])
    with pytest.raises(RLONotFoundError):
        await repo.get("rlo-missing", "1.0.0")


@pytest.mark.asyncio
async def test_wrong_version_raises_not_substitutes():
    rlo = _load_reference_rlo()
    repo = InMemoryRLORepository([rlo])
    with pytest.raises(RLOVersionNotFoundError):
        await repo.get(rlo.id, "9.9.9")


# ── Governance ─────────────────────────────────────────────────────────────────


def test_approved_rlo_passes_governance():
    rlo = _load_reference_rlo()
    assert rlo.governance.status == "approved"
    assert is_governance_approved(rlo)


def test_deprecated_rlo_fails_governance(monkeypatch):
    rlo = _load_reference_rlo()
    # Patch governance status to simulate prohibition
    deprecated_gov = Governance(status="deprecated")
    object.__setattr__(rlo, "governance", deprecated_gov)
    assert not is_governance_approved(rlo)


def test_required_prohibited_candidate_raises():
    rlo = _load_reference_rlo()
    deprecated_gov = Governance(status="deprecated")
    object.__setattr__(rlo, "governance", deprecated_gov)

    rlos = {rlo.id: rlo}
    candidates = (AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version, required=True),)
    request = _make_request(candidates, required_ids=[rlo.id])

    with pytest.raises(GovernanceViolationError):
        enforce_governance(candidates, rlos, request)


def test_non_required_prohibited_candidate_is_rejected():
    rlo = _load_reference_rlo()
    deprecated_gov = Governance(status="deprecated")
    object.__setattr__(rlo, "governance", deprecated_gov)

    rlos = {rlo.id: rlo}
    candidates = (AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version, required=False),)
    request = _make_request(candidates)

    rejected, warnings = enforce_governance(candidates, rlos, request)
    assert rlo.id in rejected
    assert len(warnings) == 1
