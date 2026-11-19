"""Tests for PlanningContextResolver — Phase 9."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learning_pipeline.contracts import (
    CourseBlueprint,
    ModalityPlan,
    RLODocument,
)
from learning_pipeline.contracts.planning import (
    ResolvedContentItem,
    ResolvedPlanningContext,
    ResolvedSceneContext,
)
from learning_pipeline.planners.context import (
    PlanningContextError,
    PlanningContextResolver,
)
from learning_pipeline.repository import (
    InMemoryRLORepository,
    RLONotFoundError,
)

_RLO_ROOT = (
    Path(__file__).parent.parent.parent
    / "examples" / "reference" / "rlos"
)
_BLUEPRINT_PATH = (
    Path(__file__).parent.parent.parent
    / "examples" / "reference" / "podcast" / "course_blueprint.json"
)
_MODALITY_PLAN_PATH = (
    Path(__file__).parent.parent.parent
    / "examples" / "reference" / "podcast" / "modality_plan.json"
)


def _load_rlo() -> RLODocument:
    path = _RLO_ROOT / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
    return RLODocument.model_validate_json(path.read_text(encoding="utf-8"))


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(
        _BLUEPRINT_PATH.read_text(encoding="utf-8")
    )


def _load_modality_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(
        _MODALITY_PLAN_PATH.read_text(encoding="utf-8")
    )


# ── Basic resolution ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_returns_context() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    context = await resolver.resolve(_load_blueprint(), _load_modality_plan())
    assert isinstance(context, ResolvedPlanningContext)


@pytest.mark.asyncio
async def test_context_blueprint_id_matches() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    blueprint = _load_blueprint()
    context = await resolver.resolve(blueprint, _load_modality_plan())
    assert context.blueprint_id == blueprint.blueprint_id


@pytest.mark.asyncio
async def test_context_has_correct_scene_count() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    modality_plan = _load_modality_plan()
    context = await resolver.resolve(_load_blueprint(), modality_plan)
    assert len(context.scenes) == len(modality_plan.scenes)


@pytest.mark.asyncio
async def test_context_scene_ids_match_modality_plan() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    modality_plan = _load_modality_plan()
    context = await resolver.resolve(_load_blueprint(), modality_plan)
    expected_ids = {s.id for s in modality_plan.scenes}
    actual_ids = {s.scene_id for s in context.scenes}
    assert actual_ids == expected_ids


@pytest.mark.asyncio
async def test_resolved_scenes_contain_content_items() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    context = await resolver.resolve(_load_blueprint(), _load_modality_plan())
    # Every scene should have at least one content item from the RLO
    assert all(len(scene.content_items) > 0 for scene in context.scenes)


@pytest.mark.asyncio
async def test_resolved_content_items_are_typed() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    context = await resolver.resolve(_load_blueprint(), _load_modality_plan())
    for scene in context.scenes:
        for item in scene.content_items:
            assert isinstance(item, ResolvedContentItem)
            assert item.content_type in {
                "objective", "concept", "component", "assessment_item"
            }


@pytest.mark.asyncio
async def test_assessment_context_preserves_diagnostic_feedback() -> None:
    rlo = _load_rlo()
    resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    context = await resolver.resolve(_load_blueprint(), _load_modality_plan())
    assessment_text = "\n".join(
        item.content
        for scene in context.scenes
        for item in scene.content_items
        if item.content_type == "assessment_item"
    )
    assert "Feedback: Correct. ADKAR follows this exact sequence." in assessment_text
    assert "Feedback: Incorrect. The fourth element is Ability" in assessment_text


@pytest.mark.asyncio
async def test_context_learner_matches_blueprint() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    blueprint = _load_blueprint()
    context = await resolver.resolve(blueprint, _load_modality_plan())
    assert context.learner == blueprint.learner


@pytest.mark.asyncio
async def test_context_accessibility_requirements_populated() -> None:
    rlo = _load_rlo()
    repo = InMemoryRLORepository([rlo])
    resolver = PlanningContextResolver(repo)
    context = await resolver.resolve(_load_blueprint(), _load_modality_plan())
    # Accessibility requirements should be a tuple (possibly empty)
    assert isinstance(context.accessibility_requirements, tuple)


# ── Error handling ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_rlo_raises_planning_context_error() -> None:
    repo = InMemoryRLORepository([])
    resolver = PlanningContextResolver(repo)
    with pytest.raises(PlanningContextError, match="not found"):
        await resolver.resolve(_load_blueprint(), _load_modality_plan())


@pytest.mark.asyncio
async def test_version_mismatch_raises_planning_context_error() -> None:
    rlo = _load_rlo()
    # Mutate version to mismatch
    data = json.loads(rlo.model_dump_json())
    data["version"] = "9.9.9"
    wrong_rlo = RLODocument.model_validate(data)
    repo = InMemoryRLORepository([wrong_rlo])
    resolver = PlanningContextResolver(repo)
    with pytest.raises(PlanningContextError):
        await resolver.resolve(_load_blueprint(), _load_modality_plan())


# ── FileRLORepository integration ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_rlo_repository_resolves_context() -> None:
    from learning_pipeline.repository import FileRLORepository

    repo = FileRLORepository(_RLO_ROOT)
    resolver = PlanningContextResolver(repo)
    context = await resolver.resolve(_load_blueprint(), _load_modality_plan())
    assert isinstance(context, ResolvedPlanningContext)
    assert len(context.scenes) == 2


@pytest.mark.asyncio
async def test_file_rlo_repository_missing_file_raises(tmp_path: Path) -> None:
    from learning_pipeline.repository import FileRLORepository

    repo = FileRLORepository(tmp_path)
    resolver = PlanningContextResolver(repo)
    with pytest.raises(PlanningContextError, match="not found"):
        await resolver.resolve(_load_blueprint(), _load_modality_plan())
