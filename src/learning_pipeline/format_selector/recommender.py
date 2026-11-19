"""Optional LLM-assisted format recommender — Phase 11.

The recommender provides pedagogical judgment among candidates already
determined feasible by deterministic code. It cannot override hard blockers
or select infeasible modalities.

One-call rule: each uncached recommendation invokes exactly one structured
model call. No repair loops.
"""
from __future__ import annotations

from learning_pipeline.prompts import load_prompt

import asyncio
import functools
import json
from typing import Any, Protocol, runtime_checkable

from llm_gateway import ModelAlias
from learning_pipeline.contracts.assembly import CourseBlueprint
from learning_pipeline.contracts.format_selection import (
    FormatRecommendation,
    FormatSelectionRequest,
    ModalityDeliveryProfile,
    ModalityEvaluation,
)

PROMPT_VERSION = "format_auto_v2"

_PACKAGE_ROOT = __import__("pathlib").Path(__file__).parents[1]
_DEFAULT_PROMPT_PATH = _PACKAGE_ROOT / "prompts" / "format_selector" / "auto.md"


class FormatRecommenderError(RuntimeError):
    """Raised when the recommender cannot complete a request."""


class FormatOutputValidationError(ValueError):
    """Raised when the model output fails validation (triggers deterministic fallback)."""


@runtime_checkable
class FormatRecommender(Protocol):
    """Provider-independent interface for one structured recommendation call."""

    model: str
    prompt_version: str

    async def recommend(
        self,
        blueprint: CourseBlueprint,
        request: FormatSelectionRequest,
        feasible_profiles: tuple[ModalityDeliveryProfile, ...],
        evaluations: tuple[ModalityEvaluation, ...],
    ) -> FormatRecommendation: ...

    @property
    def call_count(self) -> int: ...

    @property
    def last_feasible_profiles(self) -> tuple[ModalityDeliveryProfile, ...] | None: ...

    @property
    def provider_request_id(self) -> str | None: ...

    @property
    def last_input_tokens(self) -> int | None: ...

    @property
    def last_output_tokens(self) -> int | None: ...


class FakeFormatRecommender:
    """Deterministic fake recommender for tests.

    If ``fail=True``, raises FormatOutputValidationError to trigger the
    service's deterministic fallback without a second call.
    """

    model: str
    prompt_version: str

    def __init__(
        self,
        selected_modality,
        *,
        fail: bool = False,
        model: str = "fake-model",
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._selected_modality = selected_modality
        self._fail = fail
        self.model = model
        self.prompt_version = prompt_version
        self._call_count = 0
        self._last_feasible_profiles: tuple[ModalityDeliveryProfile, ...] | None = None
        self._provider_request_id: str | None = None
        self._last_input_tokens: int | None = None
        self._last_output_tokens: int | None = None

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def last_feasible_profiles(self) -> tuple[ModalityDeliveryProfile, ...] | None:
        return self._last_feasible_profiles

    @property
    def provider_request_id(self) -> str | None:
        return self._provider_request_id

    @property
    def last_input_tokens(self) -> int | None:
        return self._last_input_tokens

    @property
    def last_output_tokens(self) -> int | None:
        return self._last_output_tokens

    async def recommend(
        self,
        blueprint: CourseBlueprint,
        request: FormatSelectionRequest,
        feasible_profiles: tuple[ModalityDeliveryProfile, ...],
        evaluations: tuple[ModalityEvaluation, ...],
    ) -> FormatRecommendation:
        await asyncio.sleep(0)
        self._call_count += 1
        self._last_feasible_profiles = feasible_profiles
        if self._fail:
            raise FormatOutputValidationError("Fake recommender forced failure for testing")
        return FormatRecommendation(
            selected_modality=self._selected_modality,
            rationale="Fake LLM recommendation",
        )


class LiteLLMFormatRecommender:
    """Real LLM-backed format recommender.

    Uses the same StructuredPlanningClient infrastructure as the modality planner.
    Makes exactly one generate() call per recommend() invocation.
    """

    model: str
    prompt_version: str

    def __init__(
        self,
        client,  # StructuredPlanningClient
        *,
        model: str = ModelAlias.FORMAT_SELECTION,
        prompt_path=None,
    ) -> None:
        self._client = client
        self.model = model
        self._prompt_path = prompt_path or _DEFAULT_PROMPT_PATH
        self.prompt_version = PROMPT_VERSION
        self._prompt_cache: str | None = None
        self._call_count = 0
        self._last_feasible_profiles: tuple[ModalityDeliveryProfile, ...] | None = None
        self._provider_request_id: str | None = None
        self._last_input_tokens: int | None = None
        self._last_output_tokens: int | None = None

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def last_feasible_profiles(self) -> tuple[ModalityDeliveryProfile, ...] | None:
        return self._last_feasible_profiles

    @property
    def provider_request_id(self) -> str | None:
        return self._provider_request_id

    @property
    def last_input_tokens(self) -> int | None:
        return self._last_input_tokens

    @property
    def last_output_tokens(self) -> int | None:
        return self._last_output_tokens

    def _load_prompt(self) -> str:
        if self._prompt_cache is not None:
            return self._prompt_cache
        p = __import__("pathlib").Path(self._prompt_path)
        if not p.exists():
            raise FormatRecommenderError(
                f"Cannot load format-selector prompt: '{p}' does not exist"
            )
        self._prompt_cache = load_prompt(p)
        return self._prompt_cache

    async def recommend(
        self,
        blueprint: CourseBlueprint,
        request: FormatSelectionRequest,
        feasible_profiles: tuple[ModalityDeliveryProfile, ...],
        evaluations: tuple[ModalityEvaluation, ...],
    ) -> FormatRecommendation:
        system_prompt = self._load_prompt()
        self._last_feasible_profiles = feasible_profiles

        user_payload: dict[str, Any] = {
            "blueprint_id": blueprint.blueprint_id,
            "title": blueprint.title,
            "assessment_strategy": blueprint.assessment_strategy,
            "estimated_duration_minutes": blueprint.estimated_duration_minutes,
            "learner": json.loads(blueprint.learner.model_dump_json()),
            "feasible_profiles": [
                json.loads(p.model_dump_json()) for p in feasible_profiles
            ],
            "evaluations": [
                json.loads(e.model_dump_json()) for e in evaluations
            ],
        }

        try:
            response = await self._client.generate(
                system_prompt=system_prompt,
                user_payload=user_payload,
                output_model=FormatRecommendation,
                model=self.model,
            )
        except Exception as exc:
            raise FormatOutputValidationError(
                f"Format recommender call failed: {exc}"
            ) from exc

        self._call_count += 1
        self._provider_request_id = response.provider_request_id
        self._last_input_tokens = response.input_tokens
        self._last_output_tokens = response.output_tokens

        result = response.result
        if not isinstance(result, FormatRecommendation):
            raise FormatOutputValidationError(
                f"Model returned unexpected type: {type(result).__name__}"
            )
        return result
