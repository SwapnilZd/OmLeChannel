"""Private working-memory contracts for bounded e-learning authoring."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    ElearningCourseAuthorDraft,
)


WORKSPACE_VERSION = "authoring-workspace-v4"
CONTENT_CHARTER_VERSION = "learner-facing-content-v2"
REVIEW_RUBRIC_VERSION = "course-review-v5"


class AuthoringState(str, Enum):
    LOADED = "loaded"
    INSPECTED = "inspected"
    PLANNED = "planned"
    DRAFTED = "drafted"
    VALIDATED = "validated"
    REVIEWED = "reviewed"
    REVISING = "revising"
    READY = "ready"


class FindingSeverity(str, Enum):
    WARNING = "warning"
    BLOCKING = "blocking"


class FindingOwner(str, Enum):
    PLANNER = "planner"
    AUTHOR = "author"
    BUILDER = "builder"
    RENDERER = "renderer"
    SOURCE = "source"


class FindingRepairability(str, Enum):
    AUTOMATIC = "automatic"
    AUTHOR_PATCH = "author_patch"
    REPLAN = "replan"
    HUMAN_SOURCE = "human_source"
    ADVISORY = "advisory"


class AuthoringFinding(FrozenModel):
    finding_id: str
    code: str
    screen_id: str
    category: str
    severity: FindingSeverity
    owner: FindingOwner
    repairability: FindingRepairability
    field_path: str | None = None
    message: str
    evidence: str | None = None
    revision_instruction: str | None = None

    @model_validator(mode="after")
    def _validate_repair_route(self) -> "AuthoringFinding":
        if self.repairability == FindingRepairability.AUTHOR_PATCH:
            if self.owner != FindingOwner.AUTHOR:
                raise ValueError("author_patch findings must be owned by the author")
            if not self.field_path:
                raise ValueError("author_patch findings require an editable field_path")
            if not self.revision_instruction:
                raise ValueError("author_patch findings require a revision_instruction")
            if not self.evidence:
                raise ValueError("author_patch findings require visible/source evidence")
        if (
            self.severity == FindingSeverity.BLOCKING
            and self.owner == FindingOwner.AUTHOR
            and self.repairability != FindingRepairability.AUTHOR_PATCH
        ):
            raise ValueError("blocking author findings must use author_patch")
        return self


class ScreenIntent(FrozenModel):
    screen_id: str
    screen_type: str
    learner_action: str
    source_scene_ids: tuple[str, ...]
    learner_purpose: str
    internal_only_notes: tuple[str, ...] = ()


class RevisionRecord(FrozenModel):
    revision: int = Field(..., ge=1)
    revised_screen_ids: tuple[str, ...]
    resolved_finding_ids: tuple[str, ...]
    finding_signatures: tuple[str, ...] = ()
    revised_field_paths: tuple[str, ...] = ()


class AuthoringWorkspace(FrozenModel):
    workspace_version: str = WORKSPACE_VERSION
    workflow_id: str
    task_id: str
    deliverable_id: str
    input_hash: str
    prompt_version: str
    content_charter_version: str = CONTENT_CHARTER_VERSION
    review_rubric_version: str = REVIEW_RUBRIC_VERSION
    state: AuthoringState
    required_screen_ids: tuple[str, ...]
    intents: tuple[ScreenIntent, ...] = ()
    draft: ElearningCourseAuthorDraft | None = None
    findings: tuple[AuthoringFinding, ...] = ()
    finding_history: tuple[AuthoringFinding, ...] = ()
    revision_history: tuple[RevisionRecord, ...] = ()
    model_call_count: int = Field(0, ge=0)
    internal_tool_call_count: int = Field(0, ge=0)
    repair_attempt_count: int = Field(0, ge=0)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    initial_batch_mode: Literal["not_run", "sequential", "parallel"] = "not_run"
    initial_batch_peak_concurrency: int = Field(0, ge=0)
    initial_batch_elapsed_seconds: float = Field(0, ge=0)
    checkpoint_stages_reused: tuple[str, ...] = ()
    checkpoint_recovery_events: tuple[str, ...] = ()

    @property
    def blocking_findings(self) -> tuple[AuthoringFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.severity == FindingSeverity.BLOCKING
        )
