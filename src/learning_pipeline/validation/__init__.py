"""
Learning pipeline validation.

All validators are re-exported here so callers can write:

    from learning_pipeline.validation import (
        validate_course_blueprint,
        validate_modality_plan,
        validate_production_plan,
        validate_build_plan,
        CrossContractValidationError,
    )

Validation order for the canonical pipeline:

    validate_course_blueprint
        → validate_modality_plan
        → validate_production_plan
        → validate_build_plan
        → execute

Three-tier validation model
---------------------------

Pydantic model validation
    Validates one object locally (field types, constraints, internal consistency).

Cross-contract validation  (this package)
    Validates relationships between objects — e.g. that a modality scene only
    references content that was selected in the CourseBlueprint, or that a
    production job's dependencies form a valid DAG.

Runtime validation
    (Future) Verifies that actual executor outputs match declared output_keys.
"""

from __future__ import annotations

from .build_plan import PlanValidationError, canonical_plan_hash, validate_build_plan
from .course_blueprint import validate_course_blueprint
from .errors import CrossContractValidationError
from .graph import validate_dag
from .modality_plan import (
    ModalityPlanValidationError,
    validate_modality_plan,
)
from .production_plan import (
    ProductionSceneRefError,
    validate_production_plan,
    validate_production_scene_refs,
)
from .rlo_references import (
    InvalidRLOContentReferenceError,
    validate_content_selection,
    validate_modality_plan_scene_refs,
    validate_rlo_selection,
)

__all__ = [
    # errors
    "CrossContractValidationError",
    # graph
    "validate_dag",
    # rlo_references
    "InvalidRLOContentReferenceError",
    "validate_rlo_selection",
    "validate_content_selection",
    "validate_modality_plan_scene_refs",
    # course_blueprint
    "validate_course_blueprint",
    # modality_plan
    "ModalityPlanValidationError",
    "validate_modality_plan",
    # production_plan
    "ProductionSceneRefError",
    "validate_production_plan",
    "validate_production_scene_refs",
    # build_plan
    "PlanValidationError",
    "validate_build_plan",
    "canonical_plan_hash",
]
