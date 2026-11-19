"""Bounded, resumable controller for e-learning content authoring."""
from __future__ import annotations

from learning_pipeline.prompts import load_prompt

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from learning_pipeline.runtime.artifact_store import (
    ArtifactNotFoundError,
    ArtifactStore,
)
from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    ElearningCourseAuthorDraft,
)
from learning_pipeline.tools.elearning_bundle._authoring_client import (
    AuthoringPolicyError,
    ElearningAuthoringClient,
    StructuredAuthoringResponse,
)
from learning_pipeline.tools.elearning_bundle._authoring_errors import (
    AuthoringAgentError,
    AuthoringInfrastructureError,
    AuthoringReviewError,
    AuthoringToolError,
    AuthoringValidationError,
)
from learning_pipeline.tools.elearning_bundle._authoring_tools import AuthoringTools
from learning_pipeline.tools.elearning_bundle._authoring_review import (
    build_learner_review_projection,
)
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    AuthoringFinding,
    AuthoringState,
    AuthoringWorkspace,
    CONTENT_CHARTER_VERSION,
    FindingOwner,
    FindingRepairability,
    FindingSeverity,
    RevisionRecord,
    REVIEW_RUBRIC_VERSION,
    WORKSPACE_VERSION,
)
from learning_pipeline.tools.elearning_bundle._content_builder import (
    ElearningCourseContentBuilder,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    ElearningAuthoringBrief,
    SlotPreservationReport,
)


_REVIEW_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "prompts"
    / "elearning_author"
    / "course_review.md"
)

# Keep structured authoring responses small enough to validate reliably. Large
# courses are assembled from independently checkpointed batches; the brief
# remains authoritative for final membership and order.
_AUTHORING_BATCH_SIZE = 8
_AUTHORING_BATCH_CONCURRENCY = 3
_SEMANTIC_BLOCKING_CODES = frozenset(
    {
        "SOURCE_FIDELITY",
        "REQUIRED_CONTENT_MISSING",
        "LEARNER_INSTRUCTION_UNUSABLE",
        "PEDAGOGICAL_RATIONALE_LEAKAGE",
    }
)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthoringAgentResult:
    draft: ElearningCourseAuthorDraft
    course_dict: dict[str, Any]
    slot_report: SlotPreservationReport
    workspace: AuthoringWorkspace
    model: str


@dataclass(frozen=True)
class _InitialAuthorBatch:
    number: int
    total: int
    screen_ids: tuple[str, ...]


@dataclass(frozen=True)
class _InitialAuthorBatchOutcome:
    batch: _InitialAuthorBatch
    response: StructuredAuthoringResponse | None
    error: Exception | None
    elapsed_seconds: float


class AuthoringAgentController:
    """Own legal transitions, budgets, checkpoints, review, and revision."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        authoring_client: ElearningAuthoringClient,
        builder: ElearningCourseContentBuilder,
        policy: AgenticExecutionPolicy,
    ) -> None:
        self._store = artifact_store
        self._client = authoring_client
        self._builder = builder
        self._tools = AuthoringTools(builder)
        self._policy = policy

    async def run(
        self,
        *,
        brief: ElearningAuthoringBrief,
        workflow_id: str,
        task_id: str,
        context_bytes: bytes,
        input_hash: str,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> AuthoringAgentResult:
        namespace = f"elearning/{workflow_id}"
        workspace, checkpoint_status = await self._load_workspace(
            namespace,
            brief.deliverable_id,
            input_hash,
            prompt_version=str(payload.get("prompt_version", "unknown")),
            required_screen_ids=tuple(req.screen_id for req in brief.screen_requirements),
        )
        if workspace is None:
            workspace = AuthoringWorkspace(
                workflow_id=workflow_id,
                task_id=task_id,
                deliverable_id=brief.deliverable_id,
                input_hash=input_hash,
                prompt_version=payload.get("prompt_version", "unknown"),
                state=AuthoringState.LOADED,
                required_screen_ids=tuple(
                    req.screen_id for req in brief.screen_requirements
                ),
                checkpoint_recovery_events=(
                    (checkpoint_status,) if checkpoint_status != "missing" else ()
                ),
            )
        else:
            workspace = workspace.model_copy(
                update={
                    "checkpoint_stages_reused": tuple(
                        dict.fromkeys(
                            (*workspace.checkpoint_stages_reused, workspace.state.value)
                        )
                    )
                }
            )
        if workspace.state == AuthoringState.READY and workspace.draft is not None:
            try:
                course, report = self._builder.build(brief, workspace.draft)
            except Exception as exc:
                raise AuthoringValidationError(
                    "Completed authoring checkpoint no longer validates."
                ) from exc
            return AuthoringAgentResult(
                draft=workspace.draft,
                course_dict=course,
                slot_report=report,
                workspace=workspace.model_copy(
                    update={
                        "checkpoint_stages_reused": tuple(
                            dict.fromkeys((*workspace.checkpoint_stages_reused, "ready"))
                        )
                    }
                ),
                model="cached",
            )

        # Inspection is deliberately deterministic and scope-limited. Reuse the
        # persisted plan on task retry instead of consuming the tool budget again.
        resolved_context = self._tools.inspect_context(context_bytes)
        schemas = self._tools.inspect_schemas(brief)
        if workspace.draft is not None:
            hydrated_draft = self._tools.hydrate_assessments(
                brief, workspace.draft, resolved_context
            )
            hydrated_draft = self._tools.hydrate_scenario_navigation(
                brief, hydrated_draft
            )
            if hydrated_draft != workspace.draft:
                reconciled_findings = self._reconcile_review_findings(
                    hydrated_draft, workspace.findings
                )
                can_reuse_review = workspace.state in {
                    AuthoringState.VALIDATED,
                    AuthoringState.REVIEWED,
                } and bool(workspace.findings)
                workspace = workspace.model_copy(
                    update={
                        "draft": hydrated_draft,
                        "findings": reconciled_findings,
                        "state": (
                            AuthoringState.REVIEWED
                            if can_reuse_review
                            else AuthoringState.DRAFTED
                        ),
                        # Deterministic content upgrades are safe to revalidate
                        # on a resumed run even when a prior implementation used
                        # the local-tool allowance. Model/cost budgets remain
                        # cumulative and are never reset.
                        "internal_tool_call_count": 0,
                        "checkpoint_recovery_events": tuple(
                            dict.fromkeys(
                                (
                                    *workspace.checkpoint_recovery_events,
                                    "deterministic-content-upgrade",
                                )
                            )
                        ),
                    }
                )
                await self._save_workspace(
                    namespace, workspace, "assessment-source-hydration"
                )
        if workspace.intents:
            intents = workspace.intents
            workspace = workspace.model_copy(
                update={
                    "checkpoint_stages_reused": tuple(
                        dict.fromkeys((*workspace.checkpoint_stages_reused, "intent-plan"))
                    )
                }
            )
        else:
            intents, workspace = self._use_tool(
                workspace,
                "inspect_assignment",
                lambda: self._tools.inspect_assignment(brief, resolved_context),
            )
            _, workspace = self._use_tool(
                workspace,
                "inspect_scene_context",
                lambda: resolved_context,
            )
            _, workspace = self._use_tool(
                workspace,
                "inspect_screen_schema",
                lambda: schemas,
            )
            workspace = workspace.model_copy(
                update={"intents": intents, "state": AuthoringState.PLANNED}
            )
            await self._save_workspace(namespace, workspace, "intent-plan")

        required_authored_ids = tuple(intent.screen_id for intent in intents)
        workspace, model = await self._draft_initial_batches(
            namespace=namespace,
            workspace=workspace,
            brief=brief,
            resolved_context=resolved_context,
            schemas=schemas,
            intents=intents,
            required_screen_ids=required_authored_ids,
            system_prompt=system_prompt,
            payload=payload,
        )

        if workspace.draft is None:
            raise AuthoringValidationError(
                "The authoring brief contains no authorable screen requirements."
            )

        revision = len(workspace.revision_history)
        review_scope = (
            workspace.revision_history[-1].revised_screen_ids
            if workspace.state == AuthoringState.DRAFTED and workspace.revision_history
            else None
        )
        while True:
            assert workspace.draft is not None
            state_before_validation = workspace.state
            persisted_findings = workspace.findings
            validation, workspace = self._use_tool(
                workspace,
                "validate_draft",
                lambda: self._tools.validate_draft(
                    brief, workspace.draft, resolved_context
                ),
            )
            course, report, validation_findings = validation
            workspace = workspace.model_copy(
                update={
                    "findings": validation_findings,
                    "finding_history": self._merge_findings(
                        workspace.finding_history, validation_findings
                    ),
                    "state": AuthoringState.VALIDATED,
                }
            )

            review_findings: tuple[AuthoringFinding, ...] = ()
            if not validation_findings:
                if state_before_validation == AuthoringState.REVIEWED and persisted_findings:
                    review_findings = persisted_findings
                    workspace = workspace.model_copy(
                        update={
                            "checkpoint_stages_reused": tuple(
                                dict.fromkeys(
                                    (
                                        *workspace.checkpoint_stages_reused,
                                        f"review-r{revision + 1}",
                                    )
                                )
                            )
                        }
                    )
                else:
                    # Patch authority is field-scoped, but the reviewer needs the
                    # whole revised screen to recognize content in neighboring fields.
                    review_findings, workspace = await self._review(
                        workspace=workspace,
                        brief=brief,
                        resolved_context=resolved_context,
                        course_dict=course,
                        screen_ids=review_scope,
                    )
                workspace = workspace.model_copy(
                    update={
                        "findings": review_findings,
                        "finding_history": self._merge_findings(
                            workspace.finding_history, review_findings
                        ),
                        "state": AuthoringState.REVIEWED,
                    }
                )
            await self._save_workspace(namespace, workspace, f"review-r{revision + 1}")

            blocking = workspace.blocking_findings
            if not blocking:
                if course is None or report is None:
                    raise AuthoringValidationError(
                        "Draft passed review without a valid course build."
                    )
                _, workspace = self._use_tool(workspace, "finalize", lambda: True)
                workspace = workspace.model_copy(update={"state": AuthoringState.READY})
                await self._save_workspace(namespace, workspace, "completed")
                return AuthoringAgentResult(
                    draft=workspace.draft,
                    course_dict=course,
                    slot_report=report,
                    workspace=workspace,
                    model=model,
                )

            non_author_blocking = tuple(
                finding
                for finding in blocking
                if finding.owner != FindingOwner.AUTHOR
                or finding.repairability != FindingRepairability.AUTHOR_PATCH
            )
            if non_author_blocking:
                routes = "; ".join(
                    f"{finding.code} owner={finding.owner.value} "
                    f"repairability={finding.repairability.value}"
                    for finding in non_author_blocking
                )
                raise AuthoringValidationError(
                    "Blocking findings are not repairable by the course author: "
                    + routes
                )

            finding_signatures = tuple(
                self._finding_signature(finding) for finding in blocking
            )
            prior_signatures = {
                signature
                for record in workspace.revision_history
                for signature in record.finding_signatures
            }
            repeated = sorted(set(finding_signatures) & prior_signatures)
            if repeated:
                raise AuthoringPolicyError(
                    "Authoring patch did not resolve repeated blocking findings: "
                    + "; ".join(repeated)
                )

            if revision >= self._policy.max_repair_attempts:
                raise AuthoringPolicyError(
                    "Authoring revision limit reached with blocking findings: "
                    + "; ".join(f.message for f in blocking)
                )
            revision += 1
            failing_ids = tuple(
                dict.fromkeys(
                    f.screen_id for f in blocking if f.screen_id != "__course__"
                )
            )
            if not failing_ids:
                failing_ids = tuple(s.screen_id for s in workspace.draft.authored_screens)
            workspace = workspace.model_copy(update={"state": AuthoringState.REVISING})
            merged_draft = workspace.draft
            revision_batches = tuple(self._batches(failing_ids))
            for revision_batch_number, revision_batch in enumerate(
                revision_batches, start=1
            ):
                batch_started = time.perf_counter()
                log.info(
                    "authoring phase=revision workflow_id=%s task_id=%s revision=%s "
                    "batch=%s/%s screen_ids=%s model_calls=%s/%s",
                    workflow_id,
                    task_id,
                    revision,
                    revision_batch_number,
                    len(revision_batches),
                    list(revision_batch),
                    workspace.model_call_count,
                    self._policy.max_model_calls,
                )
                relevant_findings = tuple(
                    finding
                    for finding in blocking
                    if finding.screen_id in {*revision_batch, "__course__"}
                )
                revision_payload = self._scoped_author_payload(
                    payload=payload,
                    resolved_context=resolved_context,
                    schemas=schemas,
                    intents=intents,
                    screen_ids=revision_batch,
                )
                revision_payload.update(
                    {
                        "existing_draft": merged_draft.model_copy(
                            update={
                                "authored_screens": tuple(
                                    screen
                                    for screen in merged_draft.authored_screens
                                    if screen.screen_id in set(revision_batch)
                                )
                            }
                        ).model_dump(mode="json"),
                        "blocking_findings": [
                            finding.model_dump(mode="json")
                            for finding in relevant_findings
                        ],
                        "revision_contract": {
                            "revise_only_screen_ids": revision_batch,
                            "editable_field_paths": sorted(
                                {
                                    finding.field_path
                                    for finding in relevant_findings
                                    if finding.field_path
                                }
                            ),
                            "protected_fields_immutable": [
                                "screen_id",
                                "screen_type",
                                "source_scene_ids",
                                "navigation",
                                "assessment_source",
                                "layout",
                            ],
                        },
                    }
                )
                response = await self._call_revision(
                    system_prompt, revision_payload, workspace
                )
                self._assert_patch_changed_fields(
                    merged_draft,
                    response.draft,
                    relevant_findings,
                )
                merged_draft = self._merge_revision_screens(
                    merged_draft,
                    response.draft,
                    set(revision_batch),
                )
                workspace = self._record_author_response(workspace, response)
                model = response.model
                log.info(
                    "authoring phase=revision-complete workflow_id=%s task_id=%s "
                    "revision=%s batch=%s/%s elapsed_seconds=%.2f",
                    workflow_id,
                    task_id,
                    revision,
                    revision_batch_number,
                    len(revision_batches),
                    time.perf_counter() - batch_started,
                )
            merged_draft = self._tools.hydrate_assessments(
                brief, merged_draft, resolved_context
            )
            merged_draft = self._tools.hydrate_scenario_navigation(
                brief, merged_draft
            )
            workspace = workspace.model_copy(
                update={
                    "draft": merged_draft,
                    "state": AuthoringState.DRAFTED,
                    "repair_attempt_count": workspace.repair_attempt_count + 1,
                    "revision_history": (
                        *workspace.revision_history,
                        RevisionRecord(
                            revision=revision,
                            revised_screen_ids=failing_ids,
                            resolved_finding_ids=tuple(f.finding_id for f in blocking),
                            finding_signatures=finding_signatures,
                            revised_field_paths=tuple(
                                f"{finding.screen_id}:{finding.field_path}"
                                for finding in blocking
                                if finding.field_path
                                and finding.screen_id != "__course__"
                            ),
                        ),
                    ),
                }
            )
            await self._save_workspace(namespace, workspace, f"draft-r{revision + 1}")
            review_scope = failing_ids

    async def _draft_initial_batches(
        self,
        *,
        namespace: str,
        workspace: AuthoringWorkspace,
        brief: ElearningAuthoringBrief,
        resolved_context: dict[str, Any],
        schemas: dict[str, tuple[str, ...]],
        intents: tuple[Any, ...],
        required_screen_ids: tuple[str, ...],
        system_prompt: str,
        payload: dict[str, Any],
    ) -> tuple[AuthoringWorkspace, str]:
        existing_ids = (
            {screen.screen_id for screen in workspace.draft.authored_screens}
            if workspace.draft is not None
            else set()
        )
        canonical_ids = tuple(self._batches(required_screen_ids))
        pending = tuple(
            _InitialAuthorBatch(
                number=batch_number,
                total=len(canonical_ids),
                screen_ids=tuple(
                    screen_id
                    for screen_id in batch_ids
                    if screen_id not in existing_ids
                ),
            )
            for batch_number, batch_ids in enumerate(canonical_ids, start=1)
            if any(screen_id not in existing_ids for screen_id in batch_ids)
        )
        if not pending:
            return workspace, "cached"

        review_method = getattr(self._client, "review", None)
        self._check_model_budget(
            workspace,
            required_calls=len(pending),
            reserve_after=1 if callable(review_method) else 0,
        )
        parallel = len(pending) > 1 and not self._has_hard_usage_budget()
        mode = "parallel" if parallel else "sequential"
        stage_started = time.perf_counter()

        if parallel:
            outcomes, peak_concurrency = await self._run_parallel_initial_batches(
                batches=pending,
                workspace=workspace,
                resolved_context=resolved_context,
                schemas=schemas,
                intents=intents,
                system_prompt=system_prompt,
                payload=payload,
            )
        else:
            outcomes = ()
            peak_concurrency = 1
            current_workspace = workspace
            last_model = "cached"
            for batch in pending:
                outcome = await self._call_initial_batch(
                    batch=batch,
                    workspace=current_workspace,
                    resolved_context=resolved_context,
                    schemas=schemas,
                    intents=intents,
                    system_prompt=system_prompt,
                    payload=payload,
                    active_concurrency=1,
                    queued_started=time.perf_counter(),
                )
                current_workspace, batch_model, error = await self._apply_initial_outcome(
                    namespace=namespace,
                    workspace=current_workspace,
                    outcome=outcome,
                    brief=brief,
                    resolved_context=resolved_context,
                    required_screen_ids=required_screen_ids,
                )
                if batch_model is not None:
                    last_model = batch_model
                if error is not None:
                    current_workspace = self._record_initial_batch_metrics(
                        current_workspace,
                        mode=mode,
                        peak_concurrency=peak_concurrency,
                        elapsed_seconds=time.perf_counter() - stage_started,
                    )
                    await self._save_workspace(
                        namespace, current_workspace, "draft-batches-failed"
                    )
                    raise error
            current_workspace = self._record_initial_batch_metrics(
                current_workspace,
                mode=mode,
                peak_concurrency=peak_concurrency,
                elapsed_seconds=time.perf_counter() - stage_started,
            )
            await self._save_workspace(
                namespace, current_workspace, "draft-batches-complete"
            )
            return current_workspace, last_model

        first_error: Exception | None = None
        last_model = "cached"
        for outcome in outcomes:
            workspace, batch_model, error = await self._apply_initial_outcome(
                namespace=namespace,
                workspace=workspace,
                outcome=outcome,
                brief=brief,
                resolved_context=resolved_context,
                required_screen_ids=required_screen_ids,
            )
            if batch_model is not None:
                last_model = batch_model
            if first_error is None and error is not None:
                first_error = error

        workspace = self._record_initial_batch_metrics(
            workspace,
            mode=mode,
            peak_concurrency=peak_concurrency,
            elapsed_seconds=time.perf_counter() - stage_started,
        )
        await self._save_workspace(
            namespace,
            workspace,
            "draft-batches-failed" if first_error is not None else "draft-batches-complete",
        )
        if first_error is not None:
            raise first_error
        return workspace, last_model

    async def _run_parallel_initial_batches(
        self,
        *,
        batches: tuple[_InitialAuthorBatch, ...],
        workspace: AuthoringWorkspace,
        resolved_context: dict[str, Any],
        schemas: dict[str, tuple[str, ...]],
        intents: tuple[Any, ...],
        system_prompt: str,
        payload: dict[str, Any],
    ) -> tuple[tuple[_InitialAuthorBatchOutcome, ...], int]:
        semaphore = asyncio.Semaphore(_AUTHORING_BATCH_CONCURRENCY)
        active_concurrency = 0
        peak_concurrency = 0

        async def run_batch(batch: _InitialAuthorBatch):
            nonlocal active_concurrency, peak_concurrency
            queued_started = time.perf_counter()
            async with semaphore:
                active_concurrency += 1
                peak_concurrency = max(peak_concurrency, active_concurrency)
                try:
                    return await self._call_initial_batch(
                        batch=batch,
                        workspace=workspace,
                        resolved_context=resolved_context,
                        schemas=schemas,
                        intents=intents,
                        system_prompt=system_prompt,
                        payload=payload,
                        active_concurrency=active_concurrency,
                        queued_started=queued_started,
                    )
                finally:
                    active_concurrency -= 1

        outcomes = await asyncio.gather(*(run_batch(batch) for batch in batches))
        return tuple(outcomes), peak_concurrency

    async def _call_initial_batch(
        self,
        *,
        batch: _InitialAuthorBatch,
        workspace: AuthoringWorkspace,
        resolved_context: dict[str, Any],
        schemas: dict[str, tuple[str, ...]],
        intents: tuple[Any, ...],
        system_prompt: str,
        payload: dict[str, Any],
        active_concurrency: int,
        queued_started: float,
    ) -> _InitialAuthorBatchOutcome:
        batch_started = time.perf_counter()
        log.info(
            "authoring phase=draft workflow_id=%s task_id=%s batch=%s/%s "
            "screen_ids=%s active_concurrency=%s queue_seconds=%.2f "
            "model_calls=%s/%s",
            workspace.workflow_id,
            workspace.task_id,
            batch.number,
            batch.total,
            list(batch.screen_ids),
            active_concurrency,
            batch_started - queued_started,
            workspace.model_call_count,
            self._policy.max_model_calls,
        )
        author_payload = self._scoped_author_payload(
            payload=payload,
            resolved_context=resolved_context,
            schemas=schemas,
            intents=intents,
            screen_ids=batch.screen_ids,
            batch_number=batch.number,
            batch_count=batch.total,
        )
        try:
            response = await self._call_author(
                system_prompt, author_payload, workspace
            )
        except Exception as exc:
            elapsed = time.perf_counter() - batch_started
            log.warning(
                "authoring phase=draft-failed workflow_id=%s task_id=%s "
                "batch=%s/%s elapsed_seconds=%.2f error=%s",
                workspace.workflow_id,
                workspace.task_id,
                batch.number,
                batch.total,
                elapsed,
                exc,
            )
            return _InitialAuthorBatchOutcome(
                batch=batch,
                response=None,
                error=exc,
                elapsed_seconds=elapsed,
            )
        elapsed = time.perf_counter() - batch_started
        log.info(
            "authoring phase=draft-response workflow_id=%s task_id=%s "
            "batch=%s/%s elapsed_seconds=%.2f",
            workspace.workflow_id,
            workspace.task_id,
            batch.number,
            batch.total,
            elapsed,
        )
        return _InitialAuthorBatchOutcome(
            batch=batch,
            response=response,
            error=None,
            elapsed_seconds=elapsed,
        )

    async def _apply_initial_outcome(
        self,
        *,
        namespace: str,
        workspace: AuthoringWorkspace,
        outcome: _InitialAuthorBatchOutcome,
        brief: ElearningAuthoringBrief,
        resolved_context: dict[str, Any],
        required_screen_ids: tuple[str, ...],
    ) -> tuple[AuthoringWorkspace, str | None, Exception | None]:
        if outcome.error is not None:
            return workspace, None, outcome.error
        assert outcome.response is not None
        workspace = self._accumulate_usage(workspace, outcome.response)
        try:
            self._assert_usage_within_policy(workspace)
            merged_draft = self._merge_new_screens(
                workspace.draft,
                outcome.response.draft,
                outcome.batch.screen_ids,
                required_screen_ids,
            )
            merged_draft = self._tools.hydrate_assessments(
                brief, merged_draft, resolved_context
            )
            merged_draft = self._tools.hydrate_scenario_navigation(
                brief, merged_draft
            )
            workspace = workspace.model_copy(
                update={
                    "draft": merged_draft,
                    "findings": (),
                    "state": AuthoringState.DRAFTED,
                }
            )
            await self._save_workspace(
                namespace, workspace, f"draft-batch-{outcome.batch.number}"
            )
        except Exception as exc:
            await self._save_workspace(
                namespace, workspace, f"draft-batch-{outcome.batch.number}-rejected"
            )
            return workspace, None, exc
        log.info(
            "authoring phase=draft-complete workflow_id=%s task_id=%s "
            "batch=%s/%s screen_ids=%s elapsed_seconds=%.2f",
            workspace.workflow_id,
            workspace.task_id,
            outcome.batch.number,
            outcome.batch.total,
            list(outcome.batch.screen_ids),
            outcome.elapsed_seconds,
        )
        return workspace, outcome.response.model, None

    def _has_hard_usage_budget(self) -> bool:
        return any(
            limit is not None
            for limit in (
                self._policy.max_input_tokens,
                self._policy.max_output_tokens,
                self._policy.max_cost_usd,
            )
        )

    @staticmethod
    def _record_initial_batch_metrics(
        workspace: AuthoringWorkspace,
        *,
        mode: str,
        peak_concurrency: int,
        elapsed_seconds: float,
    ) -> AuthoringWorkspace:
        prior_mode = workspace.initial_batch_mode
        combined_mode = (
            "parallel"
            if "parallel" in {prior_mode, mode}
            else mode if prior_mode == "not_run" else prior_mode
        )
        return workspace.model_copy(
            update={
                "initial_batch_mode": combined_mode,
                "initial_batch_peak_concurrency": max(
                    workspace.initial_batch_peak_concurrency, peak_concurrency
                ),
                "initial_batch_elapsed_seconds": (
                    workspace.initial_batch_elapsed_seconds + elapsed_seconds
                ),
            }
        )

    @staticmethod
    def _batches(screen_ids: tuple[str, ...]):
        for index in range(0, len(screen_ids), _AUTHORING_BATCH_SIZE):
            yield screen_ids[index : index + _AUTHORING_BATCH_SIZE]

    @staticmethod
    def _scoped_author_payload(
        *,
        payload: dict[str, Any],
        resolved_context: dict[str, Any],
        schemas: dict[str, tuple[str, ...]],
        intents: tuple[Any, ...],
        screen_ids: tuple[str, ...],
        batch_number: int | None = None,
        batch_count: int | None = None,
    ) -> dict[str, Any]:
        allowed = set(screen_ids)
        scoped_requirements = [
            requirement
            for requirement in payload.get("authored_screen_requirements", [])
            if requirement.get("screen_id") in allowed
        ]
        source_scene_ids = {
            source_scene_id
            for requirement in scoped_requirements
            for source_scene_id in requirement.get("source_scene_ids", [])
        }
        scoped_context = dict(resolved_context)
        scenes = resolved_context.get("scenes")
        if isinstance(scenes, (list, tuple)):
            scoped_context["scenes"] = [
                scene
                for scene in scenes
                if isinstance(scene, dict)
                and scene.get("scene_id") in source_scene_ids
            ]
        return {
            **payload,
            "resolved_context": scoped_context,
            "authored_screen_requirements": scoped_requirements,
            "screen_schemas": {
                screen_id: fields
                for screen_id, fields in schemas.items()
                if screen_id in allowed
            },
            "screen_intents": [
                intent.model_dump(mode="json")
                for intent in intents
                if intent.screen_id in allowed
            ],
            "batch_contract": {
                "return_exactly_screen_ids": screen_ids,
                "omit_all_other_screens": True,
                "preserve_screen_ids_types_order_and_source_lineage": True,
                "batch_number": batch_number,
                "batch_count": batch_count,
            },
        }

    @staticmethod
    def _merge_new_screens(
        previous: ElearningCourseAuthorDraft | None,
        authored: ElearningCourseAuthorDraft,
        requested_screen_ids: tuple[str, ...],
        required_screen_ids: tuple[str, ...],
    ) -> ElearningCourseAuthorDraft:
        requested = set(requested_screen_ids)
        authored_by_id = {
            screen.screen_id: screen
            for screen in authored.authored_screens
            if screen.screen_id in requested
        }
        missing = requested - set(authored_by_id)
        if missing:
            raise AuthoringValidationError(
                "Authoring batch omitted requested screen IDs: "
                + ", ".join(sorted(missing))
            )

        combined = (
            {screen.screen_id: screen for screen in previous.authored_screens}
            if previous is not None
            else {}
        )
        combined.update(authored_by_id)
        ordered = tuple(
            combined[screen_id]
            for screen_id in required_screen_ids
            if screen_id in combined
        )
        return ElearningCourseAuthorDraft(
            draft_id=authored.draft_id,
            title=previous.title if previous is not None else authored.title,
            authored_screens=ordered,
            generated_asset_requests=(
                previous.generated_asset_requests if previous is not None else ()
            )
            + authored.generated_asset_requests,
        )

    async def _review(
        self,
        *,
        workspace: AuthoringWorkspace,
        brief: ElearningAuthoringBrief,
        resolved_context: dict[str, Any],
        course_dict: dict[str, Any],
        screen_ids: tuple[str, ...] | None = None,
        field_paths_by_screen: dict[str, tuple[str, ...]] | None = None,
    ) -> tuple[tuple[AuthoringFinding, ...], AuthoringWorkspace]:
        assert workspace.draft is not None
        scoped_ids = set(screen_ids or ())
        learner_projection = build_learner_review_projection(
            course_dict,
            brief,
            screen_ids=screen_ids,
            field_paths_by_screen=field_paths_by_screen,
        )
        projected_ids = {screen["screen_id"] for screen in learner_projection}
        source_scene_ids = {
            source_id
            for requirement in brief.screen_requirements
            if requirement.screen_id in projected_ids
            for source_id in requirement.source_scene_ids
        }
        review_context = dict(resolved_context)
        scenes = resolved_context.get("scenes")
        if isinstance(scenes, (list, tuple)):
            review_context["scenes"] = [
                scene
                for scene in scenes
                if isinstance(scene, dict)
                and scene.get("scene_id") in source_scene_ids
            ]
        assignment = brief.model_dump(mode="json")
        assignment["screen_requirements"] = [
            requirement
            for requirement in assignment.get("screen_requirements", [])
            if requirement.get("screen_id") in projected_ids
        ]
        deterministic, workspace = self._use_tool(
            workspace,
            "review_publishability",
            lambda: self._tools.review_publishability(learner_projection),
        )
        review_method = getattr(self._client, "review", None)
        if review_method is None or not learner_projection:
            return deterministic, workspace
        self._check_model_budget(workspace)
        review_started = time.perf_counter()
        log.info(
            "authoring phase=semantic-review workflow_id=%s task_id=%s "
            "screen_count=%s scope=%s model_calls=%s/%s",
            workspace.workflow_id,
            workspace.task_id,
            len(learner_projection),
            "revision" if scoped_ids else "full-course",
            workspace.model_call_count,
            self._policy.max_model_calls,
        )
        response = await review_method(
            system_prompt=load_prompt(_REVIEW_PROMPT_PATH),
            payload={
                "assignment": assignment,
                "resolved_context": review_context,
                "learner_view": learner_projection,
                "deterministic_signals": [f.model_dump(mode="json") for f in deterministic],
            },
            policy=self._policy,
        )
        valid_screen_ids = projected_ids
        editable_fields = {
            str(screen["screen_id"]): set(screen["editable_fields"])
            for screen in learner_projection
        }
        known_requirement_ids = {r.screen_id for r in brief.screen_requirements}
        accepted_findings: list[AuthoringFinding] = []
        for finding in response.result.findings:
            if finding.screen_id in valid_screen_ids:
                if (
                    finding.severity == FindingSeverity.BLOCKING
                    and (
                        finding.owner != FindingOwner.AUTHOR
                        or finding.repairability
                        != FindingRepairability.AUTHOR_PATCH
                    )
                ):
                    raise AuthoringReviewError(
                        "Semantic reviewer returned a blocking finding outside "
                        "the author's repair authority: "
                        f"{finding.code} owner={finding.owner.value} "
                        f"repairability={finding.repairability.value}."
                    )
                if finding.severity == FindingSeverity.BLOCKING:
                    if finding.code not in _SEMANTIC_BLOCKING_CODES:
                        finding = finding.model_copy(
                            update={
                                "severity": FindingSeverity.WARNING,
                                "repairability": FindingRepairability.ADVISORY,
                            }
                        )
                    else:
                        if not finding.evidence:
                            raise AuthoringReviewError(
                                f"Blocking semantic finding {finding.code} lacks evidence."
                            )
                        field_path = finding.field_path or ""
                        field_name = (
                            field_path.removeprefix("content.").split(".", 1)[0]
                        )
                        if field_name not in editable_fields[finding.screen_id]:
                            raise AuthoringReviewError(
                                f"Reviewer cited protected or unknown field_path "
                                f"{field_path!r} for screen {finding.screen_id!r}."
                            )
                accepted_findings.append(finding)
                continue
            if finding.screen_id in known_requirement_ids:
                # Video slots and other deterministic requirements are outside
                # the course-author agent's authority. Their own executors and
                # bundle validation own those findings.
                continue
            raise AuthoringReviewError(
                f"Reviewer cited unknown screen_id {finding.screen_id!r}."
            )
        workspace = self._record_usage(workspace, response)
        log.info(
            "authoring phase=semantic-review-complete workflow_id=%s task_id=%s "
            "reported_findings=%s accepted_findings=%s elapsed_seconds=%.2f",
            workspace.workflow_id,
            workspace.task_id,
            len(response.result.findings),
            len(accepted_findings),
            time.perf_counter() - review_started,
        )
        return tuple(accepted_findings), workspace

    async def _call_author(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        workspace: AuthoringWorkspace,
    ) -> StructuredAuthoringResponse:
        review_method = getattr(self._client, "review", None)
        self._check_model_budget(
            workspace,
            required_calls=1,
            reserve_after=1 if callable(review_method) else 0,
        )
        return await self._client.author(
            system_prompt=system_prompt, payload=payload, policy=self._policy
        )

    async def _call_revision(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        workspace: AuthoringWorkspace,
    ) -> StructuredAuthoringResponse:
        review_method = getattr(self._client, "review", None)
        self._check_model_budget(
            workspace,
            required_calls=1,
            reserve_after=1 if callable(review_method) else 0,
        )
        patch_method = getattr(self._client, "patch", None)
        if callable(patch_method):
            return await patch_method(
                system_prompt=system_prompt,
                payload=payload,
                policy=self._policy,
            )
        # Compatibility for provider-neutral test/custom clients. Production's
        # LiteLLM client implements the exact patch contract above.
        return await self._client.author(
            system_prompt=system_prompt,
            payload=payload,
            policy=self._policy,
        )

    def _check_model_budget(
        self,
        workspace: AuthoringWorkspace,
        *,
        required_calls: int = 1,
        reserve_after: int = 0,
    ) -> None:
        if (
            workspace.model_call_count + required_calls + reserve_after
            > self._policy.max_model_calls
        ):
            raise AuthoringPolicyError("Authoring semantic model-call budget exhausted.")

    def _use_tool(self, workspace, name, operation):
        if workspace.internal_tool_call_count >= self._policy.max_internal_tool_calls:
            raise AuthoringPolicyError(
                f"Authoring internal-tool budget exhausted before {name}."
            )
        try:
            result = operation()
        except AuthoringAgentError:
            raise
        except Exception as exc:
            raise AuthoringToolError(f"Authoring tool {name!r} failed: {exc}") from exc
        return result, workspace.model_copy(
            update={"internal_tool_call_count": workspace.internal_tool_call_count + 1}
        )

    def _record_author_response(
        self, workspace: AuthoringWorkspace, response: StructuredAuthoringResponse
    ) -> AuthoringWorkspace:
        return self._record_usage(workspace, response)

    def _record_usage(self, workspace: AuthoringWorkspace, response: Any) -> AuthoringWorkspace:
        updated = self._accumulate_usage(workspace, response)
        self._assert_usage_within_policy(updated)
        return updated

    @staticmethod
    def _accumulate_usage(
        workspace: AuthoringWorkspace, response: Any
    ) -> AuthoringWorkspace:
        def add_optional(current, value):
            return current if value is None else (current or 0) + value

        calls = int(getattr(response, "model_call_count", 1))
        cost = add_optional(workspace.estimated_cost_usd, response.estimated_cost_usd)
        input_tokens = add_optional(workspace.input_tokens, response.input_tokens)
        output_tokens = add_optional(workspace.output_tokens, response.output_tokens)
        return workspace.model_copy(
            update={
                "model_call_count": workspace.model_call_count + calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": cost,
            }
        )

    def _assert_usage_within_policy(self, workspace: AuthoringWorkspace) -> None:
        if workspace.model_call_count > self._policy.max_model_calls:
            raise AuthoringPolicyError("Authoring semantic model-call budget exceeded.")
        if (
            self._policy.max_input_tokens is not None
            and workspace.input_tokens is not None
            and workspace.input_tokens > self._policy.max_input_tokens
        ):
            raise AuthoringPolicyError("Authoring cumulative input-token budget exceeded.")
        if (
            self._policy.max_output_tokens is not None
            and workspace.output_tokens is not None
            and workspace.output_tokens > self._policy.max_output_tokens
        ):
            raise AuthoringPolicyError("Authoring cumulative output-token budget exceeded.")
        if (
            self._policy.max_cost_usd is not None
            and workspace.estimated_cost_usd is not None
            and workspace.estimated_cost_usd > self._policy.max_cost_usd
        ):
            raise AuthoringPolicyError("Authoring cumulative cost budget exceeded.")

    @staticmethod
    def _merge_findings(
        existing: tuple[AuthoringFinding, ...],
        additions: tuple[AuthoringFinding, ...],
    ) -> tuple[AuthoringFinding, ...]:
        by_id = {finding.finding_id: finding for finding in existing}
        by_id.update({finding.finding_id: finding for finding in additions})
        return tuple(by_id.values())

    @staticmethod
    def _finding_signature(finding: AuthoringFinding) -> str:
        # A single field can contain multiple independent defects.
        return (
            f"{finding.code}:{finding.screen_id}:{finding.field_path or ''}:"
            f"{finding.finding_id}"
        )

    @staticmethod
    def _assert_patch_changed_fields(
        previous: ElearningCourseAuthorDraft,
        revised: ElearningCourseAuthorDraft,
        findings: tuple[AuthoringFinding, ...],
    ) -> None:
        previous_by_id = {screen.screen_id: screen for screen in previous.authored_screens}
        revised_by_id = {screen.screen_id: screen for screen in revised.authored_screens}
        unchanged: list[str] = []
        for finding in findings:
            if finding.screen_id == "__course__" or not finding.field_path:
                continue
            field_name = finding.field_path.removeprefix("content.").split(".", 1)[0]
            before = previous_by_id.get(finding.screen_id)
            after = revised_by_id.get(finding.screen_id)
            if before is None or after is None:
                continue
            if getattr(before.content, field_name, None) == getattr(
                after.content, field_name, None
            ):
                unchanged.append(f"{finding.screen_id}:{finding.field_path}")
        if unchanged:
            raise AuthoringValidationError(
                "Authoring patch made no change to required fields: "
                + "; ".join(sorted(set(unchanged)))
            )

    @staticmethod
    def _merge_revision_screens(
        previous: ElearningCourseAuthorDraft,
        revised: ElearningCourseAuthorDraft,
        allowed_screen_ids: set[str],
    ) -> ElearningCourseAuthorDraft:
        """Merge a partial revision without granting structural authority.

        Revision responses may contain only the screens named in the revision
        contract, or may echo the complete draft in a different order. The
        checkpointed draft remains authoritative for screen membership, order,
        approved screens, course title, and asset requests.
        """
        previous_by_id = {s.screen_id: s for s in previous.authored_screens}
        revised_by_id = {s.screen_id: s for s in revised.authored_screens}

        unknown_ids = set(revised_by_id) - set(previous_by_id)
        if unknown_ids:
            raise AuthoringValidationError(
                "Revision introduced unknown screen IDs: "
                + ", ".join(sorted(unknown_ids))
            )

        missing_ids = allowed_screen_ids - set(revised_by_id)
        if missing_ids:
            raise AuthoringValidationError(
                "Revision omitted requested screen IDs: "
                + ", ".join(sorted(missing_ids))
            )

        merged_screens = tuple(
            revised_by_id[screen.screen_id]
            if screen.screen_id in allowed_screen_ids
            else screen
            for screen in previous.authored_screens
        )
        return previous.model_copy(
            update={
                "draft_id": revised.draft_id,
                "authored_screens": merged_screens,
            }
        )

    @staticmethod
    def _reconcile_review_findings(
        draft: ElearningCourseAuthorDraft,
        findings: tuple[AuthoringFinding, ...],
    ) -> tuple[AuthoringFinding, ...]:
        """Reconcile saved review findings after deterministic capability upgrades."""
        screens = {screen.screen_id: screen for screen in draft.authored_screens}
        reconciled: list[AuthoringFinding] = []
        for finding in findings:
            screen = screens.get(finding.screen_id)
            if finding.category.startswith("missing-required-assessment"):
                # Assessment hydration now guarantees complete, ordered source
                # groups; deterministic fidelity validation verifies this next.
                continue
            if finding.category == "screen-purpose":
                reconciled.append(
                    finding.model_copy(update={"severity": FindingSeverity.WARNING})
                )
                continue
            reconciled.append(finding)
        return tuple(reconciled)

    async def _load_workspace(
        self,
        namespace: str,
        deliverable_id: str,
        input_hash: str,
        *,
        prompt_version: str,
        required_screen_ids: tuple[str, ...],
    ) -> tuple[AuthoringWorkspace | None, str]:
        uri = f"artifact://{namespace}/{deliverable_id}-workspace-{input_hash[:16]}.json"
        try:
            raw = await self._store.get_bytes(uri)
        except ArtifactNotFoundError:
            return None, "missing"
        except Exception as exc:
            raise AuthoringInfrastructureError(
                f"Cannot read authoring checkpoint {uri!r}: {exc}"
            ) from exc
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, UnicodeDecodeError):
            return None, "corrupt-checkpoint-ignored"
        if not isinstance(data, dict):
            return None, "corrupt-checkpoint-ignored"
        compatibility = {
            "workspace_version": WORKSPACE_VERSION,
            "input_hash": input_hash,
            "prompt_version": prompt_version,
            "content_charter_version": CONTENT_CHARTER_VERSION,
            "review_rubric_version": REVIEW_RUBRIC_VERSION,
            "required_screen_ids": list(required_screen_ids),
        }
        if any(data.get(key) != expected for key, expected in compatibility.items()):
            return None, "incompatible-checkpoint-ignored"
        try:
            return AuthoringWorkspace.model_validate(data), "compatible-checkpoint-reused"
        except Exception:
            return None, "corrupt-checkpoint-ignored"

    async def _save_workspace(
        self, namespace: str, workspace: AuthoringWorkspace, stage: str
    ) -> None:
        data = workspace.model_dump_json(indent=2).encode("utf-8")
        try:
            await self._store.put_bytes(
                namespace=namespace,
                name=f"{workspace.deliverable_id}-{stage}-{workspace.input_hash[:16]}.json",
                data=data,
                media_type="application/json",
            )
            await self._store.put_bytes(
                namespace=namespace,
                name=f"{workspace.deliverable_id}-workspace-{workspace.input_hash[:16]}.json",
                data=data,
                media_type="application/json",
            )
        except Exception as exc:
            raise AuthoringInfrastructureError(
                f"Cannot persist authoring checkpoint {stage!r}: {exc}"
            ) from exc
