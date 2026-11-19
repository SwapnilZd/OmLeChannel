"""Video format selection tests — Phase 13C.

Verifies that FormatSelectionService correctly selects, rejects, and auto-selects
the video modality given various capability and request configurations.
"""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality, TopicProficiency
from learning_pipeline.contracts.format_selection import (
    FormatSelectionMode,
    FormatSelectionRequest,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
from learning_pipeline.format_selector.registry import build_default_registry
from learning_pipeline.format_selector.service import FormatSelectionService

_RLO_PATH = (
    __import__("pathlib").Path(__file__).parents[2]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)

_AVATAR_CAPS = frozenset({"video.avatar.render"})
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_BOTH_CAPS = _AVATAR_CAPS | _PODCAST_CAPS

_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Understand ADKAR change management.",),
)


def _load_blueprint() -> CourseBlueprint:
    from pathlib import Path
    from learning_pipeline.contracts.rlo import RLODocument
    from learning_pipeline.contracts.curriculum_assembly import AssemblyRLOCandidate, CourseAssemblyRequest
    from learning_pipeline.planners.curriculum.agent import FakeCurriculumAssemblyAgent
    from learning_pipeline.planners.curriculum.service import CourseAssemblyService
    from learning_pipeline.repository import InMemoryRLORepository
    import asyncio

    rlo = RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))
    svc = CourseAssemblyService(FakeCurriculumAssemblyAgent(), InMemoryRLORepository([rlo]))
    req = CourseAssemblyRequest(
        request_id="fs-video-test",
        learner=_LEARNER,
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Understand ADKAR change management.",
    )
    result = asyncio.run(svc.assemble_course(req))
    return result.blueprint


@pytest.fixture(scope="module")
def blueprint() -> CourseBlueprint:
    return _load_blueprint()


# ── Explicit video selection ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_video_selection_succeeds(blueprint: CourseBlueprint) -> None:
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    svc = FormatSelectionService(registry=reg, profiles=MODALITY_PROFILES)
    result = await svc.select_format(
        blueprint,
        FormatSelectionRequest(
            request_id="fs-video-explicit",
            blueprint_id=blueprint.blueprint_id,
            mode=FormatSelectionMode.EXPLICIT,
            requested_modality=Modality.VIDEO,
        ),
    )
    assert result.decision.selected_modality == Modality.VIDEO


@pytest.mark.asyncio
async def test_explicit_video_selection_fails_without_capability(blueprint: CourseBlueprint) -> None:
    from learning_pipeline.format_selector.service import FormatSelectionError
    reg = build_default_registry(available_capabilities=frozenset())
    svc = FormatSelectionService(registry=reg, profiles=MODALITY_PROFILES)
    with pytest.raises((FormatSelectionError, ValueError)):
        await svc.select_format(
            blueprint,
            FormatSelectionRequest(
                request_id="fs-video-no-cap",
                blueprint_id=blueprint.blueprint_id,
                mode=FormatSelectionMode.EXPLICIT,
                requested_modality=Modality.VIDEO,
            ),
        )


# ── Auto selection evaluates video ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_selection_picks_video_when_only_video_available(blueprint: CourseBlueprint) -> None:
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    svc = FormatSelectionService(registry=reg, profiles=MODALITY_PROFILES)
    result = await svc.select_format(
        blueprint,
        FormatSelectionRequest(
            request_id="fs-video-auto-only",
            blueprint_id=blueprint.blueprint_id,
            mode=FormatSelectionMode.AUTO,
        ),
    )
    assert result.decision.selected_modality == Modality.VIDEO


@pytest.mark.asyncio
async def test_auto_selection_can_pick_video_when_both_available(blueprint: CourseBlueprint) -> None:
    reg = build_default_registry(available_capabilities=_BOTH_CAPS)
    svc = FormatSelectionService(registry=reg, profiles=MODALITY_PROFILES)
    result = await svc.select_format(
        blueprint,
        FormatSelectionRequest(
            request_id="fs-both-auto",
            blueprint_id=blueprint.blueprint_id,
            mode=FormatSelectionMode.AUTO,
        ),
    )
    assert result.decision.selected_modality in {Modality.VIDEO, Modality.PODCAST}


@pytest.mark.asyncio
async def test_auto_selection_fails_when_no_caps(blueprint: CourseBlueprint) -> None:
    from learning_pipeline.format_selector.service import FormatSelectionError
    reg = build_default_registry(available_capabilities=frozenset())
    svc = FormatSelectionService(registry=reg, profiles=MODALITY_PROFILES)
    with pytest.raises((FormatSelectionError, ValueError)):
        await svc.select_format(
            blueprint,
            FormatSelectionRequest(
                request_id="fs-no-caps",
                blueprint_id=blueprint.blueprint_id,
                mode=FormatSelectionMode.AUTO,
            ),
        )


# ── Selection result content ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_selection_result_includes_evaluations(blueprint: CourseBlueprint) -> None:
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    svc = FormatSelectionService(registry=reg, profiles=MODALITY_PROFILES)
    result = await svc.select_format(
        blueprint,
        FormatSelectionRequest(
            request_id="fs-video-profile",
            blueprint_id=blueprint.blueprint_id,
            mode=FormatSelectionMode.EXPLICIT,
            requested_modality=Modality.VIDEO,
        ),
    )
    assert result.decision.selected_modality == Modality.VIDEO
    assert len(result.decision.evaluations) >= 1


@pytest.mark.asyncio
async def test_video_selection_result_is_json_serializable(blueprint: CourseBlueprint) -> None:
    from learning_pipeline.contracts.format_selection import FormatSelectionResult
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    svc = FormatSelectionService(registry=reg, profiles=MODALITY_PROFILES)
    result = await svc.select_format(
        blueprint,
        FormatSelectionRequest(
            request_id="fs-video-serial",
            blueprint_id=blueprint.blueprint_id,
            mode=FormatSelectionMode.EXPLICIT,
            requested_modality=Modality.VIDEO,
        ),
    )
    reloaded = FormatSelectionResult.model_validate_json(result.model_dump_json())
    assert reloaded.decision.selected_modality == Modality.VIDEO
