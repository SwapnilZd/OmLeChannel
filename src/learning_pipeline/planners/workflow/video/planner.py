"""
VideoWorkflowPlanner — Phase 13B.

Orchestrates one video planning call:
  1. Validates the modality is video.
  2. Loads the versioned system prompt from disk.
  3. Builds a rich user payload (resolved context + modality plan + capability
     constraints + approved profiles + available backgrounds).
  4. Calls the StructuredPlanningClient exactly once (one-call rule).
  5. Validates the returned VideoProductionDraft.
  6. Builds and returns a ModalityProductionPlan via VideoProductionPlanBuilder.

Provider neutrality
-------------------
The planner never sees HeyGen avatar IDs, voice IDs, asset IDs, API keys,
polling configuration, or physical paths.  It works entirely with logical
profile names and approved brand colours.

The production plan it returns is equally provider-neutral; the executor
resolves logical names at execution time.

Prompt loading is lazy and cached in-process so the file is only read once
per planner instance.
"""
from __future__ import annotations

from learning_pipeline.prompts import load_prompt

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
    ResolvedPlanningContext,
    VideoProductionDraft,
)
from learning_pipeline.planners.client import StructuredPlanningClient
from learning_pipeline.planners.workflow.video.builder import VideoProductionPlanBuilder
from learning_pipeline.planners.workflow.video.validation import validate_video_draft
from learning_pipeline.tools.catalog import ProductionToolCatalog

PROMPT_VERSION = "video_v5"

_DEFAULT_PROMPT_PATH = (
    Path(__file__).parents[3]
    / "prompts"
    / "workflow_planner"
    / "video.md"
)

_DEFAULT_AVATAR_PROFILES: frozenset[str] = frozenset(
    {"default_instructor", "default_narrator"}
)
_DEFAULT_VOICE_PROFILES: frozenset[str] = frozenset(
    {"default_instructor", "default_narrator"}
)


class VideoWorkflowPlannerError(RuntimeError):
    """Raised when the video planner cannot complete planning."""


class VideoWorkflowPlanner:
    """Plan a video episode from a resolved instructional context.

    Parameters
    ----------
    client:
        StructuredPlanningClient implementation (real or fake).
    catalog:
        Tool catalog; used to supply planner-safe capability constraints.
    prompt_path:
        Path to the versioned Markdown prompt file.  Defaults to
        ``prompts/workflow_planner/video.md``.
    model:
        Model identifier passed to the planning client.
    approved_avatar_profiles:
        Logical avatar profile names the LLM may select.
    approved_voice_profiles:
        Logical voice profile names the LLM may select.
    asset_catalog:
        Mapping of logical asset ID → artifact URI.  Used by the builder to
        resolve ExistingAssetBackgroundDraft backgrounds.  For Phase 13B
        (solid-colour only) this can be empty.
    require_captions:
        When True, validates that the draft enables captions.
    max_total_duration_seconds:
        Hard ceiling on the sum of all scene estimated_duration_seconds.
        Passed to the LLM in the user payload and enforced in validation.
    """

    def __init__(
        self,
        client: StructuredPlanningClient,
        catalog: ProductionToolCatalog,
        *,
        prompt_path: Path | None = None,
        model: str = ModelAlias.VIDEO_WORKFLOW_PLANNING,
        approved_avatar_profiles: frozenset[str] = _DEFAULT_AVATAR_PROFILES,
        approved_voice_profiles: frozenset[str] = _DEFAULT_VOICE_PROFILES,
        asset_catalog: dict[str, str] | None = None,
        require_captions: bool = False,
        max_total_duration_seconds: int = 300,
    ) -> None:
        self._client = client
        self._catalog = catalog
        self._prompt_path = Path(prompt_path) if prompt_path else _DEFAULT_PROMPT_PATH
        self._model = model
        self._approved_avatar_profiles = approved_avatar_profiles
        self._approved_voice_profiles = approved_voice_profiles
        self._asset_catalog: dict[str, str] = asset_catalog or {}
        self._require_captions = require_captions
        self._max_total_duration_seconds = max_total_duration_seconds
        self._builder = VideoProductionPlanBuilder(asset_catalog=self._asset_catalog)
        self._system_prompt: str | None = None

    # ── Public properties (used by WorkflowPlanningService for trace recording) ─

    @property
    def prompt_version(self) -> str:
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
                raise VideoWorkflowPlannerError(
                    f"Cannot load planning prompt from '{self._prompt_path}': {exc}"
                ) from exc
        return self._system_prompt

    def _build_capability_constraints(self) -> dict[str, Any]:
        try:
            manifest = self._catalog.manifest_for("video.avatar.render")
            return {
                "render_capability": manifest.capability,
                "description": manifest.description,
                "constraints": manifest.constraints,
                "input_schema": manifest.input_schema,
                "output_schema": manifest.output_schema,
            }
        except Exception:
            return {"render_capability": "video.avatar.render"}

    def _build_user_payload(
        self,
        context: ResolvedPlanningContext,
        modality_plan: ModalityPlan,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(context.model_dump_json())

        # Teaching direction lives in the modality plan, not the resolved context
        payload["modality_plan"] = json.loads(modality_plan.model_dump_json())

        # Planner-safe capability view
        payload["capability_constraints"] = self._build_capability_constraints()

        # Approved logical profiles (no provider IDs)
        payload["approved_profiles"] = {
            "avatar_profiles": sorted(self._approved_avatar_profiles),
            "voice_profiles": sorted(self._approved_voice_profiles),
        }

        # Available backgrounds: solid colours from brand contract + pre-approved assets
        brand_colors: list[str] = []
        if context.brand_contract:
            brand_colors = [
                v for k, v in context.brand_contract.items()
                if "color" in k.lower() or "colour" in k.lower() or "background" in k.lower()
            ]
        payload["available_backgrounds"] = {
            "solid_colors": brand_colors or ["#1A1A2E"],
            "existing_asset_ids": sorted(self._asset_catalog.keys()),
        }

        payload["max_total_duration_seconds"] = self._max_total_duration_seconds

        return payload

    # ── Public API ─────────────────────────────────────────────────────────────

    async def plan(
        self,
        context: ResolvedPlanningContext,
        modality_plan: ModalityPlan,
    ) -> ModalityProductionPlan:
        """Plan a video production from *context*.

        Makes exactly one structured model call per invocation (one-call rule).

        Raises:
            VideoWorkflowPlannerError:     If the modality is not video.
            PlanningClientError:           If the model call fails.
            PlanningOutputValidationError: If the model returns invalid output.
            VideoDraftValidationError:     If the draft fails semantic validation.
            VideoProductionPlanBuilderError: If the builder cannot produce a valid plan.
        """
        if modality_plan.modality != Modality.VIDEO:
            raise VideoWorkflowPlannerError(
                f"VideoWorkflowPlanner only handles 'video' modality; "
                f"got '{modality_plan.modality}'"
            )

        system_prompt = self._load_system_prompt()
        user_payload = self._build_user_payload(context, modality_plan)

        response = await self._client.generate(
            system_prompt=system_prompt,
            user_payload=user_payload,
            output_model=VideoProductionDraft,
            model=self._model,
        )

        draft = response.result
        if not isinstance(draft, VideoProductionDraft):
            raise VideoWorkflowPlannerError(
                f"Planning client returned unexpected type: {type(draft).__name__}"
            )

        validate_video_draft(
            draft,
            modality_plan,
            approved_avatar_profiles=self._approved_avatar_profiles,
            approved_voice_profiles=self._approved_voice_profiles,
            approved_asset_ids=frozenset(self._asset_catalog.keys()),
            require_captions=self._require_captions,
            max_total_duration_seconds=self._max_total_duration_seconds,
        )

        return self._builder.build(draft)
