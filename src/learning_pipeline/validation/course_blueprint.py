"""Cross-contract validation for CourseBlueprint against source RLODocuments."""

from __future__ import annotations

from learning_pipeline.contracts import CourseBlueprint, RLODocument
from learning_pipeline.validation.errors import CrossContractValidationError
from learning_pipeline.validation.rlo_references import validate_rlo_selection


def validate_course_blueprint(
    blueprint: CourseBlueprint,
    rlos: tuple[RLODocument, ...],
) -> None:
    """
    Validate that every TailoredRLORef in the blueprint resolves to a supplied
    RLODocument at the exact pinned version, and that every content selection is
    valid against the corresponding RLO.

    Pydantic already enforces local field invariants (positive duration, unique
    and positive order values, source_rlo_versions consistency with
    ordered_rlo_refs).  This validator adds cross-object checks only.

    Checks:
    - At least one learning outcome
    - At least one RLO reference
    - No duplicate rlo_id values in ordered_rlo_refs
    - Every rlo_id resolves to exactly one supplied RLODocument
    - Exact version match between the blueprint reference and the supplied RLO
    - Every content selection passes validate_rlo_selection
    """
    if not blueprint.learning_outcomes:
        raise CrossContractValidationError(
            "content_not_selected",
            f"blueprint '{blueprint.blueprint_id}' has no learning outcomes",
            object_id=blueprint.blueprint_id,
            field="learning_outcomes",
        )

    if not blueprint.ordered_rlo_refs:
        raise CrossContractValidationError(
            "content_not_selected",
            f"blueprint '{blueprint.blueprint_id}' has no RLO references",
            object_id=blueprint.blueprint_id,
            field="ordered_rlo_refs",
        )

    rlo_by_id = {rlo.id: rlo for rlo in rlos}

    seen_rlo_ids: set[str] = set()
    for tailored_ref in blueprint.ordered_rlo_refs:
        if tailored_ref.rlo_id in seen_rlo_ids:
            raise CrossContractValidationError(
                "duplicate_id",
                f"duplicate tailored RLO ref for '{tailored_ref.rlo_id}' in blueprint",
                object_id=tailored_ref.rlo_id,
                field="ordered_rlo_refs",
            )
        seen_rlo_ids.add(tailored_ref.rlo_id)

        if tailored_ref.rlo_id not in rlo_by_id:
            raise CrossContractValidationError(
                "rlo_not_found",
                f"blueprint references RLO '{tailored_ref.rlo_id}' which was not supplied",
                object_id=tailored_ref.rlo_id,
                field="rlo_id",
            )

        rlo = rlo_by_id[tailored_ref.rlo_id]
        validate_rlo_selection(tailored_ref, rlo)
