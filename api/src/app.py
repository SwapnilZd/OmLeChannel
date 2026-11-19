"""
Ingestion API — RLO upload, validation, object storage, and Qdrant indexing.
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from poc_auth import (
    COOKIE_NAME,
    SESSION_SECONDS,
    auth_enabled,
    cookie_secure,
    create_session,
    request_email,
    require_authenticated_request,
    valid_credentials,
)
from pydantic import ValidationError
from rlo_schema import SchemaVersionError, validate_rlo

from .source_drafts import router as source_drafts_router
from .objective_jobs import router as objective_jobs_router
from .source_ingestion.repository import init_db
from .source_upload import router as source_upload_router

from .catalog import (
    VersionedRLOCatalog,
    parse_versioned_rlo_key,
    version_sort_key,
    versioned_rlo_key,
)
from .indexer import EMBED_MODEL, INDEX_REVISION, RloIndexer
from .rlo_schema import (
    IngestResponse,
    RloBatchSearchRequest,
    RloBatchSearchResponse,
    RloListItem,
    RloSearchHit,
    RloSearchResult,
    RloVersionItem,
)
from .storage import get_storage

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent / "static"
SEED_DIR = os.environ.get("SEED_DIR", "/course-definitions/rlos")

_storage = None
_catalog = None
_indexer = None
_templates = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _storage, _catalog, _indexer, _templates
    _storage = get_storage()
    _catalog = VersionedRLOCatalog(_storage)
    _indexer = RloIndexer()
    _templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    init_db()
    print("[api] Storage and indexer initialised")
    _seed_missing()
    yield

app = FastAPI(title="RLO Ingestion API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(source_upload_router)
app.include_router(source_drafts_router)
app.include_router(objective_jobs_router)


@app.get("/api/health")
async def health():
    return {"status": "ready"}


def _ingest(body: bytes) -> IngestResponse:
    """Parse, validate, store, and index one RLO document."""
    if not body:
        raise ValueError("Request body is empty.")

    raw = json.loads(body)
    rlo, schema_version = validate_rlo(raw)

    uri = _catalog.put(rlo.id, rlo.version, body)
    current_version = _catalog.current_version(rlo.id)
    indexed = _indexer.upsert(rlo, uri, is_active=rlo.version == current_version)
    if current_version is not None:
        # If embedding the new current version failed, deactivate older points
        # rather than silently returning stale content as current.
        _indexer.set_active_version(rlo.id, current_version)

    return IngestResponse(
        rlo_id=rlo.id,
        schema_version=schema_version,
        rlo_version=rlo.version,
        title=rlo.title,
        topic=rlo.topic,
        domain=rlo.domain,
        level=rlo.level.value,
        concepts=len(rlo.concepts),
        components=len(rlo.components),
        assessment_items=len(rlo.assessment_items),
        storage_uri=uri,
        indexed=indexed,
        message="RLO stored successfully." + ("" if indexed else " Qdrant indexing skipped (unavailable)."),
    )


def _seed_missing() -> None:
    """Seed missing committed RLO versions and repair their indexes."""
    try:
        existing = {k for k in _storage.list_prefix("") if k.endswith(".json")}
    except Exception as exc:
        print(f"[seed] Could not inspect storage; skipping seed: {exc}")
        return

    seed_root = Path(SEED_DIR)
    if not seed_root.is_dir():
        print(f"[seed] Seed directory {SEED_DIR} not mounted; nothing to seed.")
        return

    files = sorted(seed_root.glob("*.json"))
    if not files:
        print(f"[seed] No RLO JSON files found in {SEED_DIR}.")
        return

    versions_by_id: dict[str, list[str]] = {}
    for key in existing:
        parsed = parse_versioned_rlo_key(key)
        if parsed:
            versions_by_id.setdefault(parsed[0], []).append(parsed[1])
    current_versions = {
        rlo_id: max(versions, key=version_sort_key)
        for rlo_id, versions in versions_by_id.items()
    }

    print(f"[seed] Checking {len(files)} committed seed file(s) in {SEED_DIR}")
    seeded = reindexed = unchanged = skipped = 0
    for f in files:
        rel = f.relative_to(seed_root)
        try:
            body = f.read_bytes()
            rlo, _ = validate_rlo(json.loads(body))
            key = versioned_rlo_key(rlo.id, rlo.version)
            if key in existing:
                if not _indexer.is_index_current(rlo.id, rlo.version):
                    indexed = _indexer.upsert(
                        rlo,
                        _storage.uri(key),
                        is_active=rlo.version == current_versions.get(rlo.id),
                    )
                    if indexed:
                        _indexer.set_active_version(
                            rlo.id,
                            current_versions.get(rlo.id, rlo.version),
                        )
                        reindexed += 1
                        print(f"[seed]   ✓ {rlo.id}  (repaired vector index)")
                    else:
                        print(f"[seed]   ! {rlo.id}  (vector index still unavailable)")
                unchanged += 1
                continue
            resp = _ingest(body)
            existing.add(key)
            seeded += 1
            note = "" if resp.indexed else "  (stored, not indexed — embeddings unavailable)"
            print(f"[seed]   ✓ {resp.rlo_id}{note}")
        except Exception as exc:
            skipped += 1
            summary = str(exc).splitlines()[0][:160] if str(exc) else exc.__class__.__name__
            print(f"[seed]   ✗ {rel} — skipped: {summary}")
    print(
        f"[seed] Done: {seeded} seeded, {reindexed} reindexed, "
        f"{unchanged} already stored, {skipped} skipped."
    )


@app.post(
    "/api/rlos",
    response_model=IngestResponse,
    status_code=201,
    dependencies=[Depends(require_authenticated_request)],
)
async def ingest_rlo(request: Request):
    body = await request.body()
    try:
        return _ingest(body)
    except ValidationError as exc:
        # exc.errors() can embed the raw ValueError from a model_validator in `ctx`,
        # which is not JSON-serialisable; exc.json() stringifies it safely.
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
    except SchemaVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/rlos", response_model=list[RloListItem])
async def list_rlos():
    result = []
    for stored in _catalog.list_current():
        try:
            data = json.loads(_storage.get(stored.key))
            governance = data.get("governance") or {}
            result.append(RloListItem(
                id=data.get("id", stored.rlo_id),
                title=data.get("title", ""),
                topic=data.get("topic", ""),
                domain=data.get("domain", ""),
                level=data.get("level", ""),
                status=governance.get("status", ""),
                schema_version=data.get("schema_version", ""),
                rlo_version=data.get("version", stored.rlo_version),
                storage_uri=stored.key,
            ))
        except Exception:
            continue
    return result


@app.get("/api/rlos/{rlo_id}")
async def get_rlo(rlo_id: str):
    try:
        data, _ = _catalog.get_current(rlo_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"RLO '{rlo_id}' not found.")
    return JSONResponse(content=json.loads(data))


@app.delete(
    "/api/rlos/{rlo_id}",
    status_code=204,
    dependencies=[Depends(require_authenticated_request)],
)
async def delete_rlo(rlo_id: str):
    if not _catalog.delete_all(rlo_id):
        raise HTTPException(status_code=404, detail=f"RLO '{rlo_id}' not found.")
    _indexer.delete(rlo_id)


@app.get("/api/rlos/{rlo_id}/versions", response_model=list[RloVersionItem])
async def list_rlo_versions(rlo_id: str):
    versions = _catalog.versions(rlo_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"RLO '{rlo_id}' not found.")
    current = versions[0]
    return [
        RloVersionItem(
            rlo_id=rlo_id,
            rlo_version=version,
            is_current=version == current,
            storage_uri=versioned_rlo_key(rlo_id, version),
        )
        for version in versions
    ]


@app.get("/api/rlos/{rlo_id}/versions/{rlo_version}")
async def get_rlo_version(rlo_id: str, rlo_version: str):
    try:
        data = _catalog.get_exact(rlo_id, rlo_version)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"RLO '{rlo_id}' version '{rlo_version}' not found."
        )
    return JSONResponse(content=json.loads(data))


@app.post("/api/rlo-search/batch", response_model=RloBatchSearchResponse)
async def search_rlos_batch(request: RloBatchSearchRequest):
    try:
        raw_results = _indexer.search_batch([
            (query.text, query.filters, query.limit) for query in request.queries
        ])
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    results = []
    for query, hits in zip(request.queries, raw_results, strict=True):
        results.append(RloSearchResult(
            query_id=query.query_id,
            hits=[RloSearchHit(
                rlo_id=hit["rlo_id"],
                rlo_version=hit["rlo_version"],
                score=hit["score"],
                title=hit.get("title", ""),
                topic=hit.get("topic", ""),
                domain=hit.get("domain", ""),
                level=hit.get("level", ""),
                language=hit.get("language", ""),
                locale=hit.get("locale", ""),
                estimated_duration_minutes=hit.get("estimated_duration_minutes"),
                governance_status=hit.get("status", ""),
                audience=hit.get("audience", []),
                industry_tags=hit.get("industry_tags", []),
                role_tags=hit.get("role_tags", []),
                service_line_tags=hit.get("service_line_tags", []),
                competency_tags=hit.get("competency_tags", []),
                regulatory_tags=hit.get("regulatory_tags", []),
                storage_uri=hit["storage_uri"],
            ) for hit in hits],
        ))
    return RloBatchSearchResponse(
        index_revision=INDEX_REVISION,
        embedding_model=EMBED_MODEL,
        results=results,
    )


@app.get("/", response_class=HTMLResponse)
async def upload_ui(request: Request):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(request, "index.html")


@app.get("/commission", response_class=HTMLResponse)
async def commissioning_ui(request: Request):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(request, "commission.html")


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_ui(request: Request):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(request, "jobs.html")


@app.get("/login", response_class=HTMLResponse)
async def login_ui(request: Request):
    if not auth_enabled() or request_email(request) is not None:
        return RedirectResponse("/commission", status_code=303)
    return _templates.TemplateResponse(request, "login.html", {"error": None, "email": ""})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request):
    fields = parse_qs((await request.body()).decode())
    email = fields.get("email", [""])[0].strip().lower()
    password = fields.get("password", [""])[0]
    if not valid_credentials(email, password):
        return _templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Enter a Deloitte email address and the correct password.", "email": email},
            status_code=401,
        )
    response = RedirectResponse("/commission", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        create_session(email),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )
    return response

@app.get("/source-upload")
async def source_upload_page(request: Request):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(request, "source_upload.html")


@app.get("/source-inspect/{job_id}", response_class=HTMLResponse)
async def source_inspection_page(request: Request, job_id: str):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(
        request, "source_inspect.html", {"job_id": job_id}
    )


@app.get("/rlo-drafts", response_class=HTMLResponse)
async def rlo_drafts_page(request: Request):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(request, "rlo_drafts.html")


@app.get("/objective-jobs", response_class=HTMLResponse)
async def objective_jobs_page(request: Request):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(request, "objective_jobs.html")


@app.get("/objective-jobs/{job_id}", response_class=HTMLResponse)
async def objective_job_review_page(request: Request, job_id: str):
    if auth_enabled() and request_email(request) is None:
        return RedirectResponse("/login", status_code=303)
    return _templates.TemplateResponse(
        request, "objective_job_review.html", {"job_id": job_id}
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
