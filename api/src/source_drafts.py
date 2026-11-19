"""Admin API for grounded RLO drafting, review, and publication."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from poc_auth import require_authenticated_request
from pydantic import ValidationError

from .source_authoring import draft_repository
from .source_authoring.draft_contracts import (
    RLODraftJob,
    RLODraftRequest,
    RLODraftState,
    RLOGenerationBatch,
    RLOGenerationCheckpoint,
    RLOGenerationPromptRun,
    RLOInstructionalApproachSummary,
    RLOPendingRevision,
    RLORevisionFindingOption,
    RLOReviewMetadata,
    RLOReviewRequest,
    RLORevisionPlan,
    RLORevisionPlanRequest,
    RLORevisionSubmission,
    summarize_content_provenance,
)
from .source_authoring.drafting import RLODraftingService
from .source_authoring.revision import build_revision_plan, revision_finding_options


router = APIRouter(
    prefix="/api/rlo-drafts",
    tags=["rlo-drafts"],
    dependencies=[Depends(require_authenticated_request)],
)


def _detail(exc: Exception) -> HTTPException:
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=422, detail=json.loads(exc.json()))
    return HTTPException(status_code=409, detail=str(exc))


@router.post("", response_model=RLODraftJob, status_code=202)
async def create_rlo_draft(request: Request, payload: RLODraftRequest):
    try:
        return draft_repository.create_draft_job(
            payload,
            created_by=require_authenticated_request(request),
        )
    except (ValueError, ValidationError) as exc:
        raise _detail(exc) from exc


@router.get("", response_model=list[RLODraftJob])
async def list_rlo_drafts():
    return draft_repository.list_draft_jobs()


@router.get("/batches", response_model=list[RLOGenerationBatch])
async def list_rlo_generation_batches():
    return [
        draft_repository.refresh_generation_batch(batch.batch_id)
        for batch in draft_repository.list_generation_batches()
    ]


@router.get("/batches/by-objective/{objective_job_id}", response_model=RLOGenerationBatch)
async def get_rlo_generation_batch_for_objective(objective_job_id: str):
    batch = draft_repository.get_generation_batch_for_objective_job(objective_job_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="RLO generation batch not found.")
    return draft_repository.refresh_generation_batch(batch.batch_id)


@router.get("/batches/{batch_id}", response_model=RLOGenerationBatch)
async def get_rlo_generation_batch(batch_id: str):
    try:
        return draft_repository.refresh_generation_batch(batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RLO generation batch not found.") from exc


@router.get("/{job_id}/checkpoints", response_model=list[RLOGenerationCheckpoint])
async def list_rlo_generation_checkpoints(job_id: str):
    if draft_repository.get_draft_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    return draft_repository.list_generation_checkpoints(job_id)


@router.get("/{job_id}/prompts", response_model=list[RLOGenerationPromptRun])
async def list_rlo_generation_prompts(job_id: str):
    if draft_repository.get_draft_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    return draft_repository.list_generation_prompt_runs(job_id)


@router.get("/{job_id}/review-metadata", response_model=RLOReviewMetadata)
async def export_rlo_review_metadata(job_id: str):
    job = draft_repository.get_draft_job(job_id)
    if job is None or job.authoring is None:
        raise HTTPException(status_code=404, detail="RLO review metadata not found.")
    metadata = RLOReviewMetadata(
        job_id=job.job_id,
        rlo_id=job.request.rlo_id,
        rlo_version=job.request.rlo_version,
        authoring_revision_id=job.authoring.authoring_revision_id,
        state=job.state,
        content_provenance=summarize_content_provenance(job.authoring),
        instructional_approach=RLOInstructionalApproachSummary(
            profile_id=job.authoring.methodology_profile.profile_id,
            profile_version=job.authoring.methodology_profile.version,
            content_type=job.authoring.methodology_profile.content_type.value,
            bloom_level=job.authoring.methodology_profile.bloom_level.value,
            intent=job.authoring.methodology_profile.intent,
            guidance_assessments=job.authoring.guidance_assessments,
        ),
        reviews=job.reviews,
    )
    return JSONResponse(
        content=metadata.model_dump(mode="json"),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job.request.rlo_id}-review-metadata.json"'
            )
        },
    )


@router.get("/{job_id}/export")
async def export_rlo_draft(job_id: str):
    job = draft_repository.get_draft_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    if job.draft is None:
        raise HTTPException(
            status_code=409,
            detail="A catalog-ready RLO is not available for this job yet.",
        )
    return Response(
        content=job.draft.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{job.request.rlo_id}-'
                f'{job.request.rlo_version}.json"'
            )
        },
    )


@router.get("/{job_id}", response_model=RLODraftJob)
async def get_rlo_draft(job_id: str):
    job = draft_repository.get_draft_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    return job


@router.get(
    "/{job_id}/revision-options", response_model=list[RLORevisionFindingOption]
)
async def get_rlo_revision_options(job_id: str):
    job = draft_repository.get_draft_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    return revision_finding_options(job)


@router.post("/{job_id}/revision-plan", response_model=RLORevisionPlan)
async def plan_rlo_revision(job_id: str, payload: RLORevisionPlanRequest):
    job = draft_repository.get_draft_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    try:
        return build_revision_plan(job, payload)
    except ValueError as exc:
        raise _detail(exc) from exc


@router.post("/{job_id}/revisions", response_model=RLODraftJob, status_code=202)
async def queue_rlo_revision(
    job_id: str, payload: RLORevisionSubmission, request: Request
):
    job = draft_repository.get_draft_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    try:
        plan = build_revision_plan(job, payload)
        if not plan.executable:
            raise ValueError(plan.stop_reason or "Revision is not executable")
        if payload.maximum_model_calls != plan.maximum_model_calls:
            raise ValueError(
                f"Confirm the planned ceiling of {plan.maximum_model_calls} model calls"
            )
        reviewer = require_authenticated_request(request) or "local-instructional-designer"
        pending = RLOPendingRevision(
            revision_id=str(uuid.uuid4()),
            plan=plan,
            instruction=payload.instruction,
            reviewer=reviewer,
            requested_at=datetime.now(timezone.utc).isoformat(),
            base_state=job.state,
        )
        return draft_repository.queue_scoped_revision(job_id, pending)
    except (ValueError, ValidationError) as exc:
        raise _detail(exc) from exc


@router.post("/{job_id}/retry", response_model=RLODraftJob, status_code=202)
async def retry_rlo_generation(job_id: str):
    try:
        return draft_repository.retry_draft_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft job not found.") from exc
    except ValueError as exc:
        raise _detail(exc) from exc


@router.put("/{job_id}", response_model=RLODraftJob)
async def update_rlo_draft(job_id: str, payload: dict):
    try:
        return RLODraftingService().replace_draft(job_id, payload)
    except (ValueError, ValidationError) as exc:
        raise _detail(exc) from exc


@router.post("/{job_id}/review", response_model=RLODraftJob)
async def review_rlo_draft(job_id: str, request: Request, payload: RLOReviewRequest):
    reviewer = require_authenticated_request(request) or "local-instructional-designer"
    try:
        return RLODraftingService().review(job_id, payload, reviewer=reviewer)
    except (ValueError, ValidationError) as exc:
        raise _detail(exc) from exc


@router.post("/{job_id}/publish", response_model=RLODraftJob)
async def publish_rlo_draft(job_id: str):
    job = draft_repository.get_draft_job(job_id)
    if job is None or job.draft is None:
        raise HTTPException(status_code=404, detail="Draft job not found.")
    if job.state != RLODraftState.APPROVED:
        raise HTTPException(status_code=409, detail="Only an approved draft can be published.")
    try:
        from .app import _ingest

        result = _ingest(job.draft.model_dump_json(indent=2).encode("utf-8"))
        return draft_repository.mark_published(
            job_id, rlo_id=result.rlo_id, rlo_version=result.rlo_version
        )
    except (ValueError, ValidationError) as exc:
        raise _detail(exc) from exc


@router.post("/{job_id}/approve-publish", response_model=RLODraftJob)
async def approve_and_publish_rlo(job_id: str, request: Request):
    reviewer = require_authenticated_request(request) or "local-instructional-designer"
    try:
        existing = draft_repository.get_draft_job(job_id)
        if existing is None:
            raise ValueError("draft job does not exist")
        approved = (
            existing
            if existing.state == RLODraftState.APPROVED
            else RLODraftingService().review(
                job_id,
                RLOReviewRequest(action="approve"),
                reviewer=reviewer,
            )
        )
        from .app import _ingest

        result = _ingest(approved.draft.model_dump_json(indent=2).encode("utf-8"))
        return draft_repository.mark_published(
            job_id,
            rlo_id=result.rlo_id,
            rlo_version=result.rlo_version,
        )
    except (ValueError, ValidationError) as exc:
        raise _detail(exc) from exc


@router.get("/source-versions/{source_version_id}/dependencies")
async def get_source_version_dependencies(source_version_id: str):
    return {
        "source_version_id": source_version_id,
        "published_rlos": draft_repository.published_dependencies(source_version_id),
    }
