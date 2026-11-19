from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from poc_auth import require_authenticated_request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from .source_ingestion.repository import (
    create_job,
    delete_all_jobs,
    delete_job,
    find_by_checksum,
    get_job,
    list_jobs,
)
from .storage import get_storage

ALLOWED_EXTENSIONS = {"pdf", "docx", "pptx", "txt", "md", "html", "htm", "epub"}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
EXT_TO_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain",
    "md": "text/markdown",
    "html": "text/html",
    "htm": "text/html",
    "epub": "application/epub+zip",
}

router = APIRouter(
    prefix="/api/source-uploads",
    tags=["source-upload"],
    dependencies=[Depends(require_authenticated_request)],
)

_sandbox_objective_runs: dict[str, dict[str, str]] = {}


class UploadResponse(BaseModel):
    source_id: str
    job_id: str
    status: str
    filename: str
    size_bytes: int
    checksum: str
    object_path: str


class JobStatusResponse(BaseModel):
    job_id: str
    source_id: str
    source_version_id: str
    status: str
    original_filename: str
    content_type: str | None
    size_bytes: int
    checksum: str
    uploader: str | None
    uploaded_at: str
    object_path: str
    error_message: str | None
    format_metadata: dict | None


class SandboxObjectiveRequest(BaseModel):
    roles: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    additional_context: str | None = None


def _get_extension(filename: str) -> str:
    return Path(filename).suffix.lstrip(".").lower()


def _validate_file(filename: str, content_type: str, size: int) -> None:
    extension = _get_extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '.{extension}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    expected_mime = EXT_TO_MIME[extension]
    if content_type and content_type != "application/octet-stream" and not content_type.startswith(expected_mime):
        raise HTTPException(
            status_code=415,
            detail=f"MIME type '{content_type}' does not match expected type for .{extension} files.",
        )

    if size == 0:
        raise HTTPException(status_code=400, detail="File is empty. Please upload a file with content.")
    if size > MAX_FILE_SIZE_BYTES:
        size_mb = size / 1024 / 1024
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Maximum allowed is 50 MB.",
        )


def _build_object_path(source_id: str, filename: str) -> str:
    safe_filename = Path(filename).name
    return f"source-uploads/{source_id}/original/{safe_filename}"


def _job_to_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        source_id=job.source_id,
        source_version_id=job.source_version_id,
        status=job.status,
        original_filename=job.original_filename,
        content_type=job.content_type,
        size_bytes=job.size_bytes,
        checksum=job.checksum,
        uploader=job.uploader,
        uploaded_at=job.uploaded_at.isoformat() if job.uploaded_at else "",
        object_path=job.minio_object_path,
        error_message=job.error_message,
        format_metadata=job.format_metadata,
    )


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_source_file(
    request: Request,
    file: UploadFile = File(...),
    source_id: str | None = Form(default=None),
):
    contents = await file.read(MAX_FILE_SIZE_BYTES + 1)
    filename = Path(file.filename or "unknown").name
    content_type = file.content_type or ""
    _validate_file(filename, content_type, len(contents))

    checksum = hashlib.sha256(contents).hexdigest()
    existing = find_by_checksum(checksum)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate file detected. Already uploaded as job '{existing.job_id}'.",
        )

    source_id = source_id or str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    object_path = _build_object_path(source_id, filename)
    storage = get_storage()
    try:
        storage.put(object_path, contents, content_type or "application/octet-stream")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Storage unavailable. Could not save file.") from exc

    try:
        create_job(
            job_id=job_id,
            source_id=source_id,
            original_filename=filename,
            content_type=content_type,
            size_bytes=len(contents),
            checksum=checksum,
            minio_object_path=object_path,
            uploader=require_authenticated_request(request),
        )
    except IntegrityError as exc:
        storage.delete(object_path)
        raise HTTPException(status_code=409, detail="Duplicate file detected.") from exc
    except Exception as exc:
        storage.delete(object_path)
        raise HTTPException(status_code=500, detail="Could not save job record.") from exc

    return UploadResponse(
        source_id=source_id,
        job_id=job_id,
        status="queued",
        filename=filename,
        size_bytes=len(contents),
        checksum=checksum,
        object_path=object_path,
    )


@router.get("", response_model=list[JobStatusResponse])
async def list_source_jobs():
    return [_job_to_response(job) for job in list_jobs()]


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_source_job(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return _job_to_response(job)


@router.get("/{job_id}/inspection")
async def inspect_source_extraction(job_id: str):
    from .source_ingestion.artifacts import load_artifact, load_extraction

    try:
        bundle = load_extraction(job_id)
        visual_explanations = []
        for entry in bundle.manifest.artifacts:
            if entry.kind == "visual_explanation":
                _entry, body = load_artifact(job_id, entry.artifact_id)
                visual_explanations.append(json.loads(body))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Source job or artifact not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "job": _job_to_response(bundle.job).model_dump(mode="json"),
        "document": bundle.document.model_dump(mode="json"),
        "report": bundle.report,
        "segments": [segment.model_dump(mode="json") for segment in bundle.segments],
        "visual_explanations": visual_explanations,
        "original_url": f"/api/source-uploads/{quote(job_id)}/original",
        "artifacts": [
            {
                **entry.model_dump(mode="json"),
                "url": (
                    f"/api/source-uploads/{quote(job_id)}/artifacts/"
                    f"{quote(entry.artifact_id, safe='')}"
                ),
            }
            for entry in bundle.manifest.artifacts
        ],
    }


@router.get("/{job_id}/original")
async def get_source_original(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Source job not found.")
    body = get_storage().get(job.minio_object_path)
    if hashlib.sha256(body).hexdigest() != job.checksum:
        raise HTTPException(status_code=409, detail="Source checksum mismatch.")
    filename = quote(Path(job.original_filename).name)
    return Response(
        body,
        media_type=job.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


@router.get("/{job_id}/artifacts/{artifact_id}")
async def get_source_artifact(job_id: str, artifact_id: str):
    from .source_ingestion.artifacts import load_artifact

    try:
        entry, body = load_artifact(job_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Source artifact not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        body,
        media_type=entry.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(entry.artifact_id)}"
        },
    )


def _generate_sandbox_objectives(
    job_id: str,
    payload: SandboxObjectiveRequest,
    *,
    created_by: str | None,
):
    from .source_authoring.contracts import PractitionerInstructions
    from .source_authoring.mapping import SourceMappingService
    from .source_authoring.objectives import ObjectiveDiscoveryService
    from .source_ingestion.artifacts import load_extraction
    from .source_ingestion.repository import (
        create_source_collection,
        get_source_collection,
    )

    bundle = load_extraction(job_id)
    collection_id = f"sandbox-{bundle.job.source_version_id}"
    collection = get_source_collection(collection_id)
    if collection is None:
        collection = create_source_collection(
            collection_id,
            f"Sandbox: {bundle.job.original_filename}",
            [(bundle.job.source_version_id, "Uploaded sandbox source")],
            created_by=created_by,
        )
    mapping = SourceMappingService()
    document_map = mapping.map_document(bundle.document, bundle.segments)
    collection_map = mapping.map_collection(
        collection,
        [document_map],
        {bundle.job.source_version_id: bundle.document},
    )
    has_context = bool(payload.roles or payload.tasks or payload.additional_context)
    instructions = (
        PractitionerInstructions(
            roles=payload.roles,
            tasks=payload.tasks,
            additional_context=payload.additional_context,
        )
        if has_context
        else None
    )
    return ObjectiveDiscoveryService().discover(
        collection_map,
        {bundle.job.source_version_id: bundle.document},
        instructions=instructions,
        workspace_id=f"sandbox-{bundle.job.source_version_id}",
        created_by=created_by,
    )


@router.post("/{job_id}/objectives")
async def generate_sandbox_objectives(
    job_id: str,
    request: Request,
    payload: SandboxObjectiveRequest,
):
    created_by = require_authenticated_request(request)
    current = _sandbox_objective_runs.get(job_id)
    if current and current["status"] == "running":
        raise HTTPException(status_code=409, detail="Objective generation is already running.")
    _sandbox_objective_runs[job_id] = {"status": "running", "error": ""}
    try:
        result = await asyncio.to_thread(
            _generate_sandbox_objectives,
            job_id,
            payload,
            created_by=created_by,
        )
    except KeyError as exc:
        _sandbox_objective_runs[job_id] = {"status": "failed", "error": str(exc)}
        raise HTTPException(status_code=404, detail="Source job not found.") from exc
    except ValueError as exc:
        _sandbox_objective_runs[job_id] = {"status": "failed", "error": str(exc)}
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        _sandbox_objective_runs[job_id] = {"status": "failed", "error": str(exc)}
        raise
    _sandbox_objective_runs[job_id] = {"status": "complete", "error": ""}
    return result


@router.get("/{job_id}/objectives/progress")
async def get_sandbox_objective_progress(job_id: str):
    from .source_authoring import repository as authoring_repository
    from .source_authoring.mapping import MAP_REVISION
    from .source_ingestion.artifacts import load_extraction
    from .source_ingestion.repository import (
        count_source_map_artifacts,
        get_source_map_artifact,
    )

    try:
        bundle = load_extraction(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Source job not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    source_version_id = bundle.job.source_version_id
    collection_id = f"sandbox-{source_version_id}"
    workspace_id = f"sandbox-{source_version_id}"
    completed_sections = min(
        count_source_map_artifacts("section", source_version_id),
        len(bundle.segments),
    )
    document_ready = (
        get_source_map_artifact(
            "document", source_version_id, "document", MAP_REVISION
        )
        is not None
    )
    collection_ready = (
        get_source_map_artifact(
            "collection", collection_id, "collection", MAP_REVISION
        )
        is not None
    )
    workspace = authoring_repository.get_objective_workspace(workspace_id)
    run = _sandbox_objective_runs.get(job_id, {"status": "idle", "error": ""})
    if workspace is not None:
        stage = "complete"
        message = f"Generated {len(workspace.candidates)} grounded objective candidates."
        percent = 100
    elif collection_ready:
        stage = "objectives"
        message = "Proposing, grounding, and critiquing learning objectives."
        percent = 85
    elif document_ready:
        stage = "collection_synthesis"
        message = "Synthesizing the single-source collection map."
        percent = 78
    elif completed_sections >= len(bundle.segments):
        stage = "document_synthesis"
        message = "Synthesizing section maps into a document map."
        percent = 70
    elif completed_sections:
        stage = "section_mapping"
        message = (
            f"Mapping source sections: {completed_sections} of "
            f"{len(bundle.segments)} complete."
        )
        percent = int(70 * completed_sections / len(bundle.segments))
    else:
        stage = "ready"
        message = "Ready to generate objectives."
        percent = 0
    if run["status"] == "failed":
        stage = "failed"
        message = f"Objective generation stopped: {run['error']}"
    elif run["status"] == "idle" and 0 < completed_sections < len(bundle.segments):
        message = (
            f"{completed_sections} of {len(bundle.segments)} section maps are cached. "
            "Generate objectives to resume."
        )
    elif run["status"] == "idle" and completed_sections == len(bundle.segments) and not document_ready:
        message = "Section mapping is complete. Generate objectives to resume document synthesis."
    return {
        "stage": stage,
        "message": message,
        "percent": percent,
        "completed_sections": completed_sections,
        "total_sections": len(bundle.segments),
        "document_map_ready": document_ready,
        "collection_map_ready": collection_ready,
        "workspace_id": workspace.workspace_id if workspace else None,
        "workspace_revision": workspace.revision if workspace else None,
        "candidate_count": len(workspace.candidates) if workspace else None,
        "run_status": run["status"],
        "last_error": run["error"] or None,
    }


@router.delete("/{job_id}", status_code=204)
async def delete_source_job(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    from .source_authoring.draft_repository import source_has_published_dependencies

    if source_has_published_dependencies(job.source_id):
        raise HTTPException(
            status_code=409,
            detail="Source is retained because a published RLO depends on it.",
        )
    get_storage().delete(job.minio_object_path)
    delete_job(job_id)


@router.delete("", status_code=204)
async def delete_all_source_jobs():
    from .source_authoring.draft_repository import source_has_published_dependencies

    retained = [
        job.source_id
        for job in list_jobs()
        if source_has_published_dependencies(job.source_id)
    ]
    if retained:
        raise HTTPException(
            status_code=409,
            detail="One or more sources are retained because published RLOs depend on them.",
        )
    storage = get_storage()
    for job in list_jobs():
        storage.delete(job.minio_object_path)
    delete_all_jobs()
