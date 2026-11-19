"""Worker operations for durable objective extraction jobs."""

from __future__ import annotations

import logging

from . import job_repository
from .job_contracts import ObjectiveJob, ObjectiveJobStage


logger = logging.getLogger(__name__)


def process_objective_job(job: ObjectiveJob) -> None:
    try:
        if job.workflow_stage == ObjectiveJobStage.DRAFT:
            _decompose(job)
        else:
            raise ValueError(f"unsupported queued objective stage: {job.workflow_stage}")
    except Exception as exc:
        logger.exception("Objective job %s failed", job.job_id)
        job_repository.fail_objective_job(
            job.job_id,
            str(exc),
            retryable=isinstance(exc, (ConnectionError, OSError, TimeoutError)),
        )


def _decompose(job: ObjectiveJob) -> None:
    from src.source_authoring.mapping import SourceMappingService
    from src.source_authoring.objectives import ObjectiveDiscoveryService
    from src.source_ingestion.artifacts import load_extraction
    from src.source_ingestion.repository import (
        get_latest_job_for_source_version,
        get_source_collection,
    )

    collection = get_source_collection(job.collection_id)
    if collection is None:
        raise ValueError("objective job source collection does not exist")
    progress = {"completed": job.completed_operations}

    def report(operation: str, state: str) -> None:
        if state == "completed":
            progress["completed"] += 1
        job_repository.update_objective_job_progress(
            job.job_id,
            operation=operation,
            completed_operations=progress["completed"],
            progress_detail={"state": state},
        )

    def persist_findings(findings: dict) -> None:
        job_repository.update_objective_job_progress(
            job.job_id,
            operation="Reviewing preliminary objective findings",
            completed_operations=progress["completed"],
            progress_detail=findings,
        )

    def load_checkpoint(_workspace_id: str, **identity):
        return job_repository.load_model_checkpoint(job.job_id, **identity)

    def save_checkpoint(_workspace_id: str, **values) -> None:
        job_repository.save_model_checkpoint(job.job_id, **values)

    job_repository.update_objective_job_progress(
        job.job_id,
        operation="Loading extracted source material",
        completed_operations=progress["completed"],
    )
    bundles = []
    for member in collection.members:
        source_job = get_latest_job_for_source_version(member.source_version_id)
        if source_job is None or source_job.status != "ready":
            raise ValueError("every objective source must have a ready extraction")
        bundles.append(load_extraction(source_job.job_id))
    mapping = SourceMappingService(progress_callback=report)
    document_maps = [
        mapping.map_document(bundle.document, bundle.segments) for bundle in bundles
    ]
    documents = {
        bundle.job.source_version_id: bundle.document for bundle in bundles
    }
    collection_map = mapping.map_collection(
        collection,
        document_maps,
        documents,
    )
    job_repository.update_objective_job_progress(
        job.job_id,
        operation="Discovering learning objectives",
        completed_operations=progress["completed"],
    )
    discovery = ObjectiveDiscoveryService(
        progress_callback=report,
        findings_callback=persist_findings,
        checkpoint_loader=load_checkpoint,
        checkpoint_saver=save_checkpoint,
    )
    workspace = discovery.discover(
        collection_map,
        documents,
        instructions=job.instructions,
        workspace_id=f"objective-{job.job_id}",
        created_by=job.created_by,
    )
    job_repository.complete_decomposition(
        job.job_id,
        workspace_id=workspace.workspace_id,
        workspace_revision=workspace.revision,
        prompt_runs=discovery.prompt_runs,
    )
