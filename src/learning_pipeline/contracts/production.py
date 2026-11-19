from __future__ import annotations

from pydantic import Field

from .common import FrozenModel, InputBinding, Modality


class ProductionJob(FrozenModel):
    """
    One abstract production unit in a ModalityProductionPlan.

    References source modality scenes for lineage tracing and declares its
    required capability by name.  Capability names are resolved to concrete
    executor task types by the ProductionCompiler — they never appear here.
    """

    id: str
    source_scene_ids: tuple[str, ...] = ()
    capability: str
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, InputBinding] = Field(default_factory=dict)
    output_keys: tuple[str, ...]
    max_attempts: int = Field(default=2, ge=1, le=5)


class ModalityProductionPlan(FrozenModel):
    """
    Capability-oriented production graph for one modality.

    Created by:
        WorkflowPlanner

    Consumed by:
        ProductionCompiler

    Contains:
        Abstract production jobs with capability names, input/output bindings,
        dependency edges, and source scene references.

    Does not contain:
        Executor task types, registered tool names, vendor identifiers, or
        concrete implementation details.  Those are injected by the compiler.
    """

    plan_id: str
    modality: Modality
    narrative: str
    jobs: tuple[ProductionJob, ...]
    deliverable_job_ids: tuple[str, ...]
