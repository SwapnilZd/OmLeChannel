"""Canonical ManimGenerationController — the bounded agentic state machine.

Execution flow
--------------
 1. Validate AnimationBrief (done by caller before invoking run()).
 2. Check for a completed idempotent result — return it immediately if found.
 3. Load and hash the frozen context artifact.
 4. Load or generate the scene draft (LLM call 1).
 5. Resolve template source or use generated source (with TTS injected inline).
 6. Validate source via SourcePolicyValidator.
 7. Render in isolated container with TTS credentials (bounded by ManimRenderPolicy).
 8. Validate produced media (MP4 header, captions VTT).
 9. Publish all artifacts via ArtifactStore.
10. Save completed checkpoint.
11. Return ManimVideoOutput.

Retry ownership
---------------
- Infrastructure failures → retry same source, no LLM call.
- Source errors → bounded LLM repair, then re-render.
- Narration failures → propagated to caller (TTS retry is provider-level).

Checkpointing
-------------
Every durable stage result is persisted to the ArtifactStore.  On workflow
retry, the controller resumes from the latest valid checkpoint.

Isolation
---------
Generated Python source is NEVER executed in this process.
All rendering happens via the injected ManimRenderRunner.
"""
from __future__ import annotations

from learning_pipeline.prompts import load_prompt

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from learning_pipeline.runtime.artifact_store import ArtifactRef, ArtifactStore
from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.elearning_bundle.contracts import (
    AnimationBrief,
    ManimVideoOutput,
)
from learning_pipeline.tools.manim_video._contracts import (
    ManimBindingValidationError,
    ManimError,
    ManimInfrastructureError,
    ManimMediaValidationError,
    ManimPolicyError,
    ManimRenderError,
    ManimRenderPolicy,
    ManimRenderRequest,
    ManimRepairBudgetError,
    ManimSceneDraft,
    ManimSourcePolicyError,
    ManimTrace,
)
from learning_pipeline.tools.manim_video._manim_client import (
    ManimLLMClient,
    ManimSceneDraftResponse,
    PROMPT_VERSION,
)
from learning_pipeline.tools.manim_video._render_runner import ManimRenderRunner
from learning_pipeline.tools.manim_video._source_policy import SourcePolicyValidator
from learning_pipeline.tools.manim_video._template_catalog import ManimTemplateCatalog

logger = logging.getLogger(__name__)

_PROMPT_PATH = (
    Path(__file__).resolve()
    .parent   # manim_video/
    .parent   # tools/
    .parent   # learning_pipeline/
    / "prompts"
    / "manim_render"
    / "scene_draft.md"
)

_QUALITY_MAP: dict[str, str] = {
    "low": "low_quality",
    "standard": "medium_quality",
    "high": "high_quality",
    "production": "production_quality",
}

_DEFAULT_AGENT_POLICY = AgenticExecutionPolicy(
    max_model_calls=3,
    max_repair_attempts=2,
    timeout_seconds=120,
)

_DEFAULT_RENDER_POLICY = ManimRenderPolicy(
    max_render_attempts=3,
    render_timeout_seconds=300,
    duration_tolerance_seconds=10.0,
)


class ManimGenerationController:
    """Bounded agentic controller for video.manim.render.

    All dependencies are injected at construction time, enabling complete
    replacement of the LLM client, render runner, narration service, and
    template catalog in tests.

    Parameters
    ----------
    artifact_store:
        Persists checkpoints and final artifacts.
    llm_client:
        Provider-neutral LLM client for scene drafting.
    render_runner:
        Isolated render execution boundary.
    template_catalog:
        Searchable typed catalog of available Manim templates.
    source_validator:
        Static safety checker for generated Python source.
    narration_service:
        Optional TTS service for pre-synthesizing narration.
        When None, no narration is generated regardless of AnimationBrief.
    policy:
        Bounds on LLM calls, cost, timeout.
    render_policy:
        Bounds on render attempts and per-render timeout.
    """

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        llm_client: ManimLLMClient,
        render_runner: ManimRenderRunner,
        template_catalog: ManimTemplateCatalog | None = None,
        source_validator: SourcePolicyValidator | None = None,
        tts_import: str = "",
        tts_service_call: str = "",
        policy: AgenticExecutionPolicy = _DEFAULT_AGENT_POLICY,
        render_policy: ManimRenderPolicy = _DEFAULT_RENDER_POLICY,
    ) -> None:
        self._store = artifact_store
        self._client = llm_client
        self._runner = render_runner
        self._catalog = template_catalog or ManimTemplateCatalog()
        self._source_validator = source_validator or SourcePolicyValidator()
        self._tts_import = tts_import
        self._tts_service_call = tts_service_call
        self._policy = policy
        self._render_policy = render_policy
        self._system_prompt: str | None = None

    # ── Public entry point ─────────────────────────────────────────────────────

    async def run(
        self,
        brief: AnimationBrief,
        *,
        workflow_id: str,
        task_id: str,
        context_bytes: bytes,
        context_hash: str,
    ) -> ManimVideoOutput:
        """Execute the full state machine and return a validated ManimVideoOutput.

        Parameters
        ----------
        brief:
            Validated AnimationBrief — caller is responsible for validation.
        workflow_id / task_id:
            Used for namespacing artifacts and trace metadata.
        context_bytes / context_hash:
            The resolved context artifact content and its SHA-256.
        """
        ns = f"manim/{workflow_id}"
        animation_id = brief.animation_id

        idempotency_key = self._compute_idempotency_key(brief, context_hash)

        # ── Step 1: check completed idempotent result ──────────────────────────
        completed_data = await self._load_checkpoint(ns, animation_id, idempotency_key, "completed")
        if completed_data:
            return ManimVideoOutput.model_validate(completed_data)

        # ── Tracking state ─────────────────────────────────────────────────────
        model_call_count = 0
        repair_attempt_count = 0
        render_attempt_count = 0
        checkpoint_stages_reused: list[str] = []
        # Accumulated token/cost totals across all LLM calls (draft + repairs).
        total_input_tokens: int | None = None
        total_output_tokens: int | None = None
        total_cost_usd: float | None = None

        # ── Step 2: load or generate scene draft ───────────────────────────────
        draft_data = await self._load_checkpoint(ns, animation_id, idempotency_key, "draft")
        if draft_data:
            draft = ManimSceneDraft.model_validate(draft_data)
            checkpoint_stages_reused.append("draft")
        else:
            if model_call_count >= self._policy.max_model_calls:
                raise ManimPolicyError("Model call limit reached before scene draft could be generated.")
            logger.info(
                "manim phase=draft workflow_id=%s task_id=%s animation_id=%s",
                workflow_id,
                task_id,
                animation_id,
            )
            system_prompt = self._load_system_prompt()
            payload = self._build_draft_payload(brief, context_bytes)
            init_response = await self._client.draft_scene(
                system_prompt=system_prompt,
                payload=payload,
                policy=self._policy,
            )
            draft = init_response.draft
            model_call_count += init_response.model_call_count
            self._check_cost(init_response)
            if init_response.input_tokens is not None:
                total_input_tokens = (total_input_tokens or 0) + init_response.input_tokens
            if init_response.output_tokens is not None:
                total_output_tokens = (total_output_tokens or 0) + init_response.output_tokens
            if init_response.estimated_cost_usd is not None:
                total_cost_usd = (total_cost_usd or 0.0) + init_response.estimated_cost_usd
            await self._save_checkpoint(
                ns, animation_id, idempotency_key, "draft", draft.model_dump()
            )
            logger.info(
                "manim phase=draft-complete workflow_id=%s task_id=%s "
                "animation_id=%s template_id=%s",
                workflow_id,
                task_id,
                animation_id,
                draft.template_id,
            )

        # final_draft tracks whichever draft ultimately produced the rendered source.
        final_draft = draft

        # ── Step 3: resolve template source or generated source ────────────────
        source_data = await self._load_checkpoint(ns, animation_id, idempotency_key, "source")
        if source_data:
            source_code: str = source_data["source_code"]
            checkpoint_stages_reused.append("source")
        else:
            # Binding-validation failures (e.g. narration word budgets) are
            # draft defects — repair the draft within the same bounded budget
            # the render loop uses, instead of failing the task outright.
            while True:
                try:
                    source_code = self._resolve_source(draft, brief)
                    break
                except ManimBindingValidationError as exc:
                    if repair_attempt_count >= self._policy.max_repair_attempts:
                        raise ManimRepairBudgetError(
                            f"Repair budget exhausted after {repair_attempt_count} "
                            f"attempt(s). Last error: {exc}"
                        ) from exc
                    if model_call_count >= self._policy.max_model_calls:
                        raise ManimPolicyError(
                            "Model call limit reached during draft repair."
                        ) from exc
                    system_prompt = self._load_system_prompt()
                    repair_payload = self._build_repair_payload(
                        brief,
                        context_bytes,
                        draft.model_dump_json(),
                        str(exc),
                        repair_attempt_number=repair_attempt_count + 1,
                    )
                    repair_response = await self._client.draft_scene(
                        system_prompt=system_prompt,
                        payload=repair_payload,
                        policy=self._policy,
                    )
                    draft = repair_response.draft
                    model_call_count += repair_response.model_call_count
                    repair_attempt_count += 1
                    self._check_cost(repair_response)
                    if repair_response.input_tokens is not None:
                        total_input_tokens = (total_input_tokens or 0) + repair_response.input_tokens
                    if repair_response.output_tokens is not None:
                        total_output_tokens = (total_output_tokens or 0) + repair_response.output_tokens
                    if repair_response.estimated_cost_usd is not None:
                        total_cost_usd = (total_cost_usd or 0.0) + repair_response.estimated_cost_usd
                    final_draft = draft
            self._source_validator.validate(source_code)
            await self._save_checkpoint(
                ns, animation_id, idempotency_key, "source", {"source_code": source_code}
            )

        # ── Step 4: render in isolated container (bounded retries) ───────────
        source_for_render = source_code
        video_bytes: bytes | None = None
        captions_bytes: bytes | None = None
        log_bytes: bytes = b""
        duration_seconds: float | None = None

        for render_attempt in range(1, self._render_policy.max_render_attempts + 1):
            render_attempt_count = render_attempt
            logger.info(
                "manim phase=render workflow_id=%s task_id=%s animation_id=%s "
                "attempt=%s/%s",
                workflow_id,
                task_id,
                animation_id,
                render_attempt,
                self._render_policy.max_render_attempts,
            )

            render_request = ManimRenderRequest(
                job_id=f"{animation_id}-r{render_attempt}",
                idempotency_key=idempotency_key,
                scene_class=_scene_class_name(animation_id),
                source_code=source_for_render,
                quality=_QUALITY_MAP.get(brief.quality_profile, "medium_quality"),
                expected_duration_seconds=(
                    float(brief.target_duration_seconds) if brief.target_duration_seconds else None
                ),
                workflow_id=workflow_id,
                task_id=task_id,
            )

            render_result = await self._runner.render(render_request)
            log_bytes = render_result.log_bytes

            if render_result.status == "success" and render_result.has_audio is True:
                video_bytes = render_result.video_bytes
                captions_bytes = render_result.captions_bytes
                duration_seconds = render_result.duration_seconds
                logger.info(
                    "manim phase=render-complete workflow_id=%s task_id=%s "
                    "animation_id=%s attempt=%s/%s duration_seconds=%s",
                    workflow_id,
                    task_id,
                    animation_id,
                    render_attempt,
                    self._render_policy.max_render_attempts,
                    duration_seconds,
                )
                break

            # ── Failure classification ─────────────────────────────────────────
            if render_result.status == "success":
                category = "render_error"
                failure_message = (
                    "Rendered Manim explainer contains no verified audio stream. "
                    "Use VoiceoverScene and synchronize animations with self.voiceover()."
                )
            else:
                category = render_result.failure_category or "render_error"
                failure_message = render_result.failure_message or "Render failed."
            logger.warning(
                "manim phase=render-failed workflow_id=%s task_id=%s animation_id=%s "
                "attempt=%s/%s category=%s message=%s",
                workflow_id,
                task_id,
                animation_id,
                render_attempt,
                self._render_policy.max_render_attempts,
                category,
                failure_message.splitlines()[0],
            )
            await self._save_checkpoint(
                ns,
                animation_id,
                idempotency_key,
                f"failure-{render_attempt}",
                {
                    "render_attempt": render_attempt,
                    "repair_attempts_used": repair_attempt_count,
                    "category": category,
                    "failure_message": failure_message,
                    "source_code": source_for_render,
                },
            )

            if category == "infrastructure_error":
                # Infrastructure failure: retry same source without LLM call.
                if render_attempt >= self._render_policy.max_render_attempts:
                    docker_log = log_bytes.decode(errors="replace").strip()
                    detail = f"\nDocker output:\n{docker_log}" if docker_log else ""
                    raise ManimInfrastructureError(
                        (render_result.failure_message or "Render infrastructure failed.") + detail
                    )
                continue

            # Source or render error: bounded LLM repair.
            if repair_attempt_count >= self._policy.max_repair_attempts:
                raise ManimRepairBudgetError(
                    f"Repair budget exhausted after {repair_attempt_count} "
                    f"attempt(s). Last error: {failure_message}"
                )
            if model_call_count >= self._policy.max_model_calls:
                raise ManimPolicyError("Model call limit reached during render repair.")

            system_prompt = self._load_system_prompt()
            repair_payload = self._build_repair_payload(
                brief,
                context_bytes,
                source_for_render,
                failure_message,
                repair_attempt_number=repair_attempt_count + 1,
            )
            repair_response = await self._client.draft_scene(
                system_prompt=system_prompt,
                payload=repair_payload,
                policy=self._policy,
            )
            repair_draft = repair_response.draft
            model_call_count += repair_response.model_call_count
            repair_attempt_count += 1
            self._check_cost(repair_response)
            if repair_response.input_tokens is not None:
                total_input_tokens = (total_input_tokens or 0) + repair_response.input_tokens
            if repair_response.output_tokens is not None:
                total_output_tokens = (total_output_tokens or 0) + repair_response.output_tokens
            if repair_response.estimated_cost_usd is not None:
                total_cost_usd = (total_cost_usd or 0.0) + repair_response.estimated_cost_usd

            source_for_render = self._resolve_source(repair_draft, brief)
            self._source_validator.validate(source_for_render)
            await self._save_checkpoint(
                ns,
                animation_id,
                idempotency_key,
                "source",
                {"source_code": source_for_render},
            )
            final_draft = repair_draft

        if video_bytes is None:
            raise ManimRenderError("Render failed after all attempts.")

        # ── Step 5: validate media ─────────────────────────────────────────────
        _validate_mp4_header(video_bytes)
        if captions_bytes:
            from learning_pipeline.tools.elearning_bundle._captions import (
                convert_srt_to_vtt,
                validate_vtt,
            )
            try:
                if not captions_bytes.lstrip().startswith(b"WEBVTT"):
                    captions_bytes = convert_srt_to_vtt(captions_bytes)
                validate_vtt(captions_bytes)
            except Exception as exc:
                raise ManimMediaValidationError(
                    f"Render produced invalid captions: {exc}"
                ) from exc

        # ── Step 6: publish artifacts ──────────────────────────────────────────
        video_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{animation_id}.mp4",
            data=video_bytes,
            media_type="video/mp4",
        )
        captions_ref: ArtifactRef | None = None
        if captions_bytes:
            captions_ref = await self._store.put_bytes(
                namespace=ns,
                name=f"{animation_id}.vtt",
                data=captions_bytes,
                media_type="text/vtt",
            )
        source_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{animation_id}-source.py",
            data=source_for_render.encode("utf-8"),
            media_type="text/x-python",
        )
        log_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{animation_id}-render.log",
            data=log_bytes,
            media_type="text/plain",
        )

        # ── Step 7: build and persist trace ───────────────────────────────────
        trace = ManimTrace(
            workflow_id=workflow_id,
            task_id=task_id,
            animation_id=animation_id,
            idempotency_key=idempotency_key,
            prompt_version=PROMPT_VERSION,
            model="cached" if total_input_tokens is None else "litellm",
            model_call_count=model_call_count,
            repair_attempt_count=repair_attempt_count,
            render_attempt_count=render_attempt_count,
            template_id=final_draft.template_id,
            template_version=final_draft.template_version,
            source_generated=final_draft.template_id is None,
            source_repaired=repair_attempt_count > 0,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            estimated_cost_usd=total_cost_usd,
            checkpoint_stages_reused=tuple(checkpoint_stages_reused),
            source_scene_ids=brief.source_scene_ids,
            duration_seconds=duration_seconds,
        )
        trace_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{animation_id}-trace.json",
            data=trace.model_dump_json(indent=2).encode("utf-8"),
            media_type="application/json",
        )

        # ── Step 8: build result manifest ─────────────────────────────────────
        manifest_dict = {
            "animation_id": animation_id,
            "video_uri": video_ref.uri,
            "has_audio": True,
            "captions_uri": captions_ref.uri if captions_ref else None,
            "source_uri": source_ref.uri,
            "log_uri": log_ref.uri,
            "trace_uri": trace_ref.uri,
        }
        manifest_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{animation_id}-manifest.json",
            data=json.dumps(manifest_dict, indent=2).encode("utf-8"),
            media_type="application/json",
        )

        # ── Step 9: assemble and persist output ───────────────────────────────
        output = ManimVideoOutput(
            video=video_ref,
            video_uri=video_ref.uri,
            captions=captions_ref,
            captions_uri=captions_ref.uri if captions_ref else None,
            captions_media_type="text/vtt" if captions_ref else None,
            generated_source=source_ref,
            render_log=log_ref,
            result_manifest=manifest_ref,
            trace_uri=trace_ref.uri,
        )
        await self._save_checkpoint(
            ns, animation_id, idempotency_key, "completed", output.model_dump()
        )
        return output

    # ── Private helpers ────────────────────────────────────────────────────────

    def _compute_idempotency_key(
        self, brief: AnimationBrief, context_hash: str
    ) -> str:
        payload = json.dumps(
            {
                "animation_id": brief.animation_id,
                "source_scene_ids": list(brief.source_scene_ids),
                "learning_objective": brief.learning_objective,
                "visual_direction": brief.visual_direction,
                "narration_script": brief.narration_script,
                "target_duration_seconds": brief.target_duration_seconds,
                "quality_profile": brief.quality_profile,
                "voice_profile": brief.voice_profile,
                "context_hash": context_hash,
                "prompt_version": PROMPT_VERSION,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_system_prompt(self) -> str:
        if self._system_prompt is None:
            if _PROMPT_PATH.exists():
                self._system_prompt = load_prompt(_PROMPT_PATH)
            else:
                self._system_prompt = _FALLBACK_SYSTEM_PROMPT
        return self._system_prompt

    def _build_draft_payload(
        self, brief: AnimationBrief, context_bytes: bytes
    ) -> dict[str, Any]:
        try:
            context_data = json.loads(context_bytes)
        except Exception:
            context_data = {}
        return {
            "animation_id": brief.animation_id,
            "source_scene_ids": list(brief.source_scene_ids),
            "learning_objective": brief.learning_objective,
            "teaching_purpose": brief.teaching_purpose,
            "visual_direction": brief.visual_direction,
            "narration_script": brief.narration_script,
            "target_duration_seconds": brief.target_duration_seconds,
            "quality_profile": brief.quality_profile,
            "brand_contract": brief.brand_contract,
            "accessibility_requirements": list(brief.accessibility_requirements),
            "resolved_context": context_data,
            # The FULL catalog, always: a template the agent cannot see is a
            # template it cannot prefer over free-form source.
            "available_templates": [
                {
                    "template_id": m.template_id,
                    "description": m.description,
                    "tags": list(m.tags),
                    "min_items": m.min_items,
                    "max_items": m.max_items,
                }
                for m in self._catalog.manifests()
            ],
            "prompt_version": PROMPT_VERSION,
        }

    def _build_repair_payload(
        self,
        brief: AnimationBrief,
        context_bytes: bytes,
        failed_source: str,
        failure_message: str,
        *,
        repair_attempt_number: int,
    ) -> dict[str, Any]:
        base = self._build_draft_payload(brief, context_bytes)
        base["repair_mode"] = True
        base["failed_source"] = failed_source
        base["failure_message"] = failure_message
        base["repair_attempt_number"] = repair_attempt_number
        if repair_attempt_number >= self._policy.max_repair_attempts:
            base["repair_strategy"] = (
                "Final bounded repair: simplify the composition and reduce visual density. "
                "Prefer a compatible catalog template if the custom layout remains fragile."
            )
        return base

    def _resolve_source(self, draft: ManimSceneDraft, brief: AnimationBrief) -> str:
        """Turn a ManimSceneDraft into runnable Python source."""
        if draft.template_id is not None:
            try:
                validated = self._catalog.validate_bindings(
                    draft.template_id, draft.component_bindings.model_dump(exclude_none=True)
                )
                return self._catalog.render_source(
                    draft.template_id,
                    validated,
                    brief.animation_id,
                    tts_import=self._tts_import,
                    service_call=self._tts_service_call,
                )
            except KeyError as exc:
                raise ManimRenderError(
                    f"Template {draft.template_id!r} not in catalog: {exc}"
                ) from exc
            except ValueError as exc:
                raise ManimBindingValidationError(str(exc)) from exc
        assert draft.generated_source is not None  # enforced by ManimSceneDraft validator
        return self._inject_voiceover_service(draft.generated_source)

    def _inject_voiceover_service(self, source: str) -> str:
        """Inject the approved manim-voiceover speech service into free-form source.

        Template renderers already receive this configuration directly. Free-form
        scenes own their animation and voiceover blocks, while this controller
        owns provider configuration. If the draft is still a silent ordinary
        Scene, leave it unchanged so the renderer's audio-stream gate produces a
        repairable error instead of silently publishing it.
        """
        has_voiceover_base = re.search(
            r"class\s+\w+\s*\([^)]*\bVoiceoverScene\b[^)]*\)\s*:", source
        )
        if not has_voiceover_base or "self.voiceover(" not in source:
            return source
        if not self._tts_import.strip() or not self._tts_service_call.strip():
            raise ManimRenderError(
                "Narrated generated source requires the configured manim-voiceover service."
            )

        prepared = source
        if "from manim_voiceover import VoiceoverScene" not in prepared:
            prepared = "from manim_voiceover import VoiceoverScene\n" + prepared
        if self._tts_import not in prepared:
            prepared = self._tts_import + "\n" + prepared
        if "self.set_speech_service(" in prepared:
            return prepared

        lines = prepared.splitlines()
        construct_index = next(
            (
                index
                for index, line in enumerate(lines)
                if re.match(r"^\s+def\s+construct\s*\(self\)\s*:", line)
            ),
            None,
        )
        if construct_index is None:
            return source
        indent = re.match(r"^(\s*)", lines[construct_index]).group(1) + "    "
        lines.insert(
            construct_index + 1,
            f"{indent}self.set_speech_service({self._tts_service_call})",
        )
        return "\n".join(lines) + ("\n" if prepared.endswith("\n") else "")

    def _check_cost(self, response: ManimSceneDraftResponse) -> None:
        if (
            self._policy.max_cost_usd is not None
            and response.estimated_cost_usd is not None
            and response.estimated_cost_usd > self._policy.max_cost_usd
        ):
            raise ManimPolicyError(
                f"Cost {response.estimated_cost_usd:.4f} USD exceeds "
                f"policy limit {self._policy.max_cost_usd:.4f} USD."
            )

    async def _save_checkpoint(
        self,
        namespace: str,
        animation_id: str,
        idempotency_key: str,
        stage: str,
        data: Any,
    ) -> None:
        """Persist a checkpoint JSON; non-fatal on failure."""
        try:
            name = f"{animation_id}-ckpt-{idempotency_key[:12]}-{stage}.json"
            await self._store.put_bytes(
                namespace=namespace,
                name=name,
                data=json.dumps(data, default=_json_default).encode("utf-8"),
                media_type="application/json",
            )
        except Exception:
            pass  # Checkpoint write failure is non-fatal.

    async def _load_checkpoint(
        self,
        namespace: str,
        animation_id: str,
        idempotency_key: str,
        stage: str,
    ) -> dict | None:
        """Load a checkpoint JSON; returns None if not found or invalid."""
        try:
            uri = f"artifact://{namespace}/{animation_id}-ckpt-{idempotency_key[:12]}-{stage}.json"
            data = await self._store.get_bytes(uri)
            return json.loads(data)
        except Exception:
            return None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _scene_class_name(animation_id: str) -> str:
    """Derive a Python class name from the animation_id, matching template output."""
    return f"Scene_{animation_id.replace('-', '_')}"


def _validate_mp4_header(data: bytes) -> None:
    """Check that data starts with an ISO base-media ftyp box."""
    if len(data) < 8 or data[4:8] != b"ftyp":
        raise ManimMediaValidationError(
            "Rendered video is not a valid MP4: missing ftyp box at bytes 4–8."
        )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return None
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


_FALLBACK_SYSTEM_PROMPT = (
    "You are an expert Manim animator. Generate a ManimSceneDraft for the given "
    "animation brief. Prefer existing templates over free-form source generation. "
    "Preserve any supplied narration_script exactly and do not add instructional "
    "claims, examples, or commentary beyond the brief and resolved context. "
    "Return only valid JSON matching the ManimSceneDraft schema."
)
