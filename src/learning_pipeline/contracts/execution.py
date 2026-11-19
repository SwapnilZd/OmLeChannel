from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FrozenModel, InputBinding, Modality


class TaskSpec(FrozenModel):
    """Concrete executable task in a BuildPlan, with a registered task type."""

    id: str
    task_type: str
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, InputBinding] = Field(default_factory=dict)
    output_keys: tuple[str, ...]
    max_attempts: int = Field(default=2, ge=1, le=5)


class BuildPlan(FrozenModel):
    """
    Concrete, fully compiled, executable task DAG.

    Created by:
        ProductionCompiler

    Consumed by:
        DAGRunner

    Contains:
        TaskSpecs with registered executor task types, resolved input/output
        bindings, dependency edges, and deliverable task IDs.  The plan is
        validated and persisted before any executor runs.

    Does not contain:
        LLM planning logic, capability names, production metadata, or
        anything that would require re-invoking a planner at execution time.
    """

    workflow_id: str
    source_plan_id: str
    modality: Modality
    tasks: tuple[TaskSpec, ...]
    deliverable_task_ids: tuple[str, ...]


class TaskResult(FrozenModel):
    task_id: str
    outputs: dict[str, Any]
    attempts: int


class WorkflowResult(FrozenModel):
    """
    Outputs and deliverables from a completed workflow run.

    Created by:
        DAGRunner

    Consumed by:
        Delivery layer (CLI, API, packaging)

    Contains:
        Per-task results keyed by task ID, the stable plan hash used for
        the run, and the subset of results corresponding to deliverable tasks.

    Does not contain:
        Internal retry state, intermediate executor outputs not declared as
        deliverables, or runtime scheduling metadata.
    """

    workflow_id: str
    plan_hash: str
    task_results: dict[str, TaskResult]
    deliverables: tuple[TaskResult, ...]
