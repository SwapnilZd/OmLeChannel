"""ElearningWorkflowPlanner — Phase 14D.

Orchestrates one e-learning planning call:
  1. Validates the modality is elearning.
  2. Loads the versioned system prompt from disk.
  3. Builds a rich user payload (resolved context + modality plan + capability
     constraints + approved profiles + affordance catalog).
  4. Calls the StructuredPlanningClient exactly once (one-call rule).
  5. Validates the returned ElearningProductionDraft.
  6. Builds and returns a ModalityProductionPlan via ElearningProductionPlanBuilder.

The planner does NOT handle idempotency, trace persistence, or cache lookup.
Those concerns belong to WorkflowPlanningService.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from llm_gateway import ModelAlias

from learning_pipeline.contracts import (
    Modality,
    ModalityPlan,
    ModalityProductionPlan,
)
from learning_pipeline.contracts.planning import (
    ElearningProductionDraft,
    ResolvedPlanningContext,
)
from learning_pipeline.planners.client import StructuredPlanningClient
from learning_pipeline.planners.workflow.elearning.builder import ElearningProductionPlanBuilder
from learning_pipeline.planners.workflow.elearning.validation import (
    ElearningDraftValidationError,
    validate_elearning_draft,
)
from learning_pipeline.prompts import load_prompt
from learning_pipeline.runtime.artifact_store import ArtifactStore
from learning_pipeline.tools.catalog import ProductionToolCatalog

PROMPT_VERSION = "elearning_v7"

_DEFAULT_PROMPT_PATH = (
    Path(__file__).parents[3]
    / "prompts"
    / "workflow_planner"
    / "elearning.md"
)

_DEFAULT_AVATAR_PROFILES: frozenset[str] = frozenset(
    {"default_instructor", "default_narrator"}
)
_DEFAULT_VOICE_PROFILES: frozenset[str] = frozenset(
    {"default_instructor", "default_narrator"}
)


class ElearningWorkflowPlannerError(RuntimeError):
    """Raised when the e-learning planner cannot complete planning."""


class ElearningWorkflowPlanner:
    """Plan an e-learning production from a resolved instructional context.

    Parameters
    ----------
    client:
        StructuredPlanningClient implementation (real or fake).
    catalog:
        Tool catalog; used to supply planner-safe capability constraints.
    prompt_path:
        Path to the versioned Markdown prompt file. Defaults to
        ``prompts/workflow_planner/elearning.md``.
    model:
        Model identifier passed to the planning client.
    approved_avatar_profiles:
        Logical avatar profile names the LLM may select for avatar slots.
    approved_voice_profiles:
        Logical voice profile names the LLM may select.
    """

    def __init__(
        self,
        client: StructuredPlanningClient,
        catalog: ProductionToolCatalog,
        *,
        prompt_path: Path | None = None,
        model: str = ModelAlias.ELEARNING_WORKFLOW_PLANNING,
        approved_avatar_profiles: frozenset[str] = _DEFAULT_AVATAR_PROFILES,
        approved_voice_profiles: frozenset[str] = _DEFAULT_VOICE_PROFILES,
        available_capabilities: frozenset[str] | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._client = client
        self._catalog = catalog
        self._prompt_path = Path(prompt_path) if prompt_path else _DEFAULT_PROMPT_PATH
        self._model = model
        self._approved_avatar_profiles = approved_avatar_profiles
        self._approved_voice_profiles = approved_voice_profiles
        relevant_capabilities = frozenset(
            {"elearning.course.author", "video.avatar.render", "video.manim.render"}
        )
        self._available_capabilities = (
            available_capabilities
            if available_capabilities is not None
            else relevant_capabilities
        ) & relevant_capabilities
        if "video.avatar.render" not in self._available_capabilities:
            self._approved_avatar_profiles = frozenset()
        self._artifact_store = artifact_store
        self._builder = ElearningProductionPlanBuilder()
        self._system_prompt: str | None = None

    # ── Public properties (used by WorkflowPlanningService for trace recording) ─

    @property
    def prompt_version(self) -> str:
        if self._prompt_path == _DEFAULT_PROMPT_PATH:
            return PROMPT_VERSION
        return self._prompt_path.stem

    @property
    def model(self) -> str:
        return self._model

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_system_prompt(self) -> str:
        if self._system_prompt is None:
            try:
                self._system_prompt = load_prompt(self._prompt_path)
            except OSError as exc:
                raise ElearningWorkflowPlannerError(
                    f"Cannot load planning prompt from '{self._prompt_path}': {exc}"
                ) from exc
        return self._system_prompt

    async def _persist_context(self, context: ResolvedPlanningContext) -> tuple[str, str]:
        """Hash the context and, if an artifact store is configured, persist it.

        Returns (context_uri, context_hash). When no store is configured the URI
        uses the ``memory://`` scheme — suitable for tests but not for real runs
        where the authoring executor must fetch the bytes at task execution time.
        """
        context_bytes = context.model_dump_json().encode("utf-8")
        context_hash = hashlib.sha256(context_bytes).hexdigest()
        if self._artifact_store is not None:
            ref = await self._artifact_store.put_bytes(
                namespace="planning-context",
                name=f"{context_hash[:16]}.json",
                data=context_bytes,
                media_type="application/json",
            )
            return ref.uri, context_hash
        return f"memory://planning-context/{context_hash[:16]}", context_hash

    def _build_capability_constraints(self) -> dict[str, Any]:
        constraints: dict[str, Any] = {}
        for cap in sorted(self._available_capabilities):
            try:
                manifest = self._catalog.manifest_for(cap)
                constraints[cap] = {
                    "capability": manifest.capability,
                    "description": manifest.description,
                    "constraints": manifest.constraints,
                }
            except Exception:
                constraints[cap] = {"capability": cap}
        return constraints

    def _build_user_payload(
        self,
        context: ResolvedPlanningContext,
        modality_plan: ModalityPlan,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(context.model_dump_json())

        payload["modality_plan"] = json.loads(modality_plan.model_dump_json())
        payload["capability_constraints"] = self._build_capability_constraints()
        payload["approved_profiles"] = {
            "avatar_profiles": sorted(self._approved_avatar_profiles),
            "voice_profiles": sorted(self._approved_voice_profiles),
        }
        return payload

    # ── Public API ─────────────────────────────────────────────────────────────

    async def plan(
        self,
        context: ResolvedPlanningContext,
        modality_plan: ModalityPlan,
    ) -> ModalityProductionPlan:
        """Plan an e-learning production from *context*.

        Makes exactly one structured model call per invocation (one-call rule).

        Raises:
            ElearningWorkflowPlannerError:     If the modality is not elearning.
            PlanningClientError:               If the model call fails.
            PlanningOutputValidationError:     If the model returns invalid output.
            ElearningDraftValidationError:     If the draft fails semantic validation.
            ElearningProductionPlanBuilderError: If the builder cannot produce a valid plan.
        """
        if modality_plan.modality != Modality.ELEARNING:
            raise ElearningWorkflowPlannerError(
                f"ElearningWorkflowPlanner only handles 'elearning' modality; "
                f"got '{modality_plan.modality}'"
            )

        system_prompt = self._load_system_prompt()
        user_payload = self._build_user_payload(context, modality_plan)

        response = await self._client.generate(
            system_prompt=system_prompt,
            user_payload=user_payload,
            output_model=ElearningProductionDraft,
            model=self._model,
        )

        draft = response.result
        if not isinstance(draft, ElearningProductionDraft):
            raise ElearningWorkflowPlannerError(
                f"Planning client returned unexpected type: {type(draft).__name__}"
            )

        validate_elearning_draft(
            draft,
            modality_plan,
            resolved_context=context,
            approved_avatar_profiles=self._approved_avatar_profiles,
            approved_voice_profiles=self._approved_voice_profiles,
        )

        context_uri, context_hash = await self._persist_context(context)

        return self._builder.build(
            draft,
            modality_plan=modality_plan,
            context_uri=context_uri,
            context_hash=context_hash,
        )
