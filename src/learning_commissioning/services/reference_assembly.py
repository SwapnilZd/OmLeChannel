"""Deterministic, commissioning-owned assembly agent for local/reference runs."""

from __future__ import annotations

import math
import uuid

from learning_pipeline.contracts.assembly import RLOContentSelection
from learning_pipeline.contracts.common import ContentDepth, PROFICIENCY_ORDER, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import (
    CourseAssemblyDraft,
    CourseAssemblyRequest,
    OmittedRLODecision,
    PrerequisiteBridge,
    RLOAssemblyContext,
    TailoredRLODraft,
)
from learning_pipeline.contracts.planning import StructuredPlanningResponse

REFERENCE_PROMPT_VERSION = "commissioning_reference_assembly_v1"


def _stable_prerequisite_order(
    contexts: tuple[RLOAssemblyContext, ...],
) -> list[RLOAssemblyContext]:
    """Topologically order in-candidate prerequisites while preserving input order."""

    by_id = {context.rlo_id: context for context in contexts}
    remaining = list(contexts)
    ordered: list[RLOAssemblyContext] = []
    ordered_ids: set[str] = set()
    while remaining:
        ready = next(
            (
                context
                for context in remaining
                if all(
                    prerequisite not in by_id or prerequisite in ordered_ids
                    for prerequisite in context.prerequisites
                )
            ),
            None,
        )
        if ready is None:
            # Preserve determinism; downstream validation will report the cycle.
            ordered.extend(remaining)
            break
        ordered.append(ready)
        ordered_ids.add(ready.rlo_id)
        remaining.remove(ready)
    return ordered


class CommissioningReferenceAssemblyAgent:
    """Produces a valid generic draft without a model call.

    Reference mode is intentionally conservative: it orders prerequisites,
    adds explicit bridges for prerequisites outside the selected set, and may
    omit optional trailing RLOs to respect the request's duration ceiling.
    """

    prompt_version = REFERENCE_PROMPT_VERSION
    model = "commissioning-reference"

    def __init__(self) -> None:
        self.call_count = 0

    async def create_assembly_draft(
        self,
        request: CourseAssemblyRequest,
        contexts: tuple[RLOAssemblyContext, ...],
    ) -> StructuredPlanningResponse:
        self.call_count += 1
        ordered = _stable_prerequisite_order(contexts)
        required_ids = set(request.constraints.required_rlo_ids)
        selected = list(ordered)
        limit = request.constraints.maximum_duration_minutes

        def conservative_minutes(values: list[RLOAssemblyContext]) -> int:
            selected_ids = {value.rlo_id for value in values}
            missing_edges = sum(
                1
                for value in values
                for prerequisite in value.prerequisites
                if prerequisite not in selected_ids
            )
            # Summary depth is 0.5 and the downstream proficiency adjustment
            # is at most 1.2. Each missing prerequisite bridge costs 2 minutes.
            return sum(
                max(1, math.ceil(value.estimated_duration_minutes * 0.5 * 1.2))
                for value in values
            ) + (2 * missing_edges)

        if limit is not None:
            while conservative_minutes(selected) > limit:
                removable = next(
                    (
                        context
                        for context in reversed(selected)
                        if context.rlo_id not in required_ids
                    ),
                    None,
                )
                if removable is None:
                    break
                selected.remove(removable)
        if not selected and ordered:
            # Never report an empty course as success. If even one RLO cannot
            # fit, downstream duration validation returns a typed failure.
            selected.append(ordered[0])

        selected_ids = {context.rlo_id for context in selected}
        target_floor = request.constraints.minimum_target_proficiency or TopicProficiency.INTERMEDIATE
        drafts: list[TailoredRLODraft] = []
        bridges: list[PrerequisiteBridge] = []
        for order, context in enumerate(selected, start=1):
            starting = request.learner.topic_proficiencies.get(
                context.topic,
                request.learner.default_proficiency,
            )
            target = (
                starting
                if PROFICIENCY_ORDER[starting] > PROFICIENCY_ORDER[target_floor]
                else target_floor
            )
            drafts.append(
                TailoredRLODraft(
                    rlo_id=context.rlo_id,
                    rlo_version=context.rlo_version,
                    order=order,
                    selected_content=RLOContentSelection(
                        objective_ids=(context.enabling_objective.id,),
                        concept_ids=tuple(item.id for item in context.concepts),
                        component_ids=tuple(item.id for item in context.components),
                        assessment_item_ids=tuple(item.id for item in context.assessment_items),
                    ),
                    target_proficiency=target,
                    content_depth=ContentDepth.SUMMARY,
                    role_relevance=f"Relevant to the learner: {request.learner.role}.",
                    personalization_rationale=(
                        f"Included to support the confirmed course goal: {request.course_goal}."
                    ),
                    sequencing_rationale="Ordered after any selected prerequisite RLOs.",
                )
            )
            for prerequisite in context.prerequisites:
                if prerequisite not in selected_ids:
                    bridges.append(
                        PrerequisiteBridge(
                            bridge_id=f"bridge-{context.rlo_id}-{prerequisite}",
                            before_rlo_id=context.rlo_id,
                            prerequisite_topic=prerequisite,
                            learning_direction=(
                                f"Briefly establish the prerequisite knowledge from {prerequisite}."
                            ),
                            rationale=(
                                "The prerequisite RLO is outside the confirmed blueprint selection."
                            ),
                        )
                    )

        omitted = tuple(
            OmittedRLODecision(
                rlo_id=context.rlo_id,
                rlo_version=context.rlo_version,
                rationale="Omitted in reference mode to respect the duration ceiling.",
            )
            for context in ordered
            if context.rlo_id not in selected_ids
        )
        outcomes = tuple(
            f"Upon completion, learners will be able to: {context.enabling_objective.statement}"
            for context in selected
        ) or ("Complete the confirmed learning objective.",)
        draft = CourseAssemblyDraft(
            draft_id=f"reference-{uuid.uuid4()}",
            title=f"Reference Assembly: {request.course_goal[:60]}",
            learning_outcomes=outcomes,
            ordered_rlo_drafts=tuple(drafts),
            omitted_rlos=omitted,
            prerequisite_bridges=tuple(bridges),
            sequencing_rationale=(
                "Selected RLOs are ordered by prerequisite dependencies and stable candidate order."
            ),
            assessment_strategy=(
                "Use formative checks from selected assessment items and a final knowledge check."
            ),
        )
        return StructuredPlanningResponse(
            result=draft,
            model=self.model,
            prompt_version=self.prompt_version,
        )
