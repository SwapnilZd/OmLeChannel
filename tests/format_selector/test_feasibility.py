"""Deterministic feasibility evaluation tests — Phase 11."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    DeliveryConstraints,
    FormatSelectionMode,
    FormatSelectionRequest,
    ModalityDeliveryProfile,
)
from learning_pipeline.format_selector.feasibility import (
    evaluate_all_feasibility,
    evaluate_feasibility,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES, PODCAST_PROFILE
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


def _podcast_entry(
    *,
    planner: bool = True,
    workflow: bool = True,
    disabled: bool = False,
) -> WorkflowEntry:
    return WorkflowEntry(
        modality=Modality.PODCAST,
        modality_planner_registered=planner,
        workflow_planner_registered=workflow,
        required_capabilities=frozenset({"speech.synthesize", "audio.assemble"}),
        disabled=disabled,
    )


def _make_registry(
    *entries: WorkflowEntry,
    caps: frozenset[str] = _PODCAST_CAPS,
) -> AvailableWorkflowRegistry:
    return AvailableWorkflowRegistry(entries=entries, available_capabilities=caps)


def _auto_request(**overrides) -> FormatSelectionRequest:
    defaults = dict(request_id="req-01", blueprint_id="bp-01", mode=FormatSelectionMode.AUTO)
    defaults.update(overrides)
    return FormatSelectionRequest(**defaults)


def _explicit_request(modality: Modality, **overrides) -> FormatSelectionRequest:
    defaults = dict(
        request_id="req-01", blueprint_id="bp-01",
        mode=FormatSelectionMode.EXPLICIT, requested_modality=modality,
    )
    defaults.update(overrides)
    return FormatSelectionRequest(**defaults)


# ── Excluded modality is blocked ──────────────────────────────────────────────


def test_excluded_modality_is_blocked() -> None:
    reg = _make_registry(_podcast_entry())
    request = _auto_request(
        constraints=DeliveryConstraints(excluded_modalities=(Modality.PODCAST,)),
    )
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is False
    assert any("excluded" in b for b in result.blockers)


# ── Unavailable workflow is blocked ──────────────────────────────────────────


def test_unavailable_workflow_is_blocked() -> None:
    reg = _make_registry(_podcast_entry(planner=False))
    request = _auto_request()
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is False
    assert result.available is False
    assert len(result.blockers) > 0


def test_disabled_workflow_is_blocked() -> None:
    reg = _make_registry(_podcast_entry(disabled=True))
    request = _auto_request()
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is False
    assert any("disabled" in b for b in result.blockers)


# ── Interactivity constraint ──────────────────────────────────────────────────


def test_interactivity_required_blocks_podcast() -> None:
    reg = _make_registry(_podcast_entry())
    request = _auto_request(constraints=DeliveryConstraints(requires_interactivity=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is False
    assert any("interactivity" in b for b in result.blockers)


def test_interactivity_required_allows_elearning() -> None:
    elearning_profile = MODALITY_PROFILES[Modality.ELEARNING]
    elearning_entry = WorkflowEntry(
        modality=Modality.ELEARNING,
        modality_planner_registered=True,
        workflow_planner_registered=True,
        required_capabilities=frozenset({"html.compile"}),
    )
    reg = _make_registry(elearning_entry, caps=frozenset({"html.compile"}))
    request = _auto_request(constraints=DeliveryConstraints(requires_interactivity=True))
    result = evaluate_feasibility(Modality.ELEARNING, reg, elearning_profile, request)
    assert result.feasible is True


# ── Low bandwidth constraint ──────────────────────────────────────────────────


def test_low_bandwidth_required_blocks_non_supporting_modality() -> None:
    video_profile = MODALITY_PROFILES[Modality.VIDEO]
    video_entry = WorkflowEntry(
        modality=Modality.VIDEO,
        modality_planner_registered=True,
        workflow_planner_registered=True,
        required_capabilities=frozenset({"video.render"}),
    )
    reg = _make_registry(video_entry, caps=frozenset({"video.render"}))
    request = _auto_request(constraints=DeliveryConstraints(low_bandwidth_required=True))
    result = evaluate_feasibility(Modality.VIDEO, reg, video_profile, request)
    assert result.feasible is False
    assert any("low-bandwidth" in b for b in result.blockers)


def test_low_bandwidth_required_allows_podcast() -> None:
    reg = _make_registry(_podcast_entry())
    request = _auto_request(constraints=DeliveryConstraints(low_bandwidth_required=True))
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is True


# ── Feasible modalities remain candidates ─────────────────────────────────────


def test_feasible_podcast_with_no_constraints() -> None:
    reg = _make_registry(_podcast_entry())
    request = _auto_request()
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is True
    assert result.blockers == ()


# ── evaluate_all_feasibility covers all modalities ────────────────────────────


def test_evaluate_all_covers_all_modalities() -> None:
    reg = build_default_registry(available_capabilities=_PODCAST_CAPS)
    request = _auto_request()
    all_results = evaluate_all_feasibility(reg, MODALITY_PROFILES, request)
    evaluated = {r.modality for r in all_results}
    assert evaluated == set(Modality)


def test_evaluate_all_deterministic_order() -> None:
    reg = build_default_registry(available_capabilities=_PODCAST_CAPS)
    request = _auto_request()
    r1 = evaluate_all_feasibility(reg, MODALITY_PROFILES, request)
    r2 = evaluate_all_feasibility(reg, MODALITY_PROFILES, request)
    assert [r.modality for r in r1] == [r.modality for r in r2]


# ── Cost warning (not a blocker) ──────────────────────────────────────────────


def test_cost_constraint_produces_warning_not_blocker() -> None:
    reg = _make_registry(_podcast_entry())
    request = _auto_request(
        constraints=DeliveryConstraints(maximum_production_cost_usd=5.0)
    )
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.feasible is True
    assert len(result.warnings) > 0
    assert result.blockers == ()


# ── Availability flag matches is_available ────────────────────────────────────


def test_availability_flag_matches_registry() -> None:
    reg = _make_registry(_podcast_entry(planner=False))
    request = _auto_request()
    result = evaluate_feasibility(Modality.PODCAST, reg, PODCAST_PROFILE, request)
    assert result.available == reg.is_available(Modality.PODCAST)
