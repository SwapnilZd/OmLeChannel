"""
ElearningModalityPlanner — Phase 14E.

Implements the ModalityPlanner protocol for the e-learning modality.

One uncached request makes exactly one semantic model call via the
StructuredPlanningClient.  If the output fails validation the planner
raises immediately — no automatic re-prompting or correction loop.

The planner does not see raw production tool manifests, LLM credentials,
Manim templates, HeyGen provider IDs, or executor implementation details.
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
    ElearningModalityDraft,
    ModalityPlanningContext,
)
from learning_pipeline.affordances.catalog import PlannerAffordanceView
from learning_pipeline.planners.client import StructuredPlanningClient
from learning_pipeline.planners.modality.elearning.builder import ElearningModalityPlanBuilder
from learning_pipeline.planners.modality.elearning.validation import (
    validate_elearning_modality_draft,
)


_PACKAGE_ROOT = Path(__file__).parents[3]
_DEFAULT_PROMPT_PATH = _PACKAGE_ROOT / "prompts" / "modality_planner" / "elearning.md"

PROMPT_VERSION = "elearning_modality_v4"


class ElearningModalityPlannerError(RuntimeError):
    """Raised when the E-learning Modality Planner cannot produce a valid plan."""


class ElearningModalityPlanner:
    """E-learning-specific Modality Planner.

    Makes exactly one LLM call per uncached request via a StructuredPlanningClient.
    The returned plan is validated against the blueprint and affordance view before
    being returned.  Fails fast on invalid output — no correction loop.

    Parameters
    ----------
    client:
        Provider-independent structured planning client.
    prompt_path:
        Path to the versioned Markdown system prompt.  Defaults to the
        repo-level ``prompts/modality_planner/elearning.md``.
    model:
        LLM model identifier forwarded to the client.
    """

    def __init__(
        self,
        client: StructuredPlanningClient,
        *,
        prompt_path: Path | None = None,
        model: str = ModelAlias.ELEARNING_MODALITY_PLANNING,
    ) -> None:
        self._client = client
        self._prompt_path = prompt_path or _DEFAULT_PROMPT_PATH
        self._model = model
        self._builder = ElearningModalityPlanBuilder()
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
                raise ElearningModalityPlannerError(
                    f"Cannot load modality planner prompt from '{self._prompt_path}': {exc}"
                ) from exc
        return self._system_prompt

    async def create_modality_plan(
        self,
        blueprint: CourseBlueprint,
        modality: Modality,
        context: ModalityPlanningContext,
        affordances: PlannerAffordanceView,
    ) -> ModalityPlan:
        """Plan one e-learning course, validate the draft, and return a ModalityPlan.

        Exactly one structured client call is made.

        Raises:
            ElearningModalityPlannerError: If modality != elearning, the prompt
                file is missing, or the LLM output fails validation.
        """
        if modality != Modality.ELEARNING:
            raise ElearningModalityPlannerError(
                f"ElearningModalityPlanner only handles elearning modality; got '{modality}'"
            )

        system_prompt = self._load_system_prompt()
        user_payload = {
            **json.loads(context.model_dump_json()),
            "affordances": json.loads(affordances.model_dump_json()),
        }

        try:
            response = await self._client.generate(
                system_prompt=system_prompt,
                user_payload=user_payload,
                output_model=ElearningModalityDraft,
                model=self._model,
            )
        except Exception as exc:
            raise ElearningModalityPlannerError(
                f"Modality planning client call failed: {exc}"
            ) from exc

        draft: ElearningModalityDraft = response.result

        try:
            validate_elearning_modality_draft(draft, blueprint, context, affordances)
        except Exception as exc:
            raise ElearningModalityPlannerError(
                f"Modality draft failed validation: {exc}"
            ) from exc

        return self._builder.build(draft, blueprint)
