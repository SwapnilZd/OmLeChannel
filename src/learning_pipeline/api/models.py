"""API request and response contracts for the workflow execution service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from learning_pipeline.contracts import BuildPlan, WorkflowResult
from learning_pipeline.db.repository import PersistentWorkflowStatus


class WorkflowSubmissionRequest(BaseModel):
    plan: BuildPlan


class WorkflowSubmissionResponse(BaseModel):
    workflow_id: str
    status: Literal["pending"]
    plan_hash: str


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: PersistentWorkflowStatus
    plan_hash: str
    error_message: str | None = None


class WorkflowResultResponse(BaseModel):
    workflow_id: str
    result: WorkflowResult
