"""Curriculum Assembly Agent protocol and implementations — Phase 12."""
from __future__ import annotations

from learning_pipeline.prompts import load_prompt

import json
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from llm_gateway import ModelAlias
from learning_pipeline.contracts.assembly import RLOContentSelection
from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    CourseAssemblyDraft,
    CourseAssemblyRequest,
    OmittedRLODecision,
    RLOAssemblyContext,
    TailoredRLODraft,
)
from learning_pipeline.contracts.planning import StructuredPlanningResponse
from learning_pipeline.planners.client import (
    PlanningClientError,
    PlanningOutputValidationError,
    StructuredPlanningClient,
)

PROMPT_VERSION = "course_assembly_v4"
_PROMPTS_DIR = Path(__file__).parents[2] / "prompts" / "curriculum_assembly"


@runtime_checkable
class CurriculumAssemblyAgent(Protocol):
    """Protocol for one structured assembly call per uncached request."""

    prompt_version: str
    model: str | None
    call_count: int

    async def create_assembly_draft(
        self,
        request: CourseAssemblyRequest,
        contexts: tuple[RLOAssemblyContext, ...],
    ) -> StructuredPlanningResponse: ...


# ── Fake agent ────────────────────────────────────────────────────────────────


class FakeCurriculumAssemblyAgent:
    """Deterministic reference-mode agent. No network, no credentials.

    Includes all provided contexts (none omitted by default).
    Configurable for test scenarios:
      omit_rlo_ids — RLO IDs to mark as omitted instead of included.
      fail          — raise PlanningOutputValidationError on next call.
    """

    def __init__(
        self,
        *,
        omit_rlo_ids: frozenset[str] = frozenset(),
        fail: bool = False,
        model: str = "fake-model",
        prompt_version: str = PROMPT_VERSION,
        target_proficiency: TopicProficiency = TopicProficiency.INTERMEDIATE,
        content_depth: ContentDepth = ContentDepth.WORKING,
    ) -> None:
        self._omit_rlo_ids = omit_rlo_ids
        self._fail = fail
        self.model = model
        self.prompt_version = prompt_version
        self._target_proficiency = target_proficiency
        self._content_depth = content_depth
        self.call_count = 0
        self.last_request: CourseAssemblyRequest | None = None
        self.last_contexts: tuple[RLOAssemblyContext, ...] | None = None

    async def create_assembly_draft(
        self,
        request: CourseAssemblyRequest,
        contexts: tuple[RLOAssemblyContext, ...],
    ) -> StructuredPlanningResponse:
        import asyncio
        await asyncio.sleep(0)
        self.call_count += 1
        self.last_request = request
        self.last_contexts = contexts

        if self._fail:
            raise PlanningOutputValidationError(
                "FakeCurriculumAssemblyAgent configured to fail."
            )

        ordered: list[TailoredRLODraft] = []
        omitted: list[OmittedRLODecision] = []
        order = 1

        for ctx in contexts:
            if ctx.rlo_id in self._omit_rlo_ids:
                omitted.append(OmittedRLODecision(
                    rlo_id=ctx.rlo_id,
                    rlo_version=ctx.rlo_version,
                    rationale="Not relevant to learner goals (reference mode omission).",
                ))
                continue

            # Select all content
            selected = RLOContentSelection(
                objective_ids=(ctx.enabling_objective.id,),
                concept_ids=tuple(c.id for c in ctx.concepts),
                component_ids=tuple(c.id for c in ctx.components),
                assessment_item_ids=tuple(a.id for a in ctx.assessment_items),
            )
            ordered.append(TailoredRLODraft(
                rlo_id=ctx.rlo_id,
                rlo_version=ctx.rlo_version,
                order=order,
                selected_content=selected,
                target_proficiency=self._target_proficiency,
                content_depth=self._content_depth,
                role_relevance=f"Relevant to learner role: {request.learner.role}.",
                example_context=None,
                personalization_rationale=(
                    f"Included to address course goal: {request.course_goal}."
                ),
                sequencing_rationale=(
                    "Ordered by candidate position in the eligible set."
                ),
            ))
            order += 1

        all_objective_ids: list[str] = []
        for ctx in contexts:
            if ctx.rlo_id not in self._omit_rlo_ids:
                all_objective_ids.append(ctx.enabling_objective.id)

        outcomes = tuple(
            f"Upon completion, learners will be able to: {ctx.enabling_objective.statement}"
            for ctx in contexts
            if ctx.rlo_id not in self._omit_rlo_ids
        ) or ("Complete the assigned course content.",)

        draft = CourseAssemblyDraft(
            draft_id=f"fake-draft-{uuid.uuid4()}",
            title=f"Reference Assembly: {request.course_goal[:60]}",
            learning_outcomes=outcomes,
            ordered_rlo_drafts=tuple(ordered),
            omitted_rlos=tuple(omitted),
            prerequisite_bridges=(),
            sequencing_rationale=(
                "RLOs ordered by input sequence; no cross-RLO prerequisites in this set."
            ),
            assessment_strategy=(
                "Formative checks embedded in selected assessment items. "
                "Final knowledge check at end of course."
            ),
        )

        return StructuredPlanningResponse(
            result=draft,
            model=self.model,
            prompt_version=self.prompt_version,
            provider_request_id=None,
            input_tokens=None,
            output_tokens=None,
            estimated_cost_usd=None,
        )


# ── Real agent (LiteLLM) ──────────────────────────────────────────────────────


class LiteLLMCurriculumAssemblyAgent:
    """Real assembly agent backed by LiteLLM.

    Makes one initial structured call. The service may request one additional
    duration-only repair after deterministic rejection.
    """

    def __init__(
        self,
        client: StructuredPlanningClient,
        *,
        model: str = ModelAlias.CURRICULUM_ASSEMBLY,
        prompt_path: Path | None = None,
    ) -> None:
        self._client = client
        self.model = model
        self._prompt_path = prompt_path or (_PROMPTS_DIR / "course_assembly.md")
        self.prompt_version = PROMPT_VERSION
        self.call_count = 0
        self._system_prompt: str | None = None

    def _load_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = load_prompt(self._prompt_path)
        return self._system_prompt

    @staticmethod
    def _build_user_payload(
        request: CourseAssemblyRequest,
        contexts: tuple[RLOAssemblyContext, ...],
    ) -> dict[str, Any]:
        return {
            "learner": json.loads(request.learner.model_dump_json()),
            "course_goal": request.course_goal,
            "constraints": json.loads(request.constraints.model_dump_json()),
            "brand_contract": dict(request.brand_contract),
            "candidate_rlos": [json.loads(c.model_dump_json()) for c in contexts],
            "duration_policy": {
                "version": "duration_v1",
                "hard_limit_minutes": request.constraints.maximum_duration_minutes,
                "depth_multipliers": {
                    "summary": 0.5,
                    "working": 1.0,
                    "comprehensive": 1.3,
                },
                "proficiency_gap_multipliers": {
                    "same_level": 1.0,
                    "one_level": 1.1,
                    "two_levels": 1.2,
                },
                "prerequisite_bridge_minutes": 2,
                "instructions": (
                    "Estimate every included RLO before returning the draft. "
                    "The total must not exceed hard_limit_minutes. Reduce optional "
                    "content, use summary depth where appropriate, or omit optional "
                    "RLOs. Never omit required RLOs or required content."
                ),
            },
        }

    async def create_assembly_draft(
        self,
        request: CourseAssemblyRequest,
        contexts: tuple[RLOAssemblyContext, ...],
    ) -> StructuredPlanningResponse:
        self.call_count += 1
        user_payload = self._build_user_payload(request, contexts)
        return await self._client.generate(
            system_prompt=self._load_prompt(),
            user_payload=user_payload,
            output_model=CourseAssemblyDraft,
            model=self.model,
        )

    async def repair_duration_draft(
        self,
        request: CourseAssemblyRequest,
        contexts: tuple[RLOAssemblyContext, ...],
        previous_draft: CourseAssemblyDraft,
        validation_error: str,
    ) -> StructuredPlanningResponse:
        """Make one bounded correction after deterministic duration rejection."""
        self.call_count += 1
        user_payload = self._build_user_payload(request, contexts)
        user_payload["previous_draft"] = json.loads(previous_draft.model_dump_json())
        user_payload["repair_feedback"] = validation_error
        user_payload["repair_contract"] = {
            "reason": "deterministic_duration_limit",
            "maximum_additional_attempts": 1,
            "preserve_required_rlos_and_content": True,
            "return_a_complete_replacement_draft": True,
        }
        return await self._client.generate(
            system_prompt=self._load_prompt(),
            user_payload=user_payload,
            output_model=CourseAssemblyDraft,
            model=self.model,
        )
