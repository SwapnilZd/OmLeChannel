"""FormatSelectionService — LLM-assisted mode tests — Phase 11."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    FormatSelectionMode,
    FormatSelectionRequest,
    FormatSelectorStrategy,
    SelectionBasis,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
from learning_pipeline.format_selector.recommender import FakeFormatRecommender
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)
from learning_pipeline.format_selector.service import FormatSelectionService

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_VIDEO_CAPS = frozenset({"video.render"})
_BP_PATH = Path(__file__).parents[2] / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _auto_request(blueprint: CourseBlueprint) -> FormatSelectionRequest:
    return FormatSelectionRequest(
        request_id="req-llm",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.AUTO,
    )


def _explicit_request(blueprint: CourseBlueprint, modality: Modality) -> FormatSelectionRequest:
    return FormatSelectionRequest(
        request_id="req-explicit",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.EXPLICIT,
        requested_modality=modality,
    )


def _registry_with_both() -> AvailableWorkflowRegistry:
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
                required_capabilities=_VIDEO_CAPS,
            ),
            WorkflowEntry(
                modality=Modality.ELEARNING,
                modality_planner_registered=False,
                workflow_planner_registered=False,
                required_capabilities=frozenset({"html.compile"}),
            ),
        ),
        available_capabilities=_PODCAST_CAPS | _VIDEO_CAPS,
    )


def _llm_service(recommender, registry=None) -> FormatSelectionService:
    reg = registry or _registry_with_both()
    return FormatSelectionService(
        registry=reg,
        profiles=MODALITY_PROFILES,
        recommender=recommender,
        strategy=FormatSelectorStrategy.LLM_ASSISTED,
    )


# ── LLM is called only in auto mode ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_not_called_in_explicit_mode() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST)
    service = _llm_service(recommender)
    request = _explicit_request(blueprint, Modality.PODCAST)
    await service.select_format(blueprint, request)
    assert recommender.call_count == 0


# ── LLM not called when only one feasible candidate ──────────────────────────


@pytest.mark.asyncio
async def test_llm_not_called_with_sole_feasible() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST)
    # Only podcast available
    service = FormatSelectionService(
        registry=build_default_registry(available_capabilities=_PODCAST_CAPS),
        profiles=MODALITY_PROFILES,
        recommender=recommender,
        strategy=FormatSelectorStrategy.LLM_ASSISTED,
    )
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert recommender.call_count == 0
    assert result.decision.basis == SelectionBasis.SOLE_FEASIBLE


# ── LLM receives only feasible candidates ────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_receives_only_feasible_profiles() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST)
    service = _llm_service(recommender)
    await service.select_format(blueprint, _auto_request(blueprint))
    assert recommender.last_feasible_profiles is not None
    received_modalities = {p.modality for p in recommender.last_feasible_profiles}
    # ELEARNING is not available → should not appear
    assert Modality.ELEARNING not in received_modalities
    assert Modality.PODCAST in received_modalities
    assert Modality.VIDEO in received_modalities


# ── LLM is called exactly once ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_called_exactly_once() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST)
    service = _llm_service(recommender)
    await service.select_format(blueprint, _auto_request(blueprint))
    assert recommender.call_count == 1


# ── Valid recommendation is accepted ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_llm_recommendation_is_accepted() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST)
    service = _llm_service(recommender)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.decision.selected_modality == Modality.PODCAST
    assert result.decision.basis == SelectionBasis.LLM_ASSISTED


# ── Infeasible recommendation is rejected → deterministic fallback ─────────────


@pytest.mark.asyncio
async def test_infeasible_recommendation_triggers_fallback() -> None:
    blueprint = _load_blueprint()
    # ELEARNING is not in the registry → infeasible
    recommender = FakeFormatRecommender(selected_modality=Modality.ELEARNING)
    service = _llm_service(recommender)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.decision.basis == SelectionBasis.LLM_FALLBACK
    assert result.decision.selected_modality != Modality.ELEARNING


@pytest.mark.asyncio
async def test_infeasible_fallback_reason_in_trace() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.ELEARNING)
    service = _llm_service(recommender)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.trace.llm_fallback_reason is not None


# ── Invalid output causes deterministic fallback without repair call ───────────


@pytest.mark.asyncio
async def test_recommender_failure_triggers_deterministic_fallback() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST, fail=True)
    service = _llm_service(recommender)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.decision.basis == SelectionBasis.LLM_FALLBACK
    assert recommender.call_count == 1  # exactly one call, no repair


@pytest.mark.asyncio
async def test_recommender_failure_no_second_call() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST, fail=True)
    service = _llm_service(recommender)
    await service.select_format(blueprint, _auto_request(blueprint))
    assert recommender.call_count == 1


# ── Model metadata is traced ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_recorded_in_trace() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST, model="test-model-v1")
    service = _llm_service(recommender)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.trace.model == "test-model-v1"


@pytest.mark.asyncio
async def test_prompt_version_recorded_in_trace() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.PODCAST)
    service = _llm_service(recommender)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    assert result.trace.prompt_version == recommender.prompt_version


# ── Deterministic strategy ignores recommender ────────────────────────────────


@pytest.mark.asyncio
async def test_deterministic_strategy_ignores_recommender() -> None:
    blueprint = _load_blueprint()
    recommender = FakeFormatRecommender(selected_modality=Modality.VIDEO)
    # Use DETERMINISTIC strategy even though recommender is provided
    service = FormatSelectionService(
        registry=_registry_with_both(),
        profiles=MODALITY_PROFILES,
        recommender=recommender,
        strategy=FormatSelectorStrategy.DETERMINISTIC,
    )
    await service.select_format(blueprint, _auto_request(blueprint))
    assert recommender.call_count == 0
