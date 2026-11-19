"""Learning-request preview and confirmation API."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import mimetypes
import os
import stat
import zipfile
from datetime import datetime
from pathlib import PurePosixPath
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
import httpx
from poc_auth import require_authenticated_request

from ..contracts import (
    CommissioningJobRecord,
    CommissioningJobView,
    ConfirmedLearningRequest,
    LearningCommissionRequest,
    LearningRequestConfirmation,
    LearningRequestPreview,
    DeliverableDescriptor,
)
from learning_pipeline.contracts import CourseBlueprint, Modality, WorkflowResult
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyPlanningTrace,
    CourseAssemblyReport,
)
from ..repository import (
    InMemoryPreviewRepository,
    JobNotCancelableError,
    JobNotRerunnableError,
    PostgresPreviewRepository,
)
from ..services import (
    CatalogClient,
    CandidateCurationService,
    LearningRequestPreviewService,
    RLODiscoveryService,
    SearchIntentInterpreter,
)
from ..services.preview import (
    ConfirmationRejectedError,
    PreviewNotFoundError,
    StalePreviewError,
)
from ..services.retrieval import CatalogUnavailableError
from learning_pipeline.runtime.artifact_store import (
    ArtifactStore,
    ArtifactNotFoundError,
    ArtifactReadError,
    PathTraversalError,
    create_artifact_store,
)

_service: LearningRequestPreviewService | None = None
_catalog: CatalogClient | None = None
_repository = None
_artifact_store: ArtifactStore | None = None


class CoursePreviewError(RuntimeError):
    """Raised when a completed course package cannot be safely previewed."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service, _catalog, _repository, _artifact_store
    _catalog = CatalogClient(os.getenv("RLO_CATALOG_URL", "http://api:8000"))
    database_url = os.getenv("DATABASE_URL", "").strip()
    _repository = (
        await PostgresPreviewRepository.create(database_url)
        if database_url else InMemoryPreviewRepository()
    )
    _artifact_store = create_artifact_store()
    _service = LearningRequestPreviewService(
        SearchIntentInterpreter(),
        RLODiscoveryService(_catalog),
        _catalog,
        _repository,
        CandidateCurationService(_catalog),
    )
    yield
    await _catalog.client.aclose()
    if isinstance(_repository, PostgresPreviewRepository):
        await _repository.close()


def _get_artifact_store() -> ArtifactStore:
    global _artifact_store
    if _artifact_store is None:
        _artifact_store = create_artifact_store()
    return _artifact_store


app = FastAPI(
    title="Learning Commissioning API",
    lifespan=lifespan,
    dependencies=[Depends(require_authenticated_request)],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "COMMISSIONING_UI_ORIGINS",
            "http://localhost,http://127.0.0.1",
        ).split(",")
        if origin.strip()
    ],
    allow_origin_regex=os.getenv(
        "COMMISSIONING_UI_ORIGIN_REGEX",
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    ),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)


def _get_service() -> LearningRequestPreviewService:
    if _service is None:
        raise RuntimeError("commissioning service is not initialized")
    return _service


async def _get_job_or_404(job_id: str) -> CommissioningJobRecord:
    job = await _repository.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": f"Job '{job_id}' not found."},
        )
    return job


def _langfuse_session_total(payload: dict) -> float | None:
    traces = payload.get("traces")
    if not isinstance(traces, list):
        return None
    costs = []
    for trace in traces:
        if not isinstance(trace, dict) or trace.get("totalCost") is None:
            continue
        try:
            costs.append(float(trace["totalCost"]))
        except (TypeError, ValueError):
            continue
    return round(sum(costs), 6) if costs else None


async def _langfuse_job_cost(job_id: str) -> float | None:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
        return None
    base_url = os.getenv("LANGFUSE_API_URL", "http://langfuse-web:3000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{base_url}/api/public/sessions/{job_id}",
                auth=(public_key, secret_key),
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _langfuse_session_total(response.json())
    except (httpx.HTTPError, ValueError):
        return None


def _podcast_cost_uris(result: WorkflowResult) -> list[str]:
    uris = []
    for deliverable in result.deliverables:
        value = deliverable.outputs.get("costs_uri")
        if isinstance(value, str) and value.startswith("artifact://"):
            uris.append(value)
    return uris


async def _podcast_job_cost(job_id: str) -> float | None:
    status, result_json = await _repository.get_workflow_result_json(job_id)
    if status != "succeeded" or not result_json:
        return None
    result = WorkflowResult.model_validate_json(result_json)
    total = 0.0
    found = False
    for uri in _podcast_cost_uris(result):
        try:
            payload = json.loads((await _get_artifact_store().get_bytes(uri)).decode())
            value = payload.get("total_cost_usd")
            if value is not None:
                total += float(value)
                found = True
        except (
            ArtifactNotFoundError,
            ArtifactReadError,
            PathTraversalError,
            UnicodeDecodeError,
            ValueError,
        ):
            continue
    return round(total, 6) if found else None


@app.post("/api/learning-requests/preview", response_model=LearningRequestPreview)
async def create_preview(request: LearningCommissionRequest):
    try:
        return await _get_service().create_preview(request)
    except CatalogUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "catalog_unavailable", "message": str(exc)})


@app.get(
    "/api/learning-requests/previews/{preview_id}",
    response_model=LearningRequestPreview,
)
async def get_preview(preview_id: str):
    try:
        return await _get_service().get_preview(preview_id)
    except PreviewNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "preview_not_found", "message": f"Preview '{preview_id}' not found."},
        ) from exc


@app.post(
    "/api/learning-requests/previews/{preview_id}/confirm",
    response_model=ConfirmedLearningRequest,
)
async def confirm_preview(preview_id: str, command: LearningRequestConfirmation):
    try:
        return await _get_service().confirm(preview_id, command)
    except PreviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "preview_not_found", "message": str(exc)})
    except StalePreviewError as exc:
        raise HTTPException(status_code=409, detail={"code": "stale_preview", "message": str(exc)})
    except ConfirmationRejectedError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "confirmation_rejected", "message": str(exc)}
        )


@app.get(
    "/api/learning-requests/previews/{preview_id}/job",
    response_model=CommissioningJobRecord,
)
async def get_preview_job(preview_id: str):
    job = await _repository.get_job_by_preview(preview_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": "No assembly job exists for this preview."},
        )
    return job


@app.get("/api/commissioning-jobs", response_model=list[CommissioningJobView])
async def list_commissioning_jobs(
    response: Response,
    scope: str = Query(default="all", pattern="^(all|active|completed|failed)$"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
):
    before_created_at = None
    before_job_id = None
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode() + b"=" * (-len(cursor) % 4)).decode()
            timestamp, before_job_id = raw.split("|", 1)
            before_created_at = datetime.fromisoformat(timestamp)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid jobs cursor") from exc
    jobs = await _repository.list_job_views(
        limit=limit + 1,
        before_created_at=before_created_at,
        before_job_id=before_job_id,
    )
    if len(jobs) > limit:
        last = jobs[limit - 1]
        token = base64.urlsafe_b64encode(
            f"{last.created_at.isoformat()}|{last.job_id}".encode()
        ).decode().rstrip("=")
        response.headers["X-Next-Cursor"] = token
        jobs = jobs[:limit]
    if scope == "active":
        return [
            job
            for job in jobs
            if job.status not in {"completed", "failed", "canceled"}
        ]
    if scope == "failed":
        return [job for job in jobs if job.status in {"failed", "canceled"}]
    if scope == "completed":
        return [job for job in jobs if job.status == scope]
    return jobs


@app.get("/api/commissioning-jobs/{job_id}", response_model=CommissioningJobView)
async def get_commissioning_job(job_id: str):
    view = await _repository.get_job_view(job_id)
    if view is None:
        await _get_job_or_404(job_id)
    return view


@app.get("/api/commissioning-jobs/{job_id}/cost")
async def get_commissioning_job_cost(job_id: str):
    job = await _get_job_or_404(job_id)
    llm_cost, podcast_cost = await asyncio.gather(
        _langfuse_job_cost(job_id),
        _podcast_job_cost(job_id),
    )
    components = [value for value in (llm_cost, podcast_cost) if value is not None]
    return {
        "job_id": job_id,
        "tracked_total_cost_usd": round(sum(components), 6) if components else None,
        "llm_cost_usd": llm_cost,
        "podcast_audio_cost_usd": podcast_cost,
        "complete": job.state.value == "succeeded" and llm_cost is not None and (
            job.selected_modality != Modality.PODCAST or podcast_cost is not None
        ),
        "heygen_included": False,
    }


@app.post("/api/commissioning-jobs/{job_id}/rerun", response_model=CommissioningJobView)
async def rerun_commissioning_job(job_id: str):
    await _get_job_or_404(job_id)
    try:
        await _repository.rerun_failed_job(job_id)
    except JobNotRerunnableError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_not_rerunnable",
                "message": "Only failed or canceled jobs can be restarted.",
            },
        ) from exc
    view = await _repository.get_job_view(job_id)
    if view is None:
        raise HTTPException(status_code=404, detail="job not found")
    return view


@app.post("/api/commissioning-jobs/{job_id}/restart", response_model=CommissioningJobView)
async def restart_commissioning_job(job_id: str):
    """Restart the same workflow ID so executor checkpoints remain reusable."""
    return await rerun_commissioning_job(job_id)


@app.post("/api/commissioning-jobs/{job_id}/cancel", response_model=CommissioningJobView)
async def cancel_commissioning_job(job_id: str):
    await _get_job_or_404(job_id)
    try:
        await _repository.cancel_job(job_id)
    except JobNotCancelableError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_not_cancelable",
                "message": "Only queued or running generation jobs can be canceled.",
            },
        ) from exc
    view = await _repository.get_job_view(job_id)
    if view is None:
        raise HTTPException(status_code=404, detail="job not found")
    return view


def _artifact_candidates(job_id: str, result: WorkflowResult) -> list[tuple[DeliverableDescriptor, str]]:
    candidates: list[tuple[str, str, int | None, bool]] = []
    seen: set[str] = set()
    primary_keys = {"audio_uri", "video_uri", "bundle_zip"}
    media_defaults = {
        "audio_uri": "audio/wav",
        "video_uri": "video/mp4",
        "bundle_zip": "application/zip",
        "entry_html": "text/html",
        "course_json": "application/json",
        "asset_manifest": "application/json",
    }

    def visit(key: str, value, outputs: dict) -> None:
        uri = None
        media_type = media_defaults.get(key, "application/octet-stream")
        size = None
        if isinstance(value, dict) and isinstance(value.get("uri"), str):
            uri = value["uri"]
            media_type = value.get("media_type") or media_type
            size = value.get("size_bytes")
        elif isinstance(value, str) and key.endswith("_uri"):
            uri = value
            media_type = outputs.get("media_type") or outputs.get(
                key.removesuffix("_uri") + "_media_type"
            ) or media_type
        elif isinstance(value, dict):
            for nested_key, nested_value in value.items():
                visit(nested_key, nested_value, value)
        if uri and uri.startswith("artifact://") and uri not in seen:
            seen.add(uri)
            candidates.append((uri, media_type, size, key in primary_keys))

    for deliverable in result.deliverables:
        for key, value in deliverable.outputs.items():
            visit(key, value, deliverable.outputs)

    candidates.sort(key=lambda value: (not value[3], value[0]))
    result_items = []
    for uri, media_type, size, primary in candidates:
        deliverable_id = hashlib.sha256(f"{job_id}\0{uri}".encode()).hexdigest()[:24]
        filename = PurePosixPath(uri.removeprefix("artifact://")).name or "download"
        descriptor = DeliverableDescriptor(
            deliverable_id=deliverable_id,
            filename=filename,
            media_type=media_type,
            size_bytes=size,
            primary=primary,
            download_url=(
                f"/api/commissioning-jobs/{job_id}/deliverables/"
                f"{deliverable_id}/download"
            ),
        )
        result_items.append((descriptor, uri))
    return result_items


async def _completed_deliverables(job_id: str) -> list[tuple[DeliverableDescriptor, str]]:
    job = await _get_job_or_404(job_id)
    status, result_json = await _repository.get_workflow_result_json(job_id)
    if status != "succeeded" or not result_json:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "deliverables_not_ready",
                "message": f"Job '{job.job_id}' has not completed generation.",
            },
        )
    return _artifact_candidates(job_id, WorkflowResult.model_validate_json(result_json))


@app.get(
    "/api/commissioning-jobs/{job_id}/deliverables",
    response_model=list[DeliverableDescriptor],
)
async def list_deliverables(job_id: str):
    return [item for item, _uri in await _completed_deliverables(job_id)]


async def _resolve_course_bundle(job_id: str) -> tuple[DeliverableDescriptor, bytes]:
    job = await _get_job_or_404(job_id)
    if job.selected_modality != Modality.ELEARNING:
        raise CoursePreviewError("Course preview is available only for e-learning jobs.")

    entries = await _completed_deliverables(job_id)
    match = next(
        (
            (item, uri)
            for item, uri in entries
            if item.primary and item.media_type == "application/zip"
        ),
        None,
    )
    if match is None:
        raise CoursePreviewError("The completed job does not contain a course package.")

    item, uri = match
    try:
        bundle = await _get_artifact_store().get_bytes(uri)
    except (ArtifactNotFoundError, ArtifactReadError, PathTraversalError) as exc:
        raise CoursePreviewError("The course package is unavailable.") from exc
    return item, bundle


def _safe_preview_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    names: set[str] = set()
    for member in archive.infolist():
        name = member.filename
        normalized = PurePosixPath(name)
        unix_mode = member.external_attr >> 16
        if (
            not name
            or "\\" in name
            or normalized.is_absolute()
            or ".." in normalized.parts
            or stat.S_ISLNK(unix_mode)
        ):
            raise CoursePreviewError("The course package contains an unsafe path.")
        normalized_name = normalized.as_posix().rstrip("/")
        if normalized_name in names:
            raise CoursePreviewError("The course package contains duplicate paths.")
        names.add(normalized_name)
        members.append(member)
    return members


def _course_preview_asset(bundle: bytes, asset_path: str) -> tuple[bytes, str]:
    normalized = PurePosixPath(asset_path)
    if (
        not asset_path
        or "\\" in asset_path
        or normalized.is_absolute()
        or ".." in normalized.parts
    ):
        raise CoursePreviewError("The requested course asset path is unsafe.")
    try:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            members = _safe_preview_members(archive)
            names = {member.filename.rstrip("/") for member in members}
            if "index.html" not in names:
                raise CoursePreviewError("The course package does not contain index.html.")
            requested = normalized.as_posix()
            if requested not in names:
                raise CoursePreviewError("The requested course asset was not found.")
            data = archive.read(requested)
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise CoursePreviewError("The course package could not be opened.") from exc
    media_type = mimetypes.guess_type(requested)[0] or "application/octet-stream"
    if normalized.suffix.casefold() == ".vtt":
        media_type = "text/vtt"
    return data, media_type


def _preview_response(data: bytes, media_type: str, range_header: str | None) -> Response:
    headers = {
        "Cache-Control": "private, max-age=3600",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
    }
    if range_header and range_header.startswith("bytes="):
        value = range_header.removeprefix("bytes=")
        if "," not in value:
            start_text, separator, end_text = value.partition("-")
            try:
                start = int(start_text) if start_text else 0
                end = int(end_text) if separator and end_text else len(data) - 1
            except ValueError:
                start = -1
                end = -1
            if 0 <= start <= end < len(data):
                headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
                return Response(
                    content=data[start : end + 1],
                    status_code=206,
                    media_type=media_type,
                    headers=headers,
                )
        return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
    return Response(content=data, media_type=media_type, headers=headers)


async def _course_preview_response(
    job_id: str, asset_path: str, range_header: str | None = None
) -> Response:
    try:
        _item, bundle = await _resolve_course_bundle(job_id)
        data, media_type = _course_preview_asset(bundle, asset_path)
    except CoursePreviewError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "course_preview_unavailable", "message": str(exc)},
        ) from exc
    return _preview_response(data, media_type, range_header)


@app.get("/api/commissioning-jobs/{job_id}/preview")
async def redirect_course_preview(job_id: str):
    return RedirectResponse(url=f"/api/commissioning-jobs/{job_id}/preview/")


@app.get("/api/commissioning-jobs/{job_id}/preview/")
async def open_course_preview(job_id: str, request: Request):
    return await _course_preview_response(job_id, "index.html", request.headers.get("range"))


@app.get("/api/commissioning-jobs/{job_id}/preview/{asset_path:path}")
async def get_course_preview_asset(job_id: str, asset_path: str, request: Request):
    return await _course_preview_response(job_id, asset_path, request.headers.get("range"))


@app.get("/api/commissioning-jobs/{job_id}/deliverables/{deliverable_id}/download")
async def download_deliverable(job_id: str, deliverable_id: str):
    entries = await _completed_deliverables(job_id)
    match = next(((item, uri) for item, uri in entries if item.deliverable_id == deliverable_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="deliverable not found for this job")
    item, uri = match
    try:
        data = await _get_artifact_store().get_bytes(uri)
    except (ArtifactNotFoundError, ArtifactReadError, PathTraversalError) as exc:
        raise HTTPException(status_code=404, detail="deliverable artifact is unavailable") from exc
    return Response(
        content=data,
        media_type=item.media_type,
        headers={"Content-Disposition": f'attachment; filename="{item.filename}"'},
    )


async def _get_artifact(job_id: str, name: str) -> dict:
    job = await _get_job_or_404(job_id)
    value = await _repository.get_job_artifact(job_id, name)
    if value is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "artifact_not_ready",
                "message": f"Artifact '{name}' is not available while job state is '{job.state.value}'.",
            },
        )
    return value


@app.get("/api/commissioning-jobs/{job_id}/blueprint", response_model=CourseBlueprint)
async def get_commissioning_blueprint(job_id: str):
    return await _get_artifact(job_id, "blueprint")


@app.get("/api/commissioning-jobs/{job_id}/report", response_model=CourseAssemblyReport)
async def get_commissioning_report(job_id: str):
    return await _get_artifact(job_id, "assembly_report")


@app.get("/api/commissioning-jobs/{job_id}/trace", response_model=AssemblyPlanningTrace)
async def get_commissioning_trace(job_id: str):
    return await _get_artifact(job_id, "planning_trace")
