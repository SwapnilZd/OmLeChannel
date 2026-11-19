"""Deterministic feasibility evaluation — Phase 11.

Hard feasibility decisions are made without any LLM.
An LLM cannot override blockers, remove hard constraints, or invent capabilities.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    FormatSelectionRequest,
    ModalityDeliveryProfile,
    ModalityFeasibility,
)

from .registry import AvailableWorkflowRegistry


def evaluate_feasibility(
    modality: Modality,
    registry: AvailableWorkflowRegistry,
    profile: ModalityDeliveryProfile,
    request: FormatSelectionRequest,
) -> ModalityFeasibility:
    """Evaluate whether a single modality can satisfy the request.

    All decisions here are deterministic. Hard blockers are exhaustive before
    returning so the caller can surface every reason for infeasibility.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    available = registry.is_available(modality)

    # ── Availability ──────────────────────────────────────────────────────────
    if not available:
        entry = registry.entry_for(modality)
        if entry is None:
            blockers.append(f"no workflow entry registered for '{modality}'")
        elif entry.disabled:
            blockers.append(f"'{modality}' workflow is disabled")
        elif not entry.modality_planner_registered:
            blockers.append(f"'{modality}' modality planner is not registered")
        elif not entry.workflow_planner_registered:
            blockers.append(f"'{modality}' workflow planner is not registered")
        else:
            missing = sorted(
                entry.required_capabilities - registry._available_capabilities
            )
            blockers.append(
                f"'{modality}' requires production capabilities not available: "
                f"{missing}"
            )

    # ── Explicit exclusion ────────────────────────────────────────────────────
    if modality in request.constraints.excluded_modalities:
        blockers.append(f"'{modality}' is explicitly excluded by request constraints")

    c = request.constraints

    # ── Hard delivery and accessibility constraints ───────────────────────────
    if c.requires_interactivity and not profile.supports_interactivity:
        blockers.append(
            f"'{modality}' does not support interactivity (requires_interactivity=True)"
        )
    if c.requires_offline_access and not profile.supports_offline_access:
        blockers.append(
            f"'{modality}' does not support offline access (requires_offline_access=True)"
        )
    if c.low_bandwidth_required and not profile.supports_low_bandwidth:
        blockers.append(
            f"'{modality}' does not support low-bandwidth delivery (low_bandwidth_required=True)"
        )
    if c.captions_required and not profile.supports_captions:
        blockers.append(
            f"'{modality}' does not support captions (captions_required=True)"
        )
    if c.transcript_required and not profile.supports_transcripts:
        blockers.append(
            f"'{modality}' does not support transcripts (transcript_required=True)"
        )
    if c.keyboard_navigation_required and not profile.supports_keyboard_navigation:
        blockers.append(
            f"'{modality}' does not support keyboard navigation "
            f"(keyboard_navigation_required=True)"
        )

    # ── Approximate-only budget warning ──────────────────────────────────────
    if c.maximum_production_cost_usd is not None:
        warnings.append(
            "Exact production cost cannot be guaranteed at format-selection time; "
            "validate budget after workflow planning"
        )

    return ModalityFeasibility(
        modality=modality,
        available=available,
        feasible=len(blockers) == 0,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def evaluate_all_feasibility(
    registry: AvailableWorkflowRegistry,
    profiles: dict[Modality, ModalityDeliveryProfile],
    request: FormatSelectionRequest,
) -> tuple[ModalityFeasibility, ...]:
    """Evaluate feasibility for every Modality enum value in declaration order."""
    return tuple(
        evaluate_feasibility(modality, registry, profiles[modality], request)
        for modality in Modality
    )
