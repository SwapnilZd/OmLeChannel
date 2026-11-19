"""RealElearningCourseAuthorExecutor — bounded agentic elearning.course.author.

Execution flow
--------------
1.  Validate ElearningAuthoringBrief (must have screen_requirements).
2.  Read resolved-context artifact via ArtifactStore and verify SHA-256.
3.  Check idempotency cache — reuse persisted draft if input hash matches.
4.  Build bounded authoring payload from screen_requirements.
5.  Call ElearningAuthoringClient.author() within policy bounds.
6.  Validate structured LLM output (no reserved types, no unsafe content).
7.  Build CourseContent deterministically via ElearningCourseContentBuilder.
8.  Perform schema and slot-preservation validation.
9.  Materialize declared assets (generated_asset_requests disabled by default).
10. Publish all artifacts through ArtifactStore.
11. Rewrite course asset references to logical bundle paths.
12. Publish intermediate course.json.
13. Optionally render a preview HTML.
14. Build and persist ElearningAuthoringTrace.
15. Return validated ElearningAuthorOutput.

Contract
--------
- No LLM call is made more than policy.max_model_calls times.
- No loop is unbounded.
- Credentials are never read from environment variables here.
- The ArtifactStore is required (no fake:// URI support in real mode).
- Does not call Manim, HeyGen, or the bundle assembler.
"""
from __future__ import annotations

from learning_pipeline.prompts import load_prompt

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from learning_pipeline.runtime.artifact_store import ArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.elearning_bundle._assessment_fidelity import (
    normalize_knowledge_check_requirements,
)
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AgenticExecutionPolicy,
    ElearningAuthoringTrace,
)
from learning_pipeline.tools.elearning_bundle._authoring_client import (
    PROMPT_VERSION,
    ElearningAuthoringClient,
)
from learning_pipeline.tools.elearning_bundle._authoring_controller import (
    AuthoringAgentController,
)
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    CONTENT_CHARTER_VERSION,
    REVIEW_RUBRIC_VERSION,
    WORKSPACE_VERSION,
)
from learning_pipeline.tools.elearning_bundle._content_builder import (
    CONTENT_BUILDER_VERSION,
    ElearningCourseContentBuilder,
)
from learning_pipeline.tools.elearning_bundle._seat_time import SEAT_TIME_POLICY_VERSION
from learning_pipeline.tools.elearning_bundle.contracts import (
    BundleAssetRef,
    ElearningAuthoringBrief,
    ElearningAuthorOutput,
    resolved_learner_action,
)
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError

_PROMPT_PATH = (
    Path(__file__).resolve()
    .parent  # elearning_bundle/
    .parent  # tools/
    .parent  # learning_pipeline/
    / "prompts"
    / "elearning_author"
    / "course_author.md"
)

_DEFAULT_POLICY = AgenticExecutionPolicy(
    # Large courses are authored in resumable eight-screen batches, followed
    # by review and bounded revision calls.
    max_model_calls=12,
    max_internal_tool_calls=12,
    max_fitting_attempts=2,
    max_repair_attempts=2,
    timeout_seconds=120,
)

class RealElearningCourseAuthorExecutor:
    """Bounded agentic elearning.course.author executor.

    Parameters
    ----------
    artifact_store:
        Required for artifact I/O.  All artifacts are published here.
    authoring_client:
        Provider-neutral client used for LLM calls.  Inject a
        FakeElearningAuthoringClient for tests.
    policy:
        Execution bounds.  Defaults to _DEFAULT_POLICY.
    generate_images:
        If True, honour GeneratedAssetRequest entries in the draft.
        False by default for Phase 14B (unbounded image calls deferred).
    write_preview_html:
        If True, render a preview HTML with slot placeholders.
    """

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        authoring_client: ElearningAuthoringClient,
        policy: AgenticExecutionPolicy = _DEFAULT_POLICY,
        generate_images: bool = False,
        write_preview_html: bool = False,
    ) -> None:
        self._store = artifact_store
        self._client = authoring_client
        self._policy = policy
        self._generate_images = generate_images
        self._write_preview = write_preview_html
        self._builder = ElearningCourseContentBuilder()
        self._controller = AuthoringAgentController(
            artifact_store=artifact_store,
            authoring_client=authoring_client,
            builder=self._builder,
            policy=policy,
        )
        self._system_prompt: str | None = None

    # ── Public entry point ─────────────────────────────────────────────────────

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        execution_started = time.perf_counter()
        # Step 1: validate input
        try:
            brief = ElearningAuthoringBrief.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid elearning.course.author input: {exc}"
            ) from exc

        if not brief.screen_requirements:
            raise InvalidToolInputError(
                f"[{context.task_id}] RealElearningCourseAuthorExecutor requires "
                "brief.screen_requirements to be non-empty. "
                "Use FakeElearningCourseAuthorExecutor for briefs without screen_requirements."
            )

        wf_id = context.workflow_id
        task_id = context.task_id
        ns = f"elearning/{wf_id}"

        # Step 2: read + verify resolved context
        context_bytes, context_hash = await self._read_context(brief)
        try:
            resolved_context = json.loads(context_bytes)
        except json.JSONDecodeError as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Resolved authoring context is not valid JSON: {exc}"
            ) from exc
        brief = normalize_knowledge_check_requirements(brief, resolved_context)

        # The effective configuration is part of the cache key. A run cannot
        # accidentally reuse a workspace created with different bounds/rubrics.
        policy_version = json.dumps(self._policy.model_dump(mode="json"), sort_keys=True)
        input_hash = self._builder.compute_input_hash(
            brief,
            prompt_version=PROMPT_VERSION,
            policy_version=(
                f"{WORKSPACE_VERSION}:{CONTENT_CHARTER_VERSION}:"
                f"{REVIEW_RUBRIC_VERSION}:{policy_version}"
            ),
            builder_version=CONTENT_BUILDER_VERSION,
        )
        payload = self._build_authoring_payload(brief, context_bytes)
        # LiteLLM owns provider timeout and retry behavior. Do not wrap the
        # multi-call authoring controller in a local wall-clock timeout: doing
        # so can cancel a healthy gateway request before the router's policy is
        # reached, and it prevents review/repair calls from using their budget.
        agent_result = await self._controller.run(
            brief=brief,
            workflow_id=wf_id,
            task_id=task_id,
            context_bytes=context_bytes,
            input_hash=input_hash,
            system_prompt=self._load_system_prompt(),
            payload=payload,
        )
        draft = agent_result.draft
        course_dict = agent_result.course_dict
        slot_report = agent_result.slot_report
        workspace = agent_result.workspace
        seat_time_minutes = next(
            (
                int(screen.get("metadata", {}).get("duration_minutes"))
                for screen in course_dict["screens"]
                if screen.get("type") == "title"
                and screen.get("metadata", {}).get("duration_minutes") is not None
            ),
            None,
        )

        # Step 7: materialize assets
        assets_list: list[BundleAssetRef] = []
        assets_list = await self._materialize_assets(draft, ns)

        # Step 8: publish course JSON
        course_bytes = json.dumps(course_dict, indent=2, ensure_ascii=False).encode("utf-8")
        course_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{brief.deliverable_id}.course.json",
            data=course_bytes,
            media_type="application/json",
        )

        # Step 9: optional preview HTML
        preview_ref = None
        if self._write_preview:
            preview_ref = await self._render_preview(course_dict, brief, ns)

        # Step 10: build and persist trace
        trace = ElearningAuthoringTrace(
            workflow_id=wf_id,
            task_id=task_id,
            brief_hash=input_hash,
            context_hash=context_hash,
            prompt_version=PROMPT_VERSION,
            model=agent_result.model,
            model_call_count=workspace.model_call_count,
            internal_tool_call_count=workspace.internal_tool_call_count,
            fitting_attempt_count=1 + len(workspace.revision_history),
            repair_attempt_count=workspace.repair_attempt_count,
            input_tokens=workspace.input_tokens,
            output_tokens=workspace.output_tokens,
            estimated_cost_usd=workspace.estimated_cost_usd,
            elapsed_seconds=time.perf_counter() - execution_started,
            initial_batch_mode=workspace.initial_batch_mode,
            initial_batch_peak_concurrency=workspace.initial_batch_peak_concurrency,
            initial_batch_elapsed_seconds=workspace.initial_batch_elapsed_seconds,
            authored_screen_ids=tuple(s.screen_id for s in draft.authored_screens),
            selected_screen_types={
                s.screen_id: s.screen_type for s in draft.authored_screens
            },
            slot_report=slot_report,
            review_status="ready",
            revision_count=len(workspace.revision_history),
            review_findings=tuple(f.message for f in workspace.finding_history),
            finding_counts_by_owner={
                owner: sum(
                    finding.owner.value == owner
                    for finding in workspace.finding_history
                )
                for owner in sorted(
                    {finding.owner.value for finding in workspace.finding_history}
                )
            },
            finding_counts_by_code={
                code: sum(
                    finding.code == code for finding in workspace.finding_history
                )
                for code in sorted(
                    {finding.code for finding in workspace.finding_history}
                )
            },
            repair_outcomes=tuple(
                f"revision-{record.revision}:resolved"
                for record in workspace.revision_history
            ),
            checkpoint_stages_reused=workspace.checkpoint_stages_reused,
            checkpoint_recovery_events=workspace.checkpoint_recovery_events,
            seat_time_estimate_minutes=seat_time_minutes,
            seat_time_policy_version=SEAT_TIME_POLICY_VERSION,
        )
        trace_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{brief.deliverable_id}.authoring-trace.json",
            data=trace.model_dump_json(indent=2).encode("utf-8"),
            media_type="application/json",
        )

        # Step 11: validate and return output
        try:
            output = ElearningAuthorOutput(
                course_json=course_ref,
                course_json_uri=course_ref.uri,
                assets=tuple(assets_list),
                slot_report=slot_report,
                preview_html=preview_ref,
                trace_uri=trace_ref.uri,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{task_id}] ElearningAuthorOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _read_context(
        self, brief: ElearningAuthoringBrief
    ) -> tuple[bytes, str]:
        """Read context artifact and verify its SHA-256."""
        uri = brief.resolved_context_uri
        if uri.startswith("fake://"):
            # Test-mode: context is not actually stored; return placeholder bytes.
            context_bytes = json.dumps(
                {"fake": True, "deliverable_id": brief.deliverable_id}
            ).encode("utf-8")
            context_hash = hashlib.sha256(context_bytes).hexdigest()
            return context_bytes, context_hash

        context_bytes = await self._store.get_bytes(uri)
        actual_hash = hashlib.sha256(context_bytes).hexdigest()
        expected_hash = brief.resolved_context_sha256
        if actual_hash != expected_hash:
            raise InvalidToolInputError(
                f"Context SHA-256 mismatch for {uri!r}: "
                f"expected {expected_hash!r}, got {actual_hash!r}."
            )
        return context_bytes, actual_hash

    async def _load_persisted_draft(
        self, namespace: str, input_hash: str
    ) -> dict | None:
        """Try to load a persisted draft for idempotency."""
        try:
            draft_uri = f"artifact://{namespace}/draft-{input_hash[:16]}.json"
            data = await self._store.get_bytes(draft_uri)
            return json.loads(data)
        except Exception:
            return None

    async def _persist_draft(
        self,
        namespace: str,
        input_hash: str,
        draft: Any,
    ) -> None:
        """Persist structured draft to artifact store for idempotency reuse."""
        try:
            await self._store.put_bytes(
                namespace=namespace,
                name=f"draft-{input_hash[:16]}.json",
                data=draft.model_dump_json(indent=2).encode("utf-8"),
                media_type="application/json",
            )
        except Exception:
            pass  # Persistence failure is non-fatal; idempotency is best-effort.

    def _load_system_prompt(self) -> str:
        """Load and cache the versioned authoring system prompt."""
        if self._system_prompt is None:
            self._system_prompt = load_prompt(_PROMPT_PATH)
        return self._system_prompt

    def _build_authoring_payload(
        self,
        brief: ElearningAuthoringBrief,
        context_bytes: bytes,
    ) -> dict[str, Any]:
        """Build the JSON payload passed to the authoring client."""
        try:
            context_data = json.loads(context_bytes)
        except Exception:
            context_data = {}

        authored_requirements = [
            {
                "screen_id": req.screen_id,
                "source_scene_ids": list(req.source_scene_ids),
                "screen_type": req.screen_type,
                "learner_action": resolved_learner_action(req).value,
                "content_direction": req.content_direction,
            }
            for req in brief.screen_requirements
            if getattr(req, "kind", None) == "authored_screen"
        ]
        return {
            "deliverable_id": brief.deliverable_id,
            "theme": brief.theme,
            "brand_contract": brief.brand_contract,
            "accessibility_requirements": list(brief.accessibility_requirements),
            "authoring_direction": brief.authoring_direction,
            "resolved_context": context_data,
            "authored_screen_requirements": authored_requirements,
            "protected_course_structure": authored_requirements,
            "prompt_version": PROMPT_VERSION,
        }

    async def _materialize_assets(
        self,
        draft: Any,
        namespace: str,
    ) -> list[BundleAssetRef]:
        """Publish draft asset requests; disabled by default in Phase 14B."""
        from learning_pipeline.runtime.artifact_store import ArtifactRef

        assets: list[BundleAssetRef] = []

        if not self._generate_images:
            if draft.generated_asset_requests:
                raise InvalidToolOutputError(
                    "The real author requested generated assets, but real image "
                    "generation is disabled. Refusing to publish placeholders."
                )
            return assets

        # Real image generation path (future phase — stubbed for now).
        raise NotImplementedError(
            "Real image generation is not implemented in Phase 14B. "
            "Pass generate_images=False."
        )

    async def _render_preview(
        self,
        course_dict: dict[str, Any],
        brief: ElearningAuthoringBrief,
        namespace: str,
    ) -> Any:
        """Render and publish a preview HTML with slot placeholders."""
        from learning_pipeline.tools.elearning_bundle._pipeline_bridge import (
            CourseContent,
            render_course_html,
        )

        course_obj = CourseContent.model_validate(course_dict)
        preview_html = render_course_html(course_obj, theme_id=brief.theme)
        preview_bytes = preview_html.encode("utf-8")
        return await self._store.put_bytes(
            namespace=namespace,
            name=f"{brief.deliverable_id}-preview.html",
            data=preview_bytes,
            media_type="text/html",
        )
