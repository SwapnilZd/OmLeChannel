"""
Learning Workflow API — Phase 6.

Endpoints:
  POST   /workflow-runs               — validate and persist a BuildPlan as pending
  GET    /workflow-runs/{id}          — current status
  GET    /workflow-runs/{id}/result   — WorkflowResult when succeeded
  GET    /health/live                 — liveness probe
  GET    /health/ready                — readiness probe (checks DB)

The API never executes workflow tasks.  Execution is performed by the worker process.

Architecture notes
------------------
``get_repo`` is defined at module level so that FastAPI's dependency_overrides
key is the same object whether used in route definitions or in test fixtures.
``create_app`` is a factory that accepts an optional pool for injection in tests
and the end-to-end suite (avoiding a real DB connection in the lifespan).
``app`` is the module-level singleton used by uvicorn.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Request

from learning_pipeline.api.models import (
    WorkflowResultResponse,
    WorkflowStatusResponse,
    WorkflowSubmissionRequest,
    WorkflowSubmissionResponse,
)
from learning_pipeline.config import FAKE_EXECUTOR_TASK_TYPES
from learning_pipeline.contracts import WorkflowResult
from learning_pipeline.db.repository import (
    DuplicateWorkflowError,
    PersistentWorkflowStatus,
    PostgresWorkflowRepository,
    WorkflowRepository,
)
from learning_pipeline.db.migrate import run_migrations
from learning_pipeline.validation import PlanValidationError, canonical_plan_hash, validate_build_plan


# ── Dependency ────────────────────────────────────────────────────────────────
# Module-level so tests can override via app.dependency_overrides[get_repo].

async def get_repo(request: Request) -> WorkflowRepository:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="database not configured")
    return PostgresWorkflowRepository(pool)


# ── Application factory ───────────────────────────────────────────────────────

def create_app(pool: asyncpg.Pool | None = None) -> FastAPI:
    """
    Return a FastAPI application.

    Parameters
    ----------
    pool:
        When supplied the lifespan skips DB connection and uses this pool
        directly.  Pass a real pool for end-to-end tests.  Omit for
        production (DATABASE_URL is read from the environment).
    """
    _external_pool = pool

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        if _external_pool is not None:
            app.state.pool = _external_pool
        else:
            dsn = os.getenv("DATABASE_URL", "")
            app.state.pool = await asyncpg.create_pool(dsn=dsn) if dsn else None
            if app.state.pool is not None:
                await run_migrations(app.state.pool)
        yield
        if _external_pool is None and app.state.pool is not None:
            await app.state.pool.close()

    application = FastAPI(
        title="Learning Workflow API",
        description="Submit and track deterministic learning workflow runs.",
        version="0.1.0",
        lifespan=lifespan,
    )
    # Pre-set pool so tests that skip the lifespan (httpx ASGITransport) still work
    if _external_pool is not None:
        application.state.pool = _external_pool

    # ── Routes ────────────────────────────────────────────────────────────────

    @application.post(
        "/workflow-runs",
        response_model=WorkflowSubmissionResponse,
        status_code=202,
        summary="Submit a BuildPlan for asynchronous execution",
    )
    async def submit_workflow(
        body: WorkflowSubmissionRequest,
        repo: WorkflowRepository = Depends(get_repo),
    ) -> WorkflowSubmissionResponse:
        plan = body.plan

        try:
            validate_build_plan(plan, FAKE_EXECUTOR_TASK_TYPES)
        except PlanValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        plan_hash = canonical_plan_hash(plan)

        try:
            await repo.create_pending(plan, plan_hash)
        except DuplicateWorkflowError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return WorkflowSubmissionResponse(
            workflow_id=plan.workflow_id,
            status="pending",
            plan_hash=plan_hash,
        )

    @application.get(
        "/workflow-runs/{workflow_id}",
        response_model=WorkflowStatusResponse,
        summary="Get current workflow status",
    )
    async def get_workflow_status(
        workflow_id: str,
        repo: WorkflowRepository = Depends(get_repo),
    ) -> WorkflowStatusResponse:
        record = await repo.get(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"workflow {workflow_id!r} not found")
        return WorkflowStatusResponse(
            workflow_id=record.workflow_id,
            status=record.status,
            plan_hash=record.plan_hash,
            error_message=record.error_message,
        )

    @application.get(
        "/workflow-runs/{workflow_id}/result",
        response_model=WorkflowResultResponse,
        summary="Get workflow result (only when succeeded)",
    )
    async def get_workflow_result(
        workflow_id: str,
        repo: WorkflowRepository = Depends(get_repo),
    ) -> WorkflowResultResponse:
        record = await repo.get(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"workflow {workflow_id!r} not found")
        if record.status != PersistentWorkflowStatus.SUCCEEDED:
            raise HTTPException(
                status_code=409,
                detail=f"workflow {workflow_id!r} is {record.status.value}, not succeeded",
            )
        assert record.result_json is not None
        return WorkflowResultResponse(
            workflow_id=workflow_id,
            result=WorkflowResult.model_validate_json(record.result_json),
        )

    @application.get("/health/live", summary="Liveness probe")
    async def health_live() -> dict:
        return {"status": "ok"}

    @application.get("/health/ready", summary="Readiness probe — checks database connectivity")
    async def health_ready(request: Request) -> dict:
        pool = getattr(request.app.state, "pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="database not configured")
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"status": "ok"}
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"database unreachable: {type(exc).__name__}",
            ) from exc

    return application


# Module-level singleton used by uvicorn
app = create_app()
