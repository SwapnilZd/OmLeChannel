"""RLO content-reference validation — selection constraints and scene lineage checks."""

from __future__ import annotations

from learning_pipeline.contracts import (
    ModalityPlan,
    RLOContentSelection,
    RLODocument,
    TailoredRLORef,
)
from learning_pipeline.validation.errors import CrossContractValidationError


class InvalidRLOContentReferenceError(ValueError):
    pass


def validate_rlo_selection(
    tailored_ref: TailoredRLORef,
    rlo: RLODocument,
) -> None:
    """
    Validate that a TailoredRLORef correctly references its source RLODocument.

    Checks:
    - rlo_id matches the supplied RLO
    - rlo_version matches the supplied RLO
    - selected_content specifies at least one content type explicitly
    - All selected objective IDs exist in the RLO (enabling_objective only;
      terminal_objective is a plain string with no addressable ID)
    - All selected concept IDs exist in the RLO
    - All selected component IDs exist in the RLO
    - All selected assessment item IDs exist in the RLO
    """
    if tailored_ref.rlo_id != rlo.id:
        raise CrossContractValidationError(
            "rlo_not_found",
            f"tailored ref rlo_id '{tailored_ref.rlo_id}' does not match RLO id '{rlo.id}'",
            object_id=tailored_ref.rlo_id,
            field="rlo_id",
        )

    if tailored_ref.rlo_version != rlo.version:
        raise CrossContractValidationError(
            "rlo_version_mismatch",
            f"tailored ref expects RLO '{tailored_ref.rlo_id}' at version "
            f"'{tailored_ref.rlo_version}' but supplied RLO is at version '{rlo.version}'",
            object_id=tailored_ref.rlo_id,
            field="rlo_version",
        )

    selection = tailored_ref.selected_content

    if not (
        selection.objective_ids
        or selection.concept_ids
        or selection.component_ids
        or selection.assessment_item_ids
    ):
        raise CrossContractValidationError(
            "content_not_selected",
            f"tailored ref for RLO '{tailored_ref.rlo_id}' must specify at least one "
            "content type explicitly in selected_content",
            object_id=tailored_ref.rlo_id,
            field="selected_content",
        )

    valid_obj_ids = {rlo.enabling_objective.id}
    for oid in selection.objective_ids:
        if oid not in valid_obj_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"RLO '{rlo.id}' has no objective '{oid}'",
                object_id=oid,
                field="objective_ids",
            )

    valid_concept_ids = {c.id for c in rlo.concepts}
    for cid in selection.concept_ids:
        if cid not in valid_concept_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"RLO '{rlo.id}' has no concept '{cid}'",
                object_id=cid,
                field="concept_ids",
            )

    valid_component_ids = {c.id for c in rlo.components}
    for cid in selection.component_ids:
        if cid not in valid_component_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"RLO '{rlo.id}' has no component '{cid}'",
                object_id=cid,
                field="component_ids",
            )

    valid_item_ids = {a.id for a in rlo.assessment_items}
    for aid in selection.assessment_item_ids:
        if aid not in valid_item_ids:
            raise CrossContractValidationError(
                "content_reference_not_found",
                f"RLO '{rlo.id}' has no assessment item '{aid}'",
                object_id=aid,
                field="assessment_item_ids",
            )


def validate_content_selection(
    rlo: RLODocument,
    selection: RLOContentSelection,
) -> None:
    if selection.objective_ids:
        valid_obj_ids = {rlo.enabling_objective.id}
        for oid in selection.objective_ids:
            if oid not in valid_obj_ids:
                raise InvalidRLOContentReferenceError(
                    f"RLO '{rlo.id}' has no objective '{oid}'"
                )
    if selection.concept_ids:
        valid_concept_ids = {c.id for c in rlo.concepts}
        for cid in selection.concept_ids:
            if cid not in valid_concept_ids:
                raise InvalidRLOContentReferenceError(
                    f"RLO '{rlo.id}' has no concept '{cid}'"
                )
    if selection.component_ids:
        valid_component_ids = {c.id for c in rlo.components}
        for cid in selection.component_ids:
            if cid not in valid_component_ids:
                raise InvalidRLOContentReferenceError(
                    f"RLO '{rlo.id}' has no component '{cid}'"
                )
    if selection.assessment_item_ids:
        valid_item_ids = {a.id for a in rlo.assessment_items}
        for aid in selection.assessment_item_ids:
            if aid not in valid_item_ids:
                raise InvalidRLOContentReferenceError(
                    f"RLO '{rlo.id}' has no assessment item '{aid}'"
                )


def validate_modality_plan_scene_refs(
    plan: ModalityPlan,
    source_rlos: tuple[RLODocument, ...],
) -> None:
    rlo_ids = {rlo.id for rlo in source_rlos}
    for scene in plan.scenes:
        for ref in scene.source_content:
            if ref.rlo_id not in rlo_ids:
                raise InvalidRLOContentReferenceError(
                    f"scene '{scene.id}' references RLO '{ref.rlo_id}' "
                    "which is not in the planning context"
                )
