"""FormatSelectionService — auto deterministic mode tests — Phase 11."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    FormatSelectionMode,
    FormatSelectionRequest,
    SelectionBasis,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)
from learning_pipeline.format_selector.service import FormatSelectionError, FormatSelectionService

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_VIDEO_CAPS = frozenset({"video.render"})
_BP_PATH = Path(__file__).parents[2] / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _auto_request(blueprint: CourseBlueprint, **overrides) -> FormatSelectionRequest:
    defaults = dict(
        request_id="req-auto",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.AUTO,
    )
    defaults.update(overrides)
    return FormatSelectionRequest(**defaults)


def _make_service(caps: frozenset[str] = _PODCAST_CAPS) -> FormatSelectionService:
    registry = build_default_registry(available_capabilities=caps)
    return FormatSelectionService(registry=registry, profiles=MODALITY_PROFILES)


def _registry_with_video(caps: frozenset[str]) -> AvailableWorkflowRegistry:
    return AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.PODCAST,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=frozenset({"speech.synthesize", "audio.assemble"}),
            ),
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=frozenset({"video.render"}),
            ),
            WorkflowEntry(
                modality=Modality.ELEARNING,
                modality_planner_registered=False,
                workflow_planner_registered=False,
                required_capabilities=frozenset({"html.compile"}),
            ),
        ),
        available_capabilities=caps,
    )


# ── No feasible modalities fails ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_feasible_modalities_raises() -> None:
    blueprint = _load_blueprint()
    service = _make_service(caps=frozenset())
    request = _auto_request(blueprint)
    with pytest.raises(FormatSelectionError):
        await service.select_format(blueprint, request)


# ── One feasible modality is selected without LLM ────────────────────────────


@pytest.mark.asyncio
async def test_sole_feasible_selected_without_llm() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _auto_request(blueprint)
    result = await service.select_format(blueprint, request)
    assert result.decision.selected_modality == Modality.PODCAST
    assert result.decision.basis == SelectionBasis.SOLE_FEASIBLE


@pytest.mark.asyncio
async def test_sole_feasible_basis_is_sole_feasible() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.decision.basis == SelectionBasis.SOLE_FEASIBLE


# ── Multiple feasible → scoring determines winner ─────────────────────────────


@pytest.mark.asyncio
async def test_multiple_feasible_uses_deterministic_scoring() -> None:
    blueprint = _load_blueprint()
    registry = _registry_with_video(_PODCAST_CAPS | _VIDEO_CAPS)
    service = FormatSelectionService(registry=registry, profiles=MODALITY_PROFILES)
    request = _auto_request(blueprint)
    result = await service.select_format(blueprint, request)
    assert result.decision.basis == SelectionBasis.DETERMINISTIC


@pytest.mark.asyncio
async def test_highest_score_wins() -> None:
    blueprint = _load_blueprint()
    registry = _registry_with_video(_PODCAST_CAPS | _VIDEO_CAPS)
    # Prefer podcast explicitly → it will score highest
    service = FormatSelectionService(registry=registry, profiles=MODALITY_PROFILES)
    request = _auto_request(blueprint, preferred_modalities=(Modality.PODCAST,))
    result = await service.select_format(blueprint, request)
    assert result.decision.selected_modality == Modality.PODCAST


# ── Deterministic repeated scoring is identical ───────────────────────────────


@pytest.mark.asyncio
async def test_repeated_selection_is_deterministic() -> None:
    blueprint = _load_blueprint()
    registry = _registry_with_video(_PODCAST_CAPS | _VIDEO_CAPS)
    service = FormatSelectionService(registry=registry, profiles=MODALITY_PROFILES)
    request = _auto_request(blueprint, preferred_modalities=(Modality.VIDEO,))
    r1 = await service.select_format(blueprint, request)
    r2 = await service.select_format(blueprint, request)
    assert r1.decision.selected_modality == r2.decision.selected_modality
    assert r1.decision.basis == r2.decision.basis


# ── Decision contains all evaluations ────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_evaluations_cover_all_modalities() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert {e.modality for e in result.decision.evaluations} == set(Modality)


# ── Result structure ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_result_has_trace() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.trace.input_hash != ""
    assert len(result.trace.blueprint_hash) == 64


@pytest.mark.asyncio
async def test_from_cache_is_false_on_first_call() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.from_cache is False
