"""
PodcastWorkflowPlanner — Phase 9.

Orchestrates one podcast planning call:
  1. Validates the modality is podcast.
  2. Loads the versioned system prompt from disk.
  3. Serialises the ResolvedPlanningContext as the user payload.
  4. Calls the StructuredPlanningClient exactly once (one-call rule).
  5. Validates the returned PodcastProductionDraft.
  6. Builds and returns a ModalityProductionPlan via PodcastProductionPlanBuilder.

Prompt loading is lazy and cached in-process so the file is only read once per
planner instance (not once per planning request).

The planner does NOT handle idempotency, trace persistence, or cache lookup.
Those concerns belong to WorkflowPlanningService.
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
    PodcastProductionDraft,
    ResolvedPlanningContext,
)
from learning_pipeline.planners.client import (
    StructuredPlanningClient,
)
from learning_pipeline.planners.workflow.podcast.builder import PodcastProductionPlanBuilder
from learning_pipeline.planners.workflow.podcast.validation import validate_podcast_draft
from learning_pipeline.tools.catalog import ProductionToolCatalog

PROMPT_VERSION = "podcast_v7"

_DEFAULT_PROMPT_PATH = (
    Path(__file__).parents[3]
    / "prompts"
    / "workflow_planner"
    / "podcast.md"
)


class PodcastPlannerError(RuntimeError):
    """Raised when the podcast planner cannot complete planning."""


def _resolved_context_to_payload(context: ResolvedPlanningContext) -> dict[str, Any]:
    """Serialise the resolved context to a JSON-safe user payload dict."""
    return json.loads(context.model_dump_json())


class PodcastWorkflowPlanner:
    """Plan a podcast episode from a resolved instructional context.

    Parameters
    ----------
    client:
        StructuredPlanningClient implementation (real or fake).
    catalog:
        Tool catalog; used to include planner-safe capability info in the prompt.
    prompt_path:
        Path to the versioned Markdown prompt file.  Defaults to the repo-level
        ``prompts/workflow_planner/podcast.md``.
    model:
        Model identifier passed to the planning client.
    """

    def __init__(
        self,
        client: StructuredPlanningClient,
        catalog: ProductionToolCatalog,
        *,
        prompt_path: Path | None = None,
        model: str = ModelAlias.PODCAST_WORKFLOW_PLANNING,
    ) -> None:
        self._client = client
        self._catalog = catalog
        self._prompt_path = Path(prompt_path) if prompt_path else _DEFAULT_PROMPT_PATH
        self._model = model
        self._builder = PodcastProductionPlanBuilder()
        self._system_prompt: str | None = None

    @property
    def prompt_version(self) -> str:
        """Public accessor used by WorkflowPlanningService for trace recording."""
        return PROMPT_VERSION

    @property
    def model(self) -> str:
        """Public accessor used by WorkflowPlanningService for trace recording."""
        return self._model

    def _load_system_prompt(self) -> str:
        if self._system_prompt is None:
            try:
                self._system_prompt = load_prompt(self._prompt_path)
            except OSError as exc:
                raise PodcastPlannerError(
                    f"Cannot load planning prompt from '{self._prompt_path}': {exc}"
                ) from exc
        return self._system_prompt

    async def plan(
        self,
        context: ResolvedPlanningContext,
        modality_plan: ModalityPlan,
    ) -> ModalityProductionPlan:
        """Plan a podcast production from *context*.

        Makes exactly one structured model call per invocation (one-call rule).

        Raises:
            PodcastPlannerError:           If the modality is not podcast.
            PlanningClientError:           If the model call fails.
            PlanningOutputValidationError: If the model returns invalid structured output.
            PodcastDraftValidationError:   If the draft fails semantic validation.
            PodcastPlanBuilderError:       If the builder cannot produce a valid plan.
        """
        if modality_plan.modality != Modality.PODCAST:
            raise PodcastPlannerError(
                f"PodcastWorkflowPlanner only handles 'podcast' modality; "
                f"got '{modality_plan.modality}'"
            )

        system_prompt = self._load_system_prompt()
        user_payload = _resolved_context_to_payload(context)

        response = await self._client.generate(
            system_prompt=system_prompt,
            user_payload=user_payload,
            output_model=PodcastProductionDraft,
            model=self._model,
        )

        draft = response.result
        if not isinstance(draft, PodcastProductionDraft):
            raise PodcastPlannerError(
                f"Planning client returned unexpected type: {type(draft).__name__}"
            )

        validate_podcast_draft(draft, modality_plan)

        return self._builder.build(draft)
