"""Accessibility hard-constraint tests — Phase 11."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    DeliveryConstraints,
    FormatSelectionMode,
    FormatSelectionRequest,
    SelectionBasis,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES, PODCAST_PROFILE
from learning_pipeline.format_selector.feasibility import evaluate_feasibility
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)
from learning_pipeline.format_selector.service import FormatSelectionError, FormatSelectionService

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_BP_PATH = Path(__file__).parents[2] / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _auto_request(blueprint: CourseBlueprint, constraints: DeliveryConstraints) -> FormatSelectionRequest:
    return FormatSelectionRequest(
        request_id="req-access",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.AUTO,
        constraints=constraints,
    )


def _service() -> FormatSelectionService:
    return FormatSelectionService(
        registry=build_default_registry(available_capabilities=_PODCAST_CAPS),
        profiles=MODALITY_PROFILES,
    )


def _podcast_entry() -> WorkflowEntry:
    return WorkflowEntry(
        modality=Modality.PODCAST,
        modality_planner_registered=True,
        workflow_planner_registered=True,
        required_capabilities=frozenset({"speech.synthesize", "audio.assemble"}),
    )


def _make_request(**kwargs) -> FormatSelectionRequest:
    return FormatSelectionRequest(
        request_id="req-01", blueprint_id="bp-01",
        mode=FormatSelectionMode.AUTO, **kwargs,
    )


# ── Captions required ─────────────────────────────────────────────────────────


def test_captions_required_blocked_when_profile_does_not_support() -> None:
    from learning_pipeline.contracts.format_selection import ModalityDeliveryProfile
    no_captions = ModalityDeliveryProfile(
        modality=Modality.PODCAST, enabled=True, description="test",
        supports_interactivity=False, supports_offline_access=True,
        supports_low_bandwidth=True, supports_screen_free_delivery=True,
        supports_captions=False, supports_transcripts=True, supports_keyboard_navigation=False,
    )
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(captions_required=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, no_captions, request)
    assert result.feasible is False
    assert any("captions" in b for b in result.blockers)


def test_captions_supported_profile_passes() -> None:
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(captions_required=True))
    # PODCAST_PROFILE supports captions
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is True


# ── Transcript required ───────────────────────────────────────────────────────


def test_transcript_required_blocked_when_profile_does_not_support() -> None:
    from learning_pipeline.contracts.format_selection import ModalityDeliveryProfile
    no_transcript = ModalityDeliveryProfile(
        modality=Modality.PODCAST, enabled=True, description="test",
        supports_interactivity=False, supports_offline_access=True,
        supports_low_bandwidth=True, supports_screen_free_delivery=True,
        supports_captions=True, supports_transcripts=False, supports_keyboard_navigation=False,
    )
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(transcript_required=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, no_transcript, request)
    assert result.feasible is False
    assert any("transcript" in b for b in result.blockers)


def test_transcript_supported_passes() -> None:
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(transcript_required=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is True


# ── Keyboard navigation required ──────────────────────────────────────────────


def test_keyboard_navigation_required_blocks_podcast() -> None:
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(keyboard_navigation_required=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is False
    assert any("keyboard" in b for b in result.blockers)


def test_keyboard_navigation_required_allows_elearning() -> None:
    elearning = MODALITY_PROFILES[Modality.ELEARNING]
    elearning_entry = WorkflowEntry(
        modality=Modality.ELEARNING,
        modality_planner_registered=True,
        workflow_planner_registered=True,
        required_capabilities=frozenset({"html.compile"}),
    )
    reg = AvailableWorkflowRegistry(
        entries=(elearning_entry,),
        available_capabilities=frozenset({"html.compile"}),
    )
    request = _make_request(constraints=DeliveryConstraints(keyboard_navigation_required=True))
    result = evaluate_feasibility(Modality.ELEARNING, reg, elearning, request)
    assert result.feasible is True


# ── Screen-free preferred (soft preference, scored not blocked) ───────────────


def test_screen_free_preferred_does_not_block_any_modality() -> None:
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(screen_free_preferred=True))
    # Podcast supports screen-free → no blockers even with preference set
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is True


# ── Offline access required ────────────────────────────────────────────────────


def test_offline_required_blocks_modality_that_does_not_support_it() -> None:
    from learning_pipeline.contracts.format_selection import ModalityDeliveryProfile
    no_offline = ModalityDeliveryProfile(
        modality=Modality.PODCAST, enabled=True, description="test",
        supports_interactivity=False, supports_offline_access=False,
        supports_low_bandwidth=True, supports_screen_free_delivery=True,
        supports_captions=True, supports_transcripts=True, supports_keyboard_navigation=False,
    )
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(requires_offline_access=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, no_offline, request)
    assert result.feasible is False
    assert any("offline" in b for b in result.blockers)


def test_offline_access_required_allows_podcast() -> None:
    reg = AvailableWorkflowRegistry(entries=(_podcast_entry(),), available_capabilities=_PODCAST_CAPS)
    request = _make_request(constraints=DeliveryConstraints(requires_offline_access=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is True


# ── No feasible modalities when all fail hard constraints ─────────────────────


@pytest.mark.asyncio
async def test_all_fail_hard_constraints_raises() -> None:
    blueprint = _load_blueprint()
    service = _service()
    # keyboard navigation required blocks podcast (only available modality)
    constraints = DeliveryConstraints(keyboard_navigation_required=True)
    request = _auto_request(blueprint, constraints)
    with pytest.raises(FormatSelectionError):
        await service.select_format(blueprint, request)
