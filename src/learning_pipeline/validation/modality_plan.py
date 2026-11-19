"""Modality-plan validation — capability conformance and cross-contract content checks."""

from __future__ import annotations

from learning_pipeline.contracts import (
    CourseBlueprint,
    ModalityPlan,
    RLODocument,
)
from learning_pipeline.validation.errors import CrossContractValidationError


class ModalityPlanValidationError(ValueError):
    pass


def _resolve_selected(selection_ids: tuple[str, ...], all_ids: frozenset[str]) -> frozenset[str]:
    """Return the effective selected set: all IDs when selection is empty."""
    return all_ids if not selection_ids else frozenset(selection_ids)


def _check_scene_content_refs(
    scene_id: str,
    rlo: RLODocument,
    tailored_ref_rlo_version: str,
    ref_rlo_version: str,
    ref_objective_ids: tuple[str, ...],
    ref_concept_ids: tuple[str, ...],
    ref_component_ids: tuple[str, ...],
    ref_assessment_ids: tuple[str, ...],
    selection_objective_ids: tuple[str, ...],
    selection_concept_ids: tuple[str, ...],
    selection_component_ids: tuple[str, ...],
    selection_assessment_ids: tuple[str, ...],
) -> None:
    """Validate one RLOContentRef inside a scene against its RLO and selection."""
    if ref_rlo_version != tailored_ref_rlo_version:
        raise CrossContractValidationError(
            "rlo_version_mismatch",
            f"scene '{scene_id}' content ref version '{ref_rlo_version}' does not match "
            f"blueprint pinned version '{tailored_ref_rlo_version}'",
            object_id=scene_id,
            field="rlo_version",
        )

    all_obj_ids = frozenset({rlo.enabling_objective.id})
    selected_obj = _resolve_selected(selection_objective_ids, all_obj_ids)
    for oid in ref_objective_ids:
        if oid not in all_obj_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"scene '{scene_id}' references unknown objective '{oid}' in RLO '{rlo.id}'",
                object_id=oid,
                field="objective_ids",
            )
        if oid not in selected_obj:
            raise CrossContractValidationError(
                "content_not_selected",
                f"scene '{scene_id}' references objective '{oid}' which was not selected "
                f"in the blueprint for RLO '{rlo.id}'",
                object_id=oid,
                field="objective_ids",
            )

    all_concept_ids = frozenset(c.id for c in rlo.concepts)
    selected_concepts = _resolve_selected(selection_concept_ids, all_concept_ids)
    for cid in ref_concept_ids:
        if cid not in all_concept_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"scene '{scene_id}' references unknown concept '{cid}' in RLO '{rlo.id}'",
                object_id=cid,
                field="concept_ids",
            )
        if cid not in selected_concepts:
            raise CrossContractValidationError(
                "content_not_selected",
                f"scene '{scene_id}' references concept '{cid}' which was not selected "
                f"in the blueprint for RLO '{rlo.id}'",
                object_id=cid,
                field="concept_ids",
            )

    all_component_ids = frozenset(c.id for c in rlo.components)
    selected_components = _resolve_selected(selection_component_ids, all_component_ids)
    for cid in ref_component_ids:
        if cid not in all_component_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"scene '{scene_id}' references unknown component '{cid}' in RLO '{rlo.id}'",
                object_id=cid,
                field="component_ids",
            )
        if cid not in selected_components:
            raise CrossContractValidationError(
                "content_not_selected",
                f"scene '{scene_id}' references component '{cid}' which was not selected "
                f"in the blueprint for RLO '{rlo.id}'",
                object_id=cid,
                field="component_ids",
            )

    all_item_ids = frozenset(a.id for a in rlo.assessment_items)
    selected_items = _resolve_selected(selection_assessment_ids, all_item_ids)
    for aid in ref_assessment_ids:
        if aid not in all_item_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"scene '{scene_id}' references unknown assessment '{aid}' in RLO '{rlo.id}'",
                object_id=aid,
                field="assessment_item_ids",
            )
        if aid not in selected_items:
            raise CrossContractValidationError(
                "content_not_selected",
                f"scene '{scene_id}' references assessment '{aid}' which was not selected "
                f"in the blueprint for RLO '{rlo.id}'",
                object_id=aid,
                field="assessment_item_ids",
            )


def validate_modality_plan(
    plan: ModalityPlan,
    blueprint: CourseBlueprint,
    rlos: tuple[RLODocument, ...],
    allowed_capabilities: frozenset[str],
) -> None:
    """
    Cross-contract validation for a ModalityPlan against its CourseBlueprint and source RLOs.

    Duration:
        Only enforced when ``blueprint.learner.duration_limit_minutes`` is explicitly set.
        The sum of ``target_duration_seconds`` must not exceed that limit × 60.
        Scenes that omit ``target_duration_seconds`` are excluded from the sum.
        ``blueprint.estimated_duration_minutes`` is informational only.

    Checks:
    - At least one scene
    - Unique scene IDs
    - Every preferred_capability is in allowed_capabilities
    - Every fallback capability is in allowed_capabilities
    - preferred_capability is not duplicated in acceptable_fallbacks
    - target_duration_seconds is positive when provided
    - Total declared scene duration within learner duration limit (when explicitly set)
    - Every scene content ref's rlo_id exists in the blueprint
    - Every scene content ref's rlo_version matches the blueprint's pinned version
    - Every scene content ref's rlo_id is in the supplied rlos tuple
    - Every referenced objective, concept, component, and assessment exists in the RLO
    - Every referenced content item was selected by the corresponding TailoredRLORef
    """
    if not plan.scenes:
        raise CrossContractValidationError(
            "content_not_selected",
            f"modality plan '{plan.plan_id}' has no scenes",
            object_id=plan.plan_id,
        )

    seen_scene_ids: set[str] = set()
    for scene in plan.scenes:
        if scene.id in seen_scene_ids:
            raise CrossContractValidationError(
                "duplicate_id",
                f"duplicate scene id '{scene.id}'",
                object_id=scene.id,
            )
        seen_scene_ids.add(scene.id)

    rlo_by_id = {rlo.id: rlo for rlo in rlos}
    tailored_ref_by_rlo_id = {ref.rlo_id: ref for ref in blueprint.ordered_rlo_refs}

    total_duration_seconds = 0
    any_duration = False

    for scene in plan.scenes:
        if scene.preferred_capability not in allowed_capabilities:
            raise CrossContractValidationError(
                "unsupported_capability",
                f"scene '{scene.id}' preferred_capability '{scene.preferred_capability}' "
                "is not in the allowed capability set",
                object_id=scene.id,
                field="preferred_capability",
            )

        for cap in scene.acceptable_fallbacks:
            if cap not in allowed_capabilities:
                raise CrossContractValidationError(
                    "unsupported_capability",
                    f"scene '{scene.id}' fallback capability '{cap}' "
                    "is not in the allowed capability set",
                    object_id=scene.id,
                    field="acceptable_fallbacks",
                )

        if scene.preferred_capability in scene.acceptable_fallbacks:
            raise CrossContractValidationError(
                "duplicate_id",
                f"scene '{scene.id}' preferred_capability '{scene.preferred_capability}' "
                "is duplicated in acceptable_fallbacks",
                object_id=scene.id,
                field="acceptable_fallbacks",
            )

        if scene.target_duration_seconds is not None:
            if scene.target_duration_seconds <= 0:
                raise CrossContractValidationError(
                    "invalid_duration",
                    f"scene '{scene.id}' target_duration_seconds must be positive, "
                    f"got {scene.target_duration_seconds}",
                    object_id=scene.id,
                    field="target_duration_seconds",
                )
            total_duration_seconds += scene.target_duration_seconds
            any_duration = True

        for content_ref in scene.source_content:
            if content_ref.rlo_id not in tailored_ref_by_rlo_id:
                raise CrossContractValidationError(
                    "content_reference_not_found",
                    f"scene '{scene.id}' references RLO '{content_ref.rlo_id}' "
                    "which is not in the course blueprint",
                    object_id=content_ref.rlo_id,
                )

            tailored_ref = tailored_ref_by_rlo_id[content_ref.rlo_id]

            if content_ref.rlo_id not in rlo_by_id:
                raise CrossContractValidationError(
                    "rlo_not_found",
                    f"scene '{scene.id}' references RLO '{content_ref.rlo_id}' "
                    "which was not supplied to the validator",
                    object_id=content_ref.rlo_id,
                )

            rlo = rlo_by_id[content_ref.rlo_id]
            sel = tailored_ref.selected_content

            _check_scene_content_refs(
                scene_id=scene.id,
                rlo=rlo,
                tailored_ref_rlo_version=tailored_ref.rlo_version,
                ref_rlo_version=content_ref.rlo_version,
                ref_objective_ids=content_ref.objective_ids,
                ref_concept_ids=content_ref.concept_ids,
                ref_component_ids=content_ref.component_ids,
                ref_assessment_ids=content_ref.assessment_item_ids,
                selection_objective_ids=sel.objective_ids,
                selection_concept_ids=sel.concept_ids,
                selection_component_ids=sel.component_ids,
                selection_assessment_ids=sel.assessment_item_ids,
            )

    if any_duration:
        explicit_limit = blueprint.learner.duration_limit_minutes
        if explicit_limit is not None:
            limit_seconds = explicit_limit * 60
            if total_duration_seconds > limit_seconds:
                raise CrossContractValidationError(
                    "invalid_duration",
                    f"total declared scene duration ({total_duration_seconds}s) exceeds "
                    f"learner duration limit ({limit_seconds}s)",
                )
