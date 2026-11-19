"""Build-plan validation — task graph integrity checks and stable plan hashing."""

from __future__ import annotations

import hashlib

from learning_pipeline.contracts import BuildPlan, ListInput, ObjectInput, TaskOutputInput
from learning_pipeline.validation.errors import CrossContractValidationError
from learning_pipeline.validation.graph import validate_dag


def _validate_binding_refs(
    binding: object,
    task_id: str,
    depends_on: tuple[str, ...],
    tasks_by_id: dict,
) -> None:
    """Recursively validate that every TaskOutputInput in a binding tree is valid."""
    if isinstance(binding, TaskOutputInput):
        if binding.task_id not in depends_on:
            raise PlanValidationError(
                f"task {task_id} binding must reference a declared dependency",
                code="invalid_output_binding",
            )
        producer = tasks_by_id[binding.task_id]
        if binding.output_key not in producer.output_keys:
            raise PlanValidationError(
                f"task {binding.task_id} does not declare output {binding.output_key!r}",
                code="invalid_output_binding",
            )
    elif isinstance(binding, ListInput):
        for item in binding.items:
            _validate_binding_refs(item, task_id, depends_on, tasks_by_id)
    elif isinstance(binding, ObjectInput):
        for val in binding.fields.values():
            _validate_binding_refs(val, task_id, depends_on, tasks_by_id)


class PlanValidationError(ValueError):
    """
    Raised when a BuildPlan fails structural validation.

    The ``code`` attribute mirrors the CrossContractValidationError code when
    the error originates from the shared DAG validator, so callers can check
    stable codes alongside the prose message.
    """

    def __init__(self, message: str, code: str = "build_plan_error") -> None:
        self.code = code
        super().__init__(message)


def validate_build_plan(plan: BuildPlan, registered_task_types: frozenset[str]) -> None:
    """
    Verify a BuildPlan before the DAGRunner is allowed to execute it.

    Uses the shared ``validate_dag`` helper for structural graph checks
    (uniqueness, missing dependencies, self-dependencies, cycles) and
    then validates task types, output bindings, and deliverables.

    Checks: at least one task, unique task IDs, registered task types, declared
    dependencies, no self-dependencies, no cycles, valid TaskOutputInput bindings,
    at least one deliverable task, and declared deliverable IDs.
    """
    if not plan.tasks:
        raise PlanValidationError("at least one task is required", code="missing_deliverable")

    try:
        validate_dag(
            tuple(task.id for task in plan.tasks),
            {task.id: task.depends_on for task in plan.tasks},
            object_type="task",
        )
    except CrossContractValidationError as exc:
        raise PlanValidationError(str(exc), code=exc.code) from exc

    tasks_by_id = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        if task.task_type not in registered_task_types:
            raise PlanValidationError(
                f"unsupported task type: {task.task_type}",
                code="unsupported_task_type",
            )
        for binding in task.inputs.values():
            _validate_binding_refs(binding, task.id, task.depends_on, tasks_by_id)

    if not plan.deliverable_task_ids:
        raise PlanValidationError(
            "at least one deliverable task is required",
            code="missing_deliverable",
        )

    for deliverable_id in plan.deliverable_task_ids:
        if deliverable_id not in tasks_by_id:
            raise PlanValidationError(
                f"missing deliverable task: {deliverable_id}",
                code="missing_deliverable",
            )


def canonical_plan_hash(plan: BuildPlan) -> str:
    """SHA-256 hash of the plan's canonical JSON representation."""
    payload = plan.model_dump_json(by_alias=True, exclude_none=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
