"""
VideoModalityPlanner — Phase 13C.

Implements the ModalityPlanner protocol for the video modality.

One uncached request makes exactly one semantic model call via the
StructuredPlanningClient.  If the output fails validation the planner
raises immediately — no automatic re-prompting or correction loop.

The planner does not see raw production tool manifests, HeyGen credentials,
provider avatar/voice IDs, or executor implementation details.
"""
from __future__ import annotations

from learning_pipeline.prompts import load_prompt

import json
from pathlib import Path

from llm_gateway import ModelAlias

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan
from learning_pipeline.contracts.planning import (
    ModalityAssetSummary,
    ModalityPlanningContext,
    VideoModalityDraft,
)
from learning_pipeline.affordances.catalog import PlannerAffordanceView
from learning_pipeline.planners.client import StructuredPlanningClient
from learning_pipeline.planners.modality.video.builder import VideoModalityPlanBuilder
from learning_pipeline.planners.modality.video.validation import validate_video_modality_draft


_PACKAGE_ROOT = Path(__file__).parents[3]
_DEFAULT_PROMPT_PATH = _PACKAGE_ROOT / "prompts" / "modality_planner" / "video.md"

PROMPT_VERSION = "video_modality_v4"


class VideoModalityPlannerError(RuntimeError):
    """Raised when the Video Modality Planner cannot produce a valid plan."""


class VideoModalityPlanner:
    """Video-specific Modality Planner.

    Makes exactly one LLM call per uncached request via a StructuredPlanningClient.
    The returned plan is validated against the blueprint and affordance view before
    being returned.  Fails fast on invalid output — no correction loop.

    Parameters
    ----------
    client:
        Provider-independent structured planning client.
    prompt_path:
        Path to the versioned Markdown system prompt.  Defaults to the
        repo-level ``prompts/modality_planner/video.md``.
    model:
        LLM model identifier forwarded to the client.
    approved_asset_ids:
        Logical asset IDs the LLM may reference.  Used for validation only;
        the planner also receives full ModalityAssetSummary objects.
    asset_summaries:
        Planner-safe summaries of approved visual assets included in the
        user payload so the LLM can make informed presentation decisions.
    """

    def __init__(
        self,
        client: StructuredPlanningClient,
        *,
        prompt_path: Path | None = None,
        model: str = ModelAlias.VIDEO_MODALITY_PLANNING,
        approved_asset_ids: frozenset[str] = frozenset(),
        asset_summaries: tuple[ModalityAssetSummary, ...] = (),
    ) -> None:
        self._client = client
        self._prompt_path = prompt_path or _DEFAULT_PROMPT_PATH
        self._model = model
        self._approved_asset_ids = approved_asset_ids
        self._asset_summaries = asset_summaries
        self._builder = VideoModalityPlanBuilder()
        self._system_prompt: str | None = None

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION

    @property
    def model(self) -> str:
        return self._model

    def _load_system_prompt(self) -> str:
        if self._system_prompt is None:
            try:
                self._system_prompt = load_prompt(self._prompt_path)
            except OSError as exc:
                raise VideoModalityPlannerError(
                    f"Cannot load video modality planner prompt from '{self._prompt_path}': {exc}"
                ) from exc
        return self._system_prompt

    async def create_modality_plan(
        self,
        blueprint: CourseBlueprint,
        modality: Modality,
        context: ModalityPlanningContext,
        affordances: PlannerAffordanceView,
    ) -> ModalityPlan:
        """Plan one video modality, validate the draft, and return a ModalityPlan.

        Exactly one structured client call is made.

        Raises:
            VideoModalityPlannerError: If modality != video, the prompt file is
                missing, or the LLM output fails validation.
        """
        if modality != Modality.VIDEO:
            raise VideoModalityPlannerError(
                f"VideoModalityPlanner only handles video modality; got '{modality}'"
            )

        system_prompt = self._load_system_prompt()
        user_payload = {
            **json.loads(context.model_dump_json()),
            "affordances": json.loads(affordances.model_dump_json()),
            "approved_asset_ids": sorted(self._approved_asset_ids),
            "available_assets": [
                json.loads(s.model_dump_json()) for s in self._asset_summaries
            ],
        }

        try:
            response = await self._client.generate(
                system_prompt=system_prompt,
                user_payload=user_payload,
                output_model=VideoModalityDraft,
                model=self._model,
            )
        except Exception as exc:
            raise VideoModalityPlannerError(
                f"Video modality planning client call failed: {exc}"
            ) from exc

        draft: VideoModalityDraft = response.result

        try:
            validate_video_modality_draft(
                draft,
                blueprint,
                context,
                affordances,
                approved_asset_ids=self._approved_asset_ids,
            )
        except Exception as exc:
            raise VideoModalityPlannerError(
                f"Video modality draft failed validation: {exc}"
            ) from exc

        return self._builder.build(draft, blueprint)
