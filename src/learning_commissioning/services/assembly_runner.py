"""Commissioning-owned orchestration around the existing CourseAssemblyService."""

from __future__ import annotations

from llm_gateway import ModelAlias, llm_telemetry_context, load_lite_llm_settings
from learning_pipeline.planners.client import LiteLLMPlanningClient
from learning_pipeline.planners.curriculum.agent import (
    PROMPT_VERSION,
    LiteLLMCurriculumAssemblyAgent,
)
from learning_pipeline.planners.curriculum.service import CourseAssemblyService
from learning_pipeline.db.repository import DuplicateWorkflowError, PostgresWorkflowRepository
from learning_pipeline.services.generation_planning import GenerationPlanningService
from learning_pipeline.runtime.artifact_store import ArtifactStore
from learning_pipeline.validation import canonical_plan_hash

from ..adapters.assembly import build_course_assembly_request
from ..adapters.catalog_repository import CatalogRLORepository
from ..contracts import CommissioningJobRecord
from ..repository import PostgresPreviewRepository
from .retrieval import CatalogClient
from .reference_assembly import CommissioningReferenceAssemblyAgent


class AssemblyJobRunner:
    def __init__(
        self,
        repository: PostgresPreviewRepository,
        catalog: CatalogClient,
        *,
        artifact_store: ArtifactStore,
        mode: str,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        rlo_repository = CatalogRLORepository(catalog)
        if mode.casefold() == "real":
            connection = load_lite_llm_settings()
            client = LiteLLMPlanningClient(
                base_url=connection.base_url,
                api_key=connection.api_key,
                prompt_version=PROMPT_VERSION,
            )
            agent = LiteLLMCurriculumAssemblyAgent(
                client=client,
                model=ModelAlias.COMMISSIONING_COURSE_ASSEMBLY,
            )
        else:
            agent = CommissioningReferenceAssemblyAgent()
        self.service = CourseAssemblyService(
            agent,
            rlo_repository,
            trace_root=None,
        )
        self.generation = GenerationPlanningService(
            rlo_repository,
            trace_root=None,
            artifact_store=artifact_store,
            mode=mode,
        )
        self.workflow_repository = PostgresWorkflowRepository(repository.pool)

    async def run(self, job: CommissioningJobRecord) -> None:
        try:
            preview = await self.repository.get_preview(job.preview_id)
            confirmation = await self.repository.get_confirmation(job.preview_id)
            if preview is None or confirmation is None:
                raise RuntimeError("job references a missing preview or confirmation")

            adapted = build_course_assembly_request(preview.request, confirmation)
            with llm_telemetry_context(job_id=job.job_id):
                result = await self.service.assemble_course(
                    adapted.request,
                    idempotency_key=job.job_id,
                )

            namespace = f"commissioning/jobs/{job.job_id}"
            payloads = {
                "request": ("course-assembly-request.json", adapted.request.model_dump_json(indent=2)),
                "adapter": ("assembly-adapter-trace.json", adapted.trace.model_dump_json(indent=2)),
                "blueprint": ("course-blueprint.json", result.blueprint.model_dump_json(indent=2)),
                "report": ("assembly-report.json", result.report.model_dump_json(indent=2)),
                "trace": ("planning-trace.json", result.trace.model_dump_json(indent=2)),
            }
            refs = {
                key: await self.artifact_store.put_bytes(
                    namespace,
                    filename,
                    content.encode("utf-8"),
                    "application/json",
                )
                for key, (filename, content) in payloads.items()
            }

            await self.repository.complete_job(
                job.job_id,
                assembly_request=adapted.request.model_dump_json(),
                adapter_trace=adapted.trace.model_dump_json(),
                blueprint=result.blueprint.model_dump_json(),
                assembly_report=result.report.model_dump_json(),
                planning_trace=result.trace.model_dump_json(),
                course_assembly_request_uri=refs["request"].uri,
                blueprint_uri=refs["blueprint"].uri,
                assembly_report_uri=refs["report"].uri,
                planning_trace_uri=refs["trace"].uri,
            )

            planning_request_id = f"planning-{job.job_id}"
            workflow_id = f"workflow-{job.job_id}"
            selection = await self.generation.select_format(
                result.blueprint,
                request_id=planning_request_id,
                requested_modality=preview.intent.requested_modality,
            )
            modality = selection.decision.selected_modality
            await self.repository.save_format_selection(
                job.job_id, selection.model_dump_json(), modality.value
            )

            modality_result = await self.generation.plan_modality(
                result.blueprint,
                modality,
                request_id=planning_request_id,
            )
            await self.repository.save_modality_plan(
                job.job_id,
                modality_result.modality_plan.model_dump_json(),
                modality_result.trace.model_dump_json(),
            )

            workflow_result = await self.generation.plan_workflow(
                result.blueprint,
                modality_result.modality_plan,
                request_id=planning_request_id,
                workflow_id=workflow_id,
            )
            build_plan = workflow_result.build_plan
            await self.repository.save_workflow_plan(
                job.job_id,
                production_plan=workflow_result.production_plan.model_dump_json(),
                build_plan=build_plan.model_dump_json(),
                planning_trace=workflow_result.trace.model_dump_json(),
            )
            plan_hash = canonical_plan_hash(build_plan)
            try:
                await self.workflow_repository.create_pending(build_plan, plan_hash)
            except DuplicateWorkflowError:
                existing = await self.workflow_repository.get(workflow_id)
                if existing is None or existing.plan_hash != plan_hash:
                    raise RuntimeError(
                        f"workflow {workflow_id!r} already exists with different content"
                    )
            await self.repository.link_workflow(job.job_id, workflow_id)
            print(f"[commissioning-worker] queued execution for {job.job_id}")
        except Exception as exc:
            await self.repository.fail_job(
                job.job_id,
                error_code=exc.__class__.__name__,
                error_summary=str(exc) or exc.__class__.__name__,
            )
            print(f"[commissioning-worker] failed {job.job_id}: {exc}")
