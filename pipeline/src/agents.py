"""PydanticAI agents for slide-needs planning, retrieval, selection, and fitting."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from llm_gateway import ModelAlias, build_langfuse_headers, build_litellm_metadata

from rlo_schema import RLO

from component_registry import ComponentRegistry
from constraints import format_violations, validate_budgets
from grounding import SourceReferenceError, resolve_rlo_refs
from model_gateway import make_model
from schema import (
    SCREEN_MODELS,
    ScreenBase,
    ScreenContent,
    ScreenPlan,
    ScreenPlanItem,
    SlideNeedPlanItem,
    SlideNeedsPlan,
    TemplateCandidate,
    TemplateChoices,
)


NEEDS_INSTRUCTIONS = """You are a learning experience architect planning slide needs.
Describe what each slide must represent without naming or choosing a template.

Rules:
1. Use only grounded content from the supplied v1 RLO.
2. Never infer behavior from an RLO ID, methodology name, or topic keyword.
3. Every slide need cites exact RLO dot/index paths.
4. Start with one intro need whose purpose is course_opening.
5. The second need is intro/learning_objectives and plans 2-6 rendered outcomes.
6. End with one completion/course_completion need.
7. Describe content shape, relationship, rendered item count, density, interaction preferences,
   media requirement, and sequence position accurately.
8. Assessment needs cite exactly one complete assessment_items[index] object and use its option
   count as item_count. Do not plan unsupported open-response assessment slides.
9. A media need is allowed only when a cited source provides an actual playable media URL/path.
10. Use consecutive sequence numbers and unique stable screen IDs.
"""


SELECTION_INSTRUCTIONS = """You select a template for each already-planned slide need.

Rules:
1. Select only template_id + variant_id combinations included with that slide need.
2. Return one choice for every sequence number, with no duplicates or omissions.
3. Return only sequence, template_id, variant_id, and a concise rationale.
4. Use descriptor capacity, best-use text, negative guidance, interaction, density, and media fit.
5. Do not add, remove, merge, split, or reorder slide needs.
6. Do not invent facts or examples.
"""


FITTING_INSTRUCTIONS = """You fit source-grounded learning content into one selected screen.

Rules:
1. Use only the supplied resolved RLO source values. Never invent a claim, example, or asset.
2. Preserve screen_id, sequence, type, layout_variant, and rlo_source_refs exactly.
3. Rephrase only for concise on-screen clarity without changing meaning.
4. For knowledge checks, copy stem, option text, correctness, and each option's feedback exactly.
5. For video, copy a supplied playable URL/path exactly; never synthesize a media source.
6. Respect every declared slot capacity. Do not silently truncate.
7. Use null for image_path. Use image_prompt only for a genuinely useful optional illustration.
8. Use clear, concise, measured corporate-learning language. Do not embellish the source with
   rhetorical framing, commentary, or filler.
"""


class ContentCapacityError(ValueError):
    """Source-authored content cannot fit without violating source fidelity."""


class UnsupportedAssessmentError(ValueError):
    """The selected presentation component cannot represent an assessment type."""


class TemplateRetrievalError(RuntimeError):
    """No eligible template could be retrieved for a planned slide need."""


@dataclass
class NeedPlanningDeps:
    rlo: RLO


@dataclass
class SelectionDeps:
    rlo: RLO
    needs: SlideNeedsPlan
    candidates: list[list[TemplateCandidate]]


def _assessment_ref(refs: list[str]) -> str | None:
    matches = [
        ref
        for ref in refs
        if re.fullmatch(r"assessment_items\[(?:0|[1-9][0-9]*)\]", ref)
    ]
    return matches[0] if len(matches) == 1 else None


def _validate_needs(deps: NeedPlanningDeps, plan: SlideNeedsPlan) -> None:
    if plan.rlo_id != deps.rlo.id or plan.rlo_version != deps.rlo.version:
        raise ModelRetry("Use the exact RLO id and version supplied in the input.")
    if len(plan.slides) < 3:
        raise ModelRetry("Plan at least opening, objectives, and completion slide needs.")
    first, second, last = plan.slides[0], plan.slides[1], plan.slides[-1]
    if first.need.category != "intro" or first.need.purpose != "course_opening":
        raise ModelRetry("The first slide need must be intro/course_opening.")
    if second.need.category != "intro" or second.need.purpose != "learning_objectives":
        raise ModelRetry("The second slide need must be intro/learning_objectives.")
    if second.need.item_count is None or not 2 <= second.need.item_count <= 6:
        raise ModelRetry("Plan 2-6 rendered outcomes for the learning-objectives slide.")
    if last.need.category != "completion" or last.need.purpose != "course_completion":
        raise ModelRetry("The final slide need must be completion/course_completion.")

    try:
        for slide in plan.slides:
            resolved = resolve_rlo_refs(deps.rlo, slide.rlo_source_refs)
            if slide.need.category == "assessment":
                ref = _assessment_ref(slide.rlo_source_refs)
                if ref is None:
                    raise SourceReferenceError(
                        "Each assessment need must cite exactly one complete assessment_items[index] object."
                    )
                item = resolved[ref]
                if item.get("type") == "open_response":
                    raise SourceReferenceError("Open-response slide rendering is not supported yet.")
                expected_count = len(item.get("options") or [])
                if slide.need.item_count != expected_count:
                    raise SourceReferenceError(
                        f"Assessment item_count must equal its {expected_count} supplied options."
                    )
    except SourceReferenceError as exc:
        raise ModelRetry(str(exc)) from exc


def _validate_selection(deps: SelectionDeps, output: TemplateChoices) -> None:
    if len(output.choices) != len(deps.needs.slides):
        raise ModelRetry("Return exactly one selected screen for every slide need.")
    choices = {choice.sequence: choice for choice in output.choices}
    if len(choices) != len(output.choices):
        raise ModelRetry("Return each sequence exactly once.")
    expected_sequences = {slide.sequence for slide in deps.needs.slides}
    if set(choices) != expected_sequences:
        raise ModelRetry(f"Return choices for sequences {sorted(expected_sequences)} exactly.")

    for planned, candidates in zip(deps.needs.slides, deps.candidates):
        selected = choices[planned.sequence]
        allowed = {(candidate.template_id, candidate.variant_id) for candidate in candidates}
        choice = (selected.template_id, selected.variant_id)
        if choice not in allowed:
            formatted = ", ".join(f"{template}.{variant}" for template, variant in sorted(allowed))
            raise ModelRetry(
                f"Selection {choice[0]}.{choice[1]} was not retrieved for screen "
                f"{planned.screen_id}. Choose one of: {formatted}."
            )
    selected_types = [choices[slide.sequence].template_id for slide in deps.needs.slides]
    if (
        selected_types[0] != "title"
        or selected_types[1] != "objectives"
        or selected_types[-1] != "completion"
    ):
        raise ModelRetry("Opening, objectives, and completion needs must select their matching templates.")


class SelectionAgent:
    """Plan template-independent needs, retrieve candidates, then select templates."""

    def __init__(
        self,
        model: Model | None = None,
        *,
        retries: int = 3,
        candidate_limit: int = 8,
    ) -> None:
        needs_model = model or make_model(ModelAlias.SLIDE_NEEDS_PLANNING)
        selection_model = model or make_model(ModelAlias.SLIDE_TEMPLATE_SELECTION)
        self.candidate_limit = candidate_limit
        self.needs_agent: Agent[NeedPlanningDeps, SlideNeedsPlan] = Agent(
            needs_model,
            output_type=SlideNeedsPlan,
            instructions=NEEDS_INSTRUCTIONS,
            deps_type=NeedPlanningDeps,
            retries=retries,
        )
        self.agent: Agent[SelectionDeps, TemplateChoices] = Agent(
            selection_model,
            output_type=TemplateChoices,
            instructions=SELECTION_INSTRUCTIONS,
            deps_type=SelectionDeps,
            retries=retries,
        )

        @self.needs_agent.output_validator
        def validate_needs(
            ctx: RunContext[NeedPlanningDeps], output: SlideNeedsPlan
        ) -> SlideNeedsPlan:
            _validate_needs(ctx.deps, output)
            return output

        @self.agent.output_validator
        def validate_selection(
            ctx: RunContext[SelectionDeps], output: TemplateChoices
        ) -> TemplateChoices:
            _validate_selection(ctx.deps, output)
            return output

    def plan_needs(self, rlo: RLO) -> SlideNeedsPlan:
        return self.needs_agent.run_sync(
            "Plan template-independent slide needs for this RLO:\n\n" + rlo.model_dump_json(indent=2),
            deps=NeedPlanningDeps(rlo=rlo),
            model_settings={
                "extra_body": {
                    "metadata": build_litellm_metadata(ModelAlias.SLIDE_NEEDS_PLANNING)
                },
                "extra_headers": build_langfuse_headers(ModelAlias.SLIDE_NEEDS_PLANNING),
            },
        ).output

    def run(self, rlo: RLO, registry: ComponentRegistry) -> ScreenPlan:
        needs = self.plan_needs(rlo)
        candidate_lists = registry.search_candidates_batch(
            [slide.need for slide in needs.slides],
            limit=self.candidate_limit,
        )
        for slide, candidates in zip(needs.slides, candidate_lists):
            if not candidates:
                raise TemplateRetrievalError(
                    f"No eligible template for screen {slide.screen_id}: "
                    f"{slide.need.model_dump_json()}."
                )

        selection_input = []
        for slide, candidates in zip(needs.slides, candidate_lists):
            selection_input.append(
                {
                    "slide_need": slide.model_dump(mode="json"),
                    "grounded_sources": resolve_rlo_refs(rlo, slide.rlo_source_refs),
                    "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
                }
            )
        print(
            "[selection] candidate counts: "
            + ", ".join(str(len(candidates)) for candidates in candidate_lists)
        )
        choices_result = self.agent.run_sync(
            "Select one retrieved template variant for every slide need:\n\n"
            + json.dumps(selection_input, indent=2),
            deps=SelectionDeps(rlo=rlo, needs=needs, candidates=candidate_lists),
            model_settings={
                "extra_body": {
                    "metadata": build_litellm_metadata(ModelAlias.SLIDE_TEMPLATE_SELECTION)
                },
                "extra_headers": build_langfuse_headers(ModelAlias.SLIDE_TEMPLATE_SELECTION),
            },
        ).output
        choices = {choice.sequence: choice for choice in choices_result.choices}
        return ScreenPlan(
            rlo_id=needs.rlo_id,
            rlo_version=needs.rlo_version,
            screens=[
                ScreenPlanItem(
                    screen_id=slide.screen_id,
                    sequence=slide.sequence,
                    type=choices[slide.sequence].template_id,
                    rlo_source_refs=slide.rlo_source_refs,
                    layout_variant=choices[slide.sequence].variant_id,
                    slide_need=slide.need,
                    candidate_ids=[
                        f"{candidate.template_id}.{candidate.variant_id}"
                        for candidate in candidate_lists[index]
                    ],
                    content_hints={
                        **(slide.content_hints or {}),
                        "selection_rationale": choices[slide.sequence].rationale,
                    },
                )
                for index, slide in enumerate(needs.slides)
            ],
        )


def _assessment_item(resolved: dict[str, Any]) -> dict[str, Any] | None:
    for value in resolved.values():
        if isinstance(value, dict) and {"id", "stem", "type"} <= value.keys():
            if str(value.get("type")) in {
                "multiple_choice_single",
                "multiple_choice_multi",
                "open_response",
            }:
                return value
    return None


def _assessment_feedback(output: ScreenBase, resolved: dict[str, Any]) -> str | None:
    if output.type != "knowledge_check":
        return None
    item = _assessment_item(resolved)
    if item is None:
        return "A knowledge_check must cite its complete assessment_items[index] object."
    if item.get("type") == "open_response":
        return "Open-response assessment items are not supported by knowledge_check."
    actual = output.model_dump()
    if actual.get("question_id") != item.get("id") or actual.get("stem") != item.get("stem"):
        return "Copy the assessment id and stem exactly from the cited item."
    if actual.get("question_type") != item.get("type"):
        return "Copy the assessment type exactly from the cited item."
    expected_options = [
        {
            "id": option["id"],
            "text": option["text"],
            "correct": option["correct"],
            "feedback": option["feedback"],
        }
        for option in item.get("options") or []
    ]
    if actual.get("options") != expected_options:
        return "Copy every assessment option and its diagnostic feedback exactly and in order."
    return None


class FittingAgent:
    def __init__(self, model: Model | None = None, *, retries: int = 3) -> None:
        self.model = model or make_model(ModelAlias.SLIDE_CONTENT_FITTING)
        self.retries = retries

    def run(
        self,
        plan_item: ScreenPlanItem,
        rlo: RLO,
        registry: ComponentRegistry,
    ) -> ScreenContent:
        descriptor = registry.get(plan_item.type)
        if descriptor is None:
            raise ValueError(f"Unknown component type {plan_item.type!r}.")
        model_type = SCREEN_MODELS[plan_item.type]
        resolved = resolve_rlo_refs(rlo, plan_item.rlo_source_refs)
        if plan_item.type == "knowledge_check":
            item = _assessment_item(resolved)
            if item is None:
                raise UnsupportedAssessmentError(
                    "A knowledge_check must cite one complete assessment_items[index] object."
                )
            if item.get("type") == "open_response":
                raise UnsupportedAssessmentError(
                    "Open-response assessment items do not yet have a supported screen component."
                )
            exact_content = {
                "question_id": item["id"],
                "stem": item["stem"],
                "question_type": item["type"],
                "options": item.get("options") or [],
            }
            source_violations = validate_budgets(exact_content, descriptor)
            if source_violations:
                raise ContentCapacityError(
                    "Source-authored assessment content exceeds the knowledge-check capacity; "
                    "use an adaptive template or revise the source budget.\n"
                    + format_violations(source_violations)
                )

        agent: Agent[None, Any] = Agent(
            self.model,
            output_type=model_type,
            instructions=FITTING_INSTRUCTIONS,
            retries=self.retries,
        )

        @agent.output_validator
        def validate(_: RunContext[None], output: ScreenBase) -> ScreenBase:
            if (
                output.screen_id != plan_item.screen_id
                or output.sequence != plan_item.sequence
                or output.type != plan_item.type
                or output.layout_variant != plan_item.layout_variant
                or output.rlo_source_refs != plan_item.rlo_source_refs
            ):
                raise ModelRetry("Copy all selected plan identity and variant fields exactly.")
            feedback = _assessment_feedback(output, resolved)
            if feedback:
                raise ModelRetry(feedback)
            violations = validate_budgets(
                output.model_dump(mode="json"),
                descriptor,
                min_char_floor_ratio=0.4,
            )
            if violations:
                repair = format_violations(violations)
                print(f"[fitting] budget retry for {plan_item.screen_id}:\n{repair}")
                raise ModelRetry(repair)
            return output

        prompt = (
            "Selected screen plan item:\n"
            + plan_item.model_dump_json(indent=2)
            + "\n\nResolved RLO sources:\n"
            + json.dumps(resolved, indent=2)
            + "\n\nSelected component descriptor:\n"
            + json.dumps(descriptor, indent=2)
        )
        return agent.run_sync(
            prompt,
            model_settings={
                "extra_body": {
                    "metadata": build_litellm_metadata(ModelAlias.SLIDE_CONTENT_FITTING)
                },
                "extra_headers": build_langfuse_headers(ModelAlias.SLIDE_CONTENT_FITTING),
            },
        ).output
