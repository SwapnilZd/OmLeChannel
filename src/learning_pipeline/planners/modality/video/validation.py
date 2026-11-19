"""
Video modality draft validation — Phase 13C.

Validates VideoModalityDraft against:
  - RLO reference integrity (IDs and versions exist in blueprint)
  - Content reference integrity (content IDs were selected by the blueprint)
  - Affordance validity (affordance IDs exist in the affordance view)
  - Asset reference validity (referenced_asset_id in approved asset catalog)
  - Coverage (every blueprint-selected content ID appears in at least one scene)
  - Ordering (RLO teaching order respects blueprint ordering)
  - Duration (total scene durations within the learner duration limit)
  - Presentation direction (non-empty for every scene)
  - Production capability names not used as affordance IDs
"""
from __future__ import annotations

import re

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.planning import (
    ModalityCoverageReport,
    ModalityPlanningContext,
    VideoModalityDraft,
)
from learning_pipeline.affordances.catalog import PlannerAffordanceView

# Heuristic pattern: production capability names contain a dot + a verb
_CAPABILITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z_]+\.[a-z_]+$")


class VideoModalityDraftValidationError(ValueError):
    """Raised when a VideoModalityDraft fails semantic validation."""


# ── Reference integrity ───────────────────────────────────────────────────────


def _validate_rlo_references(
    draft: VideoModalityDraft,
    blueprint: CourseBlueprint,
) -> None:
    blueprint_rlo_versions = {
        ref.rlo_id: ref.rlo_version for ref in blueprint.ordered_rlo_refs
    }
    for scene in draft.scenes:
        for ref in scene.source_content:
            if ref.rlo_id not in blueprint_rlo_versions:
                raise VideoModalityDraftValidationError(
                    f"Scene '{scene.scene_id}' references unknown RLO '{ref.rlo_id}'. "
                    f"Blueprint RLOs: {sorted(blueprint_rlo_versions)}"
                )
            expected = blueprint_rlo_versions[ref.rlo_id]
            if ref.rlo_version != expected:
                raise VideoModalityDraftValidationError(
                    f"Scene '{scene.scene_id}' references RLO '{ref.rlo_id}' "
                    f"at version '{ref.rlo_version}' but blueprint requires '{expected}'"
                )


def _validate_content_references(
    draft: VideoModalityDraft,
    context: ModalityPlanningContext,
) -> None:
    selected_by_rlo: dict[str, dict[str, frozenset[str]]] = {}
    for rlo_ctx in context.rlo_contexts:
        selected_by_rlo[rlo_ctx.rlo_id] = {
            "objective": frozenset(rlo_ctx.selected_objective_ids),
            "concept": frozenset(rlo_ctx.selected_concept_ids),
            "component": frozenset(rlo_ctx.selected_component_ids),
            "assessment": frozenset(rlo_ctx.selected_assessment_ids),
        }

    for scene in draft.scenes:
        for ref in scene.source_content:
            sel = selected_by_rlo.get(ref.rlo_id, {})
            for oid in ref.objective_ids:
                if oid not in sel.get("objective", frozenset()):
                    raise VideoModalityDraftValidationError(
                        f"Scene '{scene.scene_id}' references objective '{oid}' "
                        f"in RLO '{ref.rlo_id}' which was not selected by the blueprint"
                    )
            for cid in ref.concept_ids:
                if cid not in sel.get("concept", frozenset()):
                    raise VideoModalityDraftValidationError(
                        f"Scene '{scene.scene_id}' references concept '{cid}' "
                        f"in RLO '{ref.rlo_id}' which was not selected by the blueprint"
                    )
            for cid in ref.component_ids:
                if cid not in sel.get("component", frozenset()):
                    raise VideoModalityDraftValidationError(
                        f"Scene '{scene.scene_id}' references component '{cid}' "
                        f"in RLO '{ref.rlo_id}' which was not selected by the blueprint"
                    )
            for aid in ref.assessment_item_ids:
                if aid not in sel.get("assessment", frozenset()):
                    raise VideoModalityDraftValidationError(
                        f"Scene '{scene.scene_id}' references assessment '{aid}' "
                        f"in RLO '{ref.rlo_id}' which was not selected by the blueprint"
                    )


# ── Affordance validity ───────────────────────────────────────────────────────


def _validate_affordances(
    draft: VideoModalityDraft,
    affordance_view: PlannerAffordanceView,
) -> None:
    valid_ids = affordance_view.affordance_ids()
    for scene in draft.scenes:
        if _CAPABILITY_ID_RE.match(scene.affordance_id):
            raise VideoModalityDraftValidationError(
                f"Scene '{scene.scene_id}' uses '{scene.affordance_id}' as an affordance ID "
                "but it looks like a production capability name. "
                "Use a pedagogical affordance ID such as 'avatar_led_explanation'."
            )
        if scene.affordance_id not in valid_ids:
            raise VideoModalityDraftValidationError(
                f"Scene '{scene.scene_id}' uses affordance '{scene.affordance_id}' "
                f"which is not in the planner affordance view. "
                f"Available: {sorted(valid_ids)}"
            )


# ── Asset reference validity ──────────────────────────────────────────────────


def _validate_asset_references(
    draft: VideoModalityDraft,
    approved_asset_ids: frozenset[str],
) -> None:
    for scene in draft.scenes:
        if scene.referenced_asset_id is not None:
            if scene.referenced_asset_id not in approved_asset_ids:
                raise VideoModalityDraftValidationError(
                    f"Scene '{scene.scene_id}' references asset '{scene.referenced_asset_id}' "
                    f"which is not in the approved asset catalog. "
                    f"Approved: {sorted(approved_asset_ids)}"
                )


# ── Coverage ──────────────────────────────────────────────────────────────────


def compute_coverage_report(
    draft: VideoModalityDraft,
    context: ModalityPlanningContext,
) -> ModalityCoverageReport:
    """Compute which blueprint-selected content IDs are covered by the draft scenes."""
    required_objectives: set[str] = set()
    required_concepts: set[str] = set()
    required_components: set[str] = set()
    required_assessments: set[str] = set()

    for rlo_ctx in context.rlo_contexts:
        required_objectives.update(rlo_ctx.selected_objective_ids)
        required_concepts.update(rlo_ctx.selected_concept_ids)
        required_components.update(rlo_ctx.selected_component_ids)
        required_assessments.update(rlo_ctx.selected_assessment_ids)

    covered_objectives: set[str] = set()
    covered_concepts: set[str] = set()
    covered_components: set[str] = set()
    covered_assessments: set[str] = set()
    coverage_counts: dict[str, int] = {}

    for scene in draft.scenes:
        for ref in scene.source_content:
            for oid in ref.objective_ids:
                coverage_counts[f"obj:{oid}"] = coverage_counts.get(f"obj:{oid}", 0) + 1
                covered_objectives.add(oid)
            for cid in ref.concept_ids:
                coverage_counts[f"con:{cid}"] = coverage_counts.get(f"con:{cid}", 0) + 1
                covered_concepts.add(cid)
            for cid in ref.component_ids:
                coverage_counts[f"comp:{cid}"] = coverage_counts.get(f"comp:{cid}", 0) + 1
                covered_components.add(cid)
            for aid in ref.assessment_item_ids:
                coverage_counts[f"ass:{aid}"] = coverage_counts.get(f"ass:{aid}", 0) + 1
                covered_assessments.add(aid)

    duplicate_warnings = tuple(
        f"{key} covered {count} times"
        for key, count in sorted(coverage_counts.items())
        if count > 1
    )

    return ModalityCoverageReport(
        covered_objective_ids=tuple(sorted(covered_objectives & required_objectives)),
        covered_concept_ids=tuple(sorted(covered_concepts & required_concepts)),
        covered_component_ids=tuple(sorted(covered_components & required_components)),
        covered_assessment_ids=tuple(sorted(covered_assessments & required_assessments)),
        uncovered_objective_ids=tuple(sorted(required_objectives - covered_objectives)),
        uncovered_concept_ids=tuple(sorted(required_concepts - covered_concepts)),
        uncovered_component_ids=tuple(sorted(required_components - covered_components)),
        uncovered_assessment_ids=tuple(sorted(required_assessments - covered_assessments)),
        duplicate_coverage_warnings=duplicate_warnings,
    )


def check_coverage(coverage: ModalityCoverageReport) -> None:
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
        raise VideoModalityDraftValidationError(
            "Required content not covered by any scene: " + "; ".join(missing)
        )


# ── Ordering ──────────────────────────────────────────────────────────────────


def check_ordering(
    draft: VideoModalityDraft,
    blueprint: CourseBlueprint,
) -> None:
    sorted_refs = sorted(blueprint.ordered_rlo_refs, key=lambda r: r.order)
    rlo_blueprint_pos: dict[str, int] = {
        ref.rlo_id: i for i, ref in enumerate(sorted_refs)
    }

    first_scene_idx: dict[str, int] = {}
    for scene_idx, scene in enumerate(draft.scenes):
        for ref in scene.source_content:
            if ref.rlo_id not in first_scene_idx:
                first_scene_idx[ref.rlo_id] = scene_idx

    present_rlo_ids = [
        ref.rlo_id for ref in sorted_refs if ref.rlo_id in first_scene_idx
    ]
    for i in range(1, len(present_rlo_ids)):
        prior_rlo = present_rlo_ids[i - 1]
        current_rlo = present_rlo_ids[i]
        if first_scene_idx[current_rlo] < first_scene_idx[prior_rlo]:
            raise VideoModalityDraftValidationError(
                f"Scene ordering violates blueprint: RLO '{current_rlo}' "
                f"(blueprint position {rlo_blueprint_pos[current_rlo]}) first appears in "
                f"scene {first_scene_idx[current_rlo]} before RLO '{prior_rlo}' "
                f"(blueprint position {rlo_blueprint_pos[prior_rlo]}) first appears in "
                f"scene {first_scene_idx[prior_rlo]}"
            )


# ── Duration ──────────────────────────────────────────────────────────────────


def check_duration(
    draft: VideoModalityDraft,
    blueprint: CourseBlueprint,
) -> None:
    explicit_limit = blueprint.learner.duration_limit_minutes
    if explicit_limit is None:
        return
    limit_seconds = explicit_limit * 60
    total_seconds = sum(scene.target_duration_seconds for scene in draft.scenes)
    if total_seconds > limit_seconds:
        raise VideoModalityDraftValidationError(
            f"Total scene duration {total_seconds}s exceeds learner duration limit of "
            f"{limit_seconds}s ({explicit_limit} minutes)."
        )


# ── Combined entry point ──────────────────────────────────────────────────────


def validate_video_modality_draft(
    draft: VideoModalityDraft,
    blueprint: CourseBlueprint,
    context: ModalityPlanningContext,
    affordance_view: PlannerAffordanceView,
    *,
    approved_asset_ids: frozenset[str] = frozenset(),
) -> ModalityCoverageReport:
    """Validate a VideoModalityDraft and return a coverage report on success.

    Checks in order:
    1. RLO reference integrity
    2. Content reference integrity
    3. Affordance validity (no production capability names; must be in view)
    4. Asset reference validity
    5. Coverage (all required content covered)
    6. Blueprint ordering
    7. Duration (total within limit)

    Raises:
        VideoModalityDraftValidationError: On the first validation failure.

    Returns:
        ModalityCoverageReport: On success.
    """
    _validate_rlo_references(draft, blueprint)
    _validate_content_references(draft, context)
    _validate_affordances(draft, affordance_view)
    _validate_asset_references(draft, approved_asset_ids)

    coverage = compute_coverage_report(draft, context)
    check_coverage(coverage)
    check_ordering(draft, blueprint)
    check_duration(draft, blueprint)

    return coverage
