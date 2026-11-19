"""Draft validation — Phase 12.

Validates the LLM-produced CourseAssemblyDraft before passing it to
the deterministic blueprint builder.
"""
from __future__ import annotations

from learning_pipeline.contracts.curriculum_assembly import (
    CourseAssemblyDraft,
    CourseAssemblyRequest,
    RLOAssemblyContext,
)

_MODALITY_KEYWORDS = frozenset({
    "podcast", "video", "elearning", "e-learning",
    "host", "expert", "tts", "voice", "speaker",
    "react", "html", "slide", "screen", "manim",
    "animation", "shot", "scene", "narrat",
})


class DraftValidationError(ValueError):
    """Raised when the assembly draft fails semantic or structural validation."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def validate_draft(
    draft: CourseAssemblyDraft,
    request: CourseAssemblyRequest,
    eligible_contexts: tuple[RLOAssemblyContext, ...],
) -> None:
    """Validate the assembly draft against request constraints and eligible RLOs.

    Raises DraftValidationError on any structural or semantic violation.
    """
    eligible_ids = {(c.rlo_id, c.rlo_version) for c in eligible_contexts}
    eligible_rlo_ids = {c.rlo_id for c in eligible_contexts}

    # Every draft RLO must be among the eligible candidates
    for d in draft.ordered_rlo_drafts:
        if (d.rlo_id, d.rlo_version) not in eligible_ids:
            raise DraftValidationError(
                f"Included RLO '{d.rlo_id}' v{d.rlo_version} is not among eligible candidates."
            )

    for o in draft.omitted_rlos:
        if (o.rlo_id, o.rlo_version) not in eligible_ids:
            raise DraftValidationError(
                f"Omitted RLO '{o.rlo_id}' v{o.rlo_version} is not among eligible candidates."
            )

    # Every eligible candidate must appear exactly once
    included_keys = {(d.rlo_id, d.rlo_version) for d in draft.ordered_rlo_drafts}
    omitted_keys = {(o.rlo_id, o.rlo_version) for o in draft.omitted_rlos}
    accounted = included_keys | omitted_keys
    missing = eligible_ids - accounted
    if missing:
        raise DraftValidationError(
            f"Eligible candidates not accounted for (neither included nor omitted): {missing}"
        )

    # Required RLOs cannot be omitted
    omitted_rlo_ids = {o.rlo_id for o in draft.omitted_rlos}
    for req_id in request.constraints.required_rlo_ids:
        if req_id in omitted_rlo_ids:
            raise DraftValidationError(
                f"Required RLO '{req_id}' was omitted from the draft."
            )
        if req_id not in {d.rlo_id for d in draft.ordered_rlo_drafts}:
            if req_id in eligible_rlo_ids:
                raise DraftValidationError(
                    f"Required RLO '{req_id}' is missing from the draft."
                )

    # Order must be contiguous starting at 1
    orders = sorted(d.order for d in draft.ordered_rlo_drafts)
    expected = list(range(1, len(orders) + 1))
    if orders and orders != expected:
        raise DraftValidationError(
            f"TailoredRLODraft order values must be contiguous starting at 1, got {orders}"
        )

    # RLO ID/version consistency
    context_map = {c.rlo_id: c.rlo_version for c in eligible_contexts}
    for d in draft.ordered_rlo_drafts:
        if context_map.get(d.rlo_id) != d.rlo_version:
            raise DraftValidationError(
                f"RLO '{d.rlo_id}' version mismatch: draft has '{d.rlo_version}', "
                f"candidate has '{context_map.get(d.rlo_id)}'."
            )
    for o in draft.omitted_rlos:
        if context_map.get(o.rlo_id) != o.rlo_version:
            raise DraftValidationError(
                f"Omitted RLO '{o.rlo_id}' version mismatch: draft has '{o.rlo_version}', "
                f"candidate has '{context_map.get(o.rlo_id)}'."
            )

    # Assessment strategy must be modality-agnostic
    strategy_lower = draft.assessment_strategy.lower()
    hits = [kw for kw in _MODALITY_KEYWORDS if kw in strategy_lower]
    if hits:
        raise DraftValidationError(
            f"assessment_strategy contains modality-specific terms {hits}. "
            "Keep assessment strategy modality-agnostic."
        )

    # Learning outcomes must be non-empty strings
    for outcome in draft.learning_outcomes:
        if not outcome.strip():
            raise DraftValidationError("learning_outcomes must not contain blank strings.")
