"""Versioned deterministic scoring policy for feasible modality candidates — Phase 11.

Policy version: format_scoring_v2

Given identical inputs and this policy version, scores are identical.
Tiebreaker: alphabetical ascending by modality string value
("elearning" < "podcast" < "video"), so e-learning beats podcast beats video on ties.
"""
from __future__ import annotations

from learning_pipeline.contracts.assembly import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    FormatSelectionRequest,
    ModalityDeliveryProfile,
    ModalityEvaluation,
    ModalityFeasibility,
    SelectionFactor,
)

SCORING_POLICY_VERSION = "format_scoring_v2"

_ASSESSMENT_FOCUS_KEYWORDS = frozenset({
    "quiz", "knowledge check", "assessment", "scored", "practice", "test",
})

_SPOKEN_ASSESSMENT_KEYWORDS = frozenset({
    "spoken", "reflective", "reflection", "discussion", "dialogue",
})


def score_modality(
    modality: Modality,
    profile: ModalityDeliveryProfile,
    request: FormatSelectionRequest,
    blueprint: CourseBlueprint,
) -> ModalityEvaluation:
    """Compute a deterministic score for a single feasible modality.

    All factors in format_scoring_v2 are documented here.
    """
    factors: list[SelectionFactor] = []

    # ── Factor 1: Preferred modality order ────────────────────────────────────
    # +10 for first preference, -2 per subsequent position. Floor at 0.
    if modality in request.preferred_modalities:
        idx = list(request.preferred_modalities).index(modality)
        score = max(0.0, 10.0 - idx * 2.0)
        factors.append(SelectionFactor(
            factor="preferred_modality_order",
            score=score,
            rationale=f"'{modality}' is preferred choice #{idx + 1}",
        ))

    # ── Factor 2: Screen-free compatibility ───────────────────────────────────
    # +5 when learner prefers screen-free and modality supports it; -3 when not.
    if request.constraints.screen_free_preferred:
        if profile.supports_screen_free_delivery:
            factors.append(SelectionFactor(
                factor="screen_free_compatible",
                score=5.0,
                rationale=f"Learner prefers screen-free; '{modality}' supports it",
            ))
        else:
            factors.append(SelectionFactor(
                factor="screen_free_incompatible",
                score=-3.0,
                rationale=f"Learner prefers screen-free; '{modality}' requires a screen",
            ))

    # ── Factor 3: Low-bandwidth compatibility ─────────────────────────────────
    # +2 when low-bandwidth is required (already a hard blocker if unsupported,
    # so this rewards the modalities that passed).
    if request.constraints.low_bandwidth_required and profile.supports_low_bandwidth:
        factors.append(SelectionFactor(
            factor="low_bandwidth_compatible",
            score=2.0,
            rationale=f"Low-bandwidth delivery required; '{modality}' supports it",
        ))

    # ── Factor 4: Assessment strategy alignment ────────────────────────────────
    assessment = blueprint.assessment_strategy.lower()
    has_assessment_focus = any(kw in assessment for kw in _ASSESSMENT_FOCUS_KEYWORDS)
    has_spoken_assessment = any(kw in assessment for kw in _SPOKEN_ASSESSMENT_KEYWORDS)

    if has_assessment_focus:
        if profile.supports_interactivity:
            factors.append(SelectionFactor(
                factor="assessment_strategy_interactivity",
                score=3.0,
                rationale=(
                    f"Assessment strategy emphasises quizzes/scored content; "
                    f"'{modality}' supports interactive assessment"
                ),
            ))
        elif has_spoken_assessment:
            factors.append(SelectionFactor(
                factor="assessment_strategy_spoken",
                score=1.0,
                rationale=(
                    f"Assessment strategy uses spoken or reflective methods; "
                    f"'{modality}' supports spoken knowledge checks"
                ),
            ))

    # ── Factor 5: Instructional scope and complexity ──────────────────────────
    # Podcast is a short, focused treatment rather than an audio rendering of a
    # broad course. Count selected source units instead of relying on duration
    # estimates, which are intentionally approximate upstream.
    rlo_count = len(blueprint.ordered_rlo_refs)
    selected_unit_count = sum(
        len(ref.selected_content.objective_ids)
        + len(ref.selected_content.concept_ids)
        + len(ref.selected_content.component_ids)
        + len(ref.selected_content.assessment_item_ids)
        for ref in blueprint.ordered_rlo_refs
    )
    focused_scope = rlo_count <= 2 and selected_unit_count <= 18
    complex_scope = rlo_count >= 3 or selected_unit_count > 18

    if focused_scope and modality == Modality.PODCAST:
        factors.append(SelectionFactor(
            factor="instructional_scope",
            score=2.0,
            rationale=(
                f"Focused scope ({rlo_count} RLOs, {selected_unit_count} selected content units) "
                "is suitable for a concise host-expert podcast"
            ),
        ))
    elif complex_scope and modality == Modality.PODCAST:
        factors.append(SelectionFactor(
            factor="instructional_scope",
            score=-12.0,
            rationale=(
                f"Broad scope ({rlo_count} RLOs, {selected_unit_count} selected content units) "
                "is unsuitable for a concise podcast"
            ),
        ))
    elif complex_scope and modality == Modality.ELEARNING:
        factors.append(SelectionFactor(
            factor="instructional_scope",
            score=6.0,
            rationale=(
                f"Broad scope ({rlo_count} RLOs, {selected_unit_count} selected content units) "
                "benefits from structured, multimodal e-learning"
            ),
        ))

    total = sum(f.score for f in factors)

    return ModalityEvaluation(
        modality=modality,
        feasible=True,
        blockers=(),
        factors=tuple(factors),
        total_score=total,
    )


def score_feasible_modalities(
    feasible: tuple[ModalityFeasibility, ...],
    profiles: dict[Modality, ModalityDeliveryProfile],
    request: FormatSelectionRequest,
    blueprint: CourseBlueprint,
) -> tuple[ModalityEvaluation, ...]:
    return tuple(
        score_modality(f.modality, profiles[f.modality], request, blueprint)
        for f in feasible
    )


def select_best(
    evaluations: tuple[ModalityEvaluation, ...],
    request: FormatSelectionRequest,
) -> Modality:
    """Select the highest-scoring feasible candidate.

    Tiebreaker: alphabetical ascending by modality string value
    ("elearning" < "podcast" < "video"), documented in SCORING_POLICY_VERSION.
    """
    feasible = [e for e in evaluations if e.feasible]
    if not feasible:
        raise ValueError("No feasible evaluations to select from")
    feasible.sort(key=lambda e: (-e.total_score, e.modality.value))
    return feasible[0].modality
