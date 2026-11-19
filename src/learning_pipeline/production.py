from learning_pipeline.contracts import BuildPlan, ModalityProductionPlan, TaskSpec


class ProductionSceneRefError(ValueError):
    pass


class UnknownCapabilityError(ValueError):
    pass


class CapabilityCatalog:
    def __init__(self, mappings: dict[str, str]) -> None:
        self._mappings = dict(mappings)

    def task_type_for(self, capability: str) -> str:
        try:
            return self._mappings[capability]
        except KeyError as exc:
            raise UnknownCapabilityError(capability) from exc

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._mappings.keys())

    @property
    def task_types(self) -> set[str]:
        return set(self._mappings.values())


class ProductionCompiler:
    def __init__(self, catalog: "CapabilityCatalog | object") -> None:
        # Accepts any object with task_type_for() and capabilities — duck-typed
        # so ProductionToolCatalog can be used as the composition-root catalog
        # without making production.py depend on the tools package.
        self._catalog = catalog

    @property
    def live_capabilities(self) -> frozenset[str]:
        return self._catalog.capabilities

    def compile(
        self,
        workflow_id: str,
        production_plan: ModalityProductionPlan,
    ) -> BuildPlan:
        tasks = tuple(
            TaskSpec(
                id=job.id,
                task_type=self._catalog.task_type_for(job.capability),
                depends_on=job.depends_on,
                inputs=job.inputs,
                output_keys=job.output_keys,
                max_attempts=job.max_attempts,
            )
            for job in production_plan.jobs
        )
        return BuildPlan(
            workflow_id=workflow_id,
            source_plan_id=production_plan.plan_id,
            modality=production_plan.modality,
            tasks=tasks,
            deliverable_task_ids=production_plan.deliverable_job_ids,
        )


