"""
Shared modality draft validation primitives.

This module contains only the shared error type and coverage check used across
modality-specific validation modules (e.g. podcast, video).

Podcast-specific validation (validate_podcast_modality_draft, compute_coverage_report,
check_ordering, check_duration) lives in planners.modality.podcast.validation.
"""
from __future__ import annotations

from learning_pipeline.contracts.planning import ModalityCoverageReport


class ModalityDraftValidationError(ValueError):
    """Raised when a modality draft fails semantic validation."""


# ── Coverage ──────────────────────────────────────────────────────────────────


def check_coverage(
    coverage: ModalityCoverageReport,
) -> None:
    """Raise ModalityDraftValidationError if any required content is uncovered."""
    missing: list[str] = []
    if coverage.uncovered_objective_ids:
        missing.append(f"objectives: {list(coverage.uncovered_objective_ids)}")
    if coverage.uncovered_concept_ids:
        missing.append(f"concepts: {list(coverage.uncovered_concept_ids)}")
    if coverage.uncovered_component_ids:
        missing.append(f"components: {list(coverage.uncovered_component_ids)}")
    if coverage.uncovered_assessment_ids:
        missing.append(f"assessments: {list(coverage.uncovered_assessment_ids)}")
    if missing:
        raise ModalityDraftValidationError(
            "Required content not covered by any scene: " + "; ".join(missing)
        )
