"""Production-plan validation — scene reference integrity and cross-contract checks."""

from __future__ import annotations

from learning_pipeline.contracts import (
    ModalityPlan,
    ModalityProductionPlan,
    TaskOutputInput,
)
from learning_pipeline.validation.errors import CrossContractValidationError
from learning_pipeline.validation.graph import validate_dag


class ProductionSceneRefError(ValueError):
    pass


def validate_production_scene_refs(
    production_plan: ModalityProductionPlan,
    modality_plan: ModalityPlan,
) -> None:
    valid_scene_ids = {scene.id for scene in modality_plan.scenes}
    for job in production_plan.jobs:
        for scene_id in job.source_scene_ids:
            if scene_id not in valid_scene_ids:
                raise ProductionSceneRefError(
                    f"ProductionJob '{job.id}' references scene '{scene_id}' "
                    "which does not exist in the modality plan"
                )


def _check_job_output_bindings(
    job_id: str,
    inputs: dict,
    declared_deps: tuple[str, ...],
    jobs_by_id: dict,
) -> None:
    """Validate task_output input bindings for one production job."""
    for key, binding in inputs.items():
        if isinstance(binding, TaskOutputInput):
            if binding.task_id not in declared_deps:
                raise CrossContractValidationError(
                    "invalid_output_binding",
                    f"production job '{job_id}' input '{key}' references "
                    f"'{binding.task_id}' which is not a declared dependency",
                    object_id=job_id,
                    field=f"inputs.{key}",
                )
            producer = jobs_by_id[binding.task_id]
            if binding.output_key not in producer.output_keys:
                raise CrossContractValidationError(
                    "invalid_output_binding",
                    f"production job '{binding.task_id}' does not declare "
                    f"output '{binding.output_key}'",
                    object_id=job_id,
                    field=f"inputs.{key}",
                )


def validate_production_plan(
    production_plan: ModalityProductionPlan,
    modality_plan: ModalityPlan,
    supported_capabilities: frozenset[str],
) -> None:
    """
    Cross-contract validation for a ModalityProductionPlan against its ModalityPlan.

    Source-scene list policy:
        Jobs with an empty ``source_scene_ids`` list are permitted by contract
        (the field defaults to an empty tuple).  This covers course-level assembly
        jobs that aggregate multiple scenes without a direct 1-to-1 scene mapping.
        Every non-empty scene ID must exist in the modality plan.

    Checks:
    - Modality matches between production plan and modality plan
    - At least one production job
    - Unique job IDs, no self-dependencies, no cycles (via validate_dag)
    - Every non-empty source_scene_id exists in the modality plan
    - Every job capability is in supported_capabilities
    - task_output input bindings reference declared dependencies and declared outputs
    - At least one deliverable job
    - Every deliverable job ID exists in the production plan
    """
    if production_plan.modality != modality_plan.modality:
        raise CrossContractValidationError(
            "content_reference_not_found",
            f"production plan modality '{production_plan.modality}' does not match "
            f"modality plan modality '{modality_plan.modality}'",
            field="modality",
        )

    if not production_plan.jobs:
        raise CrossContractValidationError(
            "missing_deliverable",
            f"production plan '{production_plan.plan_id}' has no jobs",
            object_id=production_plan.plan_id,
        )

    validate_dag(
        tuple(job.id for job in production_plan.jobs),
        {job.id: job.depends_on for job in production_plan.jobs},
        object_type="production job",
    )

    jobs_by_id = {job.id: job for job in production_plan.jobs}
    valid_scene_ids = {scene.id for scene in modality_plan.scenes}

    for job in production_plan.jobs:
        for scene_id in job.source_scene_ids:
            if scene_id not in valid_scene_ids:
                raise CrossContractValidationError(
                    "invalid_scene_reference",
                    f"production job '{job.id}' references scene '{scene_id}' "
                    "which does not exist in the modality plan",
                    object_id=job.id,
                    field="source_scene_ids",
                )

        if job.capability not in supported_capabilities:
            raise CrossContractValidationError(
                "unsupported_capability",
                f"production job '{job.id}' uses capability '{job.capability}' "
                "which is not in the supported capability set",
                object_id=job.id,
                field="capability",
            )

        _check_job_output_bindings(
            job_id=job.id,
            inputs=job.inputs,
            declared_deps=job.depends_on,
            jobs_by_id=jobs_by_id,
        )

    if not production_plan.deliverable_job_ids:
        raise CrossContractValidationError(
            "missing_deliverable",
            f"production plan '{production_plan.plan_id}' has no deliverable jobs",
            object_id=production_plan.plan_id,
        )

    for deliverable_id in production_plan.deliverable_job_ids:
        if deliverable_id not in jobs_by_id:
            raise CrossContractValidationError(
                "missing_deliverable",
                f"deliverable job '{deliverable_id}' does not exist in the production plan",
                object_id=deliverable_id,
            )
